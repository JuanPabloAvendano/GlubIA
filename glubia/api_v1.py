"""API v1.

* /v1/models y /v1/chat/completions: compatibles con OpenAI. Cualquier cliente
  (SDK de OpenAI, LangChain, curl, n8n...) puede usar GlubIA cambiando base_url.
  Requieren clave de API (Authorization: Bearer glb_...) o la sesion de la UI.

* /v1/public/ask y /v1/public/info: lo que consume el portafolio. Sin clave,
  pero con la persona fija (perfil.md), limites por IP, respuestas cortas,
  cola propia de baja prioridad y CORS solo para tus dominios.
  Desactivado salvo GLUBIA_PUBLICO=1.
"""

from __future__ import annotations

import logging
import time
from typing import List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .api_ui import SYSTEM_PROMPT_DEFECTO
from .flujo import CABECERAS_SSE, eventos, recolectar, sse
from .motor import PRIORIDAD_PRIVADA, PRIORIDAD_PUBLICA, Parametros
from .seguridad import anonimizar
from .texto import GuardiaCodigo, Texto, aviso_codigo

log = logging.getLogger("glubia.api")
router = APIRouter(prefix="/v1")


class ErrorAPI(HTTPException):
    """Error con formato OpenAI: {"error": {"message", "type", "code"}}."""

    def __init__(self, status: int, mensaje: str, tipo: str = "invalid_request_error",
                 codigo: Optional[str] = None, headers: Optional[dict] = None):
        super().__init__(status_code=status, detail=mensaje, headers=headers)
        self.tipo = tipo
        self.codigo = codigo


def _estado(request: Request):
    return request.app.state.glubia


def _exigir_clave(request: Request) -> str:
    quien = _estado(request).quien(request)
    if quien is None:
        raise ErrorAPI(401, "Falta una clave de API valida (Authorization: Bearer glb_...).",
                       codigo="invalid_api_key")
    return quien


# --------------------------------------------------------------------------
# OpenAI-compatible
# --------------------------------------------------------------------------

class ParteContenido(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = "text"
    text: Optional[Texto] = None


class MensajeOA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: Union[Texto, List[ParteContenido], None] = None


class SolicitudChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: Optional[Texto] = Field(default=None, max_length=1000)
    messages: List[MensajeOA] = Field(min_length=1, max_length=1000)
    stream: bool = False
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    max_completion_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    stop: Union[Texto, List[Texto], None] = None
    n: Optional[int] = 1
    stream_options: Optional[dict] = None


def _texto(contenido) -> str:
    if contenido is None:
        return ""
    if isinstance(contenido, str):
        return contenido
    return "".join(p.text or "" for p in contenido if p.type in ("text", "input_text"))


def _normalizar(req: SolicitudChat) -> List[dict]:
    if req.n not in (None, 1):
        raise ErrorAPI(400, "Solo se admite n=1.", codigo="unsupported_parameter")
    sistemas, resto = [], []
    for m in req.messages:
        texto = _texto(m.content)
        if m.role in ("system", "developer"):
            if texto.strip():
                sistemas.append(texto.strip())
        elif m.role == "tool":
            raise ErrorAPI(400, "GlubIA no admite herramientas (role=tool).", codigo="unsupported_parameter")
        elif texto.strip() or m.role == "user":
            resto.append({"role": m.role, "content": texto})
    if not resto or resto[-1]["role"] != "user":
        raise ErrorAPI(400, "El ultimo mensaje debe tener role=user.")
    sistema = "\n\n".join(sistemas) if sistemas else SYSTEM_PROMPT_DEFECTO
    return [{"role": "system", "content": sistema}] + resto


def _finish(motivo: str) -> str:
    return "length" if motivo in ("length", "timeout") else "stop"


@router.get("/models")
async def modelos(request: Request, _: str = Depends(_exigir_clave)) -> dict:
    est = _estado(request)
    return {"object": "list", "data": [{
        "id": est.cfg.nombre_modelo, "object": "model", "created": 0, "owned_by": "glubia",
    }]}


@router.post("/chat/completions")
async def chat_completions(req: SolicitudChat, request: Request, quien: str = Depends(_exigir_clave)):
    est = _estado(request)
    cfg = est.cfg
    mensajes = _normalizar(req)
    pedido = req.max_completion_tokens or req.max_tokens or 1024
    params = Parametros(
        max_new_tokens=min(pedido, cfg.max_tokens),
        temperature=0.2 if req.temperature is None else req.temperature,
        top_p=0.9 if req.top_p is None else req.top_p,
        repetition_penalty=1.05,
        stop=tuple([req.stop] if isinstance(req.stop, str) else (req.stop or []))[:4],
        max_seg=cfg.max_seg,
    )
    trabajo, _ = est.motor.enviar(mensajes, params, PRIORIDAD_PRIVADA, "api:" + quien)
    ident = "chatcmpl-" + trabajo.id
    creado = int(time.time())
    modelo = cfg.nombre_modelo

    if not req.stream:
        texto, fin, error = await recolectar(request, trabajo)
        if error:
            if error.get("codigo") == "context_length_exceeded":
                raise ErrorAPI(400, error["mensaje"], codigo="context_length_exceeded")
            raise ErrorAPI(500, error["mensaje"], tipo="server_error", codigo=error.get("codigo"))
        fin = fin or {}
        entrada, salida = int(fin.get("tokens_entrada") or 0), int(fin.get("tokens_salida") or 0)
        return {
            "id": ident, "object": "chat.completion", "created": creado, "model": modelo,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": texto},
                         "finish_reason": _finish(str(fin.get("finish_reason", "stop")))}],
            "usage": {"prompt_tokens": entrada, "completion_tokens": salida,
                      "total_tokens": entrada + salida},
        }

    con_uso = bool((req.stream_options or {}).get("include_usage"))

    def trozo(delta: dict, finish: Optional[str] = None) -> str:
        return sse({"id": ident, "object": "chat.completion.chunk", "created": creado, "model": modelo,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

    async def cuerpo():
        yield trozo({"role": "assistant", "content": ""})
        async for tipo, valor in eventos(request, trabajo):
            if tipo == "delta":
                yield trozo({"content": valor})
            elif tipo == "error":
                yield sse({"error": {"message": valor["mensaje"], "type": "server_error",
                                     "code": valor["codigo"]}})
            elif tipo == "fin":
                yield trozo({}, _finish(str(valor["finish_reason"])))
                if con_uso:
                    e, s = int(valor["tokens_entrada"] or 0), int(valor["tokens_salida"] or 0)
                    yield sse({"id": ident, "object": "chat.completion.chunk", "created": creado,
                               "model": modelo, "choices": [],
                               "usage": {"prompt_tokens": e, "completion_tokens": s, "total_tokens": e + s}})
            elif tipo == "ping":
                yield ": ping\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(cuerpo(), media_type="text/event-stream", headers=CABECERAS_SSE)


# --------------------------------------------------------------------------
# Publico (portafolio)
# --------------------------------------------------------------------------

class MensajePublico(BaseModel):
    role: Literal["user", "assistant"]
    content: Texto = Field(max_length=4000)


class Pregunta(BaseModel):
    message: Texto = Field(min_length=1, max_length=8000)
    history: List[MensajePublico] = Field(default_factory=list, max_length=40)
    stream: bool = True


class ErrorPublico(HTTPException):
    """Error con texto pensado para mostrarse tal cual al visitante."""


def _publico_activo(request: Request):
    est = _estado(request)
    if not est.cfg.publico:
        raise ErrorPublico(status_code=404, detail="El asistente no está activado.")
    datos = est.perfil.obtener()
    if datos is None:
        raise ErrorPublico(status_code=503, detail="El asistente todavía no está configurado.")
    return est, datos


@router.get("/public/info")
async def publico_info(request: Request) -> dict:
    est, (_, nombre, sugerencias) = _publico_activo(request)
    m = est.motor.resumen()
    if m["estado"] == "cargando":
        estado = "loading"
    elif m["estado"] != "listo":
        estado = "offline"
    elif est.motor.en_cola_de(PRIORIDAD_PUBLICA) >= est.cfg.publico_cola:
        estado = "busy"
    else:
        estado = "online"
    return {
        "name": nombre,
        "status": estado,
        "queue": m["cola"],
        "suggestions": sugerencias,
        "limits": {"max_chars": est.cfg.publico_max_chars, "per_minute": est.cfg.publico_rpm,
                   "per_day": est.cfg.publico_dia},
    }


@router.post("/public/ask")
async def publico_preguntar(req: Pregunta, request: Request):
    est, (sistema, nombre, _) = _publico_activo(request)
    cfg = est.cfg
    mensaje = req.message.strip()
    if not mensaje:
        raise ErrorPublico(status_code=400, detail="Escribe una pregunta.")
    if len(mensaje) > cfg.publico_max_chars:
        raise ErrorPublico(status_code=413,
                           detail=f"La pregunta es muy larga (máximo {cfg.publico_max_chars} caracteres).")

    ip = est.ip(request)
    ok, espera = est.limites.permitir("pm:" + ip, cfg.publico_rpm, 60)
    if ok:
        ok, espera = est.limites.permitir("pd:" + ip, cfg.publico_dia, 86400)
        if not ok:
            raise ErrorPublico(status_code=429, headers={"Retry-After": str(espera)},
                               detail="Llegaste al límite de preguntas de hoy. ¡Gracias por el interés!")
    else:
        raise ErrorPublico(status_code=429, headers={"Retry-After": str(espera)},
                           detail=f"Vas muy rápido. Espera {espera} s y vuelve a preguntar.")

    historial = [{"role": m.role, "content": m.content[:1500]}
                 for m in req.history if m.content.strip()][-cfg.publico_historial:] if cfg.publico_historial else []
    mensajes = [{"role": "system", "content": sistema}] + historial + [{"role": "user", "content": mensaje}]
    params = Parametros(max_new_tokens=cfg.publico_tokens, temperature=cfg.publico_temp, top_p=0.9,
                        repetition_penalty=1.05, max_seg=cfg.publico_seg)
    trabajo, posicion = est.motor.enviar(mensajes, params, PRIORIDAD_PUBLICA, "publico")
    log.info("publico: pregunta desde %s (posicion %d)", anonimizar(ip), posicion)

    guardia = GuardiaCodigo()
    if not req.stream:
        texto, fin, error = await recolectar(request, trabajo)
        if error:
            raise ErrorPublico(status_code=500, detail="No pude responder ahora mismo. Intenta de nuevo.")
        texto = guardia.agregar(texto) + guardia.fin()
        if guardia.disparada:
            log.info("publico: respuesta con codigo cortada")
            return {"answer": (texto + "\n\n" + aviso_codigo(nombre)).strip(), "finish_reason": "stop"}
        return {"answer": texto, "finish_reason": (fin or {}).get("finish_reason")}

    async def cuerpo():
        yield sse({"id": trabajo.id, "queue": posicion})
        async for tipo, valor in eventos(request, trabajo):
            if tipo == "delta":
                limpio = guardia.agregar(valor)
                if limpio:
                    yield sse({"delta": limpio})
                if guardia.disparada:
                    trabajo.cancelar("codigo")
                    log.info("publico: respuesta con codigo cortada")
                    yield sse({"delta": "\n\n" + aviso_codigo(nombre)})
                    yield sse({"done": True, "finish_reason": "stop"})
                    return
            elif tipo == "error":
                yield sse({"error": "No pude responder ahora mismo. Intenta de nuevo."})
            elif tipo == "fin":
                resto = guardia.fin()
                if resto:
                    yield sse({"delta": resto})
                yield sse({"done": True, "finish_reason": valor["finish_reason"]})
            elif tipo == "ping":
                yield ": ping\n\n"

    return StreamingResponse(cuerpo(), media_type="text/event-stream", headers=CABECERAS_SSE)


def respuesta_error(request: Request, status: int, mensaje: str, tipo: str = "invalid_request_error",
                    codigo: Optional[str] = None, headers: Optional[dict] = None) -> JSONResponse:
    """Formatea errores segun la ruta: OpenAI en /v1, texto simple en /v1/public, detail en /api."""
    ruta = request.url.path
    if ruta.startswith("/v1/public"):
        cuerpo = {"error": mensaje}
    elif ruta.startswith("/v1/"):
        cuerpo = {"error": {"message": mensaje, "type": tipo, "code": codigo}}
    else:
        cuerpo = {"detail": mensaje}
    return JSONResponse(cuerpo, status_code=status, headers=headers)
