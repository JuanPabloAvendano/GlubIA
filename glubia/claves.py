"""Gestion de claves de API.

    python -m glubia.claves crear portafolio     # imprime la clave UNA sola vez
    python -m glubia.claves listar
    python -m glubia.claves revocar portafolio

En el contenedor:
    docker compose exec glubia python -m glubia.claves crear mi-script

Solo se guarda el hash SHA-256 de cada clave en <GLUBIA_DATA>/claves.json.
El servidor relee el archivo al cambiar: no hace falta reiniciar.
"""

from __future__ import annotations

import sys
import time

from .config import cargar_config
from .seguridad import Claves


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("crear", "listar", "revocar"):
        print(__doc__)
        return 2
    cfg = cargar_config()
    claves = Claves(cfg.data_dir / "claves.json")
    orden = argv[0]
    if orden == "listar":
        filas = claves.listar()
        if not filas:
            print("(no hay claves)")
        for c in filas:
            fecha = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["creada"] or 0))
            print(f"{c['nombre']:<24} creada {fecha}")
        return 0
    if len(argv) < 2:
        print(f"Uso: python -m glubia.claves {orden} NOMBRE")
        return 2
    nombre = argv[1]
    if orden == "crear":
        try:
            clave = claves.crear(nombre)
        except ValueError as exc:
            print(exc)
            return 1
        print(f"Clave '{nombre}' creada. Copiala ahora, no se vuelve a mostrar:\n\n  {clave}\n")
        return 0
    if claves.revocar(nombre):
        print(f"Clave '{nombre}' revocada.")
        return 0
    print(f"No existe una clave llamada '{nombre}'.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
