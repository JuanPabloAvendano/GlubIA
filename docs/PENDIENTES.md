# Lo que falta y cómo terminarlo

Estado al 3 oct 2026, versión 2.1.0. Lo que queda **no se puede hacer desde la nube**: necesita la
GPU y el NPU de tu portátil, Omarchy o tu cuenta de Cloudflare. Aquí está cada paso, en orden, con lo
que hay que instalar.

## 0. Ya está en tu disco

Los 65 archivos de la 2.1 están en `C:\Users\juanp\GlubIA`, verificados uno a uno. Falta una cosa
que no se puede escribir de forma remota: las dos acciones de GitHub.

```powershell
cd C:\Users\juanp\GlubIA
Copy-Item -Force github-ci\workflows\* .github\workflows\
```

(`dependabot.yml` ya quedó en `.github\`.) Después puedes borrar las carpetas `github-ci` y
`_temporal_claude`, que solo tienen copias y restos míos.

## 1. Instalar lo nuevo en Windows (2 minutos)

Tu `openvino_env` ya tiene OpenVINO 2026.3, FastAPI, httpx y huggingface_hub. Faltan tres paquetes
pequeños:

```powershell
cd C:\Users\juanp\GlubIA
.\openvino_env\Scripts\python.exe -m pip install segno psutil pytest
```

| Paquete | Para qué |
|---|---|
| `segno` | el código QR de la verificación en dos pasos y el del CV |
| `psutil` | que `scripts\medir.py` pueda medir la memoria en Windows |
| `pytest` | correr las pruebas |

## 2. Comprobar que todo funciona en tu equipo (5 minutos)

```powershell
.\openvino_env\Scripts\python.exe -m pytest -q                       # ~85 pruebas con el motor simulado
.\openvino_env\Scripts\python.exe portafolio\construir.py --comprobar  # "Portafolio al dia."
```

Y mira la página con el motor simulado (dos consolas, ver `PORTAFOLIO.md` §Editar):
`http://127.0.0.1:8080`.

Tu entorno usa Python 3.14; todo lo probé con 3.12. Si alguna prueba falla, mándame la salida.

## 3. Medir modelos en tu GPU y tu NPU (30–60 minutos, casi todo esperando)

Es lo único que decide qué modelo usar y si el NPU sirve (RF-02). No lo pude hacer desde aquí:
desde el entorno de trabajo no se llega a Hugging Face, y el espacio de trabajo dentro de tu
portátil solo tiene 2 núcleos virtuales, 3 GB de RAM y ni GPU ni NPU.

**Descargar Gemma 4 E2B** (~2–3 GB; queda fuera del repositorio porque `modelos/` está ignorado):

```powershell
.\openvino_env\Scripts\hf.exe download OpenVINO/gemma-4-E2B-it-int4-ov --local-dir modelos\gemma-4-e2b-it-int4-ov
```

**Medir** (cierra lo que no uses; cada comando dos veces, la segunda es la que cuenta):

```powershell
$py = ".\openvino_env\Scripts\python.exe"
& $py scripts\medir.py --modelo modelo_qwen_7b_ov --dispositivo GPU --json medidas\qwen7b-gpu.json
& $py scripts\medir.py --modelo modelos\gemma-4-e2b-it-int4-ov --dispositivo GPU --json medidas\gemma-gpu.json
& $py scripts\medir.py --modelo modelos\gemma-4-e2b-it-int4-ov --dispositivo CPU --json medidas\gemma-cpu.json
& $py scripts\medir.py --modelo modelos\gemma-4-e2b-it-int4-ov --dispositivo NPU --ov-config "MAX_PROMPT_LEN=2048,MIN_RESPONSE_LEN=256" --json medidas\gemma-npu.json
```

- Si Gemma falla al cargar con un error de arquitectura no soportada, actualiza OpenVINO a 2026.4
  (`pip install -U openvino==2026.4.* openvino-genai==2026.4.* openvino-tokenizers==2026.4.*`) y
  repite. Es el PR de Dependabot que está abierto.
- Si el NPU falla, también es información útil: guarda el error.
- En la GPU integrada, parte de la memoria del modelo no aparece como memoria del proceso. Mira
  además el Administrador de tareas → Rendimiento → GPU → "Memoria compartida".

Mándame los JSON de `medidas\` y decido contigo.

## 4. Probar cómo responde Gemma como asistente (20 minutos)

```powershell
# consola 1: GlubIA con Gemma y el asistente público
$env:GLUBIA_MODEL="modelos\gemma-4-e2b-it-int4-ov"; $env:GLUBIA_PUBLICO="1"
.\openvino_env\Scripts\python.exe glubia_server.py
# consola 2: la página
.\openvino_env\Scripts\python.exe scripts\vista_portafolio.py
# consola 3: las 9 preguntas del asistente público (incluidas las que fallaban con el 7B)
.\openvino_env\Scripts\python.exe scripts\evaluar.py --solo publica
```

Repite la consola 1 sin `GLUBIA_MODEL` (el 7B) para comparar. El resultado queda en `evaluaciones\`.

## 5. Guardar los cambios en git

Cuando estés conforme:

```powershell
git switch -c trabajo-2.1
git add -A
git status        # no deben aparecer modelos\, medidas\, datos\ ni .env (están ignorados)
git commit -m "GlubIA 2.1.0"
```

Subirlo a GitHub puede esperar.

## 6. Omarchy (cuando arranques en Linux)

Qué instalar: **Docker** (y nada más; el resto va dentro del contenedor).

```bash
sudo pacman -S --needed docker docker-compose git      # Omarchy está basado en Arch
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"                         # y cierra sesión
git clone https://github.com/JuanPabloAvendano/GlubIA.git ~/glubia
cd ~/glubia && scripts/instalar-omarchy.sh
docker compose exec glubia python -m glubia.identidad activar   # verificación en dos pasos
```

El modelo: copia `modelo_qwen_7b_ov` (y `modelos\gemma-…` si lo eliges) desde Windows a
`~/glubia/modelos/`. Detalle en `OMARCHY.md`.

Pendiente de diseño allí: **RF-01** (que la pantalla se apague sin suspender y que GlubIA use más
recursos cuando no estás). Lo hago contigo cuando tengas Omarchy instalado, porque depende de cómo
quede configurado `hypridle`.

## 7. Dominio y Cloudflare (cuando decidas el nombre)

Todo en `CLOUDFLARE.md`. Resumen: compra el dominio en Cloudflare Registrar (≈ US$10,5/año un
`.com`, sin ñ), sube `portafolio\sitio` a Pages, crea el túnel y pon su token en el `.env` de
Omarchy, y protege `ia.tu-dominio.com` con Access.

## 8. Contenido del portafolio (cuando quieras)

En `portafolio\contenido\sitio.toml`: revisar los textos marcados `REVISAR`, poner correo y
LinkedIn, y añadir Lilatex POS, Small-POS-Project, FlorLogic y Kioskeo Intenso si quieres que
aparezcan (y que la IA los conozca). Después, `construir.py`.

## Resumen

| # | Qué | Quién | Necesita |
|---|---|---|---|
| 0 | Mover las acciones de GitHub | tú | 1 comando |
| 1 | Instalar `segno`, `psutil`, `pytest` | tú | 1 comando |
| 2 | Pruebas en Windows | tú | — |
| 3 | Medir Gemma y el 7B en GPU/NPU | tú, yo analizo | descargar ~2–3 GB |
| 4 | Comparar respuestas | tú, yo analizo | lo del paso 3 |
| 5 | Commit | tú | — |
| 6 | Omarchy + RF-01 | juntos | Omarchy instalado |
| 7 | Dominio | tú | tarjeta |
| 8 | Contenido | tú, yo lo monto | una línea por proyecto |
