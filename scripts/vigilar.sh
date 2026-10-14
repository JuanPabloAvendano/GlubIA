#!/usr/bin/env bash
# ==========================================================================
#  Panel de estado de GlubIA en la terminal: contenedores, modelo, memoria y
#  enlaces publicos de los tuneles rapidos (cambian en cada reinicio).
#
#    scripts/vigilar.sh            # se refresca cada 10 s (Ctrl+C para salir)
#    scripts/vigilar.sh --una-vez  # imprime una vez y termina
#    INTERVALO=30 scripts/vigilar.sh
# ==========================================================================
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
[ -f .env ] && set -a && . ./.env && set +a

INTERVALO="${INTERVALO:-10}"
URL_PRIVADA="http://127.0.0.1:${PUERTO_PRIVADO:-8081}"

if [ -t 1 ]; then V=$'\e[32m'; R=$'\e[31m'; A=$'\e[33m'; N=$'\e[1m'; X=$'\e[0m'
else V=""; R=""; A=""; N=""; X=""; fi

enlace() {  # ultima URL trycloudflare que imprimio el servicio
  docker compose logs --no-log-prefix "$1" 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
}

codigo() { curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$1" 2>/dev/null; }

panel() {
  echo "${N}GlubIA${X} · $(date '+%F %T')"
  echo
  echo "${N}Servicios${X}"
  local filas
  filas="$(docker compose ps -a --format '{{.Service}}|{{.State}}|{{.Status}}' 2>/dev/null)"
  if [ -z "$filas" ]; then
    echo "  ${R}ninguno en marcha${X} (docker compose up -d)"
  else
    while IFS='|' read -r srv estado detalle; do
      local color="$V"
      [ "$estado" != "running" ] && color="$R"
      case "$detalle" in *unhealthy*) color="$R" ;; *starting*) color="$A" ;; esac
      printf '  %s%-18s%s %s\n' "$color" "$srv" "$X" "$detalle"
    done <<<"$filas"
  fi

  echo
  echo "${N}Modelo${X}"
  local listo
  listo="$(curl -s --max-time 5 "${URL_PRIVADA}/readyz" 2>/dev/null)"
  case "$listo" in
    *'"listo"'*) echo "  ${V}listo${X}" ;;
    "")          echo "  ${R}sin respuesta${X} en ${URL_PRIVADA}" ;;
    *)           echo "  ${A}cargando${X} ($(tr -d '\n' <<<"$listo" | cut -c1-80))" ;;
  esac
  local mem
  mem="$(docker stats --no-stream --format '{{.MemUsage}}' "$(docker compose ps -q glubia 2>/dev/null)" 2>/dev/null)"
  [ -n "$mem" ] && echo "  memoria: ${mem}"

  echo
  echo "${N}Enlaces${X}"
  echo "  local portafolio   http://127.0.0.1:${PUERTO_PORTAFOLIO:-8080}"
  echo "  local UI           ${URL_PRIVADA}"
  local srv url c
  for srv in tunel-portafolio tunel-ui; do
    url="$(enlace "$srv")"
    if [ -z "$url" ]; then
      printf '  %-18s %s\n' "$srv" "${A}sin tunel${X}"
      continue
    fi
    c="$(codigo "$url/")"
    if [ "$c" = "200" ]; then printf '  %-18s %s%s%s\n' "$srv" "$V" "$url" "$X"
    elif [ "$c" = "000" ]; then
      # Recien creado, el nombre tarda ~1 min en resolver (y el DNS local puede
      # recordar el "no existe" un rato mas): no es una caida.
      printf '  %-18s %s%s%s (aun no resuelve; espera un minuto)\n' "$srv" "$A" "$url" "$X"
    else printf '  %-18s %s%s%s (HTTP %s)\n' "$srv" "$R" "$url" "$X" "${c:-sin respuesta}"; fi
  done
  if [ -n "${CF_TUNNEL_TOKEN:-}" ]; then
    echo "  tunel con dominio  configurado (ver Cloudflare Zero Trust)"
  fi
}

if [ "${1:-}" = "--una-vez" ]; then panel; exit 0; fi

trap 'printf "\e[?25h"; exit 0' INT TERM
printf '\e[?25l'
while true; do
  salida="$(panel)"
  printf '\e[H\e[2J%s\n\nSe refresca cada %ss · Ctrl+C para salir\n' "$salida" "$INTERVALO"
  sleep "$INTERVALO"
done
