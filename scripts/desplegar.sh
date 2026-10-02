#!/usr/bin/env bash
# ==========================================================================
#  Despliega una version de GlubIA en este equipo, con vuelta atras automatica.
#
#    scripts/desplegar.sh v2.1.0     # imagen publicada por el pipeline (GHCR)
#    scripts/desplegar.sh local      # construye aqui con el codigo actual
#
#  Pasos: guarda la version actual -> descarga/construye la nueva -> reinicia
#  -> espera /readyz -> prueba de humo. Si algo falla, vuelve a la anterior.
#  Cada despliegue queda anotado en despliegues.log.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

NUEVA="${1:?Uso: scripts/desplegar.sh <version|local>  (ej. v2.1.0)}"
[ -f .env ] || { echo "Falta .env (cp .env.example .env)" >&2; exit 1; }

actual="$(grep -E '^GLUBIA_TAG=' .env | cut -d= -f2- || true)"
actual="${actual:-latest}"
IMG="$(grep -E '^GLUBIA_IMAGEN=' .env | cut -d= -f2- || true)"
IMG="${IMG:-ghcr.io/cambia-esto/glubia}"
# Reconstruir 'local' encima de 'local' borraria la version a la que volver:
# se guarda antes con otra etiqueta.
if [ "$NUEVA" = "local" ] && [ "$actual" = "local" ] && docker image inspect "${IMG}:local" >/dev/null 2>&1; then
  docker tag "${IMG}:local" "${IMG}:local-anterior"
  actual="local-anterior"
fi

fijar_tag() {
  if grep -qE '^GLUBIA_TAG=' .env; then sed -i "s|^GLUBIA_TAG=.*|GLUBIA_TAG=$1|" .env
  else echo "GLUBIA_TAG=$1" >> .env; fi
}

esperar_listo() {
  local id estado
  id="$(docker compose ps -q glubia)"
  echo -n "Esperando a que el modelo cargue"
  for _ in $(seq 1 120); do         # hasta 10 min: el primer arranque en GPU compila kernels
    estado="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id" 2>/dev/null || true)"
    case "$estado" in
      healthy) echo " listo."; return 0 ;;
      unhealthy) echo " no sano."; return 1 ;;
    esac
    if [ "$(docker inspect -f '{{.State.Running}}' "$id" 2>/dev/null)" != "true" ]; then
      echo " el contenedor se detuvo."; return 1
    fi
    echo -n "."; sleep 5
  done
  echo " tiempo agotado."; return 1
}

anotar() { echo "$(date '+%F %T')  $*" >> despliegues.log; }

echo "Version actual: ${actual}  ->  nueva: ${NUEVA}"
if [ "$NUEVA" = "local" ]; then
  fijar_tag "local"
  docker compose build glubia
else
  fijar_tag "$NUEVA"
  if ! docker compose pull glubia; then
    echo "No se pudo descargar ${NUEVA}; se mantiene ${actual}." >&2
    fijar_tag "$actual"; exit 1
  fi
fi

docker compose up -d --remove-orphans
if esperar_listo && scripts/humo.sh; then
  anotar "OK      ${actual} -> ${NUEVA}"
  echo "Desplegada ${NUEVA}."
  docker image prune -f >/dev/null || true
  exit 0
fi

echo "La version ${NUEVA} fallo. Volviendo a ${actual}..." >&2
docker compose logs --tail 60 glubia >&2 || true
fijar_tag "$actual"
docker compose up -d --remove-orphans
if esperar_listo; then
  anotar "ROLLBACK ${NUEVA} fallo; restaurada ${actual}"
else
  anotar "ROLLBACK ${NUEVA} fallo y ${actual} tampoco arranco: revisar a mano"
fi
exit 1
