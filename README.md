# GlubIA 2.0 — IA local, API y portafolio

Un modelo de lenguaje en tu propio equipo (Qwen2.5-Coder-7B sobre OpenVINO, GPU Intel o CPU), con
interfaz web propia, una API compatible con la de OpenAI y un asistente público para tu portafolio.
Nada sale de tu máquina salvo lo que tú publiques.

```
GlubIA/
├── glubia/                 el servidor (paquete Python)
│   ├── motor.py            cola, cancelación y presupuesto de contexto
│   ├── backend_openvino.py el modelo real   · backend_falso.py  uno simulado para pruebas
│   ├── api_ui.py           rutas de la interfaz (compatibles con la v1)
│   ├── api_v1.py           API OpenAI-compatible + endpoint público
│   └── ...                 config, seguridad, conversaciones, perfil, telemetría
├── glubia_server.py        lanzador (lo usan iniciar.bat / iniciar.sh)
├── ui.html                 la interfaz web
├── portafolio/             página, perfil.md de la persona y Caddyfile
├── Dockerfile, compose*.yaml, .env.example     contenedor para Omarchy
├── scripts/                instalar, desplegar, humo, descargar modelo, evaluar, vista previa
├── tests/                  pruebas (motor falso y OpenVINO real)
├── docs/                   requisitos, arquitectura, pipeline, API, Omarchy, portafolio
│   └── historia/           documentos y servidor de la etapa anterior
├── modelo_qwen_7b_ov/      el modelo (no va al repositorio)
└── datos/                  se crea solo: sesiones, conversaciones, claves, caché de OpenVINO
```

## Arranque

**Windows (como siempre):** doble clic en `iniciar.bat` (cambia antes la contraseña) o

```powershell
cd C:\Users\juanp\GlubIA
.\openvino_env\Scripts\python.exe glubia_server.py
```

No hay que instalar nada nuevo: usa las mismas librerías de tu `openvino_env`. La primera vez migra
`.glubia_secret` a `datos\` (las sesiones abiertas siguen valiendo) y apaga la telemetría de
OpenVINO.

**Omarchy / Linux con Docker:** `scripts/instalar-omarchy.sh` (detalle en `docs/OMARCHY.md`).

**Sin modelo, para probar la UI, la API o el portafolio:** `GLUBIA_MOTOR=falso`.

## Qué cambió en la 2.0

El diagnóstico completo, con cómo se reprodujo cada fallo, está en `docs/PROBLEMAS.md`. Lo esencial:

- El modelo recibía la plantilla de chat **dos veces**: tu prompt de sistema y el historial llegaban
  metidos dentro de un solo mensaje de usuario. Ahora recibe una conversación de verdad.
- **Detener** ahora detiene la generación en el servidor, y una pregunta cancelada en cola no se
  genera.
- Con mucha cola el servidor ya no parece caído: `/api/health` responde al instante.
- La memoria de la conversación se recorta por **tokens**, sin reenviar errores, y el historial se
  **sincroniza entre equipos**.
- API compatible con OpenAI, claves de API, endpoint público para el portafolio, contenedor,
  pipeline de CI/CD.

## Variables de entorno

| Variable | Por defecto | Para qué |
|---|---|---|
| `GLUBIA_PASS` | se genera y se imprime | contraseña de la UI |
| `GLUBIA_AUTH` | `1` | `0` desactiva login y claves (solo LAN de confianza) |
| `GLUBIA_MODEL` | `./modelo_qwen_7b_ov` | carpeta del modelo |
| `GLUBIA_DEVICE` | `GPU` | `GPU`, `CPU`, `AUTO`; si falla la GPU cae a CPU |
| `GLUBIA_MOTOR` | `openvino` | `falso` = respuestas simuladas, sin modelo |
| `GLUBIA_PORT` / `GLUBIA_HOST` | `11434` / `0.0.0.0` | dónde escucha |
| `GLUBIA_DATA` | `./datos` | secreto, conversaciones, claves, caché |
| `GLUBIA_HORAS` | `8` | duración de la sesión |
| `GLUBIA_TITULO` | `GlubIA` | nombre en la pestaña |
| `GLUBIA_CTX` | `8192` | tokens de contexto (pregunta + historial + respuesta) |
| `GLUBIA_MAX_TOKENS` | `4096` | tope de respuesta |
| `GLUBIA_MAX_SEG` | `300` | tope de segundos por respuesta |
| `GLUBIA_COLA` | `8` | peticiones en espera antes de responder 503 |
| `GLUBIA_CACHE_OV` | `1` | caché de compilación de OpenVINO |
| `GLUBIA_CONVERSACIONES` | `1` | historial sincronizado en el servidor |
| `GLUBIA_API_KEYS` | vacío | claves de API directas, separadas por comas |
| `GLUBIA_PROXIES` | vacío | IPs/redes de proxies de confianza (el compose pone la de Caddy) |
| `GLUBIA_PUBLICO` | `0` | `1` activa el asistente del portafolio |
| `GLUBIA_PERFIL` | `./portafolio/perfil/perfil.md` | persona del asistente público |
| `GLUBIA_PUBLICO_TOKENS` · `_RPM` · `_DIA` · `_COLA` · `_SEG` · `_MAX_CHARS` · `_HISTORIAL` | 350 · 6 · 80 · 3 · 90 · 600 · 6 | límites del asistente público |
| `GLUBIA_CORS` | vacío | orígenes que pueden llamar al asistente público desde otro dominio |
| `GLUBIA_DOCS` | `1` | documentación interactiva en `/api/docs` |
| `GLUBIA_TELEMETRIA_OV` | `0` | `1` deja la telemetría de OpenVINO como esté |

## Seguridad

- Contraseña + cookie firmada con HMAC-SHA256, `HttpOnly`, 8 h; 5 intentos fallidos por IP y bloqueo
  de 15 min. Sin flag `Secure` a propósito: la misma sesión vale en LAN (http) y por el túnel (https).
- Claves de API guardadas solo como hash (`python -m glubia.claves`).
- La IP real solo se acepta de quien corresponde: `CF-Connecting-IP` desde loopback (túnel en la misma
  máquina) o `X-Real-IP` desde `GLUBIA_PROXIES` (Caddy). Nadie en la LAN puede falsearla.
- El asistente público no puede cambiar su persona, tiene límites por IP y va detrás de tus
  peticiones. Sus logs guardan la IP recortada, nunca las preguntas.
- En el contenedor, GlubIA vive en una red interna sin salida a internet.

## Detalles técnicos que no hay que redescubrir

1. `pipe.generate()` con texto devuelve `str`; con `ChatHistory`, `DecodedResults` (`.texts[0]`,
   `.perf_metrics`).
2. **Nada bloqueante dentro de `async def`.** El pipeline solo se toca desde el hilo del motor; los
   endpoints async solo esperan colas de asyncio. (La regla "`def`, no `async def`" de la v1 era la
   forma de cumplir esto cuando el endpoint llamaba al modelo directamente.)
3. `config.do_sample = True` o la temperatura se ignora. Se parte de `pipe.get_generation_config()`
   para heredar los dos tokens de fin de Qwen (151643 y 151645).
4. **No construir la plantilla a mano**: `apply_chat_template` vale `True` por defecto. Pasar
   `ChatHistory`.
5. El pipeline no es reentrante: un solo hilo lo usa, en orden de prioridad.
6. Tras devolver `STOP`, el pipeline puede llamar una vez más al streamer para vaciar su buffer.
7. El streamer devuelve `StreamingStatus.RUNNING`/`STOP` en versiones nuevas y `False`/`True` en las
   antiguas (`getattr` defensivo).
8. OpenVINO 2026 exige CPU con AVX2.

## Documentación

- `docs/REQUISITOS.md` — requisitos funcionales y restricciones (Product Owner).
- `docs/ARQUITECTURA-OBJETIVO.md` — hacia dónde evoluciona: segmentos, proveedores, nodos.
- `docs/TRABAJO.md` — cómo trabajar desde Windows y Omarchy con un solo repositorio.
- `docs/PROBLEMAS.md` — diagnóstico de continuidad y memoria.
- `docs/PIPELINE.md` — de una rama a producción, versiones, modelos y vuelta atrás.
- `docs/API.md` — referencia y ejemplos.
- `docs/OMARCHY.md` — despliegue, firewall, dominio y túnel.
- `docs/PORTAFOLIO.md` — qué está listo, qué falta y opciones local/nube.
