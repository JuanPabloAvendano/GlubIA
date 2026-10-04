"""Rutas del buzon (/buzon y /api/buzon/*).

Acceso: solo con sesion iniciada CON verificacion de identidad (contrasena +
codigo de la aplicacion de autenticacion). Las claves de API no sirven aqui: el
buzon guarda cosas privadas y debe abrirlo una persona, no un script.

Endpoints `def` (no async): escriben en disco y SQLite, que es bloqueante; FastAPI
los ejecuta en su pool de hilos y no frenan la cola del modelo.
"""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .buzon import ErrorBuzon
from .seguridad import COOKIE, anonimizar
from .texto import Texto

log = logging.getLogger("glubia.buzon")
router = APIRouter()


class NuevoEnvio(BaseModel):
    nombre: Texto = Field(min_length=1, max_length=1000)
    tamano: int = Field(ge=0)
    tipo: Texto = Field(default="", max_length=200)
    sha256: str = Field(default="", max_length=64)


class Nota(BaseModel):
    titulo: Texto = Field(default="", max_length=200)
    texto: Texto = Field(min_length=1, max_length=3_000_000)


def _estado(request: Request):
    return request.app.state.glubia


def exigir_identidad(request: Request):
    """Sesion con verificacion en dos pasos. Devuelve el buzon."""
    est = _estado(request)
    if est.buzon is None:
        raise HTTPException(status_code=404, detail="El buzon esta desactivado (GLUBIA_BUZON=0).")
    if not est.cfg.auth:
        raise HTTPException(status_code=403, detail="El buzon necesita autenticacion (GLUBIA_AUTH=1).")
    if not est.identidad.activa:
        raise HTTPException(status_code=403, detail=(
            "Activa primero la verificacion en dos pasos en el equipo de GlubIA: "
            "python -m glubia.identidad activar"))
    if est.sesiones.nivel_token(request.cookies.get(COOKIE)) < 2:
        raise HTTPException(status_code=401, detail="Inicia sesion con tu codigo de verificacion.")
    # Defensa extra contra peticiones de otros sitios (ademas de SameSite=Lax).
    origen = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origen:
        host = request.headers.get("host", "")
        if origen.split("://", 1)[-1] != host:
            raise HTTPException(status_code=403, detail="Origen no permitido")
    return est.buzon


def _error(exc: ErrorBuzon) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/buzon", response_class=HTMLResponse, include_in_schema=False)
def pagina(request: Request) -> HTMLResponse:
    cfg = _estado(request).cfg
    if not cfg.buzon_ui_path.exists():
        return HTMLResponse("<h1>Falta buzon.html</h1>", status_code=500)
    contenido = cfg.buzon_ui_path.read_text(encoding="utf-8").replace("{{TITULO}}", html.escape(cfg.titulo))
    return HTMLResponse(contenido, headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    })


@router.get("/api/buzon")
def listar(buzon=Depends(exigir_identidad)) -> dict:
    return {"envios": buzon.listar(), "uso": buzon.uso(),
            "limites": {"parte_bytes": buzon.parte_bytes, "max_bytes": buzon.max_bytes}}


@router.post("/api/buzon/envios")
def crear(datos: NuevoEnvio, request: Request, buzon=Depends(exigir_identidad)) -> dict:
    try:
        envio = buzon.crear(datos.nombre, datos.tamano, datos.tipo, datos.sha256,
                            origen=anonimizar(_estado(request).ip(request)))
    except ErrorBuzon as exc:
        raise _error(exc) from None
    log.info("buzon: nuevo envio %s (%d bytes)", envio["id"], datos.tamano)
    return envio


@router.put("/api/buzon/envios/{envio}/partes/{n}")
async def parte(envio: str, n: int, request: Request, buzon=Depends(exigir_identidad)) -> dict:
    datos = await request.body()          # ya limitado por LimiteCuerpo
    sha = request.headers.get("x-parte-sha256")
    try:
        return await run_in_threadpool(buzon.escribir_parte, envio, n, datos, sha)
    except ErrorBuzon as exc:
        raise _error(exc) from None


@router.get("/api/buzon/envios/{envio}")
def estado(envio: str, buzon=Depends(exigir_identidad)) -> dict:
    try:
        return buzon.estado(envio)
    except ErrorBuzon as exc:
        raise _error(exc) from None


@router.post("/api/buzon/envios/{envio}/completar")
def completar(envio: str, buzon=Depends(exigir_identidad)) -> dict:
    try:
        datos = buzon.completar(envio)
    except ErrorBuzon as exc:
        raise _error(exc) from None
    log.info("buzon: envio %s completo", envio)
    return datos


@router.get("/api/buzon/envios/{envio}/descargar")
def descargar(envio: str, buzon=Depends(exigir_identidad)) -> FileResponse:
    try:
        ruta, nombre = buzon.archivo(envio)
    except ErrorBuzon as exc:
        raise _error(exc) from None
    # Siempre como descarga y nunca interpretado por el navegador: un .html o
    # .svg subido no puede ejecutar nada en este origen.
    return FileResponse(ruta, media_type="application/octet-stream", filename=nombre,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                                 "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.delete("/api/buzon/envios/{envio}")
def borrar(envio: str, buzon=Depends(exigir_identidad)) -> dict:
    try:
        buzon.borrar(envio)
    except ErrorBuzon as exc:
        raise _error(exc) from None
    return {"ok": True}


@router.post("/api/buzon/notas")
def nota(datos: Nota, request: Request, buzon=Depends(exigir_identidad)) -> dict:
    try:
        return buzon.nota(datos.titulo, datos.texto, origen=anonimizar(_estado(request).ip(request)))
    except ErrorBuzon as exc:
        raise _error(exc) from None


def ruta_es_parte(path: str) -> bool:
    return path.startswith("/api/buzon/envios/") and "/partes/" in path

