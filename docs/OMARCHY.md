# GlubIA en Omarchy

Guía para dejar GlubIA corriendo en Omarchy (Arch Linux + Hyprland) con Docker.
Sirve igual para cualquier Linux con Docker.

## Requisitos del equipo

| | Mínimo | Como tu portátil actual |
|---|---|---|
| CPU | x86-64 con AVX2 (OpenVINO 2026 lo exige) | Intel Core Ultra 5 115U |
| GPU (opcional) | Intel integrada Xe/Arc o dedicada Arc, con `/dev/dri` | Intel Graphics (Meteor Lake) |
| RAM | 12 GB para el modelo 7B (8 GB con el de 0,5B) | |
| Disco | 10 GB (modelo 4,5 GB + imagen ~1 GB + datos) | |

Sin GPU Intel (AMD, NVIDIA, máquina virtual) funciona en CPU con `compose.cpu.yaml`: más lento,
pero igual.

## Instalación

```bash
git clone https://github.com/<tu-usuario>/glubia.git ~/glubia
cd ~/glubia
scripts/instalar-omarchy.sh
```

El script comprueba Docker, AVX2 y RAM; detecta la GPU y el GID de `/dev/dri/renderD128`; crea
`.env` con una contraseña aleatoria; verifica el modelo (o lo descarga) y levanta el stack. No abre
puertos ni toca el firewall.

**El modelo:** o `scripts/descargar-modelo.sh` (misma revisión que usas hoy, verificada por hash), o
copia tu carpeta de Windows `modelo_qwen_7b_ov` a `~/glubia/modelos/qwen2.5-coder-7b-int4-ov`.

Si Docker no responde:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # y cierra sesión
```

## Qué queda corriendo

```
internet ─▶ tunel (cloudflared) ─┐   red "borde"          red "interna" (sin salida)
LAN/host ─▶ :8081 ───────────────┴─▶ web (Caddy) ─────────▶ glubia :11434
```

| Servicio | Qué es | Puerto en el equipo |
|---|---|---|
| `glubia` | el modelo, la UI y la API | ninguno: solo lo alcanza Caddy |
| `web` | Caddy delante de GlubIA privado (`:8081`) | `127.0.0.1` por defecto |
| `tunel` | Cloudflare Tunnel (perfil opcional) | ninguno: conexión saliente |

- `glubia` no tiene salida a internet: aunque algo quisiera enviar datos fuera, no puede.
- Los contenedores se reinician solos (`restart: unless-stopped`) y arrancan con Docker al
  encender el equipo.
- El primer arranque en GPU compila kernels (1–3 min). Los siguientes usan `/data/ov_cache` y
  tardan segundos. Síguelo con `docker compose logs -f glubia`.

Comprobaciones:

```bash
curl -s 127.0.0.1:8081/readyz          # {"status":"listo","device":"GPU",...}
scripts/humo.sh                        # prueba de humo completa
docker compose exec glubia clinfo -l   # ¿ve el contenedor la GPU?
```

## Acceso desde la LAN

Omarchy trae `ufw` bloqueando la entrada y usa `ufw-docker` para que los contenedores no queden
expuestos por accidente. Para abrir solo a tu red local:

```bash
# .env
WEB_BIND=0.0.0.0

docker compose up -d
sudo ufw route allow proto tcp from 192.168.1.0/24 to any port 8081   # GlubIA privado
```

(Cambia `192.168.1.0/24` por tu red. Con `ufw route` se indica el puerto del contenedor.) Para el
túnel no hace falta nada de esto: `cloudflared` sale hacia Cloudflare y no abre puertos.

## Tu dominio con Cloudflare Tunnel

1. Registra el dominio (o pásale los DNS a Cloudflare si lo compraste en otro sitio; el plan gratis
   basta).
2. Cloudflare → Zero Trust → Redes → Túneles → **Crear túnel** (tipo cloudflared), nómbralo
   `glubia` y elige Docker. Copia el token y ponlo en `.env` como `CF_TUNNEL_TOKEN`.
3. En el túnel, añade el nombre de host `ia.tu-dominio.com` → `http://web:8081`. El dominio raíz
   queda libre para el portafolio, que se publica aparte (repo `portafolio`, Cloudflare Pages).
4. `docker compose --profile tunel up -d`.
5. **Antes** de publicar `ia.tu-dominio.com`: Zero Trust → Access → Aplicaciones → *Self-hosted*
   para ese nombre, con una política que solo permita tu correo (código de un solo uso). Así tu UI
   privada queda detrás de Cloudflare además de tu contraseña.

Caddy solo confía en la IP fija de `cloudflared` (172.30.0.10) para saber la IP real del visitante,
y GlubIA solo confía en Caddy (172.31.0.20): los límites por visitante no se pueden falsear.

## Túnel rápido sin cuenta (siempre encendido)

Si aún no tienes dominio, pon `COMPOSE_PROFILES=tunel-rapido` en `.env` y `docker compose up -d`.
Se levanta `tunel-ui` (→ `web:8081`) con una URL `*.trycloudflare.com`, y vuelve solo tras cada
reinicio del equipo. La URL **cambia** cada vez que el contenedor se recrea: mírala con `scripts/vigilar.sh` (panel en vivo con servicios, modelo,
memoria y enlaces) o `scripts/vigilar.sh --una-vez`.

- La UI queda en internet protegida solo por `GLUBIA_PASS`: usa una contraseña larga.
- Recién creado, un enlace tarda ~1 minuto en resolver; el panel lo marca en amarillo.

Para que el panel se abra al iniciar sesión, en `~/.config/hypr/autostart.lua`:

```lua
o.exec_on_start("omarchy-launch-or-focus-tui --app-id=org.glubia.vigilar /ruta/a/glubia/scripts/vigilar.sh")
```

## Variantes

| Equipo | En `.env` |
|---|---|
| GPU Intel (por defecto) | `COMPOSE_FILE=compose.yaml` y `RENDER_GID` correcto |
| Solo CPU | `COMPOSE_FILE=compose.yaml:compose.cpu.yaml` |
| Windows con Docker Desktop (sin probar) | `COMPOSE_FILE=compose.yaml:compose.wsl.yaml` |

En Windows lo más sencillo sigue siendo `iniciar.bat`, que ya usa la GPU de forma nativa.

## Problemas frecuentes

- **`/readyz` dice `CPU` teniendo GPU Intel:** revisa `RENDER_GID` (`stat -c %g /dev/dri/renderD128`)
  y que `docker compose exec glubia clinfo -l` liste la GPU. En los logs verás el error exacto del
  plugin de GPU antes de la caída a CPU.
- **El contenedor se reinicia en bucle:** `docker compose logs glubia`. Lo habitual: el modelo no
  está en `./modelos/<GLUBIA_MODELO_DIR>` o falta `GLUBIA_PASS`.
- **`Illegal instruction` (código 132):** la CPU no tiene AVX2 (pasa en algunas máquinas virtuales).
- **Se queda sin memoria:** baja `GLUBIA_CTX` o usa el modelo de 0,5B; `GLUBIA_MEM` limita el
  contenedor para que no tumbe el resto del sistema.
- **La UI no responde:** `docker compose ps` y `scripts/humo.sh`.
