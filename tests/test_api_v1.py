"""API OpenAI-compatible y claves de API."""

import json

from glubia.seguridad import Claves


def test_v1_exige_clave(cliente):
    r = cliente.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"
    assert cliente.get("/v1/models").status_code == 401


def test_clave_desde_variable_de_entorno(fabricar):
    c = fabricar(GLUBIA_API_KEYS="glb_prueba123")
    h = {"Authorization": "Bearer glb_prueba123"}
    j = c.get("/v1/models", headers=h).json()
    assert j["object"] == "list" and j["data"][0]["id"] == "glubia-falso"
    assert c.get("/v1/models", headers={"Authorization": "Bearer otra"}).status_code == 401
    assert c.get("/v1/models", headers={"X-API-Key": "glb_prueba123"}).status_code == 200


def test_clave_creada_con_la_cli(fabricar, tmp_path):
    c = fabricar()
    clave = Claves(tmp_path / "datos" / "claves.json").crear("script")
    assert clave.startswith("glb_")
    assert c.get("/v1/models", headers={"Authorization": f"Bearer {clave}"}).status_code == 200
    Claves(tmp_path / "datos" / "claves.json").revocar("script")
    assert c.get("/v1/models", headers={"Authorization": f"Bearer {clave}"}).status_code == 401


def test_chat_completions_no_stream(fabricar):
    c = fabricar(GLUBIA_API_KEYS="k1")
    r = c.post("/v1/chat/completions", headers={"Authorization": "Bearer k1"}, json={
        "model": "lo-que-sea",
        "messages": [{"role": "system", "content": "Eres un pirata"},
                     {"role": "user", "content": [{"type": "text", "text": "[[sistema]]"}]}],
        "max_tokens": 50})
    j = r.json()
    assert r.status_code == 200 and j["object"] == "chat.completion"
    assert j["choices"][0]["message"] == {"role": "assistant", "content": "Eres un pirata"}
    assert j["choices"][0]["finish_reason"] == "stop"
    assert j["usage"]["total_tokens"] == j["usage"]["prompt_tokens"] + j["usage"]["completion_tokens"]


def test_chat_completions_stream(fabricar):
    c = fabricar(GLUBIA_API_KEYS="k1")
    with c.stream("POST", "/v1/chat/completions", headers={"Authorization": "Bearer k1"}, json={
            "messages": [{"role": "user", "content": "hola"}], "stream": True, "max_tokens": 8,
            "stream_options": {"include_usage": True}}) as r:
        lineas = [linea for linea in r.iter_lines() if linea.startswith("data:")]
    assert lineas[-1] == "data: [DONE]"
    trozos = [json.loads(linea[5:]) for linea in lineas[:-1]]
    assert trozos[0]["choices"][0]["delta"]["role"] == "assistant"
    texto = "".join(t["choices"][0]["delta"].get("content", "") for t in trozos if t["choices"])
    assert texto.startswith("Respuesta simulada")
    fin = [t for t in trozos if t["choices"] and t["choices"][0]["finish_reason"]]
    assert fin[0]["choices"][0]["finish_reason"] == "length"
    assert trozos[-1]["usage"]["completion_tokens"] == 8


def test_chat_completions_validaciones(fabricar):
    c = fabricar(GLUBIA_API_KEYS="k1")
    h = {"Authorization": "Bearer k1"}
    r = c.post("/v1/chat/completions", headers=h,
               json={"messages": [{"role": "assistant", "content": "x"}]})
    assert r.status_code == 400 and "user" in r.json()["error"]["message"]
    r = c.post("/v1/chat/completions", headers=h, json={"messages": [{"role": "user", "content": "x"}], "n": 3})
    assert r.status_code == 400
    r = c.post("/v1/chat/completions", headers=h, json={"messages": []})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"


def test_sin_auth_en_lan(fabricar):
    c = fabricar(GLUBIA_AUTH="0")
    assert c.get("/v1/models").status_code == 200


def test_sustitutos_sueltos_en_v1_no_dan_500(fabricar):
    """Un emoji cortado a la mitad ("\\ud83d") en cualquier campo de texto: nunca 500."""
    c = fabricar(GLUBIA_API_KEYS="k1")
    h = {"Authorization": "Bearer k1", "Content-Type": "application/json"}
    cuerpos = [
        b'{"model": "m\\ud800", "messages": [{"role": "user", "content": "hola \\ud800"}], "max_tokens": 5}',
        b'{"messages": [{"role": "system", "content": "\\ud800"}, {"role": "user", "content": "[[sistema]]"}],'
        b' "max_tokens": 5}',
        b'{"messages": [{"role": "user", "content": "x"}], "stop": ["\\udc00"], "max_tokens": 5}',
        b'{"messages": [{"role": "user", "content": "x \\ud800"}], "max_tokens": 5, "stream": true}',
    ]
    for cuerpo in cuerpos:
        r = c.post("/v1/chat/completions", content=cuerpo, headers=h)
        assert r.status_code == 200, (cuerpo, r.status_code, r.text)
        r.content.decode("utf-8")
