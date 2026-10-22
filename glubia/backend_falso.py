"""Backend simulado: responde sin modelo ni GPU.

Sirve para las pruebas automaticas, para el CI y para desarrollar la interfaz
en cualquier equipo (GLUBIA_MOTOR=falso). Respeta la misma interfaz que el
backend real, asi que la cola, la cancelacion y el recorte de contexto que se
prueban con el son exactamente los mismos que en produccion.

Comandos de prueba dentro del mensaje del usuario:
    [[sistema]]  responde con el prompt de sistema recibido
    [[error]]    simula un fallo de generacion
"""

from __future__ import annotations

import time
from typing import List

from .motor import Mensaje, Parametros, Resultado

RELLENO = ("Esta es una respuesta de prueba del motor falso de GlubIA, util para "
           "probar la interfaz y la API sin cargar el modelo. ")


class BackendFalso:
    dispositivo = "FALSO"
    overhead = 4

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
