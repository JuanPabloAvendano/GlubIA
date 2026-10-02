# Requisitos de GlubIA

Product Owner: Juan Pablo Avendaño Duque. Fecha: 2 oct 2026.
Estado de cada requisito frente a la versión 2.0: **Cumple**, **Parcial**, **Pendiente**.
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

Estado: **Pendiente.** Hoy la generación usa GPU con caída a CPU; el NPU no se usa.

### RF-03 Control total de la información *(Por validar)*

1. La IA solo sabe lo que Juan pone explícitamente: su perfil y la documentación de proyectos que
   elija (repositorios públicos de GitHub).
2. **Todo lo que la IA puede leer se considera público.** No se confía en el modelo para ocultar
   nada; no hay información "marcada como privada" dentro de su conocimiento.
3. La IA no aprende de las conversaciones: los pesos del modelo no se modifican y las preguntas de
   los visitantes no se guardan.
4. Juan añade o quita información editando archivos; el cambio se aplica sin reiniciar.

Estado: **Cumple** para el perfil (`perfil.md`, recarga en caliente, comentarios no visibles para el
modelo, preguntas no guardadas, IP anonimizada en logs). **Pendiente** la documentación de proyectos
(depende de RF-05).

### RF-04 Portafolio con chat sobre Juan

1. Página estática en el dominio propio, con CV y chat.
2. El chat responde solo sobre Juan y sus proyectos, con límites por visitante.
3. La página funciona aunque la IA esté apagada.

Estado: **Parcial.** Hecho: página, chat, estados, límites y persona fija. Falta: contenido real,
dominio, despliegue en Cloudflare Pages + túnel, y el CV generado desde la misma fuente que el perfil.

### RF-05 Consulta de documentación extensa (RAG) — fuera de alcance por ahora

Documentación larga de proyectos (`.md` extensos, conversaciones clave, diagramas e imágenes) que no
cabe en el prompt. Entra cuando sea necesaria y se apoya en RF-02 (embeddings en NPU).

Estado: **Pendiente, fuera del alcance de las 2 semanas.**

### RF-06 Trabajar en GlubIA desde Windows y desde Omarchy

1. El código vive en un repositorio de GitHub que se clona en ambos sistemas.
2. Lo que se desarrolla no afecta al servicio publicado hasta que se despliega una versión.
3. El modelo no va en el repositorio: se descarga verificado o se copia.

Estado: **Parcial.** Hecho: repositorio organizado, CI y scripts de despliegue con vuelta atrás.
Falta: crear el repositorio y la primera ejecución del CI.

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

## Resumen de estado

| Requisito | Estado |
|---|---|
| RF-01 Modos de disponibilidad | Parcial · por validar |
| RF-02 Uso del NPU | Pendiente · por validar |
| RF-03 Control de la información | Cumple (perfil) · por validar |
| RF-04 Portafolio con chat | Parcial |
| RF-05 RAG | Fuera de alcance |
| RF-06 Trabajo desde Windows y Omarchy | Parcial |
