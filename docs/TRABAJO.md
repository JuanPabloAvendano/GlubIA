# Trabajar en GlubIA desde Windows y desde Omarchy

Un solo repositorio en GitHub, dos copias de trabajo. GitHub es la fuente de verdad.

```
 Windows (desarrollo)          GitHub (fuente de verdad)          Omarchy
 C:\Users\juanp\GlubIA  ⇄  github.com/<usuario>/glubia  ⇄  ~/glubia  (desarrollo)
                                     │ etiqueta vX.Y.Z
                                     ▼
                              imagen en GHCR ──▶ servicio publicado (docker compose)
```

## Reglas

1. **Antes de empezar en cualquier equipo:** `git pull`.
2. **Al terminar:** `git add`, `git commit`, `git push`. Nunca dejes trabajo solo en un equipo.
3. Una rama por cambio (`git switch -c feat/lo-que-sea`); `main` siempre funciona.
4. El servicio publicado **no** se toca editando archivos: se actualiza con
   `scripts/desplegar.sh <versión>`.
5. Lo que no viaja por git: el modelo, `datos/`, `.env`, `respaldo_v1/`. Cada equipo tiene los suyos.

## En Windows

```powershell
cd C:\Users\juanp\GlubIA
git pull
# probar sin cargar el modelo
$env:GLUBIA_MOTOR="falso"; .\openvino_env\Scripts\python.exe glubia_server.py
# probar con el modelo
.\iniciar.bat
# pruebas
.\openvino_env\Scripts\python.exe -m pytest -q
```

## En Omarchy

```bash
cd ~/glubia
git pull
# desarrollo en otro puerto, sin tocar el servicio publicado (8081)
GLUBIA_MOTOR=falso GLUBIA_PORT=11500 GLUBIA_DATA=./datos-dev python -m glubia
scripts/verificar.sh
# publicar lo que ya está en una versión
scripts/desplegar.sh v2.1.0     # o "local" para construir con el código actual
```

Evita cargar el modelo real en desarrollo mientras el servicio publicado lo tiene cargado: con 16 GB
no caben dos. Para eso está `GLUBIA_MOTOR=falso` o el modelo de 0,5B.

## Finales de línea

`.gitattributes` fija LF para `.sh`, `.py` y la configuración, y CRLF para `.bat`. Si Git en Windows
pregunta por `core.autocrlf`, déjalo en `true` (el valor por defecto del instalador): el archivo
`.gitattributes` manda.
