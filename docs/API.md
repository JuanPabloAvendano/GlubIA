# API de GlubIA

Tres familias de rutas:

| Ruta | Acceso | Para qué |
|---|---|---|
| `/v1/models`, `/v1/chat/completions` | clave de API o sesión de la UI | API compatible con OpenAI |
| `/v1/public/ask`, `/v1/public/info` | público, con límites | el portafolio |
| `/api/*` | sesión de la UI | la interfaz web (compatible con la v1) |
| `/healthz`, `/readyz` | público | vida y disponibilidad |

Documentación interactiva: `http://<host>:11434/api/docs` (`GLUBIA_DOCS=0` para ocultarla).

## Claves de API

```bash
python -m glubia.claves crear mi-script            # en Windows, con el python de openvino_env
docker compose exec glubia python -m glubia.claves crear mi-script   # en Omarchy
python -m glubia.claves listar
python -m glubia.claves revocar mi-script
```

La clave (`glb_…`) se muestra una sola vez; en disco solo queda su hash. Se envía como
`Authorization: Bearer glb_…` (o `X-API-Key`). Con `GLUBIA_AUTH=0` (solo LAN de confianza) no se
pide clave.

## Compatible con OpenAI

Sirve cualquier cliente de OpenAI cambiando la URL base. En Omarchy, a través de Caddy, la URL es
`http://127.0.0.1:8081/v1`; en Windows, `http://127.0.0.1:11434/v1`.

```python
from openai import OpenAI

cliente = OpenAI(base_url="http://127.0.0.1:8081/v1", api_key="glb_...")
r = cliente.chat.completions.create(
    model="glubia",                      # se ignora: hay un solo modelo cargado
    messages=[{"role": "user", "content": "Unidad systemd que reinicie un servicio al fallar"}],
    max_tokens=600,
)
print(r.choices[0].message.content, r.usage)

for trozo in cliente.chat.completions.create(model="glubia", stream=True,
        messages=[{"role": "user", "content": "Hola"}]):
    print(trozo.choices[0].delta.content or "", end="", flush=True)
```

```bash
curl http://127.0.0.1:8081/v1/chat/completions \
  -H "Authorization: Bearer glb_..." -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hola"}],"max_tokens":100}'
```

Admite `messages` (system/developer, user, assistant; contenido como texto o lista de partes de
texto), `stream`, `max_tokens`/`max_completion_tokens`, `temperature`, `top_p`, `stop` (hasta 4) y
`stream_options.include_usage`. Sin mensaje de sistema se usa el de GlubIA (arquitecto de software).
No admite herramientas (`tools`), imágenes ni `n` > 1.

`finish_reason`: `stop` (terminó o se canceló) o `length` (llegó a `max_tokens` o a
`GLUBIA_MAX_SEG`). El historial se recorta solo por tokens si no cabe en `GLUBIA_CTX`.

## Público (portafolio)

Solo existe con `GLUBIA_PUBLICO=1`. En Omarchy, Caddy lo publica en el puerto del portafolio como
`/api/preguntar` y `/api/info`; nada más de GlubIA es accesible desde ahí.

```bash
curl http://127.0.0.1:8080/api/info
# {"name":"Juan Pablo Avendaño Duque","status":"online","queue":0,"suggestions":[...],"limits":{...}}

curl -N http://127.0.0.1:8080/api/preguntar -H "Content-Type: application/json" \
  -d '{"message":"¿En qué trabaja?","history":[]}'
# data: {"id": "…", "queue": 0}
# data: {"delta": "Juan "}
# …
# data: {"done": true, "finish_reason": "stop"}
```

- `status`: `online`, `busy` (cola pública llena), `loading` (modelo cargando), `offline`.
- `message`: hasta `GLUBIA_PUBLICO_MAX_CHARS` (600). `history`: se usan los últimos
  `GLUBIA_PUBLICO_HISTORIAL` (6) mensajes, cada uno recortado a 1 500 caracteres.
- `"stream": false` devuelve `{"answer": "...", "finish_reason": "..."}`.
- El sistema es siempre la persona de `perfil.md`: el visitante no puede cambiarlo.
- Límites por IP: `GLUBIA_PUBLICO_RPM` por minuto y `GLUBIA_PUBLICO_DIA` por día (429 con
  `Retry-After`). Respuestas de hasta `GLUBIA_PUBLICO_TOKENS` tokens y `GLUBIA_PUBLICO_SEG` segundos.
- Va detrás de tus peticiones privadas en la cola y tiene su propio tope (`GLUBIA_PUBLICO_COLA`).
- Errores: `{"error": "texto para mostrar tal cual al visitante"}`.
- CORS solo para los orígenes de `GLUBIA_CORS` y solo en estas rutas.
- Si el modelo empieza un bloque de código (` ``` `), la respuesta se corta ahí y se añade un aviso
  de que el asistente no programa (`finish_reason: "stop"`).
- Por Caddy solo pasan `POST /api/preguntar` y `GET /api/info` (más `OPTIONS` para CORS); cualquier
  otro método recibe 404 sin llegar a GlubIA.

## Interfaz web (`/api/*`)

Las de la v1 siguen igual (`/api/chat`, `/api/chat/stream`, `/api/login`, `/api/logout`,
`/api/session`, `/api/health`). Novedades:

- El stream emite además `{"id","queue"}` al principio y `{"context": {...}}` al empezar a generar
  (mensajes que llegaron al modelo, omitidos y tokens). Los clientes antiguos los ignoran.
- `POST /api/chat/cancel` con `{"id": "…"}` detiene esa generación.
- `POST /api/login` acepta `{"password": "…", "codigo": "123456"}`. Con la verificación en dos pasos
  activa, el código es obligatorio y el error es el mismo si falla cualquiera de los dos.
- `GET /api/session` informa además `totp_required`, `verified` (sesión iniciada con código) y
  `mailbox` (buzón disponible).
- Buzón (`/api/buzon/*`): ver `BUZON.md`.
- `GET /api/conversations`, `PUT /api/conversations/{id}`, `DELETE /api/conversations/{id}`:
  historial sincronizado (`GLUBIA_CONVERSACIONES=0` lo desactiva).

## Estados y errores comunes

| Código | Cuándo | Qué hacer |
|---|---|---|
| 401 | falta sesión o clave | iniciar sesión o enviar `Authorization` |
| 400 | el mensaje no cabe en el contexto | acortarlo o bajar `max_tokens` |
| 413 | cuerpo o pregunta demasiado grandes | acortar |
| 429 | límite por IP (público) o intentos de login | esperar `Retry-After` |
| 503 | cola llena o modelo cargando | reintentar tras `Retry-After` |

`/readyz` devuelve 200 solo con el modelo listo (`{"status":"listo","device":"GPU",…}`) y 503
mientras carga; es lo que miran Docker y `desplegar.sh`.
