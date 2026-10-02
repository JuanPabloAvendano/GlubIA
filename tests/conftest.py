"""Fixtures: app con el motor falso y un servidor uvicorn real en un hilo.

El servidor real hace falta para probar lo que fallaba en la v1 (desconexiones,
cola, hilos): TestClient no simula un cliente que se va a mitad de stream.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient  # noqa: E402

from glubia.app import crear_app  # noqa: E402
from glubia.config import cargar_config  # noqa: E402

PASS = "clave-de-prueba"


def _config(monkeypatch, tmp_path, **env):
    for k in list(os.environ):
        if k.startswith("GLUBIA_"):
            monkeypatch.delenv(k, raising=False)
    base = {
        "GLUBIA_MOTOR": "falso",
        "GLUBIA_DATA": str(tmp_path / "datos"),
        "GLUBIA_PASS": PASS,
        "GLUBIA_FALSO_RETARDO": "0.005",
        "GLUBIA_LOG": "WARNING",
    }
    base.update({k: str(v) for k, v in env.items()})
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HOME", str(tmp_path))          # telemetria: no tocar el HOME real
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return cargar_config()


def esperar_listo(cliente, intentos: int = 200) -> None:
    for _ in range(intentos):
        if cliente.get("/readyz").status_code == 200:
            return
        time.sleep(0.02)
    raise AssertionError("el motor no quedo listo")


@pytest.fixture
def fabricar(monkeypatch, tmp_path):
    """fabricar(**env) -> TestClient ya listo (el motor arranca con el lifespan)."""
    clientes = []

    def _fabricar(**env):
        cfg = _config(monkeypatch, tmp_path, **env)
        cliente = TestClient(crear_app(cfg, salir_si_falla=False))
        cliente.__enter__()
        clientes.append(cliente)
        esperar_listo(cliente)
        return cliente

    yield _fabricar
    for c in clientes:
        c.__exit__(None, None, None)


@pytest.fixture
def cliente(fabricar):
    return fabricar()


def iniciar_sesion(c) -> None:
    r = c.post("/api/login", json={"password": PASS})
    assert r.status_code == 200, r.text


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor(monkeypatch, tmp_path):
    """servidor(**env) -> URL base de un uvicorn real con el motor falso."""
    import uvicorn

    arrancados = []

    def _servidor(**env):
        cfg = _config(monkeypatch, tmp_path, GLUBIA_AUTH="0", **env)
        app = crear_app(cfg, salir_si_falla=False)
        puerto = _puerto_libre()
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning",
                                            proxy_headers=False, timeout_graceful_shutdown=2))
        hilo = threading.Thread(target=srv.run, daemon=True)
        hilo.start()
        url = f"http://127.0.0.1:{puerto}"
        import httpx
        for _ in range(300):
            try:
                if httpx.get(url + "/readyz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.02)
        arrancados.append((srv, hilo))
        return url, app

    yield _servidor
    for srv, hilo in arrancados:
        srv.should_exit = True
        hilo.join(timeout=10)
