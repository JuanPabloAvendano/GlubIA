# Cambios

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Versiones: [SemVer](https://semver.org/lang/es/).
La seccion de cada version es el texto de su Release en GitHub (lo extrae `release.yml`).

## [Sin publicar]

### Eliminado
- El portafolio sale de GlubIA a su propio repo: la pagina, `perfil.md`, `glubia/perfil.py`, el endpoint `/v1/public/*`, las variables `GLUBIA_PUBLICO*`, `GLUBIA_PERFIL` y `GLUBIA_CORS`, el puerto 8080, el tunel `tunel-portafolio` y `scripts/vista_portafolio.py`. GlubIA queda como asistente personal y local.

### Cambiado
- El Caddyfile pasa a `despliegue/Caddyfile` y solo sirve GlubIA privado (`:8081`).
- `scripts/evaluar.py` evalua solo la API privada; los casos del portafolio se fueron con el.

### Anadido
- Panel de admin (▣ Panel) y selector de modelo en la cabecera: cambiar en caliente entre modelos de Ollama y OpenVINO (si el nuevo no carga, vuelve al anterior), descargar y borrar modelos de Ollama, GPU/CPU, «pensar» y memoria de Ollama, dispositivo de OpenVINO. Lo elegido se guarda en `ajustes.json`.
- Invitados: invitaciones de un solo uso con caducidad, revocables al instante; el admin decide qué modelos pueden elegir, su largo máximo, su ritmo y sus instrucciones.
- Defensas contra prompt injection para invitados (`glubia/guardia.py`): prompt de sistema fijado por el servidor con politica de seguridad, historial firmado con HMAC, vigia de fugas (canario y frases de la politica), limpieza de caracteres invisibles, deteccion de frases tipicas (ES/EN/Base64), limite de ritmo y pausa a reincidentes. Auditoria en `auditoria.jsonl`.
- Motor Ollama (`GLUBIA_MOTOR=ollama`): usa cualquier modelo de ollama.com sin convertirlo. El modelo es una linea del `.env` (`GLUBIA_OLLAMA_MODELO`). Servicio `ollama` en compose (perfil `ollama`) con GPU Intel por Vulkan; glubia sigue sin salida a internet.
- Perfil `tunel-rapido` en compose: tunel trycloudflare a la UI que arranca solo con el equipo, sin cuenta ni token.
- `scripts/vigilar.sh`: panel en la terminal con estado de servicios, modelo, memoria y enlaces publicos.

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
