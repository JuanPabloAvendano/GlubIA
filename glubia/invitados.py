"""Invitaciones: acceso temporal y revocable para alguien a quien supervisas.

* El admin crea una invitacion con nombre y duracion; el codigo se muestra UNA
  vez y solo se guarda su hash (igual que las claves de API).
* El codigo es de un solo uso: al canjearlo se emite una cookie de invitado que
  caduca con la invitacion. Si se filtra despues, ya no sirve.
* Cada peticion del invitado vuelve a comprobar aqui que la invitacion sigue
  activa: revocar corta el acceso al instante, sin esperar a que caduque la cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # sin 0/O ni 1/I/L: se dicta sin errores
MAX_HORAS = 24 * 30


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.strip().upper().replace("-", "").encode()).hexdigest()


def _codigo() -> str:
    crudo = "".join(secrets.choice(ALFABETO) for _ in range(16))
    return "-".join(crudo[i:i + 4] for i in range(0, 16, 4))


class Invitados:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._lock = threading.Lock()
        self._d: Dict[str, dict] = self._leer()

    def _leer(self) -> Dict[str, dict]:
        try:
            return {i["id"]: i for i in json.loads(self.ruta.read_text(encoding="utf-8"))["invitaciones"]}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _escribir(self) -> None:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.ruta.with_suffix(".tmp")
            tmp.write_text(json.dumps({"invitaciones": list(self._d.values())}, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.ruta)
            os.chmod(self.ruta, 0o600)
        except OSError:
            pass

    def crear(self, nombre: str, horas: float) -> dict:
        horas = max(0.25, min(float(horas), MAX_HORAS))
        codigo = _codigo()
        inv = {"id": secrets.token_hex(6), "nombre": nombre.strip()[:60] or "invitado",
               "hash": _hash(codigo), "creada": int(time.time()),
               "expira": int(time.time() + horas * 3600), "canjeada": None, "revocada": False,
               "ultimo_uso": None}
        with self._lock:
            self._d[inv["id"]] = inv
            self._purgar()
            self._escribir()
        return {**self._publica(inv), "codigo": codigo}

    def canjear(self, codigo: str) -> Optional[dict]:
        """Codigo correcto, vigente y sin usar -> la invitacion (y queda usada)."""
        buscado = _hash(codigo or "")
        with self._lock:
            for inv in self._d.values():
                if inv["hash"] and hmac.compare_digest(inv["hash"], buscado):
                    if inv["canjeada"] or inv["revocada"] or inv["expira"] <= time.time():
                        return None
                    inv["canjeada"] = int(time.time())
                    inv["hash"] = ""            # un solo uso: ni siquiera queda el hash
                    self._escribir()
                    return self._publica(inv)
        return None

    def activa(self, inv_id: str) -> Optional[dict]:
        with self._lock:
            inv = self._d.get(inv_id)
            if not inv or inv["revocada"] or inv["expira"] <= time.time():
                return None
            ahora = int(time.time())
            if not inv["ultimo_uso"] or ahora - inv["ultimo_uso"] > 60:
                inv["ultimo_uso"] = ahora       # se escribe como mucho una vez por minuto
                self._escribir()
            return self._publica(inv)

    def revocar(self, inv_id: str) -> bool:
        with self._lock:
            inv = self._d.get(inv_id)
            if not inv:
                return False
            inv["revocada"], inv["hash"] = True, ""
            self._escribir()
            return True

    def listar(self) -> List[dict]:
        with self._lock:
            return sorted((self._publica(i) for i in self._d.values()), key=lambda i: -i["creada"])

    def _purgar(self) -> None:
        """Olvida las invitaciones terminadas hace mas de 30 dias."""
        limite = time.time() - 30 * 86400
        for k in [k for k, i in self._d.items() if i["expira"] < limite]:
            del self._d[k]

    @staticmethod
    def _publica(inv: dict) -> dict:
        ahora = time.time()
        if inv["revocada"]:
            estado = "revocada"
        elif inv["expira"] <= ahora:
            estado = "caducada"
        elif inv["canjeada"]:
            estado = "en uso"
        else:
            estado = "sin usar"
        return {k: inv[k] for k in ("id", "nombre", "creada", "expira", "canjeada", "ultimo_uso")} | {
            "estado": estado}
