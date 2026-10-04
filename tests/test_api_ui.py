"""Rutas de la interfaz: compatibilidad con la v1, sesion, contexto y conversaciones."""

import json

from conftest import PASS, iniciar_sesion


def _eventos(respuesta):
    return [json.loads(linea[5:]) for linea in respuesta.iter_lines() if linea.startswith("data:")]


def test_health_publico_y_completo(cliente):
    j = cliente.get("/api/health").json()
    assert j["status"] == "ok" and j["ready"] is True and j["device"] == "FALSO"
    assert cliente.get("/healthz").json()["status"] == "ok"
    assert cliente.get("/readyz").status_code == 200


def test_ui_se_sirve_con_titulo_y_cabeceras(fabricar):
    c = fabricar(GLUBIA_TITULO="Mi <IA>")
    r = c.get("/")
    assert r.status_code == 200
    assert "<title>Mi &lt;IA&gt;</title>" in r.text
    assert r.headers["x-frame-options"] == "DENY"


def test_chat_exige_sesion(cliente):
    assert cliente.post("/api/chat", json={"prompt": "hola"}).status_code == 401
    assert cliente.post("/api/chat").status_code == 401          # la sesion se mira antes que el cuerpo
    assert cliente.post("/v1/chat/completions").status_code == 401
    assert cliente.post("/api/chat/stream", json={"prompt": "hola"}).status_code == 401
    assert cliente.get("/api/session").json()["authenticated"] is False


def test_login_y_bloqueo_por_intentos(cliente):
    for _ in range(5):
        assert cliente.post("/api/login", json={"password": "mala"}).status_code == 401
    r = cliente.post("/api/login", json={"password": PASS})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_chat_clasico(cliente):
    iniciar_sesion(cliente)
    r = cliente.post("/api/chat", json={"prompt": "hola", "max_new_tokens": 20})
    j = r.json()
    assert r.status_code == 200 and j["status"] == "ok"
    assert j["response"].startswith("Respuesta simulada a: hola")
    assert j["tokens"] == 20 and j["finish_reason"] == "length"


def test_stream_formato_compatible_con_v1(cliente):
    iniciar_sesion(cliente)
    with cliente.stream("POST", "/api/chat/stream", json={"prompt": "hola", "max_new_tokens": 16}) as r:
        evs = _eventos(r)
    assert "id" in evs[0] and evs[0]["queue"] == 0
    assert any("context" in e for e in evs)
    deltas = "".join(e["delta"] for e in evs if "delta" in e)
    assert deltas.startswith("Respuesta simulada")
    assert evs[-1]["done"] is True and evs[-1]["tokens"] == 16 and "tps" in evs[-1]


def test_prompt_de_sistema_llega_como_sistema(cliente):
    """Regresion de la plantilla doble: el sistema del cliente es el sistema real."""
    iniciar_sesion(cliente)
    r = cliente.post("/api/chat", json={"prompt": "[[sistema]]", "system": "Eres un pirata",
                                        "max_new_tokens": 50})
    assert r.json()["response"] == "Eres un pirata"


def test_contexto_se_recorta_por_tokens(fabricar):
    c = fabricar(GLUBIA_CTX="1024")
    iniciar_sesion(c)
    historial = []
    for i in range(30):
        historial.append({"role": "user", "content": f"pregunta {i} " + "palabra " * 40})
        historial.append({"role": "assistant", "content": f"respuesta {i} " + "palabra " * 40})
    r = c.post("/api/chat", json={"prompt": "ultima", "history": historial, "max_new_tokens": 64})
    ctx = r.json()["context"]
    assert ctx["omitidos"] > 0 and ctx["tokens_prompt"] <= ctx["presupuesto"]
    assert ctx["mensajes"] % 2 == 1   # empieza en una pregunta del usuario, no en una respuesta


def test_mensaje_demasiado_largo(fabricar):
    c = fabricar(GLUBIA_CTX="1024")
    iniciar_sesion(c)
    r = c.post("/api/chat", json={"prompt": "palabra " * 2000, "max_new_tokens": 64})
    assert r.status_code == 400 and "tokens" in r.json()["detail"]


def test_error_de_generacion_llega_al_stream(cliente):
    iniciar_sesion(cliente)
    with cliente.stream("POST", "/api/chat/stream", json={"prompt": "[[error]]"}) as r:
        evs = _eventos(r)
    assert any(e.get("code") == "generation_error" for e in evs)
    assert evs[-1]["done"] is True and evs[-1]["finish_reason"] == "error"


def test_conversaciones_sincronizadas(cliente):
    iniciar_sesion(cliente)
    msgs = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hey", "err": True}]
    r = cliente.put("/api/conversations/abc123", json={"titulo": "Prueba", "msgs": msgs, "ts": 1,
                                                       "actualizada": 1000})
    assert r.status_code == 200
    # una version mas vieja no pisa a la nueva
    cliente.put("/api/conversations/abc123", json={"titulo": "Vieja", "msgs": [], "actualizada": 999})
    lista = cliente.get("/api/conversations").json()
    assert lista["conversations"][0]["titulo"] == "Prueba"
    assert lista["conversations"][0]["msgs"][1]["err"] is True
    cliente.delete("/api/conversations/abc123")
    lista = cliente.get("/api/conversations").json()
    assert lista["conversations"] == [] and lista["deleted"] == ["abc123"]


def test_conversaciones_validan_id_y_sesion(cliente):
    assert cliente.get("/api/conversations").status_code == 401
    iniciar_sesion(cliente)
    assert cliente.put("/api/conversations/../x", json={}).status_code in (400, 404)


def test_conversaciones_desactivables(fabricar):
    c = fabricar(GLUBIA_CONVERSACIONES="0")
    iniciar_sesion(c)
    assert c.get("/api/session").json()["conversations"] is False
    assert c.get("/api/conversations").status_code == 404


def test_cuerpo_gigante_rechazado(cliente):
    r = cliente.post("/v1/public/ask", content=b"x" * 40000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_secreto_migrado_desde_v1(fabricar, tmp_path):
    """Las sesiones abiertas con la v1 siguen validas tras actualizar."""
    from glubia.seguridad import cargar_secreto
    base = tmp_path / "base"
    base.mkdir()
    (base / ".glubia_secret").write_bytes(b"s" * 48)
    datos = tmp_path / "nuevo"
    assert cargar_secreto(datos, base) == b"s" * 48
    assert (datos / ".glubia_secret").exists()


def test_sustitutos_sueltos_no_rompen_la_respuesta(cliente):
    """JSON admite "\\ud83d" sin pareja (un emoji cortado por slice() en JavaScript), pero no
    es UTF-8 valido: antes daba 500. Ahora se acepta con el caracter roto reemplazado por U+FFFD."""
    iniciar_sesion(cliente)
    r = cliente.post("/api/chat", content=b'{"prompt": "hola \\ud83d mundo"}',
                     headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert "\ufffd" in r.json()["response"]      # el motor falso repite la pregunta


def test_sin_sustitutos():
    from glubia.texto import sin_sustitutos
    assert sin_sustitutos("hola") == "hola"
    assert sin_sustitutos("a\ud83db") == "a\ufffdb"
    assert sin_sustitutos("ok \U0001F600") == "ok \U0001F600"


def test_cuerpo_invalido_no_da_500(cliente):
    """Bytes que no son JSON, o JSON con bytes no UTF-8: error del cliente, nunca 500."""
    iniciar_sesion(cliente)
    for cuerpo in (b"\xff\xfe no es json", b'{"prompt": "\xff\xfe"}'):
        r = cliente.post("/api/chat", content=cuerpo, headers={"Content-Type": "application/json"})
        assert r.status_code in (400, 422), (cuerpo, r.status_code, r.text)
        assert "detail" in r.json()
