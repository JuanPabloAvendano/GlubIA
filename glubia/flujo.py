"""Ayudas para consumir un Trabajo desde un endpoint async (con o sin SSE).

Detectan cuando el cliente se va (boton Detener, pestana cerrada, timeout de un
proxy) y cancelan el trabajo en el motor. En la v1 esto dependia de que el
recolector de basura cerrara un generador sincrono, y en la practica con
Starlette 1.6 / uvicorn 0.52 nunca ocurria: la GPU seguia hasta max_new_tokens.
"""

from __future__ import annotations

import json
import time
from typing import AsyncIterator, Dict, Optional, Tuple

from fastapi import Request

from .motor import Trabajo

CABECERAS_SSE = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse(obj: object) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


async def eventos(request: Request, trabajo: Trabajo, revisar_cada: float = 1.0,
                  ping_cada: float = 10.0) -> AsyncIterator[Tuple[str, object]]:
    """Itera los eventos del trabajo. Emite ("ping", None) si hay silencio
    (mientras espera en cola) para que proxies y tuneles no corten la conexion."""
    ultimo = revisado = time.monotonic()
    try:
        while True:
            try:
                tipo, valor = await trabajo.siguiente(revisar_cada)
            except TimeoutError:
                tipo, valor = None, None
            ahora = time.monotonic()
            # Se mira si el cliente sigue ahi cada `revisar_cada` segundos aunque lleguen
            # tokens sin parar: en las respuestas sin streaming no hay otra forma de saberlo
            # (antes, una peticion abandonada seguia ocupando el modelo hasta el final).
            if ahora - revisado >= revisar_cada:
                revisado = ahora
                if await request.is_disconnected():
                    trabajo.cancelar("desconexion")
                    return
            if tipo is None:
                if ahora - ultimo >= ping_cada:
                    ultimo = ahora
                    yield "ping", None
                continue
            ultimo = ahora
            yield tipo, valor
            if tipo == "fin":
                return
    finally:
        # Cubre GeneratorExit/CancelledError (Starlette cancela el stream al
        # detectar la desconexion) y cualquier salida anticipada.
        if not trabajo.terminado:
            trabajo.cancelar("desconexion")


async def recolectar(request: Request, trabajo: Trabajo
                     ) -> Tuple[str, Optional[Dict[str, object]], Optional[Dict[str, str]]]:
    """Para respuestas no-stream: (texto, datos_fin, error)."""
    partes = []
    fin: Optional[Dict[str, object]] = None
    error: Optional[Dict[str, str]] = None
    async for tipo, valor in eventos(request, trabajo):
        if tipo == "delta":
            partes.append(valor)
        elif tipo == "error":
            error = valor  # type: ignore[assignment]
        elif tipo == "fin":
            fin = valor  # type: ignore[assignment]
    texto = (fin or {}).get("texto") or "".join(partes)
    return str(texto).strip(), fin, error
