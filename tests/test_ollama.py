"""Backend Ollama contra un Ollama de mentira (http.server en un hilo).

No necesita Ollama ni modelo: se comprueba el protocolo (/api/chat en stream),
que las opciones lleguen bien, que Detener cierre la conexion y que un modelo
no descargado de un error claro.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

MODELO = "huihui_ai/qwen3.5-abliterated:4B"


class FalsoOllama(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Manejador)
        self.peticiones = []
        self.abortadas = 0
        self.descargados = []
        self.descargados_pull = []
        self.borrados = []
        self.palabras = 200
        self.retardo = 0.0

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/api/version":
            self._json({"version": "0.0.0"})
        elif self.path == "/api/tags":
            self._json({"models": [{"name": MODELO, "size": 3_300_000_000,
                                    "details": {"parameter_size": "4.7B", "quantization_level": "Q4_K_M"}},
                                   {"name": "otro/modelo:9b", "size": 6_600_000_000, "details": {}},
                                   {"name": "qwen3-embedding:0.6b", "size": 600_000_000, "details": {}}]})
        elif self.path == "/api/ps":
            self._json({"models": [{"name": MODELO, "size_vram": 0}]})
        else:
            self._json({"error": "no"}, 404)

    def do_DELETE(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.borrados.append(cuerpo["model"])
        self._json({})

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        srv = self.server
        if self.path == "/api/pull":
            self.send_response(200)
            self.end_headers()
            for d in ({"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 50},
                      {"status": "success"}):
                self.wfile.write(json.dumps(d).encode() + b"\n")
            srv.descargados_pull.append(cuerpo["model"])
            return
        if self.path == "/api/show":
            if "embed" in cuerpo["model"]:
                return self._json({"capabilities": ["embedding"]})
            return self._json({"capabilities": ["completion", "thinking"]})
        if self.path == "/api/generate":                    # keep_alive 0: descargar de memoria
            srv.descargados.append(cuerpo["model"])
            return self._json({"done": True})
        srv.peticiones.append(cuerpo)
        if cuerpo["model"] != MODELO:
            return self._json({"error": f"model '{cuerpo['model']}' not found"}, 404)
        if not cuerpo["messages"]:
            return self._json({"model": MODELO, "done": True, "done_reason": "load"})
        ultimo = cuerpo["messages"][-1]["content"]
        n = min(srv.palabras, cuerpo["options"]["num_predict"])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for i in range(n):
                time.sleep(srv.retardo)
                texto = f"eco:{ultimo} " if i == 0 else f"p{i} "
                self.wfile.write(json.dumps({"message": {"role": "assistant", "content": texto},
                                             "done": False}).encode() + b"\n")
                self.wfile.flush()
            self.wfile.write(json.dumps({"message": {"content": ""}, "done": True,
                                         "prompt_eval_count": 17, "eval_count": n}).encode() + b"\n")
        except (BrokenPipeError, ConnectionResetError):
            srv.abortadas += 1


@pytest.fixture
def ollama():
    srv = FalsoOllama()
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield srv
    srv.shutdown()


def test_carga_precarga_y_dispositivo(fabricar, ollama):
    c = fabricar(GLUBIA_MOTOR="ollama", GLUBIA_OLLAMA_URL=ollama.url, GLUBIA_API_KEYS="k")
    motor = c.app.state.glubia.motor
    assert motor.estado == "listo" and motor.dispositivo == "OLLAMA-CPU"
    precarga = ollama.peticiones[0]
    assert precarga["messages"] == [] and precarga["keep_alive"] == -1
    assert precarga["options"]["num_ctx"] == 8192   # el mismo que en cada pregunta: sin recargas
    modelos = c.get("/v1/models", headers={"Authorization": "Bearer k"}).json()
    assert modelos["data"][0]["id"] == MODELO


def test_chat_envia_mensajes_y_opciones(fabricar, ollama):
    c = fabricar(GLUBIA_MOTOR="ollama", GLUBIA_OLLAMA_URL=ollama.url, GLUBIA_API_KEYS="k",
                 GLUBIA_CTX="4096")
    r = c.post("/v1/chat/completions", headers={"Authorization": "Bearer k"}, json={
        "messages": [{"role": "system", "content": "Eres un pirata"},
                     {"role": "user", "content": "hola"}],
        "max_tokens": 5, "temperature": 0.3, "stop": ["FIN"]})
    j = r.json()
    assert r.status_code == 200, j
    assert j["choices"][0]["message"]["content"].startswith("eco:hola")
    assert j["choices"][0]["finish_reason"] == "length"
    assert j["usage"]["prompt_tokens"] == 17 and j["usage"]["completion_tokens"] == 5

    p = ollama.peticiones[-1]
    assert p["stream"] is True and p["think"] is False
    assert p["messages"][0] == {"role": "system", "content": "Eres un pirata"}
    op = p["options"]
    assert op["num_ctx"] == 4096 and op["num_predict"] == 5 and op["stop"] == ["FIN"]
    assert op["temperature"] == pytest.approx(0.3)


def test_detener_cierra_la_conexion_con_ollama(monkeypatch, tmp_path, ollama):
    from glubia.backend_ollama import BackendOllama
    from glubia.motor import Parametros
    from tests.conftest import _config

    ollama.retardo = 0.01
    b = BackendOllama(_config(monkeypatch, tmp_path, GLUBIA_MOTOR="ollama",
                              GLUBIA_OLLAMA_URL=ollama.url))
    vistos = []

    def on_delta(texto):            # lo que hace el motor al pulsar Detener: devolver False
        vistos.append(texto)
        return len(vistos) < 3

    res = b.generar([{"role": "user", "content": "x"}], Parametros(max_new_tokens=200), on_delta)
    assert len(vistos) == 3 and res.tokens_salida < 200
    for _ in range(200):
        if ollama.abortadas:
            break
        time.sleep(0.02)
    assert ollama.abortadas == 1, "Ollama siguio generando tras Detener"


def test_modelo_no_descargado_da_error_claro(monkeypatch, tmp_path, ollama):
    from glubia.backend_ollama import BackendOllama
    from tests.conftest import _config

    cfg = _config(monkeypatch, tmp_path, GLUBIA_MOTOR="ollama", GLUBIA_OLLAMA_URL=ollama.url,
                  GLUBIA_OLLAMA_MODELO="otro/modelo:7b")
    with pytest.raises(RuntimeError, match="ollama pull otro/modelo:7b"):
        BackendOllama(cfg)


def test_sin_servidor_falla_tras_esperar(monkeypatch, tmp_path):
    from glubia.backend_ollama import BackendOllama
    from tests.conftest import _config

    cfg = _config(monkeypatch, tmp_path, GLUBIA_MOTOR="ollama", GLUBIA_OLLAMA_URL="http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="No hay Ollama"):
        BackendOllama(cfg, espera_seg=0)


def test_catalogo_panel_descarga_y_borrado(fabricar, ollama):
    from tests.conftest import iniciar_sesion

    c = fabricar(GLUBIA_MOTOR="ollama", GLUBIA_OLLAMA_URL=ollama.url)
    iniciar_sesion(c)
    modelos = {m["id"]: m for m in c.get("/api/modelos").json()["modelos"]}
    assert modelos["ollama:" + MODELO]["parametros"] == "4.7B"
    assert "ollama:otro/modelo:9b" in modelos
    assert "ollama:qwen3-embedding:0.6b" not in modelos           # no conversa: no se ofrece

    r = c.post("/api/admin/modelos/descargar", json={"nombre": "nuevo/modelo:7b"})
    assert r.status_code == 200
    for _ in range(100):
        d = c.get("/api/admin/estado").json()["descargas"]
        if d and d[0]["estado"] == "listo":
            break
        time.sleep(0.02)
    assert d[0]["estado"] == "listo" and ollama.descargados_pull == ["nuevo/modelo:7b"]

    assert c.delete("/api/admin/modelos/ollama:" + MODELO).status_code == 409   # es el activo
    assert c.delete("/api/admin/modelos/ollama:otro/modelo:9b").status_code == 200
    assert ollama.borrados == ["otro/modelo:9b"]


def test_cpu_desde_el_panel_recarga_con_num_gpu_0(fabricar, ollama):
    from tests.conftest import iniciar_sesion

    c = fabricar(GLUBIA_MOTOR="ollama", GLUBIA_OLLAMA_URL=ollama.url)
    iniciar_sesion(c)
    assert "num_gpu" not in ollama.peticiones[0]["options"]
    assert c.put("/api/admin/ajustes", json={"ollama": {"gpu": False}}).status_code == 200
    for _ in range(200):
        if len(ollama.peticiones) >= 2 and c.get("/readyz").status_code == 200:
            break
        time.sleep(0.02)
    assert ollama.peticiones[-1]["options"]["num_gpu"] == 0       # precarga del modelo en CPU
    assert ollama.descargados == [MODELO]                          # el anterior se libero antes
