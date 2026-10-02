#!/usr/bin/env bash
# Lo mismo que hace el CI, en local, antes de hacer push.
#   scripts/verificar.sh                 # lint + pruebas con el motor falso
#   GLUBIA_TEST_MODELO=./modelos/qwen2.5-coder-0.5b-int4-ov scripts/verificar.sh   # + OpenVINO real
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
PY="${PY:-python3}"
"$PY" -m ruff check .
"$PY" -m pytest -q
if command -v shellcheck >/dev/null; then shellcheck scripts/*.sh iniciar.sh; fi
echo "Verificacion completa."
