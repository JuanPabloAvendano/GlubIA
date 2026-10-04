"""Verificacion de identidad en dos pasos (TOTP, RFC 6238).

La contrasena demuestra que conoces algo; el codigo de 6 digitos de tu
aplicacion de autenticacion (Aegis, Google Authenticator, 1Password, Bitwarden...)
demuestra que tienes tu telefono. Con la verificacion activa, iniciar sesion pide
ambas cosas, y el buzon solo acepta sesiones verificadas asi.

Se activa desde la consola del equipo donde corre GlubIA (tener acceso a esa
consola es, en si, la prueba de identidad para dar de alta el telefono):

    python -m glubia.identidad activar        # muestra el codigo QR y la clave
    python -m glubia.identidad estado
    python -m glubia.identidad desactivar

En el contenedor:  docker compose exec glubia python -m glubia.identidad activar

El secreto vive en <GLUBIA_DATA>/identidad.json (permisos 600). Cada codigo solo
vale una vez: se rechaza reutilizarlo aunque siga dentro de su ventana de 30 s.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

PASO = 30
DIGITOS = 6
VENTANA = 1          # acepta el codigo anterior y el siguiente (relojes desfasados)


def generar_secreto() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _clave(secreto: str) -> bytes:
    limpio = re.sub(r"[\s-]", "", secreto).upper()
    return base64.b32decode(limpio + "=" * (-len(limpio) % 8))


def codigo_totp(secreto: str, paso: int, digitos: int = DIGITOS) -> str:
    mac = hmac.new(_clave(secreto), struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = mac[-1] & 0x0F
    numero = (struct.unpack(">I", mac[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF) % (10 ** digitos)
    return str(numero).zfill(digitos)


def uri_otpauth(secreto: str, cuenta: str = "juan", emisor: str = "GlubIA") -> str:
    etiqueta = quote(f"{emisor}:{cuenta}")
    return (f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(emisor)}"
            f"&algorithm=SHA1&digits={DIGITOS}&period={PASO}")


class Identidad:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._lock = threading.Lock()
        self._mtime: Optional[float] = None
        self._datos: dict = {}

    # ------------------------------------------------------------ persistencia

    def _cargar(self) -> dict:
        try:
            mtime = self.ruta.stat().st_mtime
        except OSError:
            self._mtime, self._datos = None, {}
            return self._datos
        if mtime != self._mtime:
            try:
                self._datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._datos = {}
            self._mtime = mtime
        return self._datos

    def _guardar(self, datos: dict) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.ruta)
        self._datos = datos
        self._mtime = self.ruta.stat().st_mtime

    # ------------------------------------------------------------ consulta

    @property
    def activa(self) -> bool:
        with self._lock:
            return bool(self._cargar().get("secreto"))

    def verificar(self, codigo: Optional[str], ahora: Optional[float] = None) -> bool:
        codigo = re.sub(r"\s", "", codigo or "")
        if not re.fullmatch(rf"\d{{{DIGITOS}}}", codigo):
            return False
        actual = int((time.time() if ahora is None else ahora) // PASO)
        with self._lock:
            datos = dict(self._cargar())
            secreto = datos.get("secreto")
            if not secreto:
                return False
            ultimo = int(datos.get("ultimo_paso", -1))
            for desfase in range(-VENTANA, VENTANA + 1):
                paso = actual + desfase
                if paso <= ultimo:
                    continue      # ya usado: un codigo no vale dos veces
                if hmac.compare_digest(codigo_totp(secreto, paso), codigo):
                    datos["ultimo_paso"] = paso
                    self._guardar(datos)
                    return True
        return False

    # ------------------------------------------------------------ alta y baja

    def activar(self, secreto: str, ultimo_paso: int = -1) -> None:
        with self._lock:
            self._guardar({"secreto": secreto, "creado": int(time.time()), "ultimo_paso": ultimo_paso})

    def desactivar(self) -> bool:
        with self._lock:
            if not self._cargar().get("secreto"):
                return False
            self._guardar({})
            return True


# --------------------------------------------------------------------------
# Consola
# --------------------------------------------------------------------------

def _mostrar_qr(uri: str) -> None:
    try:
        import segno
    except ImportError:
        print("  (instala 'segno' para ver aqui el codigo QR; mientras, usa la clave)")
        return
    segno.make(uri, error="m").terminal(compact=True)


def main(argv=None) -> int:
    from .config import cargar_config

    argv = list(sys.argv[1:] if argv is None else argv)
    orden = argv[0] if argv else ""
    if orden not in ("activar", "estado", "desactivar"):
        print(__doc__)
        return 2
    cfg = cargar_config()
    ident = Identidad(cfg.data_dir / "identidad.json")

    if orden == "estado":
        print("Verificacion en dos pasos:", "ACTIVA" if ident.activa else "no activada")
        return 0
    if orden == "desactivar":
        print("Desactivada." if ident.desactivar() else "No estaba activada.")
        return 0

    if ident.activa and "--forzar" not in argv:
        print("Ya esta activa. Para cambiar de telefono: activar --forzar")
        return 1
    secreto = generar_secreto()
    uri = uri_otpauth(secreto, cuenta=cfg.titulo.lower())
    print("\nEscanea este codigo con tu aplicacion de autenticacion:\n")
    _mostrar_qr(uri)
    agrupada = " ".join(secreto[i:i + 4] for i in range(0, len(secreto), 4))
    print(f"\nO escribe la clave a mano (tipo: basada en tiempo, 6 digitos):\n\n   {agrupada}\n")
    usado = -1
    if "--sin-confirmar" not in argv:
        for _ in range(3):
            try:
                codigo = input("Codigo que muestra la aplicacion: ")
            except EOFError:
                print("\nSin consola interactiva: usa 'activar --sin-confirmar'.")
                return 1
            paso = int(time.time() // PASO)
            validos = [paso + d for d in range(-VENTANA, VENTANA + 1)
                       if hmac.compare_digest(codigo_totp(secreto, paso + d), re.sub(r"\s", "", codigo))]
            if validos:
                usado = validos[0]      # el codigo de la confirmacion no sirve luego para entrar
                break
            print("No coincide. Revisa la hora del telefono e intentalo otra vez.")
        else:
            print("No se activo nada.")
            return 1
    ident.activar(secreto, usado)
    print("\nVerificacion en dos pasos ACTIVA. Desde ahora iniciar sesion pide tambien el codigo.")
    print("Guarda la clave en un lugar seguro: si pierdes el telefono, la necesitas para recuperarlo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
