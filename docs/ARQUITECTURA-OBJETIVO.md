# GlubIA — Contexto y arquitectura objetivo

> Documento de traspaso para otro chat, modelo o desarrollador. Léelo completo antes de proponer
> cambios. Fecha: 2 oct 2026. Versión del producto al escribirlo: 2.0.0.

## 1. Rol y drivers

- **Cliente y Product Owner:** Juan Pablo Avendaño Duque (Colombia, trabaja en español). Él decide
  prioridades; las preguntas abiertas de la sección 10 son suyas.
- **Drivers de arquitectura, en este orden:**
  1. **Escalabilidad:** crecer en segmentos, modelos, dispositivos y usuarios sin reescribir.
  2. **Flexibilidad:** cambiar modelo, motor, almacenamiento o lugar de despliegue por configuración.
  3. **Portabilidad y privacidad:** el mismo producto corre en cualquier equipo propio (Windows,
     Omarchy, un servidor con GPU futuro) y se mueve de uno a otro; los datos no salen salvo
     decisión explícita.
  4. **Velocidad para añadir segmentos:** un segmento nuevo debe ser, idealmente, una carpeta de
     configuración, no código.
- **El plan cambiará.** Toda decisión debe ser reversible y quedar registrada (sección 9).

## 2. Qué es GlubIA hoy (2.0)

IA local: Qwen2.5-Coder-7B INT4 sobre OpenVINO GenAI 2026.3, en la GPU integrada de un portátil
Intel Core Ultra 5 115U (Windows). Interfaz web propia, API compatible con OpenAI y un asistente
público para un portafolio personal. Carpeta: `C:\Users\juanp\GlubIA`.

Mapa del código actual:

| Pieza | Archivo | Rol |
|---|---|---|
| Motor | `glubia/motor.py` | un hilo dueño del pipeline, cola con prioridades, cancelación por token, recorte de contexto por tokens |
| Backends | `glubia/backend_openvino.py`, `backend_falso.py` | generación real / simulada (pruebas) |
| API UI | `glubia/api_ui.py` | `/api/*` (sesión por cookie), conversaciones en SQLite |
| API v1 | `glubia/api_v1.py` | `/v1/models`, `/v1/chat/completions` (claves), `/v1/public/*` (portafolio) |
| Seguridad | `glubia/seguridad.py` | sesiones HMAC, claves hasheadas, IP real, limitador acotado |
| Persona | `glubia/perfil.py` + `portafolio/perfil/perfil.md` | el único "segmento" que existe, cableado a mano |
| Despliegue | `Dockerfile`, `compose*.yaml`, `portafolio/Caddyfile`, `scripts/` | contenedor, Caddy, túnel Cloudflare, desplegar con rollback |
| Pipeline | `github-ci/` (va a `.github/`), `scripts/evaluar.py` | CI con motor falso + OpenVINO real, release a GHCR, evaluación de modelos |
| Docs | `docs/PROBLEMAS.md`, `PIPELINE.md`, `API.md`, `OMARCHY.md`, `PORTAFOLIO.md` | detalle |

Estado real: 51 pruebas pasan (Python 3.12–3.14, incluidas pruebas con OpenVINO real). **Nunca se ha
ejecutado** en el equipo de Juan con la 2.0, ni se ha construido la imagen Docker, ni se ha
desplegado en Omarchy. El repositorio de GitHub aún no existe.

Otros componentes del ecosistema: `nodo_red.py` (transferencia de archivos en LAN con mDNS y PIN,
puerto 8500). Proyecto relacionado a futuro: servidor con 4× RTX 3090 para modelos grandes
(DeepSeek), con ángulo de negocio de privacidad para sectores como notarías.

## 3. Límites de la 2.0 frente a los drivers

1. **Un solo modelo, un solo proceso, una generación a la vez.** El motor no escala horizontalmente
   y el backend está acoplado a OpenVINO.
2. **El segmento está cableado:** "privado/arquitecto" y "público/portafolio" son rutas y código
   distintos. Añadir un tercero (p. ej. American Urban o notarías) exige programar.
3. **Persistencia acoplada a SQLite local** y a un único nodo; los datos de Windows y de Omarchy
   están separados.
4. **Sin noción de nodo/dispositivo:** no hay registro de qué equipos pueden inferir ni cómo
   alcanzarlos de forma privada.
5. **Despliegue y uso en el mismo equipo:** si Windows y Omarchy comparten portátil (arranque dual,
   pregunta abierta), el servicio cae mientras se trabaja.
6. **Sin conocimiento propio (RAG):** la persona solo sabe lo que cabe en el prompt.

## 4. Arquitectura objetivo

Principio: **núcleo estable y pequeño, todo lo demás enchufable por configuración** (puertos y
adaptadores). Las aplicaciones nunca hablan con el modelo: hablan con la API.

```
            apps (UI propia, portafolio, futuras por segmento, clientes OpenAI)
                                  │  HTTPS / API v1 estable
                          ┌───────▼────────┐
                          │    Gateway     │  auth, claves, límites, enrutado por segmento,
                          │  (FastAPI)     │  API OpenAI-compatible, streaming, auditoría
                          └───┬───────┬────┘
              registro de     │       │  cola de trabajos (en proceso → Redis/NATS)
              segmentos       │       │
        ┌─────────────┐  ┌────▼───────▼─────┐      ┌──────────────────┐
        │ segmentos/  │  │ Orquestador      │◀────▶│ Registro de      │
        │ (YAML+docs) │  │ (contexto, RAG,  │      │ modelos y nodos  │
        └─────────────┘  │  políticas)      │      └──────────────────┘
                         └────────┬─────────┘
                    ┌─────────────┼──────────────┐
             ┌──────▼─────┐ ┌─────▼──────┐ ┌─────▼───────┐
             │ Worker     │ │ Worker     │ │ Proveedor   │
             │ OpenVINO   │ │ vLLM/llama │ │ remoto      │  (solo si el segmento lo permite)
             │ (portátil) │ │ (GPU 3090) │ │ OpenAI-API  │
             └────────────┘ └────────────┘ └─────────────┘
         Almacén: interfaz única → SQLite (un nodo) | Postgres + pgvector (varios nodos)
         Red privada entre nodos: Tailscale/WireGuard. Exposición pública: Cloudflare Tunnel.
```

### 4.1 Segmento (la unidad de crecimiento)

Un segmento = persona + conocimiento + políticas + canales. Se declara en
`segmentos/<id>/segmento.yaml` y se recarga en caliente:

```yaml
id: portafolio
nombre: Asistente del portafolio de Juan
visibilidad: publico          # publico | privado | clave
persona: persona.md           # prompt de sistema
conocimiento:                  # opcional: RAG
  fuentes: [docs/*.md]
modelo:
  preferido: qwen2.5-7b-instruct
  alternativos: [qwen2.5-coder-7b]
  requiere: { contexto_min: 8192 }
limites: { tokens: 350, rpm: 6, dia: 80, cola: 3, prioridad: baja }
privacidad: { proveedores_remotos: false, guardar_conversaciones: false }
canales:
  web: { ruta: /s/portafolio, cors: [https://tu-dominio.com] }
```

Reglas:
- Una ruta genérica (`/v1/segments/{id}/chat` y `model: "segmento:<id>"` en la API OpenAI) sirve a
  todos; no hay endpoints por segmento.
- Los actuales "privado" y "portafolio" pasan a ser los dos primeros segmentos (`codigo`,
  `portafolio`) sin cambiar el comportamiento visible.
- Añadir un segmento = crear la carpeta + (opcional) una app en `apps/`. Objetivo: menos de una hora.

### 4.2 Proveedores de inferencia y registro de modelos

- Interfaz `ProveedorInferencia` (contar tokens, plantilla, generar en streaming con cancelación,
  capacidades). Implementaciones: `openvino` (hoy), `falso`, y después `vllm`/`llama.cpp` para
  NVIDIA y `openai_compatible` para remotos.
- `modelos.yaml` sustituye a `scripts/modelos.conf`: id, origen, revisión, hash, motor, dispositivos
  válidos, contexto, RAM estimada.
- El orquestador elige proveedor por segmento, capacidad y disponibilidad (con respaldo).

### 4.3 Workers y nodos

- Fase intermedia: gateway y worker como procesos separados en la misma máquina, con una cola.
- Fase multi-nodo: cada equipo corre un **agente de nodo** que anuncia sus modelos y capacidad al
  registro; los trabajos se envían por cola. Los nodos se ven por red privada (Tailscale); ningún
  worker se expone a internet.
- Portabilidad: imagen + volumen de datos + modelo verificado por hash. Mover GlubIA = `exportar`
  (datos) e `importar` en otro nodo, documentado y probado.

### 4.4 Almacenamiento

Interfaz `Almacen` para conversaciones, claves, auditoría y vectores. SQLite + sqlite-vec en un
nodo; Postgres + pgvector cuando haya varios. Cada registro lleva `segmento_id` (aislamiento por
segmento desde el principio, aunque haya un solo usuario).

### 4.5 Aplicaciones

Monorepo con `apps/` (UI, portafolio, futuras por segmento) que solo usan la API v1 o un SDK
mínimo generado del OpenAPI. Una app nunca importa código del servidor.

### 4.6 Transversal

Configuración 12-factor (variables de entorno + YAML), secretos fuera del repo, logs estructurados
(JSON), métricas Prometheus (`/metrics`: cola, tokens/s, errores por segmento), versión de API
estable (`/v1` no se rompe; los cambios incompatibles van a `/v2`).

## 5. Estructura de repositorio objetivo

```
glubia/
├── nucleo/            dominio: segmentos, conversaciones, políticas (sin dependencias externas)
├── puertos/           interfaces: ProveedorInferencia, Almacen, Cola, Conocimiento
├── adaptadores/       openvino, falso, vllm, openai_remoto, sqlite, postgres, redis...
├── gateway/           FastAPI: auth, API v1, streaming
├── worker/            consume la cola y ejecuta en un proveedor
└── nodo/              agente de nodo (fase multi-nodo)
segmentos/<id>/        segmento.yaml, persona.md, conocimiento/
modelos.yaml
apps/ui, apps/portafolio, apps/<segmento>
despliegue/            compose por perfil (un-nodo, gateway, worker-gpu), Caddy, túnel
tests/                 contrato de API, por puerto, por adaptador, de extremo a extremo
docs/adr/              decisiones
```

## 6. Plan de migración (incremental, siempre desplegable)

Cada fase termina con las pruebas en verde, la API v1 intacta y una versión publicada.

| Fase | Objetivo | Entregable verificable |
|---|---|---|
| 0. Base | repo en GitHub, CI corriendo, primer despliegue en Omarchy, prueba en GPU real | release v2.0.x desplegada con `desplegar.sh` |
| 1. Puertos | extraer `ProveedorInferencia`, `Almacen`, `RegistroSegmentos` dentro del proceso actual | mismas pruebas + pruebas de contrato por puerto |
| 2. Segmentos | `segmentos/` en YAML; `codigo` y `portafolio` migrados; ruta genérica | crear un tercer segmento sin tocar código |
| 3. Modelos | `modelos.yaml`, varios modelos, elección por segmento, `evaluar.py` por segmento | cambiar el modelo de un segmento por config |
| 4. Procesos | gateway y worker separados con cola; `/metrics` | escalar a 2 workers en una máquina |
| 5. Nodos | agente de nodo, Tailscale, export/import | inferencia en un segundo equipo |
| 6. Conocimiento | RAG por segmento (embeddings en OpenVINO, sqlite-vec) | segmento que cita sus documentos |
| 7. Datos | Postgres + pgvector cuando haya más de un nodo con estado | migración probada ida y vuelta |

No hacer todavía: Kubernetes, microservicios por segmento, multi-tenant con usuarios externos.
Se revisa cuando la fase 5 lo pida.

## 7. Restricciones técnicas que no hay que redescubrir

- OpenVINO GenAI 2026.3: `apply_chat_template` es `True` por defecto → pasar `ChatHistory`, no
  ChatML a mano (la 1.0 la aplicaba dos veces). `generate(str)` devuelve `str`; con `ChatHistory`,
  `DecodedResults`.
- Partir de `pipe.get_generation_config()` (eos 151645, stop 151643/151645); `do_sample=True` o se
  ignora la temperatura.
- El pipeline no es reentrante: un hilo por pipeline. Nada bloqueante en `async def`.
- Tras `StreamingStatus.STOP` el streamer puede recibir una llamada más.
- OpenVINO 2026 exige AVX2. Telemetría: escribir `0` en el archivo de consentimiento antes de
  importar.
- Uvicorn 0.52 declara ASGI 2.3: la cancelación depende de detectar desconexión de forma activa
  (`glubia/flujo.py`).
- GPU Intel en contenedor: `/dev/dri` + `group_add` con el GID de render del anfitrión; runtime del
  PPA `kobuk-team/intel-graphics`. Omarchy usa `ufw` + `ufw-docker`.
- `.github/` no se puede escribir de forma remota desde estas herramientas: entregar en otra carpeta.

## 8. Cómo trabajar en este proyecto

- Idioma: español. Código con identificadores en español; textos visibles con tildes.
- Antes de cambiar comportamiento, una prueba que lo fije (`tests/`, motor falso; `-m openvino` para
  lo que toca el modelo). Reproducir primero los fallos.
- No romper `/v1` ni `/api/*` usados por `ui.html` y el portafolio.
- Respaldar antes de sobrescribir archivos del usuario (como se hizo con `respaldo_v1/`).
- Cada decisión de arquitectura, un ADR corto en `docs/adr/NNN-titulo.md` (contexto, decisión,
  alternativas, consecuencias).

## 9. Decisiones tomadas (ADR resumidos)

1. **Interfaz servida por el propio servidor (mismo origen)** — evita CORS y contenido mixto con el
   túnel. Vigente.
2. **API compatible con OpenAI como contrato externo** — cualquier cliente sirve. Vigente.
3. **El modelo fuera de la imagen**, versionado por revisión y hash. Vigente.
4. **Despliegue pull** (el nodo tira de releases) en vez de runners en casa. Vigente.
5. **Segmentos como configuración, no código** — driver de velocidad. Nueva, pendiente de fase 2.
6. **Puertos y adaptadores** para inferencia y almacenamiento — driver de flexibilidad. Nueva.

## 10. Preguntas abiertas para el Product Owner

1. ¿Windows y Omarchy están en el mismo portátil (arranque dual) o en máquinas distintas? Define si
   hace falta un nodo siempre encendido.
2. ¿Qué segmentos siguen después del portafolio y del de código? (Candidatos: American Urban,
   notarías y sector legal, ciberseguridad.)
3. ¿Habrá usuarios externos (clientes) o solo uso propio? Cambia autenticación y aislamiento.
4. ¿Se acepta un proveedor remoto como respaldo en algún segmento, o privacidad estricta siempre?
5. ¿Qué hardware hay para un segundo nodo y cuándo?
6. Prioridad entre conocimiento propio (RAG) y multi-nodo.
