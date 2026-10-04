"""Configuracion por variables de entorno.

Todas las rutas por defecto son relativas a la carpeta del proyecto, asi que la
carpeta se puede mover o copiar sin tocar nada (igual que en la version 1).
En el contenedor se fijan GLUBIA_DATA=/data y GLUBIA_MODEL=/modelos/...
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

BASE_DIR = Path(__file__).resolve().parent.parent

Red = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


def _texto(nombre: str, defecto: str = "") -> str:
    valor = os.environ.get(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip()


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.environ.get(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() not in ("0", "false", "no", "off")


def _entero(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    try:
        valor = int(_texto(nombre, str(defecto)))
    except ValueError:
        raise SystemExit(f"{nombre} debe ser un numero entero") from None
    return max(minimo, min(maximo, valor))


def _decimal(nombre: str, defecto: float, minimo: float, maximo: float) -> float:
    try:
        valor = float(_texto(nombre, str(defecto)))
    except ValueError:
        raise SystemExit(f"{nombre} debe ser un numero") from None
    return max(minimo, min(maximo, valor))


def _lista(nombre: str) -> Tuple[str, ...]:
    return tuple(x.strip() for x in _texto(nombre).split(",") if x.strip())


def _redes(nombre: str) -> Tuple[Red, ...]:
    redes = []
    for item in _lista(nombre):
        try:
            redes.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise SystemExit(f"{nombre}: '{item}' no es una IP ni una red valida") from None
    return tuple(redes)


def _json(nombre: str) -> Optional[Dict[str, Any]]:
    """Objeto JSON en una variable de entorno; None si no esta definida."""
    valor = _texto(nombre)
    if not valor:
        return None
    try:
        datos = json.loads(valor)
    except ValueError as exc:
        raise SystemExit(f"{nombre} no es JSON valido: {exc}") from None
    if not isinstance(datos, dict):
        raise SystemExit(f"{nombre} debe ser un objeto JSON, por ejemplo {{\"CLAVE\": \"valor\"}}")
    return datos


def _ruta(nombre: str, defecto: Path) -> Path:
    valor = _texto(nombre)
    return Path(valor).expanduser() if valor else defecto


@dataclass(frozen=True)
class Config:
    base_dir: Path
    data_dir: Path
    motor: str
    model_path: Path
    device: str
    host: str
    port: int
    titulo: str
    auth: bool
    password: str
    sesion_horas: int
    # Generacion
    ctx_tokens: int
    max_tokens: int
    max_seg: int
    cola_max: int
    cache_ov: bool
    pipeline: str                       # auto | llm | vlm
    ov_config: Dict[str, Any]           # propiedades extra de OpenVINO (GLUBIA_OV_CONFIG)
    plantilla_extra: Optional[Dict[str, Any]]   # contexto de la plantilla; None = automatico
    # Red y acceso
    proxies: Tuple[Red, ...]
    api_keys_env: Tuple[str, ...]
    conversaciones: bool
    docs: bool
    # Endpoint publico (portafolio)
    publico: bool
    precalentar: bool
    perfil_path: Path
    publico_nombre: str
    publico_tokens: int
    publico_temp: float
    publico_rpm: int
    publico_dia: int
    publico_cola: int
    publico_seg: int
    publico_max_chars: int
    publico_historial: int
    cors: Tuple[str, ...]
    # Buzon (envio de archivos con verificacion de identidad)
    buzon: bool
    buzon_dir: Path
    buzon_max_mb: int
    buzon_cuota_gb: float
    buzon_reserva_gb: float
    buzon_parte_mb: int
    # Varios
    telemetria_ov: bool
    log_nivel: str
    falso_retardo: float

    @property
    def ui_path(self) -> Path:
        return self.base_dir / "ui.html"

    @property
    def buzon_ui_path(self) -> Path:
        return self.base_dir / "buzon.html"

    @property
    def nombre_modelo(self) -> str:
        return "glubia-falso" if self.motor == "falso" else self.model_path.name


def _pipeline() -> str:
    valor = _texto("GLUBIA_PIPELINE", "auto").lower()
    if valor not in ("auto", "llm", "vlm"):
        raise SystemExit("GLUBIA_PIPELINE debe ser 'auto', 'llm' o 'vlm'")
    return valor


def cargar_config() -> Config:
    motor = _texto("GLUBIA_MOTOR", "openvino").lower()
    if motor not in ("openvino", "falso"):
        raise SystemExit("GLUBIA_MOTOR debe ser 'openvino' o 'falso'")

    data_dir = _ruta("GLUBIA_DATA", BASE_DIR / "datos")
    return Config(
        base_dir=BASE_DIR,
        data_dir=data_dir,
        motor=motor,
        model_path=_ruta("GLUBIA_MODEL", BASE_DIR / "modelo_qwen_7b_ov"),
        device=_texto("GLUBIA_DEVICE", "GPU").upper(),
        host=_texto("GLUBIA_HOST", "0.0.0.0"),
        port=_entero("GLUBIA_PORT", 11434, 1, 65535),
        titulo=_texto("GLUBIA_TITULO", "GlubIA"),
        auth=_bool("GLUBIA_AUTH", True),
        password=os.environ.get("GLUBIA_PASS", "").strip(),
        sesion_horas=_entero("GLUBIA_HORAS", 8, 1, 24 * 30),
        ctx_tokens=_entero("GLUBIA_CTX", 8192, 1024, 32768),
        max_tokens=_entero("GLUBIA_MAX_TOKENS", 4096, 16, 8192),
        max_seg=_entero("GLUBIA_MAX_SEG", 300, 10, 3600),
        cola_max=_entero("GLUBIA_COLA", 8, 1, 200),
        cache_ov=_bool("GLUBIA_CACHE_OV", True),
        pipeline=_pipeline(),
        ov_config=_json("GLUBIA_OV_CONFIG") or {},
        plantilla_extra=_json("GLUBIA_PLANTILLA_EXTRA"),
        proxies=_redes("GLUBIA_PROXIES"),
        api_keys_env=_lista("GLUBIA_API_KEYS"),
        conversaciones=_bool("GLUBIA_CONVERSACIONES", True),
        docs=_bool("GLUBIA_DOCS", True),
        publico=_bool("GLUBIA_PUBLICO", False),
        precalentar=_bool("GLUBIA_PRECALENTAR", True),
        perfil_path=_ruta("GLUBIA_PERFIL", BASE_DIR / "portafolio" / "perfil" / "perfil.md"),
        publico_nombre=_texto("GLUBIA_PUBLICO_NOMBRE"),
        publico_tokens=_entero("GLUBIA_PUBLICO_TOKENS", 350, 32, 2048),
        publico_temp=_decimal("GLUBIA_PUBLICO_TEMP", 0.3, 0.0, 1.5),
        publico_rpm=_entero("GLUBIA_PUBLICO_RPM", 6, 1, 600),
        publico_dia=_entero("GLUBIA_PUBLICO_DIA", 80, 1, 100000),
        publico_cola=_entero("GLUBIA_PUBLICO_COLA", 3, 1, 100),
        publico_seg=_entero("GLUBIA_PUBLICO_SEG", 90, 10, 600),
        publico_max_chars=_entero("GLUBIA_PUBLICO_MAX_CHARS", 600, 50, 4000),
        publico_historial=_entero("GLUBIA_PUBLICO_HISTORIAL", 6, 0, 20),
        cors=_lista("GLUBIA_CORS"),
        buzon=_bool("GLUBIA_BUZON", True),
        buzon_dir=_ruta("GLUBIA_BUZON_DIR", data_dir / "buzon"),
        buzon_max_mb=_entero("GLUBIA_BUZON_MAX_MB", 10240, 1, 1024 * 1024),
        buzon_cuota_gb=_decimal("GLUBIA_BUZON_CUOTA_GB", 100.0, 0.1, 100000.0),
        buzon_reserva_gb=_decimal("GLUBIA_BUZON_RESERVA_GB", 10.0, 0.0, 100000.0),
        # Cloudflare corta cualquier peticion de mas de 100 MB (planes Free y Pro):
        # las partes deben quedar por debajo con margen.
        buzon_parte_mb=_entero("GLUBIA_BUZON_PARTE_MB", 8, 1, 90),
        telemetria_ov=_bool("GLUBIA_TELEMETRIA_OV", False),
        log_nivel=_texto("GLUBIA_LOG", "INFO").upper(),
        falso_retardo=_decimal("GLUBIA_FALSO_RETARDO", 0.02, 0.0, 5.0),
    )
