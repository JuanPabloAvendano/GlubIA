"""Regresiones de continuidad medidas en la v1, contra un uvicorn real.

1. Pulsar Detener no paraba la generacion en el servidor.
2. Una pregunta cancelada mientras esperaba en cola se generaba igual.
3. Con muchas peticiones en cola, /api/health tardaba 16,7 s (pool de hilos agotado).
"""

import asyncio
import json
import time

import httpx


def _contar_deltas(chunk: bytes) -> int:
    return chunk.count(b'"delta"')


def test_detener_corta_la_generacion_en_curso(servidor):
    url, app = servidor(GLUBIA_FALSO_RETARDO="0.02")
    motor = app.state.glubia.motor

    async def prueba():
        async with httpx.AsyncClient(timeout=30) as c:
            async with c.stream("POST", url + "/api/chat/stream",
                                json={"prompt": "x", "max_new_tokens": 500}) as r:
                n = 0
                async for chunk in r.aiter_bytes():
                    n += _contar_deltas(chunk)
                    if n >= 10:
                        break   # el usuario pulsa Detener
        # sin peticion de cancelacion explicita: basta con cerrar la conexion
        t0 = time.monotonic()
        while motor.actual is not None and time.monotonic() - t0 < 5:
            await asyncio.sleep(0.05)
        return time.monotonic() - t0, motor.ultimo

    espera, ultimo = asyncio.run(prueba())
    assert motor.actual is None, "la generacion siguio despues de cerrar el stream"
    assert espera < 3
    assert ultimo["tokens"] < 200   # en la v1 llegaba a 500 (max_new_tokens)


def test_cancelacion_explicita_por_id(servidor):
    url, app = servidor(GLUBIA_FALSO_RETARDO="0.02")

    async def prueba():
        async with httpx.AsyncClient(timeout=30) as c:
            async with c.stream("POST", url + "/api/chat/stream",
                                json={"prompt": "x", "max_new_tokens": 500}) as r:
                ident, fin = None, None
                async for linea in r.aiter_lines():
                    if not linea.startswith("data:"):
                        continue
                    ev = json.loads(linea[5:])
                    if "id" in ev:
                        ident = ev["id"]
                        cancel = await c.post(url + "/api/chat/cancel", json={"id": ident})
                        assert cancel.json()["ok"] is True
                    if ev.get("done"):
                        fin = ev
                return fin

    fin = asyncio.run(prueba())
    assert fin["finish_reason"] == "cancelled" and fin["tokens"] < 500


def test_cancelada_en_cola_no_se_genera(servidor):
    url, app = servidor(GLUBIA_FALSO_RETARDO="0.02")
    motor = app.state.glubia.motor
    tokens_generados = []
    original = motor.backend.generar

    def espia(mensajes, p, on_delta):
        res = original(mensajes, p, on_delta)
        tokens_generados.append(res.tokens_salida)
        return res

    motor.backend.generar = espia

    async def stream(c, cortar=None):
        async with c.stream("POST", url + "/api/chat/stream", json={"prompt": "x", "max_new_tokens": 60}) as r:
            if cortar is not None:
                await asyncio.sleep(cortar)
                return "cortado"
            async for _ in r.aiter_bytes():
                pass
            return "completo"

    async def prueba():
        async with httpx.AsyncClient(timeout=30) as c:
            a = asyncio.create_task(stream(c))
            await asyncio.sleep(0.2)
            b = asyncio.create_task(stream(c, cortar=0.3))   # pulsa Detener mientras espera
            await asyncio.sleep(0.2)
            t0 = time.monotonic()
            cc = asyncio.create_task(stream(c))
            await asyncio.gather(a, b, cc)
            return time.monotonic() - t0

    duracion_c = asyncio.run(prueba())
    # Solo A y C generan; B se descarta sin tocar el modelo.
    assert len(tokens_generados) == 2, tokens_generados
    assert duracion_c < 3.6   # en la v1 C esperaba tambien los 60 tokens de B


def test_health_responde_con_la_cola_llena(servidor):
    url, _ = servidor(GLUBIA_FALSO_RETARDO="0.05", GLUBIA_COLA="60")

    async def prueba():
        limites = httpx.Limits(max_connections=200)
        async with httpx.AsyncClient(timeout=60, limits=limites) as c:
            async def stream():
                try:
                    async with c.stream("POST", url + "/api/chat/stream",
                                        json={"prompt": "x", "max_new_tokens": 40}) as r:
                        async for _ in r.aiter_bytes():
                            pass
                except httpx.HTTPError:
                    pass
            tareas = [asyncio.create_task(stream()) for _ in range(45)]
            await asyncio.sleep(1.5)
            t0 = time.monotonic()
            r = await c.get(url + "/api/health")
            dt = time.monotonic() - t0
            for t in tareas:
                t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            return dt, r.json()

    dt, salud = asyncio.run(prueba())
    assert dt < 0.5, f"/api/health tardo {dt:.2f}s"   # en la v1: 16,7 s
    assert salud["queue"] >= 40


def test_cola_llena_devuelve_503(servidor):
    url, app = servidor(GLUBIA_FALSO_RETARDO="0.05", GLUBIA_COLA="2")
    motor = app.state.glubia.motor

    async def prueba():
        async with httpx.AsyncClient(timeout=30) as c:
            async def stream():
                async with c.stream("POST", url + "/api/chat/stream",
                                    json={"prompt": "x", "max_new_tokens": 40}) as r:
                    async for _ in r.aiter_bytes():
                        pass
            tareas = [asyncio.create_task(stream())]          # 1 genera...
            while motor.actual is None:
                await asyncio.sleep(0.01)
            tareas += [asyncio.create_task(stream()) for _ in range(2)]   # ...y 2 esperan
            while motor.en_cola < 2:
                await asyncio.sleep(0.01)
            r = await c.post(url + "/api/chat", json={"prompt": "x"})
            for t in tareas:
                t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            return r

    r = asyncio.run(prueba())
    assert r.status_code == 503 and r.headers["retry-after"] == "5"


def test_lo_privado_pasa_antes_que_lo_publico(servidor, tmp_path):
    perfil = tmp_path / "perfil.md"
    perfil.write_text("# Juan\nHola.", encoding="utf-8")
    url, app = servidor(GLUBIA_FALSO_RETARDO="0.02", GLUBIA_PUBLICO="1", GLUBIA_PERFIL=str(perfil),
                        GLUBIA_PUBLICO_RPM="100", GLUBIA_PUBLICO_COLA="5")
    orden = []
    motor = app.state.glubia.motor
    original = motor.backend.generar

    def espia(mensajes, p, on_delta):
        orden.append("publico" if "portafolio" in mensajes[0]["content"] else "privado")
        return original(mensajes, p, on_delta)

    motor.backend.generar = espia

    async def prueba():
        async with httpx.AsyncClient(timeout=30) as c:
            async def pub():
                r = await c.post(url + "/v1/public/ask", json={"message": "hola", "stream": False})
                assert r.status_code == 200
            async def priv():
                r = await c.post(url + "/api/chat", json={"prompt": "hola", "max_new_tokens": 20})
                assert r.status_code == 200
            primero = asyncio.create_task(pub())       # ocupa el motor
            await asyncio.sleep(0.1)
            otros = [asyncio.create_task(pub()), asyncio.create_task(pub())]
            await asyncio.sleep(0.1)
            mio = asyncio.create_task(priv())          # llega despues, pero pasa antes
            await asyncio.gather(primero, *otros, mio)

    asyncio.run(prueba())
    assert orden[:2] == ["publico", "privado"], orden


def test_cancelar_en_cola_libera_la_plaza_al_momento(servidor):
    """Cancelar una pregunta que espera libera su plaza y cierra su stream ya."""
    url, app = servidor(GLUBIA_FALSO_RETARDO="0.05", GLUBIA_COLA="1")
    motor = app.state.glubia.motor

    async def prueba():
        async with httpx.AsyncClient(timeout=30) as c:
            async def stream(nombre, eventos):
                async with c.stream("POST", url + "/api/chat/stream",
                                    json={"prompt": "x", "max_new_tokens": 60}) as r:
                    async for linea in r.aiter_lines():
                        if linea.startswith("data:"):
                            eventos.append((time.monotonic(), json.loads(linea[5:])))
            ev_a, ev_b = [], []
            a = asyncio.create_task(stream("A", ev_a))          # genera ~3 s
            while motor.actual is None:
                await asyncio.sleep(0.01)
            b = asyncio.create_task(stream("B", ev_b))          # espera: cola llena (1)
            while not ev_b:
                await asyncio.sleep(0.01)
            lleno = await c.post(url + "/api/chat", json={"prompt": "x"})
            t0 = time.monotonic()
            await c.post(url + "/api/chat/cancel", json={"id": ev_b[0][1]["id"]})
            await b                                              # su stream se cierra ya
            cierre_b = time.monotonic() - t0
            libre = motor.en_cola
            a.cancel()
            await asyncio.gather(a, return_exceptions=True)
            return lleno.status_code, cierre_b, libre, ev_b[-1][1]

    lleno, cierre_b, libre, fin_b = asyncio.run(prueba())
    assert lleno == 503
    assert cierre_b < 1.0, f"B tardo {cierre_b:.2f}s en cerrarse"   # antes: hasta que A terminara
    assert libre == 0
    assert fin_b["done"] is True and fin_b["finish_reason"] == "cancelled"
