REGISTRO DE IA · NO ES FUENTE
Generado por: Claude · 22-oct-2026, a pedido de Juan (barra de progreso)
Estado de revisión: SIN REVISAR · pesos inferidos, confirmar
Manda por encima: `docs/REQUISITOS.md` · `CHANGELOG.md` · la palabra de Juan

# Progreso · GlubIA
Producto final: asistente personal y local (Qwen sobre OpenVINO) con UI y API compatible con OpenAI, corriendo en Windows y en Omarchy, con modos de disponibilidad, NPU y RAG.
Tarea actual: T-2.1

## H-1 · Versión 2.0 publicada · peso 30
- [x] T-1.1 · Servidor, UI, API OpenAI, cola y conversaciones · peso 5
- [x] T-1.2 · Contenedor, CI, GHCR, despliegue con vuelta atrás · peso 3
- [x] T-1.3 · Separar el portafolio a su repo · peso 1

## H-2 · Versión 2.1 (rama fix/prompts-2.1) · peso 15
- [ ] T-2.1 · Cerrar 2.1 y publicarla · peso 3
  - [x] Prompts corregidos (fix/prompts-2.1)
  - [x] Túnel rápido y vigilar.sh
  - [ ] Integrar fix/permisos-scripts (.gitignore UTF-8, chmod +x)
  - [ ] Integrar docs/claude-md
  - [ ] README sin el endpoint público retirado
  - [ ] Decidir número de versión y etiquetar
- [ ] T-2.2 · RF-06 · correr en Omarchy (Docker, grupo docker, modelo copiado) · peso 2
- [x] T-2.3 · Motor Ollama (GLUBIA_MOTOR=ollama, modelo en una línea del .env) · peso 1
- [x] T-2.4 · Panel de admin, selector de modelo e invitados con defensas anti prompt injection · peso 2

## H-3 · Requisitos pendientes · peso 40
- [ ] T-3.1 · RF-01 · Modos de disponibilidad e inactividad · peso 2 · avance 50
- [ ] T-3.2 · RF-02 · Uso del NPU · peso 3
- [ ] T-3.3 · RF-05 · RAG sobre documentación extensa · peso 3
- [ ] T-3.4 · Memoria a largo plazo y batching · peso 2

## H-4 · Nuevo uso de GlubIA (por definir) · peso 15
- [ ] T-4.1 · Definir el nuevo uso tras salir el portafolio · peso 1
