"""Historial de conversaciones en SQLite.

En la v1 el historial vivia solo en el localStorage del navegador: no te seguia
entre el portatil y el movil, se perdia al limpiar datos del navegador y el
limite de ~5 MB hacia fallar el guardado en conversaciones largas. Ahora la UI
lo sincroniza con este almacen (y sigue funcionando sin el).

Los borrados dejan una lapida para que los demas equipos tambien los borren.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional


class Conversaciones:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._lock = threading.Lock()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._con()) as con, con:
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass  # unidades de red o de solo lectura: se queda en modo normal
            con.execute(
                """CREATE TABLE IF NOT EXISTS conversaciones (
                       id TEXT PRIMARY KEY,
                       titulo TEXT NOT NULL DEFAULT '',
                       mensajes TEXT,
                       creada INTEGER NOT NULL,
                       actualizada INTEGER NOT NULL,
                       borrada INTEGER NOT NULL DEFAULT 0)""")

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.ruta, timeout=5)
        return con

    def listar(self, limite: int = 300) -> Dict[str, List]:
        with self._lock, closing(self._con()) as con:
            filas = con.execute(
                "SELECT id, titulo, mensajes, creada, actualizada FROM conversaciones "
                "WHERE borrada = 0 ORDER BY actualizada DESC LIMIT ?", (limite,)).fetchall()
            borradas = con.execute(
                "SELECT id FROM conversaciones WHERE borrada = 1 ORDER BY actualizada DESC LIMIT 1000"
            ).fetchall()
        return {
            "conversations": [
                {"id": f[0], "titulo": f[1], "msgs": json.loads(f[2] or "[]"),
                 "ts": f[3], "actualizada": f[4]} for f in filas],
            "deleted": [f[0] for f in borradas],
        }

    def guardar(self, cid: str, titulo: str, msgs: list, ts: Optional[int],
                actualizada: Optional[int]) -> int:
        ahora = int(time.time() * 1000)
        actualizada = int(actualizada or ahora)
        with self._lock, closing(self._con()) as con, con:
            con.execute(
                """INSERT INTO conversaciones (id, titulo, mensajes, creada, actualizada, borrada)
                   VALUES (?, ?, ?, ?, ?, 0)
                   ON CONFLICT(id) DO UPDATE SET titulo = excluded.titulo,
                       mensajes = excluded.mensajes, actualizada = excluded.actualizada, borrada = 0
                   WHERE excluded.actualizada >= conversaciones.actualizada""",
                (cid, titulo, json.dumps(msgs, ensure_ascii=False), int(ts or ahora), actualizada))
        return actualizada

    def borrar(self, cid: str) -> None:
        ahora = int(time.time() * 1000)
        with self._lock, closing(self._con()) as con, con:
            con.execute(
                """INSERT INTO conversaciones (id, titulo, mensajes, creada, actualizada, borrada)
                   VALUES (?, '', NULL, ?, ?, 1)
                   ON CONFLICT(id) DO UPDATE SET mensajes = NULL, titulo = '',
                       actualizada = excluded.actualizada, borrada = 1""",
                (cid, ahora, ahora))
