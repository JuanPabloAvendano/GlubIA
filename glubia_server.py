#!/usr/bin/env python3
"""
GlubIA - lanzador compatible.

iniciar.bat, iniciar.sh e iniciar-con-tunel.bat siguen llamando a este archivo,
pero el codigo vive ahora en el paquete glubia/ (ver README.md):

    python glubia_server.py      equivale a      python -m glubia

La version 1 completa queda como referencia en respaldo_v1/glubia_server.py.
"""

from glubia.__main__ import main

if __name__ == "__main__":
    main()
