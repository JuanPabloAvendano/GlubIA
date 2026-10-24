#!/usr/bin/env bash
# ==========================================================
#  GlubIA - arranque en Linux/macOS
#    ./iniciar.sh           solo LAN
#    ./iniciar.sh --tunel   ademas abre un tunel Cloudflare
#  Las rutas se resuelven relativas a este archivo: la carpeta
#  se puede mover o copiar sin tocar nada.
# ==========================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

export GLUBIA_PASS="${GLUBIA_PASS:-cambia-esta-clave}"
export GLUBIA_DEVICE="${GLUBIA_DEVICE:-GPU}"
export GLUBIA_PORT="${GLUBIA_PORT:-11434}"

# venv local si existe, si no el python del PATH
if [ -x "openvino_env/bin/python" ]; then PY="openvino_env/bin/python"
elif [ -x "venv/bin/python" ];        then PY="venv/bin/python"
else PY="$(command -v python3 || command -v python)"; fi

TUNEL=0
[ "${1:-}" = "--tunel" ] && TUNEL=1

if [ "$TUNEL" = "1" ] && [ "${GLUBIA_AUTH:-1}" = "0" ]; then
  echo "ABORTADO: no se expone un tunel con GLUBIA_AUTH=0." >&2
  exit 1
fi

pids=()
limpiar(){ for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap limpiar EXIT INT TERM

if [ "$TUNEL" = "1" ]; then
  "$PY" glubia_server.py & pids+=($!)
  echo "Esperando a que el modelo cargue..."
  for _ in $(seq 1 90); do
    curl -sf "http://127.0.0.1:${GLUBIA_PORT}/readyz" >/dev/null && break
    sleep 2
  done
  echo "Abriendo tunel Cloudflare..."
  cloudflared tunnel --url "http://127.0.0.1:${GLUBIA_PORT}"
else
  exec "$PY" glubia_server.py
fi
