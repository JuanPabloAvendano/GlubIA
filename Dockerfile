# syntax=docker/dockerfile:1.7
# ==========================================================================
#  GlubIA - imagen de produccion
#
#  Requisitos del equipo anfitrion:
#    * Linux x86-64 con AVX2 (OpenVINO 2026 lo exige; cualquier Intel/AMD de
#      ~2015 en adelante lo tiene).
#    * Para GPU: graficos Intel (Iris Xe, Arc, Core Ultra) con /dev/dri.
#      Sin GPU funciona igual en CPU (compose.cpu.yaml).
#
#  El MODELO NO va dentro de la imagen: se monta en /modelos (4,5 GB que no
#  deben viajar en cada actualizacion). Los datos persistentes van en /data.
#
#  Construir:   docker build -t glubia .
#  Sin runtime de GPU (imagen mas pequena):  --build-arg INTEL_GPU=0
# ==========================================================================
FROM ubuntu:26.04

ARG DEBIAN_FRONTEND=noninteractive
ARG INTEL_GPU=1
ARG UID=1000
ARG GID=1000
ARG VERSION=dev

LABEL org.opencontainers.image.title="GlubIA" \
      org.opencontainers.image.description="IA local con OpenVINO, interfaz web y API compatible con OpenAI" \
      org.opencontainers.image.version="${VERSION}"

# Python + tini (senales y procesos huerfanos) + runtime de computo Intel.
# El PPA kobuk-team/intel-graphics es el que documenta Intel para GPUs de
# cliente en Ubuntu 24.04 (Meteor Lake / Core Ultra incluidos).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates python3 python3-venv tini \
 && if [ "$INTEL_GPU" = "1" ]; then \
        apt-get install -y --no-install-recommends software-properties-common gpg-agent \
     && add-apt-repository -y ppa:kobuk-team/intel-graphics \
     && apt-get update \
     && apt-get install -y --no-install-recommends libze-intel-gpu1 libze1 intel-opencl-icd clinfo \
     && apt-get purge -y --auto-remove software-properties-common gpg-agent ; \
    fi \
 && rm -rf /var/lib/apt/lists/*

# Dependencias de Python fijadas (requirements.txt), en un venv propio.
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /opt/venv \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Usuario sin privilegios. La imagen de Ubuntu trae 'ubuntu' con UID 1000:
# se elimina para que glubia pueda usar 1000 (el UID habitual en Omarchy) y
# los archivos montados desde el anfitrion tengan permisos sin sorpresas.
# El archivo de consentimiento en "0" apaga la telemetria de OpenVINO.
RUN (userdel -r ubuntu 2>/dev/null || true) && (groupdel ubuntu 2>/dev/null || true) \
 && groupadd -g "${GID}" glubia \
 && useradd -m -u "${UID}" -g "${GID}" -s /usr/sbin/nologin glubia \
 && mkdir -p /data /modelos /perfil /home/glubia/intel \
 && printf 0 > /home/glubia/intel/openvino_telemetry \
 && chown -R glubia:glubia /data /home/glubia

WORKDIR /app
COPY glubia/ /app/glubia/
COPY ui.html glubia_server.py /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/glubia \
    GLUBIA_DATA=/data \
    GLUBIA_MODEL=/modelos/qwen2.5-coder-7b-int4-ov \
    GLUBIA_PERFIL=/perfil/perfil.md \
    GLUBIA_HOST=0.0.0.0 \
    GLUBIA_PORT=11434 \
    GLUBIA_DEVICE=GPU

USER glubia
EXPOSE 11434
VOLUME ["/data"]

# /readyz da 200 solo con el modelo cargado. El primer arranque en GPU compila
# kernels (1-3 min); los siguientes usan /data/ov_cache y tardan segundos.
HEALTHCHECK --interval=30s --timeout=5s --start-period=240s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/readyz', timeout=4)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "glubia"]
