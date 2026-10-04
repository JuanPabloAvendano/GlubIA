"""Buzon: recibir cualquier archivo o nota en el equipo donde corre GlubIA.

Pensado para mandarte cosas a ti mismo desde cualquier sitio (el movil, otro
equipo, a traves del tunel): chats, documentos, comprimidos, lo que sea.

Decisiones:
* Subida por PARTES (8 MiB por defecto). Cloudflare corta cualquier peticion de
  mas de 100 MB en los planes Free y Pro; con partes no hay limite practico de
  tamano y una subida cortada se reanuda donde quedo.
* Nada se ejecuta ni se descomprime: los archivos solo se guardan. Un .zip se
  queda como .zip (evita bombas de descompresion y rutas maliciosas dentro).
* El nombre que manda el cliente nunca decide la ruta en disco: se sanea y va
  detras del identificador del envio.
* Lo que llega al buzon NO lo lee la IA. Es almacenamiento privado; si quieres
  que GlubIA use algo, lo mueves tu a su conocimiento.
* Integridad: SHA-256 del archivo completo (y, si el cliente la manda, de cada parte).
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RESERVADOS_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                      *(f"LPT{i}" for i in range(1, 10))}
MAX_NOTA = 2 * 1024 * 1024


class ErrorBuzon(Exception):
    """Error con mensaje para el usuario y codigo HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.status = status


def sanear_nombre(nombre: str, maximo: int = 150) -> str:
    nombre = unicodedata.normalize("NFC", nombre or "")
    nombre = nombre.replace("\\", "/").split("/")[-1]                       # sin carpetas
    nombre = "".join(c for c in nombre if c.isprintable() and c not in '<>:"|?*')
    nombre = re.sub(r"\s+", " ", nombre).strip().strip(".").strip()          # sin "..", sin ocultos
    if not nombre:
        nombre = "archivo"
    base, ext = os.path.splitext(nombre)
    if base.upper() in RESERVADOS_WINDOWS:
        base = "_" + base
    ext = ext[:16]
    return (base[: maximo - len(ext)] or "archivo") + ext


class Buzon:
    def __init__(self, raiz: Path, parte_bytes: int, max_bytes: int, cuota_bytes: int,
                 reserva_bytes: int):
        self.raiz = raiz
        self.parte_bytes = parte_bytes
        self.max_bytes = max_bytes
        self.cuota_bytes = cuota_bytes
        self.reserva_bytes = reserva_bytes
        self.parciales = raiz / "parciales"
        self.archivos = raiz / "archivos"
        for d in (self.parciales, self.archivos):
            d.mkdir(parents=True, exist_ok=True)
        self._db = raiz / "indice.db"
        self._lock = threading.Lock()                   # metadatos
        self._locks: Dict[str, threading.Lock] = {}     # escritura por envio
        with closing(self._con()) as con, con:
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            con.execute("""CREATE TABLE IF NOT EXISTS envios (
                id TEXT PRIMARY KEY, tipo TEXT NOT NULL, nombre TEXT NOT NULL,
                tamano INTEGER NOT NULL, mime TEXT, sha256 TEXT, sha256_cliente TEXT,
                estado TEXT NOT NULL, ruta TEXT, creado INTEGER NOT NULL,
                completado INTEGER, origen TEXT)""")
            con.execute("""CREATE TABLE IF NOT EXISTS partes (
                envio TEXT NOT NULL, n INTEGER NOT NULL, bytes INTEGER NOT NULL,
                PRIMARY KEY (envio, n))""")
        self.limpiar_abandonados()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------------------------------------ utilidades

    def partes_de(self, tamano: int) -> int:
        return (tamano + self.parte_bytes - 1) // self.parte_bytes

    def _bytes_parte(self, tamano: int, n: int) -> int:
        return min(self.parte_bytes, tamano - n * self.parte_bytes)

    def _lock_de(self, envio: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(envio, threading.Lock())

    def _fila(self, con: sqlite3.Connection, envio: str) -> sqlite3.Row:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", envio or ""):
            raise ErrorBuzon("Identificador no valido", 400)
        fila = con.execute("SELECT * FROM envios WHERE id = ?", (envio,)).fetchone()
        if fila is None:
            raise ErrorBuzon("Ese envio no existe", 404)
        return fila

    def _ruta_final(self, envio: str, nombre: str) -> Path:
        carpeta = self.archivos / time.strftime("%Y-%m-%d")
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = (carpeta / f"{envio[:8]}-{nombre}").resolve()
        if not ruta.is_relative_to(self.archivos.resolve()):     # defensa extra
            raise ErrorBuzon("Nombre de archivo no valido", 400)
        return ruta

    def uso(self) -> Dict[str, int]:
        with closing(self._con()) as con:
            usado = con.execute("SELECT COALESCE(SUM(tamano), 0) FROM envios").fetchone()[0]
        libre = shutil.disk_usage(self.raiz).free
        return {"usado": int(usado), "cuota": self.cuota_bytes, "libre_disco": int(libre),
                "reserva": self.reserva_bytes}

    @staticmethod
    def _publico(fila: sqlite3.Row, recibidas: Optional[int] = None) -> Dict[str, object]:
        datos = {k: fila[k] for k in ("id", "tipo", "nombre", "tamano", "mime", "sha256",
                                      "estado", "creado", "completado")}
        if recibidas is not None:
            datos["partes_recibidas"] = recibidas
        return datos

    # ------------------------------------------------------------ subida

    def crear(self, nombre: str, tamano: int, mime: str = "", sha256: str = "",
              origen: str = "") -> Dict[str, object]:
        if tamano < 0:
            raise ErrorBuzon("Tamano no valido")
        if tamano > self.max_bytes:
            raise ErrorBuzon(f"El archivo supera el maximo de {self.max_bytes // 1048576} MB por envio", 413)
        if sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            raise ErrorBuzon("sha256 no valido")
        self.limpiar_abandonados()
        u = self.uso()
        if u["usado"] + tamano > self.cuota_bytes:
            raise ErrorBuzon("El buzon esta lleno (cuota). Borra envios antiguos o sube GLUBIA_BUZON_CUOTA_GB.", 507)
        if u["libre_disco"] - tamano < self.reserva_bytes:
            raise ErrorBuzon("No queda espacio libre suficiente en el disco del equipo.", 507)

        envio = secrets.token_urlsafe(12)
        limpio = sanear_nombre(nombre)
        parcial = self.parciales / f"{envio}.part"
        with open(parcial, "wb") as f:
            f.truncate(tamano)                       # reserva (dispersa) del tamano final
        with self._lock, closing(self._con()) as con, con:
            con.execute("""INSERT INTO envios (id, tipo, nombre, tamano, mime, sha256_cliente,
                           estado, ruta, creado, origen) VALUES (?, 'archivo', ?, ?, ?, ?, 'subiendo', ?, ?, ?)""",
                        (envio, limpio, tamano, (mime or "")[:120], sha256.lower() or None,
                         str(parcial), int(time.time()), origen))
        return {"id": envio, "nombre": limpio, "tamano": tamano, "parte_bytes": self.parte_bytes,
                "partes": self.partes_de(tamano)}

    def escribir_parte(self, envio: str, n: int, datos: bytes,
                       sha256_parte: Optional[str] = None) -> Dict[str, object]:
        with closing(self._con()) as con:
            fila = self._fila(con, envio)
        if fila["estado"] != "subiendo":
            raise ErrorBuzon("Ese envio ya no admite partes", 409)
        total = self.partes_de(fila["tamano"])
        if not 0 <= n < total:
            raise ErrorBuzon(f"Parte fuera de rango (0..{total - 1})", 400)
        esperado = self._bytes_parte(fila["tamano"], n)
        if len(datos) != esperado:
            raise ErrorBuzon(f"La parte {n} debe tener {esperado} bytes y llegaron {len(datos)}", 400)
        if sha256_parte and hashlib.sha256(datos).hexdigest() != sha256_parte.lower():
            raise ErrorBuzon(f"La parte {n} llego danada (sha256 distinto): reenviala", 422)

        with self._lock_de(envio):
            with open(fila["ruta"], "r+b") as f:
                f.seek(n * self.parte_bytes)
                f.write(datos)
            with self._lock, closing(self._con()) as con, con:
                con.execute("INSERT OR REPLACE INTO partes (envio, n, bytes) VALUES (?, ?, ?)",
                            (envio, n, len(datos)))
                recibidas = con.execute("SELECT COUNT(*) FROM partes WHERE envio = ?", (envio,)).fetchone()[0]
        return {"id": envio, "parte": n, "partes_recibidas": recibidas, "partes": total}

    def estado(self, envio: str) -> Dict[str, object]:
        with closing(self._con()) as con:
            fila = self._fila(con, envio)
            hechas = {r[0] for r in con.execute("SELECT n FROM partes WHERE envio = ?", (envio,))}
        total = self.partes_de(fila["tamano"])
        datos = self._publico(fila, len(hechas))
        datos.update({"partes": total, "parte_bytes": self.parte_bytes,
                      "faltan": [n for n in range(total) if n not in hechas][:5000]})
        return datos

    def completar(self, envio: str) -> Dict[str, object]:
        with self._lock_de(envio):
            info = self.estado(envio)
            if info["estado"] == "completo":
                return info
            if info["estado"] != "subiendo":
                raise ErrorBuzon("Ese envio no se puede completar", 409)
            if info["faltan"]:
                raise ErrorBuzon(f"Faltan {len(info['faltan'])} partes", 409)
            with closing(self._con()) as con:
                fila = self._fila(con, envio)
            h = hashlib.sha256()
            with open(fila["ruta"], "rb") as f:
                for bloque in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(bloque)
            digest = h.hexdigest()
            if fila["sha256_cliente"] and fila["sha256_cliente"] != digest:
                raise ErrorBuzon("El archivo completo no coincide con el sha256 enviado: vuelve a subirlo", 422)
            final = self._ruta_final(envio, fila["nombre"])
            os.replace(fila["ruta"], final)
            with self._lock, closing(self._con()) as con, con:
                con.execute("""UPDATE envios SET estado = 'completo', sha256 = ?, ruta = ?, completado = ?
                               WHERE id = ?""", (digest, str(final), int(time.time()), envio))
                con.execute("DELETE FROM partes WHERE envio = ?", (envio,))
        with self._lock:
            self._locks.pop(envio, None)
        return self.estado(envio)

    # ------------------------------------------------------------ notas

    def nota(self, titulo: str, texto: str, origen: str = "") -> Dict[str, object]:
        datos = texto.encode("utf-8")
        if not datos.strip():
            raise ErrorBuzon("La nota esta vacia")
        if len(datos) > MAX_NOTA:
            raise ErrorBuzon("La nota es muy larga (maximo 2 MB); mandala como archivo", 413)
        titulo = (titulo or "").strip() or time.strftime("Nota %Y-%m-%d %H:%M")
        contenido = f"# {titulo}\n\n> Recibida {time.strftime('%Y-%m-%d %H:%M')}\n\n{texto}\n".encode()
        envio = secrets.token_urlsafe(12)
        nombre = sanear_nombre(titulo, 100)
        if not nombre.lower().endswith((".md", ".txt")):
            nombre += ".md"
        final = self._ruta_final(envio, nombre)
        final.write_bytes(contenido)
        ahora = int(time.time())
        with self._lock, closing(self._con()) as con, con:
            con.execute("""INSERT INTO envios (id, tipo, nombre, tamano, mime, sha256, estado, ruta,
                           creado, completado, origen) VALUES (?, 'nota', ?, ?, 'text/markdown', ?,
                           'completo', ?, ?, ?, ?)""",
                        (envio, nombre, len(contenido), hashlib.sha256(contenido).hexdigest(),
                         str(final), ahora, ahora, origen))
        return self.estado(envio)

    # ------------------------------------------------------------ consulta y borrado

    def listar(self, limite: int = 500) -> List[Dict[str, object]]:
        with closing(self._con()) as con:
            filas = con.execute("SELECT * FROM envios ORDER BY creado DESC LIMIT ?", (limite,)).fetchall()
            cuentas = dict(con.execute("SELECT envio, COUNT(*) FROM partes GROUP BY envio").fetchall())
        salida = []
        for f in filas:
            d = self._publico(f, cuentas.get(f["id"], 0) if f["estado"] == "subiendo" else None)
            if f["estado"] == "subiendo":
                d["partes"] = self.partes_de(f["tamano"])
            salida.append(d)
        return salida

    def archivo(self, envio: str) -> Tuple[Path, str]:
        with closing(self._con()) as con:
            fila = self._fila(con, envio)
        if fila["estado"] != "completo":
            raise ErrorBuzon("El envio aun no esta completo", 409)
        ruta = Path(fila["ruta"])
        if not ruta.is_file():
            raise ErrorBuzon("El archivo ya no esta en el disco", 410)
        return ruta, fila["nombre"]

    def borrar(self, envio: str) -> None:
        with self._lock_de(envio):
            with closing(self._con()) as con:
                fila = self._fila(con, envio)
            try:
                Path(fila["ruta"]).unlink()
            except FileNotFoundError:
                pass
            with self._lock, closing(self._con()) as con, con:
                con.execute("DELETE FROM envios WHERE id = ?", (envio,))
                con.execute("DELETE FROM partes WHERE envio = ?", (envio,))
        with self._lock:
            self._locks.pop(envio, None)

    def limpiar_abandonados(self, horas: float = 24) -> int:
        """Borra subidas sin terminar y sin actividad en las ultimas `horas`."""
        limite = time.time() - horas * 3600
        with closing(self._con()) as con:
            viejos = [r["id"] for r in con.execute(
                "SELECT id, ruta FROM envios WHERE estado = 'subiendo' AND creado < ?", (int(limite),))
                if not Path(r["ruta"]).exists() or Path(r["ruta"]).stat().st_mtime < limite]
        for envio in viejos:
            self.borrar(envio)
        return len(viejos)
