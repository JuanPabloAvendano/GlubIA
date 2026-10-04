"""Integracion con openvino_genai real (CPU).

Necesita un modelo OpenVINO en GLUBIA_TEST_MODELO; si no, se salta. En el CI se
usa OpenVINO/Qwen2.5-Coder-0.5B-Instruct-int4-ov (misma familia y plantilla que el
de produccion, pero 15 veces mas pequeno). Tambien se ha pasado con el 7B real.

El modelo se carga UNA vez para todo el modulo: con un 7B en un equipo de 8 GB,
cargarlo por prueba agota la memoria.

    GLUBIA_TEST_MODELO=/ruta/al/modelo pytest -m openvino
"""

import asyncio
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

MODELO = os.environ.get("GLUBIA_TEST_MODELO", "")
pytestmark = [pytest.mark.openvino,
              pytest.mark.skipif(not MODELO or not Path(MODELO).exists(),
                                 reason="define GLUBIA_TEST_MODELO con un modelo OpenVINO")]


@pytest.fixture(scope="module")
def ov(tmp_path_factory):
    """(url, app) de un uvicorn real con el modelo cargado una sola vez."""
    import uvicorn

    from glubia.app import crear_app
    from glubia.config import cargar_config

    tmp = tmp_path_factory.mktemp("ov")
    with pytest.MonkeyPatch.context() as mp:
        for k in list(os.environ):
            if k.startswith("GLUBIA_") and k != "GLUBIA_TEST_MODELO":
                mp.delenv(k, raising=False)
        for k, v in {"GLUBIA_MOTOR": "openvino", "GLUBIA_MODEL": MODELO, "GLUBIA_DEVICE": "CPU",
                     "GLUBIA_DATA": str(tmp / "datos"), "GLUBIA_AUTH": "0", "GLUBIA_CTX": "4096",
                     "GLUBIA_LOG": "WARNING"}.items():
            mp.setenv(k, v)
        mp.setenv("HOME", str(tmp))
        app = crear_app(cargar_config(), salir_si_falla=False)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning",
                                        timeout_graceful_shutdown=2))
    hilo = threading.Thread(target=srv.run, daemon=True)
    hilo.start()
    url = f"http://127.0.0.1:{puerto}"
    limite = time.monotonic() + 600
    while time.monotonic() < limite:
        try:
            r = httpx.get(url + "/readyz", timeout=2)
            if r.status_code == 200:
                break
            if r.json().get("status") == "error":
                pytest.fail(r.json().get("error"))
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    yield url, app
    srv.should_exit = True
    hilo.join(timeout=20)


def test_carga_y_plantilla_medida(ov):
    _, app = ov
    motor = app.state.glubia.motor
    assert motor.estado == "listo" and motor.dispositivo == "CPU"
    b = motor.backend
    assert b.tipo == "llm"
    assert b.overhead == 5            # ChatML: <|im_start|> rol \n ... <|im_end|> \n
    assert b.tokens_generacion == 3   # <|im_start|> assistant \n


def test_sin_plantilla_doble(ov):
    """Los tokens de entrada deben ser exactamente los de UNA plantilla."""
    url, app = ov
    b = app.state.glubia.motor.backend
    mensajes = [{"role": "system", "content": "Eres un pirata."}, {"role": "user", "content": "Hola"}]
    esperado = b.contar(b.tok.apply_chat_template(mensajes, add_generation_prompt=True))
    r = httpx.post(url + "/v1/chat/completions", timeout=300,
                   json={"messages": mensajes, "max_tokens": 4, "temperature": 0})
    assert r.status_code == 200, r.text
    assert r.json()["usage"]["prompt_tokens"] == esperado


def test_presupuesto_coincide_con_tokens_reales(ov):
    _, app = ov
    motor = app.state.glubia.motor
    b = motor.backend
    mensajes = [{"role": "system", "content": "S"}, {"role": "user", "content": "uno"},
                {"role": "assistant", "content": "dos"}, {"role": "user", "content": "tres cuatro"}]
    _, info = motor.ajustar_contexto(mensajes, 16)
    real = b.contar(b.tok.apply_chat_template(mensajes, add_generation_prompt=True))
    assert abs(info["tokens_prompt"] - real) <= 2, (info, real)


def test_cancelar_detiene_openvino(ov):
    """Cerrar el stream (boton Detener) corta la generacion real en pocos tokens."""
    url, app = ov
    motor = app.state.glubia.motor

    async def prueba():
        async with httpx.AsyncClient(timeout=300) as c:
            async with c.stream("POST", url + "/v1/chat/completions",
                                json={"messages": [{"role": "user", "content": "Cuenta hasta mil"}],
                                      "max_tokens": 4000, "temperature": 0, "stream": True}) as r:
                n = 0
                async for linea in r.aiter_lines():
                    if '"content"' in linea:
                        n += 1
                        if n == 5:
                            break
        t0 = time.monotonic()
        while motor.actual is not None and time.monotonic() - t0 < 30:
            await asyncio.sleep(0.05)

    asyncio.run(prueba())
    assert motor.actual is None
    assert motor.ultimo["tokens"] < 50, motor.ultimo


def test_stream_ui_con_modelo_real(ov):
    url, _ = ov
    with httpx.stream("POST", url + "/api/chat/stream", timeout=300,
                      json={"prompt": "hola", "max_new_tokens": 16, "temperature": 0}) as r:
        lineas = [linea for linea in r.iter_lines() if linea.startswith("data:")]
    assert '"done": true' in lineas[-1]
