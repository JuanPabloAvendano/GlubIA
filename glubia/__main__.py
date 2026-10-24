"""Arranque:  python -m glubia   (o python glubia_server.py, que hace lo mismo)."""

from __future__ import annotations

import uvicorn

from . import __version__
from .app import configurar_logs, crear_app
from .config import cargar_config


def _banner(cfg, estado) -> None:
    linea = "=" * 66
    print(f"\n{linea}")
    donde = "ollama" if cfg.motor == "ollama" else cfg.device
    print(f"  {cfg.titulo} {__version__}  ->  modelo {cfg.nombre_modelo} (cargando en {donde})")
    print(f"  Local .......... http://127.0.0.1:{cfg.port}")
    print(f"  Red local ...... http://<ip-de-esta-maquina>:{cfg.port}")
    print(f"  API ............ http://127.0.0.1:{cfg.port}/v1  (compatible con OpenAI)")
    print(f"  Datos .......... {cfg.data_dir}")
    if cfg.auth:
        if estado.sesiones.generada:
            print(f"\n  CONTRASENA GENERADA PARA ESTA SESION: {estado.sesiones.password}")
            print("  Define GLUBIA_PASS para fijar una propia.")
        else:
            print("\n  Acceso protegido con la contrasena de GLUBIA_PASS.")
    else:
        print("\n  AUTENTICACION DESACTIVADA (GLUBIA_AUTH=0). No lo expongas por tunel.")
    print(f"{linea}\n", flush=True)


def main() -> None:
    cfg = cargar_config()
    configurar_logs(cfg.log_nivel)
    if cfg.motor == "openvino" and not cfg.model_path.exists():
        raise SystemExit(
            f"No encuentro el modelo en:\n  {cfg.model_path}\n"
            "Colocalo junto a este archivo o define GLUBIA_MODEL.")
    app = crear_app(cfg)
    _banner(cfg, app.state.glubia)
    uvicorn.run(
        app, host=cfg.host, port=cfg.port, log_level="warning",
        proxy_headers=False,            # la IP real la resuelve seguridad.ip_cliente
        server_header=False,
        timeout_graceful_shutdown=5,    # los streams abiertos no retrasan el apagado
    )


if __name__ == "__main__":
    main()
