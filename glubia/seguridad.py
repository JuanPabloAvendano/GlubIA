"""Sesiones de la UI, claves de API, IP real del cliente y limites por IP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple

from fastapi import Request

log = logging.getLogger("glubia.seguridad")

COOKIE = "glubia_sesion"


# --------------------------------------------------------------------------
# Secreto de firma y sesiones (mismo formato que la version 1: las cookies
# existentes siguen valiendo si el secreto se conserva).
# --------------------------------------------------------------------------

def cargar_secreto(data_dir: Path, base_dir: Path) -> bytes:
    ruta = data_dir / ".glubia_secret"
    antigua = base_dir / ".glubia_secret"
    try:
        if not ruta.exists() and antigua.exists() and antigua != ruta:
            data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(antigua, ruta)   # migracion desde la v1: no se cierran sesiones
        if ruta.exists():
            datos = ruta.read_bytes().strip()
            if len(datos) >= 32:
                return datos
    except OSError:
        pass
    datos = secrets.token_bytes(48)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
        os.chmod(ruta, 0o600)  # en Windows es un no-op silencioso
    except OSError:
        log.warning("no se pudo guardar %s; las sesiones solo viven en memoria", ruta)
    return datos


class Sesiones:
    def __init__(self, secreto: bytes, password: str, auth: bool, horas: int):
        self.secreto = secreto
        self.auth = auth
        self.horas = horas
        self.generada = auth and not password
        self.password = password or (secrets.token_urlsafe(9) if auth else "")

    def _firmar(self, payload: str) -> str:
        mac = hmac.new(self.secreto, payload.encode("utf-8"), hashlib.sha256).digest()
        return payload + "." + base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")

    def crear_token(self, nivel: int = 1) -> str:
        """nivel 1 = contrasena; nivel 2 = contrasena + codigo de verificacion."""
        expira = int(time.time()) + self.horas * 3600
        return self._firmar(f"{expira}:{secrets.token_urlsafe(8)}:{nivel}")

    def nivel_token(self, token: Optional[str]) -> int:
        """0 si no vale. Los tokens de la v2.0 (sin nivel) cuentan como nivel 1."""
        if not token:
            return 0
        try:
            payload, _ = token.rsplit(".", 1)
            partes = payload.split(":")
            expira = int(partes[0])
            nivel = int(partes[2]) if len(partes) > 2 else 1
        except (ValueError, IndexError):
            return 0
        if not hmac.compare_digest(self._firmar(payload), token):
            return 0
        return nivel if expira > time.time() else 0

    def token_valido(self, token: Optional[str]) -> bool:
        return self.nivel_token(token) > 0

    def password_correcta(self, intento: str) -> bool:
        return hmac.compare_digest(intento.encode("utf-8"), self.password.encode("utf-8"))


# --------------------------------------------------------------------------
# Claves de API (Authorization: Bearer glb_...). Se guardan solo sus hashes.
# --------------------------------------------------------------------------

def _hash(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


class Claves:
    def __init__(self, ruta: Path, desde_env: Tuple[str, ...] = ()):
        self.ruta = ruta
        self._env = {_hash(k): "env" for k in desde_env}
        self._cache: Dict[str, str] = {}
        self._mtime: Optional[float] = None
        self._lock = threading.Lock()

    def _leer(self) -> Dict[str, dict]:
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            return {c["nombre"]: c for c in datos.get("claves", [])}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _escribir(self, claves: Dict[str, dict]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps({"claves": list(claves.values())}, indent=2), encoding="utf-8")
        os.replace(tmp, self.ruta)
        try:
            os.chmod(self.ruta, 0o600)
        except OSError:
            pass

    def _hashes(self) -> Dict[str, str]:
        with self._lock:
            try:
                mtime = self.ruta.stat().st_mtime
            except OSError:
                mtime = None
            if mtime != self._mtime:
                self._cache = {c["hash"]: n for n, c in self._leer().items() if "hash" in c}
                self._mtime = mtime
            return {**self._env, **self._cache}

    def verificar(self, clave: str) -> Optional[str]:
        if not clave:
            return None
        buscado = _hash(clave)
        encontrado = None
        for h, nombre in self._hashes().items():
            if hmac.compare_digest(h, buscado):
                encontrado = nombre
        return encontrado

    def crear(self, nombre: str) -> str:
        claves = self._leer()
        if nombre in claves:
            raise ValueError(f"ya existe una clave llamada '{nombre}'")
        clave = "glb_" + secrets.token_urlsafe(32)
        claves[nombre] = {"nombre": nombre, "hash": _hash(clave), "creada": int(time.time())}
        self._escribir(claves)
        return clave

    def revocar(self, nombre: str) -> bool:
        claves = self._leer()
        if claves.pop(nombre, None) is None:
            return False
        self._escribir(claves)
        return True

    def listar(self) -> list:
        return [{"nombre": n, "creada": c.get("creada")} for n, c in self._leer().items()]


# --------------------------------------------------------------------------
# IP real del cliente
# --------------------------------------------------------------------------

def ip_cliente(request: Request, proxies) -> str:
    """
    * Si la conexion llega de un proxy de confianza (GLUBIA_PROXIES, p. ej. el
      Caddy del compose), se usa X-Real-IP, que ese proxy sobrescribe siempre.
    * Si llega desde loopback (cloudflared en la misma maquina, como en
      iniciar-con-tunel.bat), se usa CF-Connecting-IP, igual que en la v1.
    * En cualquier otro caso, la IP de la conexion. Nadie en la LAN puede
      falsear su IP con cabeceras.
    """
    directa = request.client.host if request.client else "?"
    try:
        ip = ipaddress.ip_address(directa)
    except ValueError:
        return directa
    if proxies and any(ip in red for red in proxies):
        real = request.headers.get("x-real-ip", "").strip()
        if real:
            return real
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[-1].strip()
        return directa
    if ip.is_loopback:
        cf = request.headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf
    return directa


def anonimizar(ip: str) -> str:
    """IP recortada para los logs de visitantes: 181.52.33.7 -> 181.52.x.x.

    Sirve para ver abusos (misma red repitiendo) sin guardar la IP completa de
    nadie en disco. Los limites por IP usan la completa, pero solo en memoria.
    """
    try:
        dir_ip = ipaddress.ip_address(ip)
    except ValueError:
        return "?"
    if dir_ip.version == 4:
        a, b, _, _ = ip.split(".")
        return f"{a}.{b}.x.x"
    return ":".join(dir_ip.exploded.split(":")[:3]) + "::x"


# --------------------------------------------------------------------------
# Limitador por ventana deslizante, con memoria acotada.
# En la v1 el diccionario de intentos fallidos crecia sin limite con cada IP
# nueva (un escaneo desde muchas IPs lo inflaba indefinidamente).
# --------------------------------------------------------------------------

class Limitador:
    def __init__(self, max_claves: int = 10000):
        self._d: OrderedDict[str, Deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_claves

    def _cola(self, clave: str) -> Deque[float]:
        q = self._d.get(clave)
        if q is None:
            q = deque()
            self._d[clave] = q
            while len(self._d) > self._max:
                self._d.popitem(last=False)
        else:
            self._d.move_to_end(clave)
        return q

    def permitir(self, clave: str, limite: int, ventana: float) -> Tuple[bool, int]:
        """Cuenta un intento si cabe. Devuelve (permitido, segundos_para_reintentar)."""
        ahora = time.monotonic()
        with self._lock:
            q = self._cola(clave)
            while q and q[0] <= ahora - ventana:
                q.popleft()
            if len(q) >= limite:
                return False, int(q[0] + ventana - ahora) + 1
            q.append(ahora)
            return True, 0

    def registrar(self, clave: str) -> int:
        with self._lock:
            q = self._cola(clave)
            q.append(time.monotonic())
            return len(q)

    def cuenta(self, clave: str, ventana: float) -> Tuple[int, int]:
        """(eventos en la ventana, segundos hasta que caduque el mas antiguo)."""
        ahora = time.monotonic()
        with self._lock:
            q = self._d.get(clave)
            if not q:
                return 0, 0
            while q and q[0] <= ahora - ventana:
                q.popleft()
            if not q:
                return 0, 0
            return len(q), int(q[0] + ventana - ahora) + 1

    def limpiar(self, clave: str) -> None:
        with self._lock:
            self._d.pop(clave, None)

    def __len__(self) -> int:
        return len(self._d)
