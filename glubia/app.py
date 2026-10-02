"""Ensambla la aplicacion: estado compartido, middlewares, errores y rutas."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from . import __version__
from .api_ui import router as router_ui
from .api_v1 import ErrorAPI, respuesta_error
from .api_v1 import router as router_v1
from .config import Config, cargar_config
from .conversaciones import Conversaciones
from .motor import Motor, NoListo, Ocupado
from .perfil import Perfil
from .seguridad import COOKIE, Claves, Limitador, Sesiones, cargar_secreto, ip_cliente

log = logging.getLogger("glubia")


class Estado:
    """Todo lo que comparten las rutas. Vive en app.state.glubia."""

    def __init__(self, cfg: Config, fabrica=None):
        self.cfg = cfg
        try:
            cfg.data_dir.mkdir(parents=True, exist_ok=True)
            data_ok = True
        except OSError as exc:
            log.warning("no se pudo crear %s (%s): sin persistencia en disco", cfg.data_dir, exc)
            data_ok = False

        self.sesiones = Sesiones(cargar_secreto(cfg.data_dir, cfg.base_dir), cfg.password,
                                 cfg.auth, cfg.sesion_horas)
        self.claves = Claves(cfg.data_dir / "claves.json", cfg.api_keys_env)
        self.conversaciones: Optional[Conversaciones] = None
        if cfg.conversaciones and data_ok:
            try:
                self.conversaciones = Conversaciones(cfg.data_dir / "glubia.db")
            except Exception as exc:  # noqa: BLE001
                log.warning("conversaciones en servidor desactivadas: %s", exc)
        self.perfil = Perfil(cfg.perfil_path, cfg.publico_nombre)
        self.limites = Limitador()
        self.fallos = Limitador()

        if fabrica is None:
            if cfg.motor == "falso":
                from .backend_falso import crear as fabrica
            else:
                from .backend_openvino import crear as fabrica
        self.motor = Motor(cfg, fabrica)

    def ip(self, request: Request) -> str:
        return ip_cliente(request, self.cfg.proxies)

    def quien(self, request: Request) -> Optional[str]:
        """Identidad de quien llama: 'lan', 'sesion', 'clave:<nombre>' o None."""
        if not self.cfg.auth:
            return "lan"
        auth = request.headers.get("authorization", "")
        if auth[:7].lower() == "bearer ":
            nombre = self.claves.verificar(auth[7:].strip())
            if nombre:
                return "clave:" + nombre
        directa = request.headers.get("x-api-key", "").strip()
        if directa:
            nombre = self.claves.verificar(directa)
            if nombre:
                return "clave:" + nombre
        if self.sesiones.token_valido(request.cookies.get(COOKIE)):
            return "sesion"
        return None


# --------------------------------------------------------------------------
# Middlewares ASGI
# --------------------------------------------------------------------------

async def _responder_json(send, status: int, mensaje: str) -> None:
    import json
    cuerpo = json.dumps({"detail": mensaje, "error": mensaje}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(cuerpo)).encode())]})
    await send({"type": "http.response.body", "body": cuerpo})


class LimiteCuerpo:
    """Corta cuerpos enormes ANTES de que FastAPI los lea en memoria.

    El endpoint publico admite 32 KB; el resto, 16 MB (conversaciones largas).
    """

    def __init__(self, app, publico: int = 32 * 1024, general: int = 16 * 1024 * 1024):
        self.app = app
        self.publico = publico
        self.general = general

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE"):
            return await self.app(scope, receive, send)
        limite = self.publico if scope["path"].startswith("/v1/public") else self.general
        cabeceras = dict(scope.get("headers") or [])
        declarado = cabeceras.get(b"content-length")
        if declarado is not None:
            try:
                if int(declarado) > limite:
                    return await _responder_json(send, 413, "Cuerpo de la peticion demasiado grande")
            except ValueError:
                return await _responder_json(send, 400, "Content-Length no valido")

        cuerpo = bytearray()
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            cuerpo += msg.get("body", b"")
            if len(cuerpo) > limite:
                return await _responder_json(send, 413, "Cuerpo de la peticion demasiado grande")
            if not msg.get("more_body", False):
                break

        entregado = False

        async def receive_repetido():
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": bytes(cuerpo), "more_body": False}
            return await receive()   # despues del cuerpo: avisos de desconexion reales

        return await self.app(scope, receive_repetido, send)


class CorsPublico:
    """CORS solo para /v1/public/* y solo para los origenes de GLUBIA_CORS."""

    def __init__(self, app, origenes):
        self.app = app
        self.origenes = list(origenes)
        self.cors = CORSMiddleware(app, allow_origins=self.origenes, allow_methods=["GET", "POST"],
                                   allow_headers=["Content-Type"], max_age=600)

    async def __call__(self, scope, receive, send):
        if self.origenes and scope["type"] == "http" and scope["path"].startswith("/v1/public"):
            return await self.cors(scope, receive, send)
        return await self.app(scope, receive, send)


# --------------------------------------------------------------------------

def configurar_logs(nivel: str) -> None:
    logging.basicConfig(level=getattr(logging, nivel, logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def crear_app(cfg: Optional[Config] = None, fabrica=None, salir_si_falla: bool = True) -> FastAPI:
    cfg = cfg or cargar_config()
    estado = Estado(cfg, fabrica)
    estado.motor.salir_si_falla = salir_si_falla

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        estado.motor.iniciar()   # el modelo carga en su hilo: /healthz responde desde ya
        yield
        estado.motor.detener()

    app = FastAPI(
        title=f"{cfg.titulo} API", version=__version__, lifespan=ciclo, redirect_slashes=False,
        docs_url="/api/docs" if cfg.docs else None, redoc_url=None,
        openapi_url="/api/openapi.json" if cfg.docs else None,
    )
    app.state.glubia = estado

    publico = lambda request: request.url.path.startswith("/v1/public")  # noqa: E731

    @app.exception_handler(Ocupado)
    async def _ocupado(request: Request, exc: Ocupado):
        texto = ("Hay muchas preguntas en espera. Inténtalo de nuevo en unos segundos." if publico(request)
                 else "GlubIA está ocupada respondiendo otras preguntas. Reintenta en unos segundos.")
        return respuesta_error(request, 503, texto, "server_error", "busy", headers={"Retry-After": "5"})

    @app.exception_handler(NoListo)
    async def _no_listo(request: Request, exc: NoListo):
        texto = ("La IA se está despertando. Prueba en un minuto." if publico(request)
                 else f"El modelo aún no está listo ({exc}). Reintenta en unos segundos.")
        return respuesta_error(request, 503, texto, "server_error", "model_loading", headers={"Retry-After": "10"})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if isinstance(exc, ErrorAPI):
            return respuesta_error(request, exc.status_code, str(exc.detail), exc.tipo, exc.codigo,
                                   headers=exc.headers)
        return respuesta_error(request, exc.status_code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/v1/public"):
            return respuesta_error(request, 422, "La pregunta no tiene un formato válido.")
        if request.url.path.startswith("/v1/"):
            primero = exc.errors()[0] if exc.errors() else {}
            campo = ".".join(str(x) for x in primero.get("loc", []) if x != "body")
            return respuesta_error(request, 400, f"Parámetro no válido: {campo} ({primero.get('msg', '')})")
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        m = estado.motor.resumen()
        cuerpo = {"status": m["estado"], "device": m["dispositivo"], "model": cfg.nombre_modelo,
                  "queue": m["cola"], "version": __version__}
        if m["error"]:
            cuerpo["error"] = m["error"]
        return JSONResponse(cuerpo, status_code=200 if m["estado"] == "listo" else 503)

    app.include_router(router_ui)
    app.include_router(router_v1)

    # El ultimo en anadirse es el mas externo.
    app.add_middleware(CorsPublico, origenes=cfg.cors)
    app.add_middleware(LimiteCuerpo)
    return app
