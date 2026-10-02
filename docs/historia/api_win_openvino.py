import json
import queue
import threading
from typing import List, Literal

import uvicorn
import openvino_genai as ov_genai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

MODEL_PATH = "modelo_qwen_7b_ov"
DEVICE = "GPU"
PORT = 11434

print(f"Cargando Qwen2.5-Coder-7B en {DEVICE} para la API...")
pipe = ov_genai.LLMPipeline(MODEL_PATH, DEVICE)

# El pipeline no es reentrante: una sola generación a la vez.
pipe_lock = threading.Lock()

SYSTEM_PROMPT = """
Eres un Arquitecto de Software y Especialista en Sistemas Linux Debian y Ciberseguridad.
Tu objetivo es responder dudas sobre administración de Linux, scripts Bash/Python, patrones de diseño y seguridad.
Reglas:
- Responde de forma técnica, precisa y concisa.
- Proporciona código limpio listo para copiar, siempre dentro de bloques ``` con el lenguaje indicado.
- Limítate exclusivamente a tareas de desarrollo, administración de Linux y arquitectura de software.
"""

app = FastAPI(title="GlubIA - API OpenVINO Local", redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # no usamos cookies; "*" + credenciales es conflictivo
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PromptRequest(BaseModel):
    prompt: str
    history: List[Message] = []
    max_new_tokens: int = 1024
    temperature: float = 0.2


def build_prompt(req: PromptRequest) -> str:
    partes = [f"<|im_start|>system\n{SYSTEM_PROMPT.strip()}<|im_end|>\n"]
    for turno in req.history:
        partes.append(f"<|im_start|>{turno.role}\n{turno.content}<|im_end|>\n")
    partes.append(f"<|im_start|>user\n{req.prompt}<|im_end|>\n<|im_start|>assistant\n")
    return "".join(partes)


def build_config(req: PromptRequest) -> "ov_genai.GenerationConfig":
    config = ov_genai.GenerationConfig()
    config.max_new_tokens = req.max_new_tokens
    # Sin do_sample la temperatura se ignora y la salida es siempre greedy.
    config.do_sample = req.temperature > 0
    config.temperature = max(req.temperature, 0.01)
    config.top_p = 0.9
    config.repetition_penalty = 1.05
    return config


# Compatibilidad entre versiones de openvino_genai:
# las nuevas esperan StreamingStatus, las antiguas un bool (False = continuar).
_CONTINUE = getattr(getattr(ov_genai, "StreamingStatus", None), "RUNNING", False)


@app.get("/")
@app.get("/health")
@app.get("/api/chat/health")
def health_check():
    return {
        "status": "ok",
        "message": "Servidor IA Activo",
        "model": "Qwen2.5-Coder-7B",
        "device": DEVICE,
        "streaming": True,
    }


# Nota: def (no async def). FastAPI lo ejecuta en un hilo aparte y así una
# generación larga no bloquea el health check ni al resto de dispositivos.
@app.post("/api/chat")
@app.post("/api/chat/")
def chat_endpoint(req: PromptRequest):
    try:
        with pipe_lock:
            resultado = pipe.generate(build_prompt(req), build_config(req))
        # generate() devuelve DecodedResults, que no es serializable a JSON.
        return {"status": "ok", "response": str(resultado).strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
@app.post("/api/chat/stream/")
def chat_stream(req: PromptRequest):
    trozos: "queue.Queue" = queue.Queue()

    def streamer(subword: str):
        trozos.put(("delta", subword))
        return _CONTINUE

    def worker():
        try:
            with pipe_lock:
                pipe.generate(build_prompt(req), build_config(req), streamer=streamer)
        except Exception as exc:  # noqa: BLE001
            trozos.put(("error", str(exc)))
        finally:
            trozos.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    def eventos():
        while True:
            tipo, valor = trozos.get()
            if tipo == "done":
                yield "data: " + json.dumps({"done": True}) + "\n\n"
                return
            if tipo == "error":
                yield "data: " + json.dumps({"error": valor}) + "\n\n"
                continue
            yield "data: " + json.dumps({"delta": valor}) + "\n\n"

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/chat")
@app.get("/api/chat/")
def chat_get_fallback():
    return {"status": "ok", "message": "Endpoint de chat listo para recibir peticiones POST."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)