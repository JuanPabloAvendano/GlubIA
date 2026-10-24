#!/usr/bin/env bash
# ==========================================================================
#  Prueba de humo contra un despliegue en marcha (la usa desplegar.sh).
#
#    scripts/humo.sh                  # puertos de .env en 127.0.0.1
#    URL_PRIVADA=http://127.0.0.1:8081 scripts/humo.sh
#
#  Comprueba: modelo listo, UI servida, login y clave exigidos y Caddyfile
#  valido. Sale con 1 si algo falla.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
[ -f .env ] && set -a && . ./.env && set +a

URL_PRIVADA="${URL_PRIVADA:-http://127.0.0.1:${PUERTO_PRIVADO:-8081}}"
fallos=0

comprobar() {  # comprobar "descripcion" comando...
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  ok    $desc"; else echo "  FALLO $desc"; fallos=$((fallos + 1)); fi
}
# Se guarda la respuesta antes de buscar: con pipefail, `curl | grep -q` puede
# fallar aunque haya coincidencia (grep cierra la tuberia y curl recibe SIGPIPE).
contiene() { local out; out="$(curl -fsS --max-time "${3:-20}" "$1")" || return 1; grep -q -- "$2" <<<"$out"; }
codigo() { [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X "${3:-GET}" "$1")" = "$2" ]; }

echo "Prueba de humo"
comprobar "GlubIA listo (/readyz)"            contiene "${URL_PRIVADA}/readyz" '"status":"listo"'
comprobar "UI privada servida"                contiene "${URL_PRIVADA}/" "GlubIA"
comprobar "chat exige sesion (401)"           codigo "${URL_PRIVADA}/api/chat" 401 POST
comprobar "API v1 exige clave (401)"          codigo "${URL_PRIVADA}/v1/models" 401
comprobar "sin endpoint publico (404)"        codigo "${URL_PRIVADA}/v1/public/info" 404
if command -v docker >/dev/null && docker compose ps web >/dev/null 2>&1; then
  comprobar "Caddyfile valido"                docker compose exec -T web caddy validate --config /etc/caddy/Caddyfile
fi

if [ "$fallos" -gt 0 ]; then echo "$fallos comprobacion(es) fallaron"; exit 1; fi
echo "Todo en orden."
