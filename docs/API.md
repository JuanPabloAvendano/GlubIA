# API de GlubIA

Dos familias de rutas:

| Ruta | Acceso | Para qué |
|---|---|---|
| `/v1/models`, `/v1/chat/completions` | clave de API o sesión de la UI | API compatible con OpenAI |
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

## Interfaz web (`/api/*`)

Las de la v1 siguen igual (`/api/chat`, `/api/chat/stream`, `/api/login`, `/api/logout`,
`/api/session`, `/api/health`). Novedades:

- El stream emite además `{"id","queue"}` al principio y `{"context": {...}}` al empezar a generar
  (mensajes que llegaron al modelo, omitidos y tokens). Los clientes antiguos los ignoran.
- `POST /api/chat/cancel` con `{"id": "…"}` detiene esa generación.
- `GET /api/conversations`, `PUT /api/conversations/{id}`, `DELETE /api/conversations/{id}`:
  historial sincronizado (`GLUBIA_CONVERSACIONES=0` lo desactiva).

- El evento final del stream (y la respuesta de `/api/chat`) trae `firma`: el cliente la devuelve en
  cada turno del asistente del `history`. Para un invitado, los turnos sin firma válida se descartan.

## Modelos, panel de admin e invitados

| Ruta | Quién | Qué |
|---|---|---|
| `GET /api/modelos` | admin, invitado | catálogo (Ollama + carpetas OpenVINO), activo, estado del cambio. El invitado ve solo el activo y los permitidos |
| `POST /api/modelos/activar` `{"id"}` | admin, invitado con permiso | carga ese modelo en caliente; si falla, vuelve al anterior |
| `GET /api/admin/estado` | admin | modelos, ajustes, descargas, invitaciones y auditoría |
| `PUT /api/admin/ajustes` | admin | `{"ollama":{"gpu","pensar","keep"}, "openvino":{"device"}, "invitados":{"modelos","cambiar_modelo","max_tokens","rpm","system"}}` (parcial) |
| `POST /api/admin/modelos/descargar` `{"nombre"}` | admin | `ollama pull` en segundo plano; el progreso sale en `/api/admin/estado` |
| `DELETE /api/admin/modelos/ollama:<nombre>` | admin | `ollama rm` (no el activo) |
| `POST /api/admin/invitados` `{"nombre","horas"}` | admin | crea una invitación; el `codigo` solo viene en esta respuesta |
| `DELETE /api/admin/invitados/{id}` | admin | revoca al instante |

Ids de modelo: `ollama:usuario/modelo:etiqueta` y `openvino:<carpeta en GLUBIA_MODELOS>`. El modelo
elegido se guarda en `<GLUBIA_DATA>/ajustes.json` y manda sobre `GLUBIA_MOTOR`/`GLUBIA_OLLAMA_MODELO`.

Invitado: `POST /api/login` con `{"codigo": "XXXX-XXXX-XXXX-XXXX"}` (un solo uso; la cookie caduca con
la invitación). O el enlace `/?invitacion=CODIGO`. Los invitados no usan `/v1`, ni conversaciones en
el servidor, ni el panel.

## Estados y errores comunes

| Código | Cuándo | Qué hacer |
|---|---|---|
| 401 | falta sesión o clave | iniciar sesión o enviar `Authorization` |
| 400 | el mensaje no cabe en el contexto | acortarlo o bajar `max_tokens` |
| 413 | cuerpo o pregunta demasiado grandes | acortar |
| 429 | intentos de login | esperar `Retry-After` |
| 503 | cola llena o modelo cargando | reintentar tras `Retry-After` |

`/readyz` devuelve 200 solo con el modelo listo (`{"status":"listo","device":"GPU",…}`) y 503
mientras carga; es lo que miran Docker y `desplegar.sh`.
