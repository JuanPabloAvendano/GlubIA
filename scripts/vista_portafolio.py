#!/usr/bin/env python3
"""
Vista previa local del portafolio, sin Docker ni Caddy (Windows o Linux).

Sirve portafolio/sitio y reenvia /api/preguntar y /api/info a GlubIA, igual que
portafolio/Caddyfile en el puerto 8080. Solo biblioteca estandar.

    # consola 1 (motor falso: no necesita modelo ni GPU)
    set GLUBIA_MOTOR=falso & set GLUBIA_PUBLICO=1 & python glubia_server.py
    # consola 2
    python scripts/vista_portafolio.py            # http://127.0.0.1:8080

    python scripts/vista_portafolio.py --puerto 8090 --glubia http://127.0.0.1:11434
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTAS = {"/api/preguntar": "/v1/public/ask", "/api/info": "/v1/public/info"}
SALTAR = {"transfer-encoding", "connection", "content-length", "server", "date"}


class Manejador(http.server.SimpleHTTPRequestHandler):
    glubia = "http://127.0.0.1:11434"

    def log_message(self, formato, *args):  # silencioso
        pass

    def _reenviar(self, destino: str) -> None:
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else None
        peticion = urllib.request.Request(
            self.glubia + destino, data=cuerpo, method=self.command,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            respuesta = urllib.request.urlopen(peticion, timeout=300)
        except urllib.error.HTTPError as exc:
            respuesta = exc
        except OSError:
            self.send_error(502, "GlubIA no responde")
            return
        self.send_response(respuesta.status)
        for clave, valor in respuesta.headers.items():
            if clave.lower() not in SALTAR:
                self.send_header(clave, valor)
        self.send_header("Connection", "close")
        self.end_headers()
        while True:   # streaming: se reenvia cada trozo en cuanto llega
            trozo = respuesta.read1(4096)
            if not trozo:
                break
            self.wfile.write(trozo)
            self.wfile.flush()

    def do_GET(self):
        if self.path in RUTAS:
            return self._reenviar(RUTAS[self.path])
        return super().do_GET()

    def do_POST(self):
        if self.path in RUTAS:
            return self._reenviar(RUTAS[self.path])
        self.send_error(404)


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main() -> None:
    ap = argparse.ArgumentParser(description="Vista previa local del portafolio")
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--glubia", default="http://127.0.0.1:11434")
    args = ap.parse_args()
    Manejador.glubia = args.glubia.rstrip("/")
    manejador = functools.partial(Manejador, directory=str(RAIZ / "portafolio" / "sitio"))
    print(f"Portafolio en http://127.0.0.1:{args.puerto}  (IA: {Manejador.glubia})  Ctrl+C para salir")
    with Servidor(("127.0.0.1", args.puerto), manejador) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
