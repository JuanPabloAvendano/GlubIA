# GlubIA — instrucciones para Claude

IA local (Qwen2.5-Coder-7B INT4 sobre OpenVINO GenAI) con UI web propia, API compatible con OpenAI y
un asistente público para el portafolio. Product Owner: Juan Pablo (trabaja en español; el código,
los comentarios y la documentación del repo van en español).

## Antes de proponer cambios

- `README.md`, sección "Detalles técnicos que no hay que redescubrir": reglas de OpenVINO que ya
  costaron fallos (nada bloqueante en `async def`, el pipeline solo lo toca el hilo del motor, no
  construir la plantilla de chat a mano, `do_sample=True` para que cuente la temperatura...).
- `docs/ARQUITECTURA-OBJETIVO.md`: hacia dónde evoluciona y las preguntas abiertas que decide Juan.
- `docs/TRABAJO.md`: un solo repo, dos equipos (Windows y Omarchy). GitHub es la fuente de verdad.

## Mapa

- `glubia/` — paquete del servidor: `motor.py` (cola, cancelación, contexto por tokens),
  `backend_openvino.py` / `backend_falso.py`, `api_ui.py`, `api_v1.py`, `seguridad.py`, `perfil.py`.
- `glubia_server.py` — lanzador. `ui.html` — la interfaz. `portafolio/` — sitio, `perfil.md`, Caddyfile.
- `Dockerfile`, `compose*.yaml`, `.env.example`, `scripts/` — despliegue en Omarchy (`docs/OMARCHY.md`).
- `docs/historia/` — etapa anterior, solo referencia: no se edita ni se lintea.

## Comandos

```bash
GLUBIA_MOTOR=falso GLUBIA_PORT=11500 GLUBIA_DATA=./datos-dev python -m glubia   # desarrollo sin modelo
scripts/verificar.sh            # ruff + pytest (motor falso) + shellcheck: lo mismo que el CI
pytest -q -m "not openvino"     # pruebas rápidas
scripts/humo.sh                 # prueba de humo del stack en Docker
docker compose logs -f glubia   # seguir el servicio publicado
```

## Reglas

- No cargar el modelo real en desarrollo si el servicio publicado ya lo tiene cargado: con 15 GB
  de RAM no caben dos. Usar `GLUBIA_MOTOR=falso` o el modelo de 0,5B.
- El servicio publicado no se toca editando archivos: se actualiza con `scripts/desplegar.sh`.
- Nunca al repo: el modelo (`modelos/`, `modelo_qwen_7b_ov/`), `datos/`, `.env`, `respaldo_v1/`.
- Una rama por cambio; `main` siempre funciona. Cambios de versión se anotan en `CHANGELOG.md`
  (sección `[Sin publicar]`).
- Finales de línea: LF salvo `.bat` (CRLF). Ojo con archivos guardados desde PowerShell: pueden
  quedar en UTF-16.

## Este equipo (Omarchy)

Portátil Intel Core Ultra (Meteor Lake): GPU en `/dev/dri/renderD128` (grupo `render`, GID 987) y
NPU presente pero sin usar todavía. Repo en `~/Work/glubia` (los docs dicen `~/glubia`; las rutas
de los scripts son relativas, da igual).
