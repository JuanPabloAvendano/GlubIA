#!/usr/bin/env bash
# ==========================================================================
#  Prueba de humo contra un despliegue en marcha (la usa desplegar.sh).
#
#    scripts/humo.sh                  # puertos de .env en 127.0.0.1
#    URL_PRIVADA=http://127.0.0.1:8081 URL_PUBLICA=http://127.0.0.1:8080 scripts/humo.sh
#
#  Comprueba: modelo listo, UI servida, login exigido, portafolio servido,
#  asistente publico respondiendo y Caddyfile valido. Sale con 1 si algo falla.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
[ -f .env ] && set -a && . ./.env && set +a

URL_PRIVADA="${URL_PRIVADA:-http://127.0.0.1:${PUERTO_PRIVADO:-8081}}"
URL_PUBLICA="${URL_PUBLICA:-http://127.0.0.1:${PUERTO_PORTAFOLIO:-8080}}"
fallos=0

comprobar() {  # comprobar "descripcion" comando...
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  ok    $desc"; else echo "  FALLO $desc"; fallos=$((fallos + 1)); fi
}
# Se guarda la respuesta antes de buscar: con pipefail, `curl | grep -q` puede
# fallar aunque haya coincidencia (grep cierra la tuberia y curl recibe SIGPIPE).
contiene() { local out; out="$(curl -fsS --max-time "${3:-20}" "$1")" || return 1; grep -q -- "$2" <<<"$out"; }
preguntar() {
  local out
  out="$(curl -fsS --max-time 120 -H 'Content-Type: application/json' \
         -d '{"message":"Quien eres?","stream":false}' "${URL_PUBLICA}/api/preguntar")" || return 1
  grep -q '"answer"' <<<"$out"
}
codigo() { [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X "${3:-GET}" "$1")" = "$2" ]; }

echo "Prueba de humo"
comprobar "GlubIA listo (/readyz)"            contiene "${URL_PRIVADA}/readyz" '"status":"listo"'
comprobar "UI privada servida"                contiene "${URL_PRIVADA}/" "GlubIA"
comprobar "chat exige sesion (401)"           codigo "${URL_PRIVADA}/api/chat" 401 POST
comprobar "API v1 exige clave (401)"          codigo "${URL_PRIVADA}/v1/models" 401
comprobar "portafolio servido"                contiene "${URL_PUBLICA}/" "<html"
comprobar "el portafolio no expone la UI"     codigo "${URL_PUBLICA}/api/session" 404
if [ "${GLUBIA_PUBLICO:-1}" != "0" ]; then
  comprobar "asistente publico en linea"      contiene "${URL_PUBLICA}/api/info" '"status":"online"'
  comprobar "asistente publico responde"      preguntar
fi
if command -v docker >/dev/null && docker compose ps web >/dev/null 2>&1; then
  comprobar "Caddyfile valido"                docker compose exec -T web caddy validate --config /etc/caddy/Caddyfile
fi

if [ "$fallos" -gt 0 ]; then echo "$fallos comprobacion(es) fallaron"; exit 1; fi
echo "Todo en orden."
