# Cambios

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Versiones: [SemVer](https://semver.org/lang/es/).
La seccion de cada version es el texto de su Release en GitHub (lo extrae `release.yml`).

## [Sin publicar]

## [2.1.0] - 2026-10-03

### Anadido
- **Buzon privado** (`/buzon`): envia a tu equipo archivos de cualquier tipo (documentos, comprimidos, exportaciones de chats...) y notas de texto. Subida por partes de 8 MiB con reanudacion, comprobacion sha256 por parte y del archivo completo, cuota y reserva de disco. Nada se ejecuta ni se descomprime. Ver `docs/BUZON.md`.
- **Verificacion en dos pasos (TOTP)**: `python -m glubia.identidad activar` muestra un QR para tu app de autenticacion. Con ella activa, el login pide contrasena y codigo, y el buzon solo se abre con sesion verificada.
- **Generador del portafolio** (`portafolio/construir.py`): la pagina, el CV imprimible, la 404, `_headers`, `robots.txt`, `sitemap.xml` y lo que sabe la IA (`perfil.md`) salen de un solo archivo de datos, `portafolio/contenido/sitio.toml`. Anadir proyectos, videos de YouTube, audios o documentos es anadir datos. La politica de seguridad de contenido se calcula segun lo que la pagina usa.
- **Modelos multimodales y de otras familias**: `GLUBIA_PIPELINE=auto` detecta si el modelo es de formato VLM (Gemma 4, Qwen3.5) o LLM. `GLUBIA_OV_CONFIG` pasa opciones a OpenVINO (p. ej. `MAX_PROMPT_LEN` para el NPU) y el razonamiento `<think>` se desactiva y, si aparece, se filtra.
- `scripts/medir.py`: tiempo de carga, memoria, primer token y tokens/s de un modelo, en JSON.
- Prueba de concepto de las comunicaciones (`docs/POC.md`) y pruebas de comportamiento con agentes (`docs/PRUEBAS-AGENTES.md`).

### Corregido
- El asistente del portafolio hablaba en primera persona como si fuera Juan, inventaba reputacion y convertia los datos que faltaban en negativas ("no ha trabajado en ninguna empresa"). Nueva persona en tercera persona con reglas explicitas.
- Por el Caddy publico pasaban PUT, DELETE, TRACE... hacia GlubIA; ahora solo POST en `/api/preguntar` y GET en `/api/info`.
- Con `flush_interval -1` en Caddy 2.6, una peticion sin streaming abandonada seguia ocupando el modelo; y en el servidor tampoco se notaba hasta ~19 s despues. Las dos cosas.
- Un cuerpo que no era JSON valido, o un texto con sustitutos UTF-16 sueltos, daba error 500.
- La pagina: la pregunta se perdia si fallaba el envio, una respuesta cortada a medias se borraba, cualquier error se mostraba como "dormida", el foco era invisible en modo de alto contraste y las sugerencias parecian pulsables mientras la IA cargaba. La 404 ya funciona en rutas anidadas.

### Cambiado
- `requirements.txt` fija solo dependencias directas (lo que rompia los PR de Dependabot).
- El repositorio es `JuanPabloAvendano/GlubIA` y la imagen `ghcr.io/juanpabloavendano/glubia`.

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
