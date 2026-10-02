"""Apaga la telemetria de OpenVINO.

Verificado con openvino 2026.3: importar openvino_genai carga openvino_telemetry
y, si no existe el archivo de consentimiento, lo da por ACEPTADO y envia eventos
de uso a www.google-analytics.com al crear el pipeline. No viajan las
conversaciones, pero algo sale de la maquina, y eso contradice la promesa de
GlubIA. Con el archivo en "0" no se envia nada.

Ojo: se escribe el archivo directamente. `opt_in_out --opt_out` tambien sirve,
pero manda un ultimo evento avisando del cambio.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("glubia")


def archivo_consentimiento() -> Path | None:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "")
        sub = "Intel Corporation"
    else:
        base = str(Path.home())
        sub = "intel"
    if not base or not os.path.isdir(base):
        return None
    return Path(base) / sub / "openvino_telemetry"


def desactivar_telemetria_openvino(permitir: bool = False) -> None:
    """Debe llamarse ANTES de importar openvino u openvino_genai."""
    if permitir:
        return
    ruta = archivo_consentimiento()
    if ruta is None:
        return
    try:
        if ruta.exists() and ruta.read_text(encoding="utf-8").strip() == "0":
            return
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("0", encoding="utf-8")
        log.info("[privacidad] telemetria de OpenVINO desactivada (%s)", ruta)
    except OSError as exc:
        log.warning("[privacidad] no se pudo desactivar la telemetria de OpenVINO: %s", exc)
