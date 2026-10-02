# Diagnóstico de continuidad y memoria (versión 1)

Revisión de `glubia_server.py` 1.0 y `ui.html` con las versiones exactas de tu `openvino_env`
(OpenVINO GenAI 2026.3, FastAPI 0.141, Starlette 1.6, Uvicorn 0.52). Cada fallo se reprodujo
antes de corregirlo y tiene una prueba automática que falla si vuelve a aparecer.

| # | Problema | Afecta a | Estado en 2.0 |
|---|---|---|---|
| 1 | La plantilla de chat se aplicaba dos veces | memoria y persona | Corregido |
| 2 | Detener no paraba la generación en el servidor | continuidad | Corregido |
| 3 | Una pregunta cancelada en cola se generaba igual | continuidad | Corregido |
| 4 | Con cola larga, `/api/health` y el login dejaban de responder | continuidad | Corregido |
| 5 | Los errores y "(detenido)" se reenviaban al modelo como conversación | memoria | Corregido |
| 6 | Historial cortado a ciegas en 8 turnos, sin mirar tokens | memoria | Corregido |
| 7 | Historial atrapado en un navegador (`localStorage`) | continuidad | Corregido |
| 8 | OpenVINO enviaba telemetría a Google Analytics | privacidad | Corregido |
| 9 | El modelo cargaba al importar: sin respuesta durante la carga | continuidad | Corregido |
| 10 | Registro de intentos de login sin límite de memoria | memoria (RAM) | Corregido |
| 11 | Al caducar la sesión se perdía el texto escrito | continuidad | Corregido |
| 12 | Sin límite de tiempo por respuesta ni de cola | continuidad | Corregido |
| 13 | El proceso no se reiniciaba solo si caía | continuidad | Corregido (contenedor) |

## 1. La plantilla de chat se aplicaba dos veces

Desde OpenVINO GenAI 2025.x, `GenerationConfig.apply_chat_template` vale `True` por defecto y
`generate()` envuelve cualquier texto en la plantilla del tokenizer. El servidor ya armaba la
plantilla ChatML a mano, así que se aplicaba dos veces. Con tu tokenizer y un simple "Hola", el
modelo recibía esto (53 tokens en vez de 24):

```
<|im_start|>system
You are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>
<|im_start|>user
<|im_start|>system
Eres un Arquitecto de Software...<|im_end|>
<|im_start|>user
Hola<|im_end|>
<|im_start|>assistant
<|im_end|>
<|im_start|>assistant
```

Consecuencias: el prompt de sistema real era el genérico de Qwen; tu prompt de arquitecto y todo
el historial llegaban metidos dentro de **un único mensaje de usuario**, seguidos de un turno vacío
del asistente. El modelo "recordaba" la conversación como texto pegado, no como diálogo, y la
persona del portafolio habría sido fácil de saltar.

**Arreglo:** se pasa un `ChatHistory` y la plantilla la aplica el tokenizer una sola vez
(`backend_openvino.py`). Prueba: `test_sin_plantilla_doble` compara los tokens de entrada reales con
los de una única plantilla.

## 2 y 3. Detener no detenía nada

El streaming dependía de que el recolector de basura cerrara un generador síncrono al irse el
cliente. Con Starlette 1.6 y Uvicorn 0.52 eso no ocurre. Medido con un OpenVINO simulado:

- Detener tras 10 tokens: el servidor siguió hasta 100 de 100.
- Pregunta B cancelada mientras esperaba: se generó completa y la siguiente pregunta (C) tardó
  7,9 s en vez de unos 3 s.

En uso real eso son minutos de GPU por cada "Detener" y la siguiente pregunta esperando detrás.

**Arreglo:** un hilo único dueño del pipeline, una cola con prioridades y un evento de cancelación
que se revisa en cada token (`motor.py`). Se cancela al cerrar la conexión, por id
(`POST /api/chat/cancel`, que la UI llama al pulsar Detener) o por tiempo (`GLUBIA_MAX_SEG`). Los
trabajos cancelados en cola se descartan sin tocar el modelo.

## 4. La cola agotaba los hilos

Cada petición en espera ocupaba un hilo del pool de AnyIO (40 por defecto), y `/api/health` y el
login también necesitaban uno. Con 45 streams en cola, `/api/health` tardó **16,7 s**. Desde fuera
parece que el servidor se cayó (la UI marca "sin enlace"); con el portafolio público, 40 visitantes
a la vez habrían bloqueado también tu acceso privado.

**Arreglo:** los endpoints son `async` y solo esperan colas de asyncio; la generación vive en su
propio hilo. Con 45 en cola el health responde en milisegundos. La cola tiene tope (`GLUBIA_COLA`;
devuelve 503 con `Retry-After`) y las preguntas públicas tienen su propio tope y menor prioridad.

> La regla de la v1 "endpoints con `def`, no `async def`" sigue siendo cierta en su intención: nada
> bloqueante dentro de un `async def`. En la 2.0 el pipeline nunca se llama desde un endpoint.

## 5. Los errores contaminaban la memoria

Los textos "**No se pudo completar:** …", "*(sin respuesta)*" y "*(detenido)*" se guardaban como
mensajes del asistente y se reenviaban como contexto: el modelo leía sus propios errores como si
fueran parte de la conversación. Ahora se guardan con una marca (`err`, `detenido`), se pintan en la
UI y no viajan al modelo (tampoco los de conversaciones antiguas, que se reconocen por su texto).

## 6. Historial por número de mensajes, no por tokens

El cliente enviaba 8 turnos y el servidor cortaba en 16 mensajes, sin mirar su tamaño: o se olvidaba
de más (turnos cortos) o se desbordaba el contexto (bloques de código largos). Ahora el servidor
recorta por tokens reales: conserva el sistema y la última pregunta y añade los turnos más recientes
que quepan en `GLUBIA_CTX` menos la respuesta. La UI muestra cuántos mensajes llegaron al modelo y
cuántos quedaron fuera. El cálculo coincide con el real a ±2 tokens (`test_presupuesto_…`).

## 7. Historial atrapado en el navegador

Vivía solo en `localStorage`: no te seguía del portátil al móvil, se perdía al limpiar el navegador
y fallaba al pasar de ~5 MB. Ahora se sincroniza con SQLite en el servidor (`/api/conversations`),
con borrados propagados. Sin servidor o sin red, la UI sigue funcionando como antes.

## 8. Telemetría de OpenVINO

Importar `openvino_genai` carga `openvino_telemetry`; sin archivo de consentimiento lo da por
aceptado y envía eventos de uso a `www.google-analytics.com`. No viajan tus conversaciones, pero sí
algo, y eso contradice "nada sale de tu máquina". Ahora se escribe el consentimiento en `0` antes de
importarlo (en Windows: `%LOCALAPPDATA%\Intel Corporation\openvino_telemetry`). En el contenedor,
además, GlubIA vive en una red interna sin salida a internet.

## 9 a 13. Otros

- **Carga al importar:** durante la carga (de 30 s a varios minutos en GPU) no respondía nada. Ahora
  carga en segundo plano: `/healthz` responde al instante y `/readyz` dice cuándo está listo. Con la
  caché de OpenVINO (`datos/ov_cache`) los arranques siguientes son mucho más rápidos.
- **Intentos de login:** el diccionario por IP crecía sin límite; ahora es acotado (10 000 IPs).
- **Sesión caducada:** el texto que escribías se perdía; ahora vuelve al cuadro de texto.
- **Tiempo y cola:** sin límites, una petición podía ocupar la GPU indefinidamente.
- **Reinicio:** era un proceso en primer plano; en el contenedor se reinicia solo y tiene healthcheck.

## Pendiente (no es un fallo, son mejoras siguientes)

- **Memoria a largo plazo entre conversaciones** (notas que GlubIA recuerde siempre, tipo "uso
  Debian 12 y Omarchy"). Hoy cada conversación empieza de cero, aunque ya se sincronizan.
- **Resumen de lo que queda fuera del contexto**, en vez de solo descartarlo.
- **Varias generaciones a la vez** con `ContinuousBatchingPipeline` (hoy, una a la vez y en cola).
- **NPU** del Core Ultra: posible con OpenVINO, pero pide un modelo cuantizado para NPU.
- **Consumo de RAM real en tu equipo:** no se pudo medir desde aquí. Referencia: el modelo INT4 pesa
  4,5 GB y en GPU integrada usa memoria del sistema; cuenta con unos 6–7 GB para el 7B.
