# Cambios

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Versiones: [SemVer](https://semver.org/lang/es/).
La seccion de cada version es el texto de su Release en GitHub (lo extrae `release.yml`).

## [Sin publicar]

## [2.0.0] - 2026-10-02

### Corregido
- El prompt se envolvia dos veces en la plantilla de chat (openvino_genai aplica la suya por defecto desde 2025.x): el modelo veia "You are Qwen..." como sistema real y todo el historial dentro de un solo mensaje de usuario. Ahora se pasa un `ChatHistory` y la plantilla se aplica una vez.
- El boton Detener no paraba la generacion en el servidor; una pregunta cancelada mientras esperaba se generaba completa igualmente.
- Con muchas peticiones en cola se agotaba el pool de hilos y `/api/health` tardaba 16,7 s (con 45 en cola).
- Los mensajes de error y "(detenido)" se reenviaban al modelo como parte de la conversacion.
- El historial se cortaba a ciegas en 8 turnos; ahora se recorta por tokens (`GLUBIA_CTX`).
- El registro de intentos de login crecia sin limite con cada IP nueva.
- OpenVINO enviaba telemetria de uso a Google Analytics; ahora se desactiva antes de importarlo.
- Al caducar la sesion se perdia el texto que estabas escribiendo.
- Sin sesion, un POST mal formado devolvia 422 en vez de 401.

### Anadido
- API compatible con OpenAI: `/v1/models` y `/v1/chat/completions` (con y sin streaming), con claves de API (`python -m glubia.claves`).
- Endpoint publico para el portafolio (`/v1/public/ask`, `/v1/public/info`): persona fija desde `perfil.md`, limites por IP, cola de baja prioridad, CORS solo para tus dominios.
- Conversaciones en el servidor (SQLite): el historial de la UI te sigue entre equipos.
- Cola con prioridades, cancelacion por id (`/api/chat/cancel`), limite de tiempo por respuesta y 503 con `Retry-After` cuando esta llena.
- `/healthz` y `/readyz`; el modelo carga en segundo plano y la UI muestra "cargando modelo".
- Cache de compilacion de OpenVINO en `datos/ov_cache`: arranques mucho mas rapidos en GPU.
- Contenedor (Dockerfile, compose para GPU Intel, CPU y WSL), Caddy, tunel Cloudflare opcional.
- Pipeline: CI con pruebas (motor falso y OpenVINO real), publicacion en GHCR por etiqueta, despliegue con vuelta atras, evaluacion de modelos.
- Portafolio inicial con conversacion en vivo con la IA.

### Cambiado
- El codigo vive en el paquete `glubia/`; `glubia_server.py` sigue siendo el lanzador.
- Los datos persistentes van en `datos/` (o `GLUBIA_DATA`). El `.glubia_secret` de la v1 se migra solo: las sesiones abiertas siguen valiendo.

## [1.0.0] - 2026-08-15
- Servidor e interfaz en el mismo origen y puerto, login con cookie HMAC, streaming SSE, tunel Cloudflare.
