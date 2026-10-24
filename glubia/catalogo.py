"""Catalogo de modelos: los de Ollama y las carpetas OpenVINO, bajo un mismo id.

    ollama:<usuario/modelo:etiqueta>     p. ej. ollama:huihui_ai/qwen3.5-abliterated:9b
    openvino:<carpeta en GLUBIA_MODELOS> p. ej. openvino:qwen2.5-coder-7b-int4-ov

Desde el id se arma la Config con la que el motor carga ese modelo, asi que
cambiar de modelo (o de motor) es solo pedirle al motor que recargue con ella.
Las descargas de Ollama corren en un hilo y el panel consulta su progreso.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

log = logging.getLogger("glubia.catalogo")

NOMBRE_OLLAMA = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)?(:[A-Za-z0-9][A-Za-z0-9._-]*)?$")
CARPETA_OV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
FALSOS = ("glubia-falso", "glubia-falso-2")      # el motor falso ofrece dos para probar el cambio


class ModeloInvalido(ValueError):
    pass


def id_de(cfg) -> str:
    if cfg.motor == "ollama":
        return "ollama:" + cfg.ollama_modelo
    if cfg.motor == "falso":
        return "falso:" + cfg.falso_nombre
    return "openvino:" + cfg.model_path.name


def validar_nombre_ollama(nombre: str) -> str:
    nombre = (nombre or "").strip()
    if len(nombre) > 120 or not NOMBRE_OLLAMA.match(nombre):
        raise ModeloInvalido("Nombre no valido. Formato: usuario/modelo:etiqueta (como en «ollama run»).")
    return nombre


class Catalogo:
    def __init__(self, cfg_base):
        self.base = cfg_base
        self.url = cfg_base.ollama_url
        self._descargas: Dict[str, dict] = {}
        self._capacidades: Dict[str, list] = {}     # digest -> capacidades (no cambian)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ Ollama HTTP

    def _ollama(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None, timeout: float = 5):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.url + ruta, data=datos, method=metodo,
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    def _json(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None, timeout: float = 5) -> dict:
        with self._ollama(metodo, ruta, cuerpo, timeout) as r:
            return json.loads(r.read() or b"{}")

    # ------------------------------------------------------------ listado

    def listar(self) -> dict:
        modelos: List[dict] = []
        error_ollama = None
        if self.base.motor == "falso":
            modelos += [{"id": "falso:" + n, "motor": "falso", "nombre": n, "bytes": 0,
                         "parametros": "-", "cuantizacion": "-"} for n in FALSOS]
        if self.url:
            try:
                cargados = {m.get("name") for m in self._json("GET", "/api/ps").get("models", [])}
                for m in self._json("GET", "/api/tags").get("models", []):
                    if not self._conversa(m):
                        continue                    # embeddings y similares: no sirven para chatear
                    d = m.get("details") or {}
                    modelos.append({
                        "id": "ollama:" + m["name"], "motor": "ollama", "nombre": m["name"],
                        "bytes": m.get("size", 0), "parametros": d.get("parameter_size", "?"),
                        "cuantizacion": d.get("quantization_level", "?"), "familia": d.get("family", ""),
                        "en_memoria": m["name"] in cargados,
                    })
            except (urllib.error.URLError, OSError, ValueError) as exc:
                error_ollama = f"Ollama no responde en {self.url}: {exc}"
        modelos += self._openvino()
        return {"modelos": modelos, "error_ollama": error_ollama}

    def _conversa(self, m: dict) -> bool:
        clave = m.get("digest") or m["name"]
        if clave not in self._capacidades:
            try:
                caps = self._json("POST", "/api/show", {"model": m["name"]}).get("capabilities")
            except (urllib.error.URLError, OSError, ValueError):
                return True                         # en la duda, se muestra
            self._capacidades[clave] = caps if isinstance(caps, list) else ["completion"]
        return "completion" in self._capacidades[clave]

    def _openvino(self) -> List[dict]:
        out = []
        try:
            carpetas = sorted(p for p in self.base.modelos_dir.iterdir() if p.is_dir())
        except OSError:
            return out
        for p in carpetas:
            xml = p / "openvino_model.xml"
            if not xml.exists() or not CARPETA_OV.match(p.name):
                continue
            peso = sum(f.stat().st_size for f in p.glob("*.bin"))
            out.append({"id": "openvino:" + p.name, "motor": "openvino", "nombre": p.name, "bytes": peso,
                        "parametros": _parametros(p.name), "cuantizacion": "int4" if "int4" in p.name else "?"})
        return out

    def existe(self, id_modelo: str) -> bool:
        return any(m["id"] == id_modelo for m in self.listar()["modelos"])

    # ------------------------------------------------------------ id -> Config

    def cfg_para(self, id_modelo: str, ajustes: dict):
        motor, _, nombre = (id_modelo or "").partition(":")
        o, ov = ajustes["ollama"], ajustes["openvino"]
        if motor == "ollama":
            return dataclasses.replace(self.base, motor="ollama", ollama_modelo=validar_nombre_ollama(nombre),
                                       ollama_gpu=bool(o["gpu"]), ollama_pensar=bool(o["pensar"]),
                                       ollama_keep=str(o["keep"]))
        if motor == "openvino":
            if not CARPETA_OV.match(nombre):
                raise ModeloInvalido("Carpeta de modelo no valida")
            return dataclasses.replace(self.base, motor="openvino", model_path=self.base.modelos_dir / nombre,
                                       device=str(ov["device"]).upper())
        if motor == "falso" and nombre in FALSOS:
            return dataclasses.replace(self.base, motor="falso", falso_nombre=nombre)
        raise ModeloInvalido(f"Modelo desconocido: {id_modelo}")

    # ------------------------------------------------------------ descargar / borrar

    def descargar(self, nombre: str) -> dict:
        nombre = validar_nombre_ollama(nombre)
        if not self.url:
            raise ModeloInvalido("Ollama no esta configurado (GLUBIA_OLLAMA_URL)")
        with self._lock:
            actual = self._descargas.get(nombre)
            if actual and actual["estado"] == "descargando":
                return dict(actual)
            estado = {"nombre": nombre, "estado": "descargando", "detalle": "empezando", "total": 0,
                      "hecho": 0, "inicio": time.time()}
            self._descargas[nombre] = estado
        threading.Thread(target=self._descargar, args=(nombre,), daemon=True, name="glubia-pull").start()
        return dict(estado)

    def _descargar(self, nombre: str) -> None:
        estado = self._descargas[nombre]
        try:
            with self._ollama("POST", "/api/pull", {"model": nombre, "stream": True}, timeout=600) as r:
                for linea in r:
                    if not linea.strip():
                        continue
                    d = json.loads(linea)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    with self._lock:
                        estado["detalle"] = d.get("status", "")
                        if d.get("total"):
                            estado["total"], estado["hecho"] = d["total"], d.get("completed", 0)
            with self._lock:
                estado.update(estado="listo", detalle="descargado", fin=time.time())
            log.info("modelo descargado: %s", nombre)
        except Exception as exc:  # noqa: BLE001
            mensaje = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    mensaje = json.loads(exc.read()).get("error", mensaje)
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                estado.update(estado="error", detalle=mensaje, fin=time.time())
            log.warning("fallo descargando %s: %s", nombre, mensaje)

    def descargas(self) -> List[dict]:
        with self._lock:
            return [dict(d) for d in self._descargas.values()]

    def borrar(self, nombre: str) -> None:
        nombre = validar_nombre_ollama(nombre)
        try:
            self._json("DELETE", "/api/delete", {"model": nombre}, timeout=30)
        except urllib.error.HTTPError as exc:
            raise ModeloInvalido(f"Ollama no pudo borrarlo ({exc.code})") from None


def _parametros(nombre: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)b", nombre.lower())
    return m.group(1).upper() + "B" if m else "?"
