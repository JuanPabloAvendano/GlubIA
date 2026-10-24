"""Backend Ollama: el modelo lo sirve un `ollama serve` y GlubIA le habla por HTTP.

Sirve para usar cualquier modelo de ollama.com sin convertirlo a OpenVINO.
Cambiar de modelo es una linea del .env:

    GLUBIA_MOTOR=ollama
    GLUBIA_OLLAMA_MODELO=huihui_ai/qwen3.5-abliterated:4B   # lo mismo que en "ollama run ..."

La cola, la cancelacion y el recorte de contexto siguen en motor.py. Aqui solo:

* La plantilla de chat la aplica Ollama (viene dentro del modelo): se envian
  los mensajes tal cual a /api/chat, igual que el ChatHistory de OpenVINO.
* Detener = cerrar la conexion: Ollama aborta la generacion al perder al cliente.
* Ollama no expone su tokenizer, asi que `contar` ESTIMA (3 caracteres por
  token, a la baja para no desbordar el contexto). Los tokens reales de cada
  respuesta si salen exactos: los devuelve Ollama al final del stream.
* Solo usa la libreria estandar (urllib): sin dependencias nuevas en la imagen.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import List, Optional

from .motor import Mensaje, Parametros, Resultado

log = logging.getLogger("glubia.ollama")

CARACTERES_POR_TOKEN = 3


class BackendOllama:
    overhead = 5    # Qwen/ChatML; la estimacion de contar() ya deja margen

    def __init__(self, cfg, espera_seg: float = 120.0):
        self.url = cfg.ollama_url
        self.modelo = cfg.ollama_modelo
        self.nombre_modelo = cfg.nombre_modelo
        self.keep = cfg.ollama_keep
        self.pensar = cfg.ollama_pensar
        self.gpu = cfg.ollama_gpu
        self.ctx = cfg.ctx_tokens
        self.timeout = cfg.max_seg + 60

        self._esperar_servidor(espera_seg)
        modelos = [m.get("name") for m in self._json("GET", "/api/tags").get("models", [])]
        if self.modelo not in modelos and f"{self.modelo}:latest" not in modelos:
            raise RuntimeError(
                f"Ollama no tiene '{self.modelo}'. Descargalo con:  "
                f"docker compose exec ollama ollama pull {self.modelo}   "
                f"(disponibles: {', '.join(filter(None, modelos)) or 'ninguno'})")

        # "think" solo se envia a modelos que razonan: a los demas Ollama les da error.
        try:
            capacidades = self._json("POST", "/api/show", {"model": self.modelo}).get("capabilities") or []
        except RuntimeError:
            capacidades = []
        self.razona = "thinking" in capacidades

        # Precarga: deja el modelo en memoria para que la primera pregunta no espere.
        log.info("cargando %s en Ollama (%s)...", self.modelo, "GPU" if self.gpu else "CPU")
        # Con las mismas opciones que usara generar(): si no, Ollama recarga el
        # modelo en la primera pregunta para cambiar el contexto o el dispositivo.
        self._json("POST", "/api/chat", {"model": self.modelo, "messages": [],
                                         "keep_alive": self._keep(),
                                         "options": self._base()}, timeout=600)
        self.dispositivo = self._dispositivo()

    # ------------------------------------------------------------ HTTP

    def _peticion(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        return urllib.request.Request(self.url + ruta, data=datos, method=metodo,
                                      headers={"Content-Type": "application/json"})

    def _json(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None, timeout: float = 30):
        try:
            with urllib.request.urlopen(self._peticion(metodo, ruta, cuerpo), timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama {ruta}: {exc.code} {self._detalle(exc)}") from None

    @staticmethod
    def _detalle(exc: urllib.error.HTTPError) -> str:
        try:
            return json.loads(exc.read()).get("error", "")
        except Exception:  # noqa: BLE001
            return exc.reason or ""

    def _esperar_servidor(self, segundos: float) -> None:
        """El contenedor de Ollama puede tardar en abrir el puerto tras un reinicio."""
        limite = time.monotonic() + segundos
        while True:
            try:
                self._json("GET", "/api/version", timeout=5)
                return
            except (urllib.error.URLError, OSError) as exc:
                if time.monotonic() > limite:
                    raise RuntimeError(f"No hay Ollama en {self.url}: {exc}") from None
                time.sleep(1)

    def _base(self) -> dict:
        op = {"num_ctx": self.ctx}
        if not self.gpu:
            op["num_gpu"] = 0              # 0 capas en la GPU = todo en CPU
        return op

    def cerrar(self) -> None:
        """Descarga el modelo de la memoria de Ollama (al cambiar a otro)."""
        try:
            self._json("POST", "/api/generate", {"model": self.modelo, "keep_alive": 0}, timeout=30)
        except Exception as exc:  # noqa: BLE001
            log.warning("no se pudo descargar %s de la memoria: %s", self.modelo, exc)

    def _keep(self):
        try:
            return int(self.keep)          # -1 = siempre en memoria, 0 = descargar al terminar
        except ValueError:
            return self.keep               # "30m", "2h"...

    def _dispositivo(self) -> str:
        try:
            for m in self._json("GET", "/api/ps").get("models", []):
                if m.get("name") in (self.modelo, f"{self.modelo}:latest"):
                    return "OLLAMA-GPU" if m.get("size_vram") else "OLLAMA-CPU"
        except Exception:  # noqa: BLE001
            pass
        return "OLLAMA"

    # ------------------------------------------------------------ tokens

    def contar(self, texto: str) -> int:
        return -(-len(texto) // CARACTERES_POR_TOKEN) if texto else 0

    # ------------------------------------------------------------ generacion

    def _opciones(self, p: Parametros) -> dict:
        op = {
            **self._base(),
            "num_predict": int(p.max_new_tokens),
            "temperature": float(p.temperature),
            "top_p": float(p.top_p),
            "repeat_penalty": float(p.repetition_penalty),
        }
        if p.top_k:
            op["top_k"] = int(p.top_k)
        if p.stop:
            op["stop"] = list(p.stop)
        return op

    def generar(self, mensajes: List[Mensaje], p: Parametros, on_delta) -> Resultado:
        cuerpo = {"model": self.modelo, "messages": mensajes, "stream": True,
                  "keep_alive": self._keep(), "options": self._opciones(p)}
        if self.razona:
            cuerpo["think"] = self.pensar
        inicio = time.monotonic()
        ttft: Optional[float] = None
        partes: List[str] = []
        final: dict = {}
        try:
            resp = urllib.request.urlopen(self._peticion("POST", "/api/chat", cuerpo),
                                          timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama: {exc.code} {self._detalle(exc)}") from None
        with resp:
            for linea in resp:
                if not linea.strip():
                    continue
                dato = json.loads(linea)
                if dato.get("error"):
                    raise RuntimeError(f"Ollama: {dato['error']}")
                texto = (dato.get("message") or {}).get("content", "")
                if texto:
                    if ttft is None:
                        ttft = round((time.monotonic() - inicio) * 1000, 1)
                    partes.append(texto)
                    if not on_delta(texto):
                        break              # cerrar la conexion = Ollama deja de generar
                if dato.get("done"):
                    final = dato
                    break

        texto = "".join(partes)
        entrada = int(final.get("prompt_eval_count") or 0) or sum(
            self.contar(m["content"]) + self.overhead for m in mensajes)
        salida = int(final.get("eval_count") or 0) or self.contar(texto)
        return Resultado(texto.strip(), entrada, salida, ttft)


def crear(cfg) -> BackendOllama:
    return BackendOllama(cfg)
