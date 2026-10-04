# Requisitos de GlubIA

Product Owner: Juan Pablo Avendaño Duque. Fecha: 2 oct 2026 (actualizado el 3 oct con la 2.1).
Estado de cada requisito frente a la versión 2.1: **Cumple**, **Parcial**, **Pendiente**.
Los marcados *Por validar* esperan la aprobación del PO antes de implementarse.

## Objetivo inmediato (2 semanas)

Un portafolio personal completo en un dominio propio: página estática (Cloudflare Pages) con un chat
de IA que responde sobre Juan y algunos de sus proyectos, servido por GlubIA corriendo en Omarchy en
su propio portátil.

## Requisitos funcionales

### RF-01 Modos de disponibilidad del servicio *(Por validar)*

El equipo no debe estar encendido 24/7 por salud del hardware. GlubIA se comporta según el estado
del equipo:

| Estado del equipo | Comportamiento de GlubIA |
|---|---|
| Arrancado en **Windows** | Desconectado. El chat del portafolio muestra "dormida" y ofrece contacto. |
| **Apagado** (noches, cuidado de batería) | Desconectado, igual que arriba. |
| **Omarchy en uso** (Juan trabajando) | Sirve con **recursos limitados**: el trabajo de Juan tiene prioridad. |
| **Omarchy inactivo** (pantalla apagada, sin uso) | Sirve con **todos los recursos** disponibles. |
| **Omarchy suspendido** | No es un estado válido para servir: la inactividad debe apagar la pantalla, no suspender. |

Criterios de aceptación:
1. Al quedar Omarchy inactivo, la pantalla se apaga y el sistema **no** se suspende mientras haya
   corriente.
2. Al detectar inactividad, GlubIA pasa a recursos completos; al volver Juan, a limitados, en menos
   de 5 s y sin cortar respuestas en curso.
3. Al arrancar Omarchy, GlubIA arranca solo; al pasar a Windows o apagar, el portafolio sigue
   visible y el chat informa que la IA no está disponible.
4. El cambio de modo queda en el registro (hora y modo).

Estado: **Parcial.** Hecho: arranque automático con Docker, página que funciona con la IA apagada
(estado "dormida"), límite fijo de memoria. Falta: configuración de inactividad sin suspensión y el
cambio dinámico de recursos (propuesta: ganchos de `hypridle` que ajustan CPU y prioridad del
contenedor con `docker update`).

### RF-02 Uso del NPU *(Por validar)*

GlubIA debe aprovechar el NPU del procesador (Intel AI Boost) como parte de su proceso de inferencia.
Además del rendimiento, el objetivo es aprender a usarlo, porque las nuevas generaciones de equipos
lo traen.

Criterios de aceptación:
1. Al menos una etapa del proceso (primero: embeddings para búsqueda en documentos) se ejecuta en el
   NPU mediante OpenVINO, con caída automática a CPU si el NPU no está disponible.
2. `/readyz` informa qué dispositivo usa cada etapa (p. ej. `generacion: GPU`, `embeddings: NPU`).
3. Medición comparativa NPU frente a CPU documentada.

Restricción: no se usa `intel-npu-acceleration-library`; Intel la archivó y recomienda OpenVINO.
PyTorch se usa solo para preparar o exportar modelos.

Estado: **Pendiente.** Hoy la generación usa GPU con caída a CPU; el NPU no se usa. Preparado en la
2.1: `GLUBIA_OV_CONFIG` para pasar `MAX_PROMPT_LEN` y demás opciones del NPU, y `scripts/medir.py`
para la comparación del criterio 3. Como RF-05 (y con él los embeddings) quedó fuera de alcance,
**propuesta para validar:** que la primera etapa en el NPU sea la generación del modelo pequeño del
portafolio, que además encaja con el modo limitado de RF-01 (ver `MODELOS.md`).

### RF-03 Control total de la información *(Por validar)*

1. La IA solo sabe lo que Juan pone explícitamente: su perfil y la documentación de proyectos que
   elija (repositorios públicos de GitHub).
2. **Todo lo que la IA puede leer se considera público.** No se confía en el modelo para ocultar
   nada; no hay información "marcada como privada" dentro de su conocimiento.
3. La IA no aprende de las conversaciones: los pesos del modelo no se modifican y las preguntas de
   los visitantes no se guardan.
4. Juan añade o quita información editando archivos; el cambio se aplica sin reiniciar.

Estado: **Cumple** para el perfil (recarga en caliente, comentarios no visibles para el modelo,
preguntas no guardadas, IP anonimizada en logs). Desde la 2.1 el perfil se genera desde
`portafolio/contenido/` (lo mismo que alimenta la página y el CV) y los textos en primera persona se
le pasan al modelo como citas tuyas. Lo que llega por el buzón (RF-07) **no** lo lee la IA. **Pendiente** la documentación de proyectos
(depende de RF-05).

### RF-04 Portafolio con chat sobre Juan

1. Página estática en el dominio propio, con CV y chat.
2. El chat responde solo sobre Juan y sus proyectos, con límites por visitante.
3. La página funciona aunque la IA esté apagada.

Estado: **Parcial.** Hecho: página, CV imprimible, 404 y perfil de la IA generados desde un solo
archivo (`portafolio/contenido/sitio.toml`), chat con estados, límites, persona en tercera persona
probada con agentes (`PRUEBAS-AGENTES.md`). Falta: dominio, despliegue en Cloudflare Pages + túnel
(`CLOUDFLARE.md`) y completar contacto (correo, LinkedIn) y, si quieres, más proyectos.

### RF-05 Consulta de documentación extensa (RAG) — fuera de alcance por ahora

Documentación larga de proyectos (`.md` extensos, conversaciones clave, diagramas e imágenes) que no
cabe en el prompt. Entra cuando sea necesaria y se apoya en RF-02 (embeddings en NPU).

Estado: **Pendiente, fuera del alcance de las 2 semanas.**

### RF-06 Trabajar en GlubIA desde Windows y desde Omarchy

1. El código vive en un repositorio de GitHub que se clona en ambos sistemas.
2. Lo que se desarrolla no afecta al servicio publicado hasta que se despliega una versión.
3. El modelo no va en el repositorio: se descarga verificado o se copia.

Estado: **Parcial.** Hecho: repositorio `JuanPabloAvendano/GlubIA` público, CI en verde (pruebas,
OpenVINO real, construcción y validación de la imagen), publicación en GHCR, Dependabot y scripts de
despliegue con vuelta atrás. Falta: el primer despliegue en Omarchy.

### RF-07 Buzón privado con verificación de identidad *(Por validar)*

Juan puede enviarse a su equipo cualquier tipo de información (chats, documentos, comprimidos,
notas) desde cualquier lugar, demostrando que es él.

1. Para enviar hace falta contraseña **y** un código de un solo uso de su teléfono (TOTP).
2. Se admite cualquier tipo y tamaño de archivo (hasta la cuota), con reanudación si se corta.
3. Lo recibido no se ejecuta, no se descomprime y no lo lee la IA.
4. Se comprueba la integridad (sha256) y se puede descargar o borrar desde la misma página.
5. Funciona a través de Cloudflare (límite de 100 MB por petición, RT-07).

Estado: **Cumple** a falta de validar (`BUZON.md`, probado de punta a punta en `POC.md`). Falta
activarlo en Omarchy con `python -m glubia.identidad activar`.

## Restricciones técnicas

- **RT-01 Soberanía:** el modelo se ejecuta completo en el equipo de Juan, sin servicios de terceros
  para generar respuestas.
- **RT-02 Hardware:** Intel Core Ultra 5 115U (GPU integrada + NPU), 16 GB LPDDR5 compartidos entre
  sistema, GPU y modelo; ~300 GB de disco en Omarchy. El modelo elegido debe dejar memoria para el
  trabajo diario (objetivo: ≤ 4 GB para el modelo del portafolio).
- **RT-03 Crecimiento del portafolio:** se espera un aumento continuo de funcionalidades
  (documentos descargables por CDN, audios con la voz de Juan, videos de YouTube propios, más
  segmentos). Añadir un tipo de contenido debe ser añadir datos, no rediseñar; la página debe seguir
  siendo estática y el contenido pesado vivir en un CDN o servicio externo.
- **RT-04 Escalabilidad y flexibilidad** son los drivers de arquitectura (ver
  `ARQUITECTURA-OBJETIVO.md`).
- **RT-05 Salud del equipo:** no se exige disponibilidad 24/7; la disponibilidad objetivo es
  "mientras Omarchy esté encendido".
- **RT-06 Plataforma:** OpenVINO 2026 (exige AVX2), Docker en Omarchy, Cloudflare (DNS, túnel, Pages).
- **RT-07 Tamaño de petición:** Cloudflare corta en 100 MB cada petición en los planes Free y Pro.
  Toda subida grande va por partes (el buzón usa 8 MiB).

## Resumen de estado

| Requisito | Estado |
|---|---|
| RF-01 Modos de disponibilidad | Parcial · por validar |
| RF-02 Uso del NPU | Pendiente · por validar |
| RF-03 Control de la información | Cumple (perfil) · por validar |
| RF-04 Portafolio con chat | Parcial |
| RF-05 RAG | Fuera de alcance |
| RF-06 Trabajo desde Windows y Omarchy | Parcial |
| RF-07 Buzón con verificación | Cumple · por validar |
