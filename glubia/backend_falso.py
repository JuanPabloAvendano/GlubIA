"""Backend simulado: responde sin modelo ni GPU.

Sirve para las pruebas automaticas, para el CI y para desarrollar el portafolio
en cualquier equipo (GLUBIA_MOTOR=falso). Respeta la misma interfaz que el
backend real, asi que la cola, la cancelacion y el recorte de contexto que se
prueban con el son exactamente los mismos que en produccion.

Comandos de prueba dentro del mensaje del usuario:
    [[sistema]]   responde con el prompt de sistema recibido
    [[error]]     simula un fallo de generacion
    [[pensar]]    responde con un bloque <think>...</think> delante (debe filtrarse)
    [[historial]] responde con los mensajes recibidos, uno por linea (rol: texto)
    [[codigo]]    responde con un bloque de codigo (el asistente publico debe cortarlo)
"""

from __future__ import annotations

import time
from typing import List

from .motor import Mensaje, Parametros, Resultado

RELLENO = ("Esta es una respuesta de prueba del motor falso de GlubIA, util para "
           "probar la interfaz, la API y el portafolio sin cargar el modelo. ")


class BackendFalso:
    dispositivo = "FALSO"
    tipo = "falso"
    overhead = 4
    tokens_generacion = 3

    def __init__(self, cfg):
        self.retardo = cfg.falso_retardo
        self.nombre_modelo = cfg.nombre_modelo

    def contar(self, texto: str) -> int:
        return len(texto.split()) if texto else 0

    def generar(self, mensajes: List[Mensaje], p: Parametros, on_delta) -> Resultado:
        ultimo = next((m["content"] for m in reversed(mensajes) if m["role"] == "user"), "")
        sistema = mensajes[0]["content"] if mensajes and mensajes[0]["role"] == "system" else ""
        if "[[error]]" in ultimo:
            raise RuntimeError("fallo simulado")
        if "[[sistema]]" in ultimo:
            base = sistema
        elif "[[pensar]]" in ultimo:
            base = "<think> razonamiento interno que no debe verse </think>\n\nRespuesta visible."
        elif "[[codigo]]" in ultimo:
            base = "Claro, aqui tienes: ```python def ordenar(xs): return sorted(xs) ``` y " + RELLENO * 20
        elif "[[historial]]" in ultimo:
            base = " | ".join(f"{m['role']}: {m['content']}" for m in mensajes if m["role"] != "system")
        else:
            base = f"Respuesta simulada a: {ultimo[:200]}. " + RELLENO * 40

        entrada = sum(self.contar(m["content"]) + self.overhead for m in mensajes) + 3
        salida = []
        for palabra in base.split()[: p.max_new_tokens]:
            if self.retardo:
                time.sleep(self.retardo)
            if not on_delta(palabra + " "):
                break
            salida.append(palabra)
        return Resultado(" ".join(salida), entrada, len(salida), 1.0)


def crear(cfg) -> BackendFalso:
    return BackendFalso(cfg)
