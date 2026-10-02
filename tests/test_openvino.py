"""Integracion con openvino_genai real (CPU).

Necesita un modelo OpenVINO en GLUBIA_TEST_MODELO; si no, se salta. En el CI se
usa OpenVINO/Qwen2.5-Coder-0.5B-Instruct-int4-ov (misma familia y plantilla que el de
produccion, pero 15 veces mas pequeno).

    GLUBIA_TEST_MODELO=/ruta/al/modelo pytest -m openvino
"""

import os
import time
from pathlib import Path

import pytest

MODELO = os.environ.get("GLUBIA_TEST_MODELO", "")
pytestmark = [pytest.mark.openvino,
              pytest.mark.skipif(not MODELO or not Path(MODELO).exists(),
                                 reason="define GLUBIA_TEST_MODELO con un modelo OpenVINO")]


@pytest.fixture
def ov(fabricar):
    c = fabricar(GLUBIA_MOTOR="openvino", GLUBIA_MODEL=MODELO, GLUBIA_DEVICE="CPU",
                 GLUBIA_API_KEYS="k")
    return c, c.app.state.glubia.motor


def test_carga_con_cache(ov, tmp_path):
    c, motor = ov
    assert motor.estado == "listo" and motor.dispositivo == "CPU"
    assert any((tmp_path / "datos" / "ov_cache").iterdir()), "CACHE_DIR no se uso"
    assert motor.backend.overhead == 5   # ChatML: <|im_start|> rol \n ... <|im_end|> \n


def test_sin_plantilla_doble(ov):
    """Los tokens de entrada deben ser exactamente los de UNA plantilla."""
    c, motor = ov
    b = motor.backend
    mensajes = [{"role": "system", "content": "Eres un pirata."}, {"role": "user", "content": "Hola"}]
    esperado = b.contar(b.tok.apply_chat_template(mensajes, add_generation_prompt=True))
    r = c.post("/v1/chat/completions", headers={"Authorization": "Bearer k"},
               json={"messages": mensajes, "max_tokens": 4, "temperature": 0})
    assert r.status_code == 200, r.text
    assert r.json()["usage"]["prompt_tokens"] == esperado


def test_presupuesto_coincide_con_tokens_reales(ov):
    c, motor = ov
    b = motor.backend
    mensajes = [{"role": "system", "content": "S"}, {"role": "user", "content": "uno"},
                {"role": "assistant", "content": "dos"}, {"role": "user", "content": "tres cuatro"}]
    _, info = motor.ajustar_contexto(mensajes, 16)
    real = b.contar(b.tok.apply_chat_template(mensajes, add_generation_prompt=True))
    assert abs(info["tokens_prompt"] - real) <= 2, (info, real)


def test_cancelar_detiene_openvino(servidor):
    """Cerrar el stream (boton Detener) corta la generacion real en pocos tokens."""
    import asyncio

    import httpx
    url, app = servidor(GLUBIA_MOTOR="openvino", GLUBIA_MODEL=MODELO, GLUBIA_DEVICE="CPU")
    motor = app.state.glubia.motor

    async def prueba():
        async with httpx.AsyncClient(timeout=60) as c:
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
        while motor.actual is not None and time.monotonic() - t0 < 10:
            await asyncio.sleep(0.05)

    asyncio.run(prueba())
    assert motor.actual is None
    assert motor.ultimo["tokens"] < 4000, motor.ultimo


def test_stream_ui_con_modelo_real(ov):
    c, _ = ov
    with c.stream("POST", "/api/chat/stream", headers={"Authorization": "Bearer k"},
                  json={"prompt": "hola", "max_new_tokens": 16, "temperature": 0}) as r:
        lineas = [linea for linea in r.iter_lines() if linea.startswith("data:")]
    assert '"done": true' in lineas[-1]
