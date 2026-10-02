@echo off
REM ==========================================================
REM  GlubIA + tunel Cloudflare
REM
REM  Levanta el servidor y, en otra ventana, cloudflared.
REM  La URL https://....trycloudflare.com aparece en la ventana
REM  del tunel. Cambia en cada reinicio.
REM
REM  Necesitas cloudflared.exe: ponlo junto a este archivo o
REM  instalalo con  winget install --id Cloudflare.cloudflared
REM ==========================================================
setlocal
cd /d "%~dp0"

if "%GLUBIA_PASS%"=="" set GLUBIA_PASS=cambia-esta-clave
if "%GLUBIA_DEVICE%"=="" set GLUBIA_DEVICE=GPU
if "%GLUBIA_PORT%"=="" set GLUBIA_PORT=11434

if "%GLUBIA_AUTH%"=="0" (
  echo.
  echo  ABORTADO: no se expone un tunel con GLUBIA_AUTH=0.
  pause
  exit /b 1
)

set PY=%~dp0openvino_env\Scripts\python.exe
if not exist "%PY%" set PY=python

set CF=%~dp0cloudflared.exe
if not exist "%CF%" set CF=cloudflared

echo  Arrancando servidor GlubIA...
start "GlubIA servidor" cmd /k ""%PY%" glubia_server.py"

echo  Esperando a que cargue el modelo...
REM Pregunta a /readyz cada 2 s (hasta 3 min) en vez de esperar 30 s a ciegas.
for /l %%i in (1,1,90) do (
  curl -s -f -o nul http://127.0.0.1:%GLUBIA_PORT%/readyz && goto :listo
  timeout /t 2 /nobreak >nul
)
echo  El modelo no respondio en 3 minutos; se abre el tunel igualmente.
:listo

echo  Abriendo tunel Cloudflare...
"%CF%" tunnel --url http://127.0.0.1:%GLUBIA_PORT%

echo.
echo  Tunel cerrado. El servidor sigue en su propia ventana.
pause
