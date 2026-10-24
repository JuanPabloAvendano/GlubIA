"""Rutas de la interfaz web. Compatibles con la v1: ui.html antiguo sigue funcionando."""

from __future__ import annotations

import html
import logging
import re
import time
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .api_admin import es_admin
from .flujo import CABECERAS_SSE, eventos, recolectar, sse
from .guardia import Vigia, analizar, firma_valida, firmar, nuevo_canario, sistema_invitado
from .motor import PRIORIDAD_INVITADO, PRIORIDAD_PRIVADA, Parametros
from .seguridad import COOKIE, anonimizar

log = logging.getLogger("glubia.ui")
router = APIRouter()

SYSTEM_PROMPT_DEFECTO = (
    "Eres un Arquitecto de Software y Especialista en Sistemas Linux Debian y "
    "Ciberseguridad.\n"
    "Tu objetivo es responder dudas sobre administracion de Linux, scripts "
    "Bash/Python, patrones de diseno y seguridad.\n"
    "Reglas:\n"
    "- Responde de forma tecnica, precisa y concisa.\n"
    "- Proporciona codigo limpio listo para copiar, siempre dentro de bloques "
    "``` con el lenguaje indicado.\n"
    "- Limitate exclusivamente a tareas de desarrollo, administracion de Linux "
    "y arquitectura de software."
)

MAX_TEXTO = 200_000


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_TEXTO)
    firma: Optional[str] = Field(default=None, max_length=64)   # solo la emite el servidor


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_TEXTO)
    history: List[Message] = Field(default_factory=list, max_length=400)
    system: Optional[str] = Field(default=None, max_length=20_000)
    max_new_tokens: int = Field(default=1024, ge=16, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class LoginRequest(BaseModel):
    password: str = Field(default="", max_length=500)
    codigo: str = Field(default="", max_length=40)      # invitacion de invitado


class CancelRequest(BaseModel):
    id: str = Field(max_length=64)


class MensajeGuardado(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_TEXTO)
    err: Optional[bool] = None
    detenido: Optional[bool] = None
    firma: Optional[str] = Field(default=None, max_length=64)


class ConversacionIn(BaseModel):
    titulo: str = Field(default="", max_length=300)
    msgs: List[MensajeGuardado] = Field(default_factory=list, max_length=4000)
    ts: Optional[int] = None
    actualizada: Optional[int] = None


ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _estado(request: Request):
    return request.app.state.glubia


def exigir_acceso(request: Request) -> str:
    quien = _estado(request).quien(request)
    if quien is None:
        raise HTTPException(status_code=401, detail="Sesión no válida")
    return quien


def _mensajes(req: PromptRequest) -> List[dict]:
    sistema = (req.system or SYSTEM_PROMPT_DEFECTO).strip()
    mensajes = [{"role": "system", "content": sistema}]
    mensajes += [{"role": m.role, "content": m.content} for m in req.history if m.content.strip()]
    mensajes.append({"role": "user", "content": req.prompt})
    return mensajes


def _params(est, req: PromptRequest) -> Parametros:
    return Parametros(max_new_tokens=min(req.max_new_tokens, est.cfg.max_tokens),
                      temperature=req.temperature, top_p=0.9, repetition_penalty=1.05,
                      max_seg=est.cfg.max_seg)


class Peticion:
    """Lo que el servidor decide enviar al modelo, segun quien pregunta.

    Admin: tal cual (su prompt de sistema, su temperatura). Invitado: el prompt
    de sistema lo pone el servidor (politica + el del admin + canario), se ignora
    el que mande el navegador, los turnos del asistente sin firma valida se
    descartan, se quitan caracteres invisibles y se aplican sus limites.
    """

    def __init__(self, est, req: PromptRequest, quien: str, request: Request):
        self.quien = quien
        self.vigia: Optional[Vigia] = None
        self.est = est
        if es_admin(quien) or quien.startswith("clave:"):
            self.mensajes, self.params = _mensajes(req), _params(est, req)
            self.prioridad, self.origen = PRIORIDAD_PRIVADA, "ui"
            return

        inv = est.ajustes.get("invitados")
        ip = anonimizar(est.ip(request))
        bloqueado, espera = est.ritmo.cuenta("alerta:" + quien, 600)
        if bloqueado >= 3:
            raise HTTPException(status_code=429, headers={"Retry-After": str(espera)},
                                detail="Acceso pausado por intentos de saltarse las reglas. "
                                       f"Reintenta en {espera // 60 + 1} min.")
        ok, espera = est.ritmo.permitir("msg:" + quien, int(inv["rpm"]), 60)
        if not ok:
            raise HTTPException(status_code=429, headers={"Retry-After": str(espera)},
                                detail=f"Demasiados mensajes seguidos. Espera {espera} s.")

        prompt, alertas = analizar(req.prompt)
        historial, descartados = [], 0
        for m in req.history:
            if m.role == "assistant" and not firma_valida(est.secreto, m.content, m.firma or ""):
                descartados += 1             # turno del asistente fabricado o alterado
                continue
            texto = analizar(m.content)[0] if m.role == "user" else m.content
            if texto.strip():
                historial.append({"role": m.role, "content": texto})
        if descartados:
            alertas.append("historial_sin_firma")
        if alertas:
            est.auditoria.registrar("alerta", quien, ip=ip, alertas=alertas, extracto=req.prompt[:300])
            if "frase_de_inyeccion" in alertas or "inyeccion_codificada" in alertas:
                est.ritmo.registrar("alerta:" + quien)

        canario = nuevo_canario()
        sistema = sistema_invitado(inv["system"], canario)
        self.vigia = Vigia(canario)
        self.mensajes = ([{"role": "system", "content": sistema}]
                         + historial + [{"role": "user", "content": prompt}])
        self.params = Parametros(max_new_tokens=min(req.max_new_tokens, int(inv["max_tokens"]), est.cfg.max_tokens),
                                 temperature=0.3, top_p=0.9, repetition_penalty=1.05, max_seg=est.cfg.max_seg)
        self.prioridad, self.origen = PRIORIDAD_INVITADO, quien

    def fuga(self, texto: str, prompt: str = "") -> bool:
        """True si la salida filtra el prompt de sistema. Lo registra y cuenta como reincidencia."""
        if self.vigia is None or not self.vigia.fuga(texto):
            return False
        self.est.auditoria.registrar("fuga_de_prompt", self.quien, extracto=prompt[:300])
        self.est.ritmo.registrar("alerta:" + self.quien)
        return True


# --------------------------------------------------------------------------
# Interfaz y estado
# --------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
async def raiz(request: Request) -> HTMLResponse:
    cfg = _estado(request).cfg
    if not cfg.ui_path.exists():
        return HTMLResponse("<h1>Falta ui.html</h1><p>Debe estar junto a glubia_server.py.</p>",
                            status_code=500)
    contenido = cfg.ui_path.read_text(encoding="utf-8").replace("{{TITULO}}", html.escape(cfg.titulo))
    return HTMLResponse(contenido, headers={
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    })


@router.get("/health")
@router.get("/api/health")
@router.get("/api/chat/health")
async def health(request: Request) -> dict:
    est = _estado(request)
    m = est.motor.resumen()
    listo = m["estado"] == "listo"
    return {
        "status": "ok",
        "ready": listo,
        "state": m["estado"],
        "message": "Servidor IA Activo" if listo else f"Modelo {m['estado']}",
        "app": est.cfg.titulo,
        "version": __version__,
        "model": est.cfg.nombre_modelo,
        "device": m["dispositivo"] or "-",
        "queue": m["cola"],
        "busy": m["generando"],
        "streaming": True,
        "auth": est.cfg.auth,
    }


@router.get("/api/session")
async def sesion(request: Request) -> dict:
    est = _estado(request)
    quien = est.quien(request)
    admin = es_admin(quien)
    datos = {
        "auth_required": est.cfg.auth,
        "authenticated": quien is not None,
        "rol": "admin" if admin else ("invitado" if quien and quien.startswith("invitado:") else None),
        "system_prompt": SYSTEM_PROMPT_DEFECTO if admin else "",
        "version": __version__,
        "conversations": est.conversaciones is not None and admin,
        "ctx_tokens": est.cfg.ctx_tokens,
        "max_tokens": est.cfg.max_tokens,
    }
    if quien and quien.startswith("invitado:"):
        inv = est.invitados.activa(quien.split(":", 1)[1]) or {}
        aj = est.ajustes.get("invitados")
        datos["invitado"] = {"nombre": inv.get("nombre"), "expira": inv.get("expira"),
                             "puede_cambiar_modelo": aj["cambiar_modelo"],
                             "max_tokens": min(int(aj["max_tokens"]), est.cfg.max_tokens)}
    return datos


@router.post("/api/login")
def login(datos: LoginRequest, request: Request, response: Response) -> dict:
    est = _estado(request)
    if not est.cfg.auth:
        return {"ok": True, "auth_required": False}
    ip = est.ip(request)
    fallos, restante = est.fallos.cuenta("login:" + ip, 15 * 60)
    if fallos >= 5:
        raise HTTPException(status_code=429,
                            detail=f"Demasiados intentos fallidos. Reintenta en {restante // 60 + 1} min.",
                            headers={"Retry-After": str(restante)})
    if datos.codigo:
        inv = est.invitados.canjear(datos.codigo)
        if inv is None:
            n = est.fallos.registrar("login:" + ip)
            log.warning("[auth] codigo de invitado no valido desde %s (%d/5)", ip, n)
            raise HTTPException(status_code=401, detail="Invitación no válida, ya usada o caducada")
        est.fallos.limpiar("login:" + ip)
        segundos = max(60, inv["expira"] - int(time.time()))
        response.set_cookie(COOKIE, est.sesiones.crear_token(invitado=inv["id"], expira=inv["expira"]),
                            max_age=segundos, httponly=True, samesite="lax", path="/")
        est.auditoria.registrar("entrada_invitado", "invitado:" + inv["id"], invitado=inv["nombre"],
                                ip=anonimizar(ip))
        log.info("[auth] invitado %s entro desde %s", inv["nombre"], anonimizar(ip))
        return {"ok": True, "rol": "invitado"}
    if not est.sesiones.password_correcta(datos.password):
        n = est.fallos.registrar("login:" + ip)
        log.warning("[auth] intento fallido desde %s (%d/5)", ip, n)
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    est.fallos.limpiar("login:" + ip)
    # Sin Secure a proposito: la misma cookie debe servir en la LAN (http) y a
    # traves del tunel (https). SameSite=Lax basta al ser todo mismo origen.
    response.set_cookie(COOKIE, est.sesiones.crear_token(), max_age=est.cfg.sesion_horas * 3600,
                        httponly=True, samesite="lax", path="/")
    log.info("[auth] sesion iniciada desde %s", ip)
    return {"ok": True, "rol": "admin"}


@router.post("/api/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------

@router.post("/api/chat")
@router.post("/api/chat/")
async def chat(req: PromptRequest, request: Request, quien: str = Depends(exigir_acceso)) -> JSONResponse:
    est = _estado(request)
    pet = Peticion(est, req, quien, request)
    trabajo, _ = est.motor.enviar(pet.mensajes, pet.params, pet.prioridad, pet.origen)
    texto, fin, error = await recolectar(request, trabajo)
    if error:
        codigo = 400 if error.get("codigo") == "context_length_exceeded" else 500
        return JSONResponse({"detail": error["mensaje"]}, status_code=codigo)
    if pet.fuga(texto, req.prompt):
        texto = "No puedo hacer eso aquí."
    fin = fin or {}
    return JSONResponse({
        "status": "ok",
        "response": texto,
        "firma": firmar(est.secreto, texto),
        "seconds": fin.get("segundos"),
        "device": est.motor.dispositivo,
        "tokens": fin.get("tokens_salida"),
        "tps": fin.get("tps"),
        "finish_reason": fin.get("finish_reason"),
        "context": fin.get("contexto"),
    })


@router.post("/api/chat/stream")
@router.post("/api/chat/stream/")
async def chat_stream(req: PromptRequest, request: Request,
                      quien: str = Depends(exigir_acceso)) -> StreamingResponse:
    est = _estado(request)
    pet = Peticion(est, req, quien, request)
    trabajo, posicion = est.motor.enviar(pet.mensajes, pet.params, pet.prioridad, pet.origen)

    async def cuerpo():
        yield sse({"id": trabajo.id, "queue": posicion})
        acumulado = ""
        async for tipo, valor in eventos(request, trabajo):
            if tipo == "delta":
                acumulado += valor
                if pet.fuga(acumulado, req.prompt):
                    # El prompt de sistema se esta filtrando: se corta, se avisa y se registra.
                    trabajo.cancelar("fuga")
                    yield sse({"error": "Respuesta cortada por seguridad.", "code": "blocked"})
                    yield sse({"done": True, "tokens": 0, "seconds": 0, "tps": 0, "finish_reason": "blocked",
                               "context": None})
                    return
                yield sse({"delta": valor})
            elif tipo == "inicio":
                yield sse({"context": valor})
            elif tipo == "error":
                yield sse({"error": valor["mensaje"], "code": valor["codigo"]})
            elif tipo == "fin":
                yield sse({"done": True, "tokens": valor["tokens_salida"], "seconds": valor["segundos"],
                           "tps": valor["tps"], "finish_reason": valor["finish_reason"],
                           "context": valor["contexto"], "firma": firmar(est.secreto, acumulado)})
            elif tipo == "ping":
                yield ": ping\n\n"

    return StreamingResponse(cuerpo(), media_type="text/event-stream", headers=CABECERAS_SSE)


@router.post("/api/chat/cancel")
async def chat_cancel(datos: CancelRequest, request: Request, quien: str = Depends(exigir_acceso)) -> dict:
    origen = None if es_admin(quien) else quien      # un invitado solo detiene lo suyo
    return {"ok": _estado(request).motor.cancelar(datos.id, origen)}


@router.get("/api/chat")
@router.get("/api/chat/")
async def chat_get_fallback() -> dict:
    return {"status": "ok", "message": "Endpoint de chat listo para recibir peticiones POST."}


# --------------------------------------------------------------------------
# Conversaciones sincronizadas (def: SQLite es bloqueante y rapido -> pool)
# --------------------------------------------------------------------------

# La sesion se comprueba como dependencia: antes de validar el cuerpo (401, no 422).
def _almacen(request: Request, quien: str = Depends(exigir_acceso)):
    if not es_admin(quien):
        raise HTTPException(status_code=403, detail="Las conversaciones en el servidor son solo del admin")
    almacen = _estado(request).conversaciones
    if almacen is None:
        raise HTTPException(status_code=404, detail="Conversaciones en el servidor desactivadas")
    return almacen


@router.get("/api/conversations")
def conversaciones_listar(almacen=Depends(_almacen)) -> dict:
    return almacen.listar()


@router.put("/api/conversations/{cid}")
def conversaciones_guardar(cid: str, datos: ConversacionIn, almacen=Depends(_almacen)) -> dict:
    if not ID_VALIDO.match(cid):
        raise HTTPException(status_code=400, detail="Identificador no valido")
    msgs = [m.model_dump(exclude_none=True) for m in datos.msgs]
    act = almacen.guardar(cid, datos.titulo, msgs, datos.ts, datos.actualizada)
    return {"ok": True, "actualizada": act}


@router.delete("/api/conversations/{cid}")
def conversaciones_borrar(cid: str, almacen=Depends(_almacen)) -> dict:
    if not ID_VALIDO.match(cid):
        raise HTTPException(status_code=400, detail="Identificador no valido")
    almacen.borrar(cid)
    return {"ok": True}
