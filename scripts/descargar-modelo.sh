#!/usr/bin/env bash
# ==========================================================================
#  Descarga un modelo del catalogo (scripts/modelos.conf) en ./modelos/<carpeta>
#
#    scripts/descargar-modelo.sh                       # el modelo de produccion
#    scripts/descargar-modelo.sh qwen2.5-coder-0.5b-int4-ov  # otro del catalogo
#
#  No instala nada en el anfitrion: usa un contenedor python:3.12-slim de un
#  solo uso. Alternativa sin descargar: copia la carpeta modelo_qwen_7b_ov de
#  Windows a ./modelos/qwen2.5-coder-7b-int4-ov (es el mismo modelo).
# ==========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

NOMBRE="${1:-qwen2.5-coder-7b-int4-ov}"
DESTINO="${GLUBIA_MODELOS:-./modelos}"

linea="$(grep -v '^#' scripts/modelos.conf | grep "^${NOMBRE}|" || true)"
if [ -z "$linea" ]; then
  echo "No esta '${NOMBRE}' en scripts/modelos.conf. Disponibles:" >&2
  grep -v '^#' scripts/modelos.conf | cut -d'|' -f1 | sed 's/^/  - /' >&2
  exit 1
fi
IFS='|' read -r carpeta repo revision hash <<<"$linea"

mkdir -p "$DESTINO"
DESTINO="$(readlink -f "$DESTINO")"
echo "Descargando ${repo}@${revision:0:12} en ${DESTINO}/${carpeta} ..."

docker run --rm \
  -e HF_HUB_DISABLE_TELEMETRY=1 -e HF_HOME=/tmp/hf \
  -e DUENIO="$(id -u):$(id -g)" \
  -v "${DESTINO}:/out" \
  python:3.12-slim sh -ec "
    pip install -q --root-user-action=ignore 'huggingface_hub>=1.0'
    hf download '${repo}' --revision '${revision}' --local-dir '/out/${carpeta}'
    rm -rf '/out/${carpeta}/.cache'
    chown -R \"\$DUENIO\" '/out/${carpeta}'
  "

if [ "$hash" != "-" ]; then
  echo "Verificando integridad de openvino_model.bin ..."
  echo "${hash}  ${DESTINO}/${carpeta}/openvino_model.bin" | sha256sum -c -
fi
echo "Listo. En .env:  GLUBIA_MODELO_DIR=${carpeta}"
