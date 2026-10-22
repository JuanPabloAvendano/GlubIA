"""API v1.

* /v1/models y /v1/chat/completions: compatibles con OpenAI. Cualquier cliente
  (SDK de OpenAI, LangChain, curl, n8n...) puede usar GlubIA cambiando base_url.
  Requieren clave de API (Authorization: Bearer glb_...) o la sesion de la UI.
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
from .motor import PRIORIDAD_PRIVADA, Parametros

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
    text: Optional[str] = None


class MensajeOA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: Union[str, List[ParteContenido], None] = None


class SolicitudChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: Optional[str] = None
    messages: List[MensajeOA] = Field(min_length=1, max_length=1000)
    stream: bool = False
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    max_completion_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    stop: Union[str, List[str], None] = None
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


def respuesta_error(request: Request, status: int, mensaje: str, tipo: str = "invalid_request_error",
                    codigo: Optional[str] = None, headers: Optional[dict] = None) -> JSONResponse:
    """Formatea errores segun la ruta: OpenAI en /v1, detail en /api."""
    if request.url.path.startswith("/v1/"):
        cuerpo = {"error": {"message": mensaje, "type": tipo, "code": codigo}}
    else:
        cuerpo = {"detail": mensaje}
    return JSONResponse(cuerpo, status_code=status, headers=headers)
