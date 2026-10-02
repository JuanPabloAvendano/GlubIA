@echo off
REM ==========================================================
REM  GlubIA - arranque en Windows
REM  Doble clic sobre este archivo. Todo se resuelve relativo
REM  a la carpeta donde este el .bat, asi que puedes moverla.
REM ==========================================================
setlocal
cd /d "%~dp0"

REM --- Contrasena de acceso. Cambiala. ---------------------
if "%GLUBIA_PASS%"=="" set GLUBIA_PASS=cambia-esta-clave

REM --- Dispositivo: GPU y si falla cae a CPU solo ----------
if "%GLUBIA_DEVICE%"=="" set GLUBIA_DEVICE=GPU
if "%GLUBIA_PORT%"=="" set GLUBIA_PORT=11434

REM --- Interprete: venv local si existe, si no el del PATH -
set PY=%~dp0openvino_env\Scripts\python.exe
if not exist "%PY%" set PY=python

echo.
echo  Arrancando GlubIA...  (Ctrl+C para parar)
echo.
"%PY%" glubia_server.py

echo.
echo  El servidor se ha detenido.
pause
