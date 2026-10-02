"""GlubIA: IA local sobre OpenVINO con interfaz web propia y API.

El paquete se organiza asi:

    config.py          variables de entorno -> Config
    telemetria.py      apaga la telemetria de OpenVINO antes de importarlo
    motor.py           cola de trabajos, cancelacion, presupuesto de contexto
    backend_openvino.py / backend_falso.py   quien genera de verdad
    seguridad.py       sesiones, claves de API, limites por IP
    conversaciones.py  historial en SQLite (sincroniza la UI entre equipos)
    perfil.py          persona del portafolio para el endpoint publico
    api_ui.py          rutas de la interfaz (compatibles con la version 1)
    api_v1.py          API OpenAI-compatible + endpoint publico
    app.py             ensambla la aplicacion FastAPI
"""

__version__ = "2.0.0"
