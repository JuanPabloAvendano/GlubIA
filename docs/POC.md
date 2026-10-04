# Prueba de concepto de las comunicaciones

Fecha: 2026-10-03. Objetivo: comprobar, antes de comprar nada, que cada tramo entre el visitante y
tu equipo se comporta como se espera: CORS, streaming, cancelación, subidas grandes y dos equipos
detrás del mismo nombre.

## Montaje

Se reprodujo la topología de producción en un entorno Linux de pruebas, con Caddy haciendo de
Cloudflare donde hacía falta:

```
 navegador ── :18070  "Cloudflare Pages" (la página en otro origen)
     │
     └──────── :18080  Caddy del portafolio ──► GlubIA con el modelo real (Qwen2.5-Coder-7B, CPU)
               :18090  "borde de Cloudflare": corta a 100 MB por petición ──► GlubIA (motor simulado)
               :18060  un nombre, dos nodos (A y B), el primero que responda ──► como dos conectores del túnel
```

El `Caddyfile` de producción se comprobó además con **Caddy 2.10.2** (el de la imagen
`caddy:2-alpine`) y con la 2.6 de las distribuciones.

## Resultados

| # | Prueba | Resultado |
|---|---|---|
| 1 | La página en otro origen habla con la IA (CORS) | ✅ preflight 200; solo se autoriza tu origen, un origen ajeno no recibe `Access-Control-Allow-Origin` |
| 2 | Caddy expone solo lo público | ✅ tras la corrección: `PUT/DELETE/TRACE/PATCH` a `/api/preguntar` y `/api/info` ya no llegan a GlubIA; `/v1/models`, `/api/session`, `/buzon`, `/docs` → 404 |
| 3 | 404 en rutas anidadas (`/a/b/c`) | ✅ tras la corrección: página 404 propia, con estilos |
| 4 | Streaming (SSE) a través del proxy | ✅ primer trozo a 0,01 s de una respuesta de 2 s: no hay búfer |
| 5 | **Detener** a través del proxy libera el modelo | ✅ la siguiente pregunta empieza en 0,12 s |
| 6 | Abandonar una petición **sin streaming** a través del proxy | ✅ tras la corrección (antes: 19,7 s ocupando el modelo para nadie) |
| 7 | Buzón: 30 MB en partes de 8 MiB por el "borde" de 100 MB | ✅ 4 partes en 0,3 s, reintento de una parte sin errores, sha256 coincide al bajarlo |
| 8 | Buzón: lo que excede los límites | ✅ 101 MB en una petición → 413 en el borde; parte de 20 MB directa a GlubIA → 413 |
| 9 | Buzón: contraseña sin código | ✅ 401 |
| 10 | Dos nodos: se apaga uno | ✅ responde el otro en ≤ 5 s |
| 11 | Dos nodos: la sesión al cambiar de nodo | ⚠️ se pierde: cada nodo firma con su propio secreto (ver abajo) |

Además, con un navegador real (Chromium) y respuestas simuladas, 15 de 15 comprobaciones de la
página: sugerencias desactivadas mientras carga, la pregunta vuelve a la caja tras un 429, la
respuesta parcial se conserva si se corta la conexión (y un stream que se cierra vacío se trata como corte), un 5xx vuelve a consultar el estado, cada
código de `/api/info` se muestra como debe (502/530 → dormida, 404/403 → no disponible, 429 → sin
cambio), los enlaces markdown del modelo funcionan y los `javascript:` no, el lector de pantalla
recibe la respuesta completa una sola vez, foco visible en alto contraste.

## Lo que se corrigió por esta prueba

- **Métodos en Caddy:** las rutas públicas ahora filtran por método (`POST` para preguntar, `GET`
  para el estado). Antes, cualquier método llegaba a GlubIA.
- **`flush_interval -1` en Caddy:** con Caddy 2.6, si el visitante abandonaba una petición sin
  streaming, Caddy no cerraba la conexión con GlubIA y el modelo seguía trabajando. Se quitó: Caddy
  ya envía al instante las respuestas `text/event-stream`, así que el streaming no cambia.
- **En el servidor:** GlubIA solo miraba si el cliente seguía conectado cuando no llegaban tokens;
  ahora lo mira cada segundo siempre.
- **404:** `handle_errors` en Caddy y rutas absolutas en `404.html`.

## Consecuencias para el diseño

**Dos equipos detrás del mismo nombre (Windows y Omarchy).** Cloudflare Tunnel permite varios
conectores para el mismo túnel y manda cada visita al **más cercano**, sin reparto ni afinidad. Si
algún día corres GlubIA en los dos a la vez:

- El asistente público funciona igual (no tiene sesión).
- Tu sesión privada y la verificación se pierden al saltar de equipo, salvo que copies
  `datos/.glubia_secret` (y, si quieres los mismos códigos, `datos/identidad.json`) de uno al otro.
- El buzón y las conversaciones viven en el disco de cada equipo: no se comparten.

Recomendación: **un solo equipo publicado a la vez** (Omarchy), que es además lo que pide RF-01.
Windows queda para desarrollar.

**Subidas grandes.** El límite de 100 MB por petición de Cloudflare (Free y Pro; 200 MB en
Business) no afecta: el buzón sube por partes de 8 MiB. Un archivo de varios GB funciona igual.

**Lo que no se pudo probar aquí:** el túnel real de Cloudflare, Cloudflare Access delante de
`/buzon` y la GPU/NPU del portátil. Son los primeros pasos cuando tengas el dominio (ver
`CLOUDFLARE.md`).

## Repetirlo

Los scripts de esta prueba están pensados para el entorno de pruebas, pero la lógica es la misma
contra tu Omarchy: `scripts/humo.sh` cubre el arranque, y las pruebas `tests/test_continuidad.py`
(cancelación con y sin streaming) y `tests/test_buzon.py` corren en el CI.
