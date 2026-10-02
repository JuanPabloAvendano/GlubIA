#!/usr/bin/env bash
# ==========================================================================
#  Actualizacion automatica (opcional): si hay una Release mas nueva en
#  GitHub que la desplegada, la despliega con scripts/desplegar.sh (que hace
#  vuelta atras sola si algo falla). Pensado para un temporizador de systemd;
#  ver docs/PIPELINE.md, seccion "Despliegue automatico".
#
#  Necesita en .env:
#    GLUBIA_REPO=tu-usuario/glubia
#    GITHUB_TOKEN=...   (solo si el repositorio es privado; permiso de lectura)
# ==========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
set -a; . ./.env; set +a

: "${GLUBIA_REPO:?Define GLUBIA_REPO=usuario/repositorio en .env}"
cabeceras=(-H "Accept: application/vnd.github+json")
[ -n "${GITHUB_TOKEN:-}" ] && cabeceras+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")

ultima="$(curl -fsS "${cabeceras[@]}" "https://api.github.com/repos/${GLUBIA_REPO}/releases/latest" \
          | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)"
actual="${GLUBIA_TAG:-latest}"

if [ -z "$ultima" ]; then echo "No se pudo leer la ultima Release."; exit 1; fi
if [ "$ultima" = "$actual" ]; then echo "Al dia (${actual})."; exit 0; fi
# Solo hacia delante: nunca baja de version por su cuenta.
if [ "$(printf '%s\n%s\n' "${actual#v}" "${ultima#v}" | sort -V | tail -n1)" != "${ultima#v}" ]; then
  echo "La desplegada (${actual}) es mas nueva que la ultima Release (${ultima}): no se toca."
  exit 0
fi
echo "Nueva version ${ultima} (desplegada: ${actual})."
exec scripts/desplegar.sh "$ultima"
