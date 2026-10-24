"""Ajustes que se cambian desde el panel de admin y sobreviven a los reinicios.

Viven en <GLUBIA_DATA>/ajustes.json. Las variables de entorno dan los valores
de partida; lo que guardes en el panel manda sobre ellas. Si el archivo se
rompe, GlubIA arranca con los valores del entorno (nunca se queda sin modelo).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger("glubia.ajustes")

SYSTEM_INVITADO = (
    "Eres GlubIA, un asistente tecnico que corre en el equipo personal de Juan. "
    "Ahora hablas con un invitado al que Juan dio acceso temporal.\n"
    "Ayudas con programacion, Linux, arquitectura de software y seguridad defensiva. "
    "Responde en el idioma del invitado, de forma clara y concisa."
)


def defectos(cfg) -> Dict[str, Any]:
    return {
        "modelo": None,                     # id del catalogo; None = el del entorno
        "ollama": {"gpu": cfg.ollama_gpu, "pensar": cfg.ollama_pensar, "keep": cfg.ollama_keep},
        "openvino": {"device": cfg.device},
        "invitados": {
            "modelos": [],                  # ids que un invitado puede elegir
            "cambiar_modelo": True,         # si puede cambiar el modelo activo (entre los permitidos)
            "max_tokens": 1024,
            "rpm": 8,                       # mensajes por minuto por invitado
            "system": SYSTEM_INVITADO,
        },
    }


def _fusionar(base: dict, encima: dict) -> dict:
    """Mezcla recursiva que solo acepta claves conocidas (lo que sobra se ignora)."""
    out = copy.deepcopy(base)
    for k, v in (encima or {}).items():
        if k not in out:
            continue
        if isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _fusionar(out[k], v)
        else:
            out[k] = v
    return out


class Ajustes:
    def __init__(self, ruta: Path, cfg):
        self.ruta = ruta
        self._defecto = defectos(cfg)
        self._lock = threading.Lock()
        self._datos = self._leer()

    def _leer(self) -> Dict[str, Any]:
        try:
            return _fusionar(self._defecto, json.loads(self.ruta.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return copy.deepcopy(self._defecto)
        except (OSError, ValueError) as exc:
            log.warning("ajustes.json ilegible (%s): se usan los valores del entorno", exc)
            return copy.deepcopy(self._defecto)

    def todo(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._datos)

    def get(self, seccion: str) -> Any:
        with self._lock:
            return copy.deepcopy(self._datos[seccion])

    def actualizar(self, cambios: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._datos = _fusionar(self._datos, cambios)
            try:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.ruta.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._datos, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.ruta)
            except OSError as exc:
                log.warning("no se pudieron guardar los ajustes (%s): solo duran hasta reiniciar", exc)
            return copy.deepcopy(self._datos)
