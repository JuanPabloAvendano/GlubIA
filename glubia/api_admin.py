"""Panel de admin y selector de modelo.

Todo cambio sobre el equipo (modelo activo, descargas, ajustes, invitados) pasa
por aqui, con la sesion de admin comprobada en el servidor. El modelo de IA no
tiene ninguna via para llamar a estas rutas: no tiene herramientas.

    GET  /api/modelos                 catalogo (el invitado ve solo los permitidos)
    POST /api/modelos/activar         cambiar el modelo activo
    GET  /api/admin/estado            todo lo que pinta el panel
    PUT  /api/admin/ajustes           GPU/CPU, pensar, permisos de invitados...
    POST /api/admin/modelos/descargar         ollama pull
    DELETE /api/admin/modelos/{id}            ollama rm
    POST /api/admin/invitados         crear invitacion (el codigo se ve una vez)
    DELETE /api/admin/invitados/{id}  revocar
"""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .catalogo import ModeloInvalido, id_de

log = logging.getLogger("glubia.admin")
router = APIRouter()


def _estado(request: Request):
    return request.app.state.glubia


def es_admin(quien: Optional[str]) -> bool:
    return quien in ("sesion", "lan")


def exigir_sesion(request: Request) -> str:
    quien = _estado(request).quien(request)
    if quien is None:
        raise HTTPException(status_code=401, detail="Sesión no válida")
    if quien.startswith("clave:"):
        raise HTTPException(status_code=403, detail="Las claves de API no administran GlubIA")
    return quien


def exigir_admin(quien: str = Depends(exigir_sesion)) -> str:
    if not es_admin(quien):
        raise HTTPException(status_code=403, detail="Solo el admin puede hacer esto")
    return quien


# --------------------------------------------------------------------------
# Selector de modelo (admin e invitados con permiso)
# --------------------------------------------------------------------------

class Activar(BaseModel):
    id: str = Field(min_length=3, max_length=200)


def _resumen_modelos(est, quien: str) -> dict:
    cat = est.catalogo.listar()
    activo = id_de(est.cfg)
    m = est.motor.resumen()
    inv = est.ajustes.get("invitados")
    datos = {"activo": activo, "estado": m["estado"], "dispositivo": m["dispositivo"],
             "cambio": est.motor.cambio, "modelos": cat["modelos"], "error_ollama": cat["error_ollama"],
             "puede_cambiar": True}
    if not es_admin(quien):
        permitidos = set(inv["modelos"]) | {activo}
        datos["modelos"] = [{k: x.get(k) for k in ("id", "nombre", "parametros", "motor")}
                            for x in cat["modelos"] if x["id"] in permitidos]
        datos["puede_cambiar"] = bool(inv["cambiar_modelo"])
        datos["error_ollama"] = None
        datos["cambio"] = {k: est.motor.cambio.get(k) for k in ("modelo", "estado")}
    return datos


@router.get("/api/modelos")
def modelos(request: Request, quien: str = Depends(exigir_sesion)) -> dict:
    return _resumen_modelos(_estado(request), quien)


def activar_modelo(est, id_modelo: str, quien: str) -> None:
    try:
        cfg = est.catalogo.cfg_para(id_modelo, est.ajustes.todo())
    except ModeloInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not est.catalogo.existe(id_modelo):
        raise HTTPException(status_code=404, detail="Ese modelo no está instalado")
    est.motor.cambiar(cfg, quien)
    est.ajustes.actualizar({"modelo": id_modelo})
    est.auditoria.registrar("cambio_modelo", quien, modelo=id_modelo)
    log.info("[%s] cambio de modelo -> %s", quien, id_modelo)


@router.post("/api/modelos/activar")
def activar(datos: Activar, request: Request, quien: str = Depends(exigir_sesion)) -> dict:
    est = _estado(request)
    if not es_admin(quien):
        inv = est.ajustes.get("invitados")
        if not inv["cambiar_modelo"] or datos.id not in inv["modelos"]:
            raise HTTPException(status_code=403, detail="No tienes permiso para usar ese modelo")
        ok, espera = est.ritmo.permitir("cambio:" + quien, 1, 60)
        if not ok:
            raise HTTPException(status_code=429, detail=f"Espera {espera} s para volver a cambiar de modelo")
    if datos.id == id_de(est.cfg) and est.motor.estado == "listo":
        return {"ok": True, "sin_cambios": True}
    activar_modelo(est, datos.id, quien)
    return {"ok": True}


# --------------------------------------------------------------------------
# Panel de admin
# --------------------------------------------------------------------------

class AjOllama(BaseModel):
    gpu: Optional[bool] = None
    pensar: Optional[bool] = None
    keep: Optional[str] = Field(default=None, pattern=r"^(-1|0|\d{1,4}[smh])$")


class AjOpenvino(BaseModel):
    device: Optional[Literal["GPU", "CPU", "AUTO", "NPU"]] = None


class AjInvitados(BaseModel):
    modelos: Optional[List[str]] = Field(default=None, max_length=50)
    cambiar_modelo: Optional[bool] = None
    max_tokens: Optional[int] = Field(default=None, ge=64, le=8192)
    rpm: Optional[int] = Field(default=None, ge=1, le=120)
    system: Optional[str] = Field(default=None, min_length=1, max_length=8000)


class AjustesIn(BaseModel):
    ollama: Optional[AjOllama] = None
    openvino: Optional[AjOpenvino] = None
    invitados: Optional[AjInvitados] = None


class Descarga(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)


class NuevaInvitacion(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    horas: float = Field(default=2, gt=0, le=24 * 30)


@router.get("/api/admin/estado")
def panel(request: Request, quien: str = Depends(exigir_admin)) -> dict:
    est = _estado(request)
    return {
        "modelos": _resumen_modelos(est, quien),
        "ajustes": est.ajustes.todo(),
        "descargas": est.catalogo.descargas(),
        "invitados": est.invitados.listar(),
        "auditoria": est.auditoria.ultimos(60),
    }


@router.put("/api/admin/ajustes")
def guardar_ajustes(datos: AjustesIn, request: Request, quien: str = Depends(exigir_admin)) -> dict:
    est = _estado(request)
    cambios = datos.model_dump(exclude_none=True)
    for seccion in ("ollama", "openvino", "invitados"):
        if seccion in cambios and not cambios[seccion]:
            del cambios[seccion]
    nuevos = est.ajustes.actualizar(cambios)
    est.auditoria.registrar("ajustes", quien, secciones=sorted(cambios))
    # GPU/CPU, pensar o dispositivo afectan al modelo cargado: se recarga con ellos.
    if est.cfg.motor in cambios:
        activar_modelo(est, id_de(est.cfg), quien)
    return nuevos


@router.post("/api/admin/modelos/descargar")
def descargar(datos: Descarga, request: Request, quien: str = Depends(exigir_admin)) -> dict:
    est = _estado(request)
    try:
        estado = est.catalogo.descargar(datos.nombre)
    except ModeloInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    est.auditoria.registrar("descarga", quien, modelo=datos.nombre)
    return estado


@router.delete("/api/admin/modelos/{id_modelo:path}")
def borrar_modelo(id_modelo: str, request: Request, quien: str = Depends(exigir_admin)) -> dict:
    est = _estado(request)
    motor, _, nombre = id_modelo.partition(":")
    if motor != "ollama":
        raise HTTPException(status_code=400, detail="Solo se borran desde aquí modelos de Ollama")
    if id_modelo == id_de(est.cfg):
        raise HTTPException(status_code=409, detail="Es el modelo activo: cambia a otro antes de borrarlo")
    try:
        est.catalogo.borrar(nombre)
    except ModeloInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    inv = est.ajustes.get("invitados")
    if id_modelo in inv["modelos"]:
        est.ajustes.actualizar({"invitados": {"modelos": [m for m in inv["modelos"] if m != id_modelo]}})
    est.auditoria.registrar("borrado", quien, modelo=id_modelo)
    return {"ok": True}


@router.post("/api/admin/invitados")
def crear_invitacion(datos: NuevaInvitacion, request: Request, quien: str = Depends(exigir_admin)) -> dict:
    est = _estado(request)
    inv = est.invitados.crear(datos.nombre, datos.horas)
    est.auditoria.registrar("invitacion", quien, invitado=inv["nombre"], id=inv["id"], expira=inv["expira"])
    return inv


@router.delete("/api/admin/invitados/{inv_id}")
def revocar_invitacion(inv_id: str, request: Request, quien: str = Depends(exigir_admin)) -> dict:
    est = _estado(request)
    if not est.invitados.revocar(inv_id):
        raise HTTPException(status_code=404, detail="No existe esa invitación")
    est.auditoria.registrar("revocada", quien, id=inv_id)
    return {"ok": True}

