#!/usr/bin/env bash
# ==========================================================================
#  Primera instalacion de GlubIA en Omarchy (o cualquier Linux con Docker).
#  Es idempotente: se puede volver a ejecutar sin romper nada.
#
#    git clone <tu-repo> ~/glubia && cd ~/glubia
#    scripts/instalar-omarchy.sh
#
#  Comprueba requisitos, detecta GPU Intel, crea .env, verifica el modelo y
#  levanta el stack. No abre puertos ni toca el firewall: eso es una decision
#  tuya (ver docs/OMARCHY.md).
# ==========================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

ok()    { echo "  ok    $*"; }
aviso() { echo "  AVISO $*"; }
fatal() { echo "  ERROR $*" >&2; exit 1; }

echo "1/6 Requisitos"
command -v docker >/dev/null || fatal "Docker no esta instalado (Omarchy lo trae; si no: sudo pacman -S docker docker-compose docker-buildx)"
docker info >/dev/null 2>&1 || fatal "Docker no responde: sudo systemctl enable --now docker  y  sudo usermod -aG docker \$USER (cierra sesion despues)"
docker compose version >/dev/null 2>&1 || fatal "Falta el plugin docker compose"
ok "Docker $(docker version -f '{{.Server.Version}}') con compose"
grep -qw avx2 /proc/cpuinfo || fatal "La CPU no tiene AVX2: OpenVINO 2026 no arranca en este equipo"
ok "CPU con AVX2: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
mem_gb=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
if [ "$mem_gb" -lt 12 ]; then aviso "RAM ${mem_gb} GB: el modelo 7B pide ~8 GB; considera qwen2.5-coder-0.5b-int4-ov"; else ok "RAM ${mem_gb} GB"; fi

echo "2/6 Configuracion (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  clave="$(head -c 18 /dev/urandom | base64 | tr -d '/+=' )"
  sed -i "s|^GLUBIA_PASS=.*|GLUBIA_PASS=${clave}|" .env
  chmod 600 .env
  ok "creado .env con una contrasena aleatoria (GLUBIA_PASS en .env)"
else
  ok ".env ya existe: no se toca"
fi

echo "3/6 GPU"
if [ -e /dev/dri/renderD128 ]; then
  gid="$(stat -c %g /dev/dri/renderD128)"
  sed -i "s|^RENDER_GID=.*|RENDER_GID=${gid}|" .env
  if grep -qE '^COMPOSE_FILE=.*compose\.cpu\.yaml' .env; then
    aviso "hay GPU pero .env fuerza solo CPU (COMPOSE_FILE)"
  fi
  vendor="$(cat /sys/class/drm/renderD128/device/vendor 2>/dev/null || echo '?')"
  if [ "$vendor" = "0x8086" ]; then ok "GPU Intel en /dev/dri/renderD128 (grupo ${gid})"
  else aviso "GPU no Intel (${vendor}): OpenVINO usara la CPU"; sed -i "s|^COMPOSE_FILE=.*|COMPOSE_FILE=compose.yaml:compose.cpu.yaml|" .env; fi
else
  sed -i "s|^COMPOSE_FILE=.*|COMPOSE_FILE=compose.yaml:compose.cpu.yaml|" .env
  aviso "sin /dev/dri: se usara solo la CPU (compose.cpu.yaml)"
fi

echo "4/6 Modelo"
set -a; . ./.env; set +a
modelo="${GLUBIA_MODELOS:-./modelos}/${GLUBIA_MODELO_DIR:-qwen2.5-coder-7b-int4-ov}"
if [ -f "${modelo}/openvino_model.xml" ]; then
  ok "modelo en ${modelo}"
else
  aviso "no hay modelo en ${modelo}"
  echo "        Opcion A: scripts/descargar-modelo.sh"
  echo "        Opcion B: copia aqui la carpeta modelo_qwen_7b_ov de Windows"
  read -r -p "        Descargar ahora (~4,5 GB)? [s/N] " r || r=n
  [ "${r,,}" = "s" ] && scripts/descargar-modelo.sh "${GLUBIA_MODELO_DIR:-qwen2.5-coder-7b-int4-ov}" || fatal "sin modelo no se puede arrancar"
fi

echo "5/6 Perfil del portafolio"
if [ -f portafolio/perfil/perfil.md ]; then ok "portafolio/perfil/perfil.md"; else aviso "falta portafolio/perfil/perfil.md"; fi
grep -q "COMPLETAR" portafolio/perfil/perfil.md 2>/dev/null && aviso "perfil.md aun tiene partes por COMPLETAR"

# La carpeta del buzon debe existir antes de arrancar: si la crea Docker, queda de root
# y el contenedor (usuario 1000) no puede escribir en ella.
mkdir -p "${GLUBIA_BUZON_HOST:-./buzon}"

echo "6/6 Arranque"
if [ "${GLUBIA_IMAGEN:-}" = "ghcr.io/cambia-esto/glubia" ] || ! docker compose pull glubia 2>/dev/null; then
  aviso "sin imagen publicada: se construye aqui (tarda unos minutos la primera vez)"
  sed -i "s|^GLUBIA_TAG=.*|GLUBIA_TAG=local|" .env
  docker compose build glubia
fi
docker compose up -d
echo
echo "Listo. Sigue la carga con:  docker compose logs -f glubia"
echo "  GlubIA privado ...... http://127.0.0.1:${PUERTO_PRIVADO:-8081}"
echo "  Portafolio .......... http://127.0.0.1:${PUERTO_PORTAFOLIO:-8080}"
echo "  Comprobar todo ...... scripts/humo.sh"
echo
echo "Para el buzon (enviarte archivos), activa la verificacion en dos pasos:"
echo "  docker compose exec glubia python -m glubia.identidad activar"
