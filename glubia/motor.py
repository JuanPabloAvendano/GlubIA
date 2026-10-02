"""Motor de generacion: un unico hilo duenio del pipeline y una cola con prioridades.

Por que asi (problemas medidos en la version 1):

* Cada peticion en espera ocupaba un hilo del pool de AnyIO (40 por defecto) y
  /api/health tambien necesitaba uno: con 45 streams en cola el health tardo
  16,7 s. Aqui la generacion vive en UN hilo propio y los endpoints son async:
  esperar en la cola no consume hilos.
* El boton Detener no paraba la generacion en el servidor (seguia hasta
  max_new_tokens) y una pregunta cancelada mientras esperaba se generaba igual.
  Aqui cada trabajo lleva un Event de cancelacion que se revisa en cada token,
  y los trabajos cancelados en cola se descartan sin generar.

La regla de la version 1 sigue en pie: nada bloqueante dentro de un `async def`.
El pipeline solo se toca desde el hilo del motor; los endpoints async solo
esperan colas de asyncio.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

log = logging.getLogger("glubia.motor")

PRIORIDAD_PRIVADA = 0   # tu UI y tus claves de API pasan primero
PRIORIDAD_PUBLICA = 1   # visitantes del portafolio


class Ocupado(Exception):
    """La cola esta llena: el cliente debe reintentar luego."""


class NoListo(Exception):
    """El modelo aun carga o fallo al cargar."""


class DemasiadoLargo(Exception):
    """El ultimo mensaje (mas el sistema) no cabe en el contexto."""


@dataclass
class Parametros:
    max_new_tokens: int
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 0                # 0 = el del modelo (generation_config.json)
    repetition_penalty: float = 1.05
    stop: Tuple[str, ...] = ()
    max_seg: float = 300.0


class Resultado(NamedTuple):
    texto: str
    tokens_entrada: int
    tokens_salida: int
    ttft_ms: Optional[float]


Mensaje = Dict[str, str]
FabricaBackend = Callable[[object], object]


@dataclass
class Trabajo:
    mensajes: List[Mensaje]
    params: Parametros
    prioridad: int
    origen: str
    loop: asyncio.AbstractEventLoop
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    creado: float = field(default_factory=time.monotonic)
    cancelado: threading.Event = field(default_factory=threading.Event)
    motivo: Optional[str] = None
    terminado: bool = False
    iniciado: bool = False          # ya salio de la cola (lo protege el lock del motor)
    cola: asyncio.Queue[Tuple[str, object]] = field(default_factory=asyncio.Queue)
    al_cancelar: Optional[Callable[[Trabajo], None]] = field(default=None, repr=False)

    def emitir(self, tipo: str, valor: object = None) -> None:
        """Se llama desde el hilo del motor; entrega el evento al bucle async."""
        try:
            self.loop.call_soon_threadsafe(self.cola.put_nowait, (tipo, valor))
        except RuntimeError:
            pass  # el bucle ya cerro (apagado del servidor)

    def cancelar(self, motivo: str = "cliente") -> None:
        if self.cancelado.is_set():
            return
        self.motivo = motivo
        self.cancelado.set()
        if self.al_cancelar is not None:
            self.al_cancelar(self)

    async def siguiente(self, timeout: float) -> Tuple[str, object]:
        evento = await asyncio.wait_for(self.cola.get(), timeout)
        if evento[0] == "fin":
            self.terminado = True
        return evento


class Motor:
    def __init__(self, cfg, fabrica: FabricaBackend):
        self.cfg = cfg
        self._fabrica = fabrica
        self.backend = None
        self.estado = "cargando"          # cargando | listo | error | detenido
        self.error: Optional[str] = None
        self.dispositivo: Optional[str] = None
        self.actual: Optional[Trabajo] = None
        self.ultimo: Dict[str, object] = {}
        self._cola: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._esperando = {PRIORIDAD_PRIVADA: 0, PRIORIDAD_PUBLICA: 0}
        self._activos: Dict[str, Trabajo] = {}
        self._hilo = threading.Thread(target=self._bucle, name="glubia-motor", daemon=True)
        self.salir_si_falla = True

    # ------------------------------------------------------------ ciclo de vida

    def iniciar(self) -> None:
        if not self._hilo.is_alive():
            self._hilo.start()

    def detener(self) -> None:
        self.estado = "detenido"
        with self._lock:
            activos = list(self._activos.values())
        for t in activos:
            t.cancelar("apagado")      # los que esperaban se cierran al momento (_al_cancelar)
        self._cola.put((-1, next(self._seq), None))
        self._hilo.join(timeout=10)

    @property
    def en_cola(self) -> int:
        with self._lock:
            return sum(self._esperando.values())

    def en_cola_de(self, prioridad: int) -> int:
        with self._lock:
            return self._esperando[prioridad]

    # ------------------------------------------------------------ API publica

    def enviar(self, mensajes: List[Mensaje], params: Parametros,
               prioridad: int = PRIORIDAD_PRIVADA, origen: str = "ui") -> Tuple[Trabajo, int]:
        """Encola un trabajo. Llamar desde el bucle async. Devuelve (trabajo, posicion)."""
        if self.estado != "listo":
            raise NoListo(self.estado if self.estado != "error" else f"error: {self.error}")
        trabajo = Trabajo(mensajes=mensajes, params=params, prioridad=prioridad,
                          origen=origen, loop=asyncio.get_running_loop(), al_cancelar=self._al_cancelar)
        with self._lock:
            total = sum(self._esperando.values())
            if total >= self.cfg.cola_max:
                raise Ocupado(f"hay {total} peticiones esperando")
            if prioridad == PRIORIDAD_PUBLICA and self._esperando[PRIORIDAD_PUBLICA] >= self.cfg.publico_cola:
                raise Ocupado("demasiadas preguntas publicas en espera")
            delante = sum(n for p, n in self._esperando.items() if p <= prioridad)
            delante += 1 if self.actual is not None else 0
            self._esperando[prioridad] += 1
            self._activos[trabajo.id] = trabajo
            self._cola.put((prioridad, next(self._seq), trabajo))
        return trabajo, delante

    def cancelar(self, trabajo_id: str) -> bool:
        with self._lock:
            trabajo = self._activos.get(trabajo_id)
        if trabajo is None:
            return False
        trabajo.cancelar("solicitud")
        return True

    def _al_cancelar(self, trabajo: Trabajo) -> None:
        """Si aun esperaba turno, libera su plaza YA y cierra su stream.

        Sin esto, una pregunta cancelada seguia contando en la cola hasta que el
        motor la sacaba, y podia provocar 503 a peticiones nuevas sin motivo.
        """
        with self._lock:
            if trabajo.iniciado:
                return                 # ya esta generando: lo para on_delta en el siguiente token
            trabajo.iniciado = True    # el hilo lo descartara al sacarlo de la cola
            self._esperando[trabajo.prioridad] -= 1
            self._activos.pop(trabajo.id, None)
        trabajo.emitir("fin", self._fin(trabajo, "cancelled"))

    # ------------------------------------------------------------ hilo del motor

    def _bucle(self) -> None:
        try:
            self.backend = self._fabrica(self.cfg)
            self.dispositivo = getattr(self.backend, "dispositivo", "?")
            self.estado = "listo"
            log.info("modelo listo en %s", self.dispositivo)
        except Exception as exc:  # noqa: BLE001
            self.estado = "error"
            self.error = str(exc)
            log.error("no se pudo cargar el modelo: %s", exc)
            if self.salir_si_falla:
                # Sin modelo no hay servicio: salir para que Docker reinicie y
                # el error quede a la vista en `docker compose logs`.
                os._exit(3)
            return

        while True:
            _, _, trabajo = self._cola.get()
            if trabajo is None:
                break
            with self._lock:
                if trabajo.iniciado:   # cancelado mientras esperaba: ya se descontó y se cerró
                    continue
                trabajo.iniciado = True
                self._esperando[trabajo.prioridad] -= 1
            try:
                if trabajo.cancelado.is_set():
                    trabajo.emitir("fin", self._fin(trabajo, "cancelled"))
                    continue
                self.actual = trabajo
                self._ejecutar(trabajo)
            except DemasiadoLargo as exc:
                trabajo.emitir("error", {"codigo": "context_length_exceeded", "mensaje": str(exc)})
                trabajo.emitir("fin", self._fin(trabajo, "error"))
            except Exception as exc:  # noqa: BLE001
                log.exception("fallo generando (%s)", trabajo.origen)
                trabajo.emitir("error", {"codigo": "generation_error", "mensaje": str(exc)})
                trabajo.emitir("fin", self._fin(trabajo, "error"))
            finally:
                self.actual = None
                with self._lock:
                    self._activos.pop(trabajo.id, None)

    @staticmethod
    def _fin(trabajo: Trabajo, motivo: str, **extra) -> Dict[str, object]:
        datos = {"finish_reason": motivo, "texto": "", "tokens_entrada": 0, "tokens_salida": 0,
                 "segundos": 0.0, "tps": 0.0, "ttft_ms": None, "contexto": None}
        datos.update(extra)
        return datos

    def _ejecutar(self, trabajo: Trabajo) -> None:
        p = trabajo.params
        espera = time.monotonic() - trabajo.creado
        mensajes, contexto = self.ajustar_contexto(trabajo.mensajes, p.max_new_tokens)
        trabajo.emitir("inicio", contexto)

        limite = time.monotonic() + p.max_seg
        motivo: Dict[str, Optional[str]] = {"v": None}

        def on_delta(texto: str) -> bool:
            # Tras un STOP el pipeline puede llamar una vez mas para vaciar su
            # buffer: por eso se revisa la cancelacion antes de emitir.
            if trabajo.cancelado.is_set():
                motivo["v"] = motivo["v"] or "cancelled"
                return False
            if time.monotonic() > limite:
                motivo["v"] = motivo["v"] or "timeout"
                return False
            if texto:
                trabajo.emitir("delta", texto)
            return True

        inicio = time.monotonic()
        res: Resultado = self.backend.generar(mensajes, p, on_delta)
        seg = max(time.monotonic() - inicio, 1e-3)
        fin = motivo["v"] or ("length" if res.tokens_salida >= p.max_new_tokens else "stop")
        tps = round(res.tokens_salida / seg, 1)
        self.ultimo = {"tps": tps, "tokens": res.tokens_salida, "segundos": round(seg, 2)}
        log.info("%s: %s | espera %.1fs | %d+%d tokens | %.1fs | %.1f tok/s",
                 trabajo.origen, fin, espera, res.tokens_entrada, res.tokens_salida, seg, tps)
        trabajo.emitir("fin", self._fin(
            trabajo, fin, texto=res.texto, tokens_entrada=res.tokens_entrada,
            tokens_salida=res.tokens_salida, segundos=round(seg, 2), tps=tps,
            ttft_ms=res.ttft_ms, contexto=contexto))

    # ------------------------------------------------------------ contexto

    def ajustar_contexto(self, mensajes: List[Mensaje], max_new_tokens: int
                         ) -> Tuple[List[Mensaje], Dict[str, int]]:
        """Recorta el historial por TOKENS (no por numero de mensajes).

        Se conservan siempre el sistema y la ultima pregunta; despues entran los
        turnos mas recientes que quepan en GLUBIA_CTX - max_new_tokens. Antes se
        cortaba a ciegas en 8 turnos (cliente) y 16 mensajes (servidor), sin
        mirar su tamano: o se olvidaba de mas, o se desbordaba el contexto.
        """
        b = self.backend
        presupuesto = self.cfg.ctx_tokens - max_new_tokens - 8
        sistema = [m for m in mensajes if m["role"] == "system"][:1]
        resto = [m for m in mensajes if m["role"] != "system"]
        if not resto or resto[-1]["role"] != "user":
            raise DemasiadoLargo("el ultimo mensaje debe ser del usuario")

        costos = [b.contar(m["content"]) + b.overhead for m in resto]
        usado = sum(b.contar(m["content"]) + b.overhead for m in sistema) + costos[-1] + 3
        if usado > presupuesto:
            raise DemasiadoLargo(
                f"El mensaje ocupa ~{usado} tokens y solo caben {presupuesto} "
                f"(GLUBIA_CTX={self.cfg.ctx_tokens} menos {max_new_tokens} de respuesta). "
                "Acortalo o baja max_new_tokens.")

        inicio = len(resto) - 1
        for i in range(len(resto) - 2, -1, -1):
            if usado + costos[i] > presupuesto:
                break
            usado += costos[i]
            inicio = i
        # No arrancar el contexto con una respuesta huerfana del asistente.
        while inicio < len(resto) - 1 and resto[inicio]["role"] == "assistant":
            usado -= costos[inicio]
            inicio += 1
        incluidos = resto[inicio:]
        info = {"mensajes": len(incluidos), "omitidos": len(resto) - len(incluidos),
                "tokens_prompt": usado, "presupuesto": presupuesto}
        return sistema + incluidos, info

    # ------------------------------------------------------------ estado

    def resumen(self) -> Dict[str, object]:
        return {
            "estado": self.estado,
            "error": self.error,
            "dispositivo": self.dispositivo,
            "cola": self.en_cola,
            "generando": self.actual is not None,
            "ultimo": self.ultimo,
        }
