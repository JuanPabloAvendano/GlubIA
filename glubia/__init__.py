"""GlubIA: IA local sobre OpenVINO con interfaz web propia y API.

El paquete se organiza asi:

    config.py          variables de entorno -> Config
    telemetria.py      apaga la telemetria de OpenVINO antes de importarlo
    motor.py           cola de trabajos, cancelacion, presupuesto de contexto
    backend_openvino.py / backend_ollama.py / backend_falso.py   quien genera
    seguridad.py       sesiones, claves de API, limites por IP
    catalogo.py        modelos de Ollama y OpenVINO bajo un mismo id; descargas
    ajustes.py         lo que se cambia desde el panel (ajustes.json)
    invitados.py       invitaciones de un solo uso, con caducidad
    guardia.py         defensas contra prompt injection y auditoria
    api_admin.py       panel de admin y selector de modelo
    conversaciones.py  historial en SQLite (sincroniza la UI entre equipos)
    api_ui.py          rutas de la interfaz (compatibles con la version 1)
    api_v1.py          API OpenAI-compatible
    app.py             ensambla la aplicacion FastAPI
"""

__version__ = "2.0.0"
