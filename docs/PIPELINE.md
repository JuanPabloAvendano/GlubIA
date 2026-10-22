# Pipeline de actualización

Cómo pasa un cambio de tu editor al GlubIA que corre en Omarchy, y cómo se cambia de modelo sin
romper nada.

```
 código                                                     Omarchy
 ──────                                                     ───────
 rama feat/… ──PR──▶ CI ─────────────────────▶ main
                     ├ calidad   (ruff, shellcheck, pruebas con motor falso)
                     ├ openvino  (pruebas con OpenVINO real + Qwen2.5-Coder-0.5B)
                     └ contenedor (construye la imagen, la arranca, valida compose y Caddy)

 main ──etiqueta v2.1.0──▶ Release ──▶ ghcr.io/<tú>/glubia:v2.1.0 ──▶ scripts/desplegar.sh v2.1.0
                                                                       ├ espera /readyz
                                                                       ├ prueba de humo
                                                                       └ si falla: vuelve sola a la anterior

 modelo ──▶ scripts/descargar-modelo.sh ──▶ GLUBIA_MODELO_DIR ──▶ reinicio ──▶ scripts/evaluar.py
           (revisión fijada + sha256)                                         (puerta de calidad)
```

El modelo nunca viaja dentro de la imagen: se actualizan por separado y con ritmos distintos.

## 1. Primera vez: el repositorio

1. Crea en GitHub un repositorio **privado** llamado `glubia`.
2. Lo más fácil: `powershell -ExecutionPolicy Bypass -File scripts\crear-repo.ps1 -Usuario TU-USUARIO`
   hace todo lo de abajo y además comprueba que no se suba el modelo ni ningún secreto.
   A mano, en tu carpeta (Windows, PowerShell). El primer comando coloca la configuracion de GitHub
   Actions, que se entrego en `github-ci\` porque `.github\` no se puede escribir de forma remota:

   ```powershell
   cd C:\Users\juanp\GlubIA
   Copy-Item -Recurse -Force github-ci\* .github\ ; Remove-Item -Recurse github-ci
   git init -b main
   git add .
   git status          # comprueba que NO aparecen modelo_qwen_7b_ov, openvino_env, datos ni .env
   git commit -m "GlubIA 2.0"
   git remote add origin https://github.com/<tu-usuario>/glubia.git
   git push -u origin main
   ```

   `.gitignore` deja fuera el modelo (4,5 GB), el venv, `datos/` y `.env`; `.gitattributes` fija
   los finales de línea para que los `.sh` funcionen en Linux aunque edites en Windows.
3. En GitHub → Settings → Branches: protege `main` (exigir PR y que pasen `calidad`, `openvino` y
   `contenedor`).
4. Cambia `ghcr.io/cambia-esto/glubia` por `ghcr.io/<tu-usuario>/glubia` en `.env.example`.
5. Tras la primera Release, en GitHub → Packages → glubia: déjalo privado y en Omarchy haz
   `docker login ghcr.io` con un token de solo lectura (`read:packages`), o hazlo público (la
   imagen no contiene secretos ni el modelo).

## 2. Día a día

- Una rama por cambio: `feat/memoria-larga`, `fix/cola`, `modelo/qwen3`.
- Antes de subir: `scripts/verificar.sh` (lo mismo que el CI, en local).
- Pull request a `main`; se fusiona solo con el CI en verde.
- `main` siempre se puede desplegar.

Para probar la UI o la API sin GPU ni modelo: `GLUBIA_MOTOR=falso python glubia_server.py`.

## 3. Versiones

[SemVer](https://semver.org/lang/es/) en `glubia/__init__.py`:

- **parche** (2.0.1): arreglos sin cambios de API.
- **menor** (2.1.0): funciones nuevas compatibles.
- **mayor** (3.0.0): cambios que rompen la API o la configuración.

Para publicar:

1. Sube `__version__` y escribe su sección en `CHANGELOG.md`.
2. PR, CI en verde, fusiona.
3. `git tag v2.1.0 && git push origin v2.1.0`.

`release.yml` comprueba que la etiqueta coincide con `__version__`, publica la imagen
(`v2.1.0`, `v2.1`, `latest` y `sha-…`, con SBOM y procedencia) y crea la Release con las notas del
CHANGELOG.

## 4. Desplegar en Omarchy

```bash
cd ~/glubia
git pull                       # trae compose, Caddyfile y scripts
scripts/desplegar.sh v2.1.0    # o "local" para construir aquí con el código actual
```

`desplegar.sh` guarda la versión actual, descarga la nueva, reinicia, espera a que el modelo cargue,
pasa `scripts/humo.sh` y, si algo falla, vuelve sola a la anterior. Todo queda en `despliegues.log`.

### Despliegue automático (opcional)

`scripts/actualizar-auto.sh` despliega la última Release si es más nueva que la desplegada (nunca
baja de versión). Para que lo haga cada noche, como servicio de tu usuario:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/glubia-actualizar.service <<'EOF'
[Unit]
Description=Actualiza GlubIA a la ultima Release
[Service]
Type=oneshot
WorkingDirectory=%h/glubia
ExecStart=%h/glubia/scripts/actualizar-auto.sh
EOF
cat > ~/.config/systemd/user/glubia-actualizar.timer <<'EOF'
[Unit]
Description=Busca versiones nuevas de GlubIA cada noche
[Timer]
OnCalendar=*-*-* 03:30
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now glubia-actualizar.timer
loginctl enable-linger "$USER"     # que corra aunque no hayas iniciado sesión
```

Necesita `GLUBIA_REPO=<tu-usuario>/glubia` en `.env` (y `GITHUB_TOKEN` de solo lectura si el repo
es privado). No uses un *runner* de GitHub dentro de tu equipo: con este modelo "tirar en vez de
empujar" no hace falta abrir nada hacia internet.

## 5. Cambiar de modelo

El modelo es la pieza que más cambia el comportamiento, así que tiene su propia puerta de calidad.

1. Añade una línea en `scripts/modelos.conf` (carpeta, repositorio, revisión fija y, si la tienes,
   el sha256 de `openvino_model.bin`).
2. `scripts/descargar-modelo.sh <carpeta>` descarga esa revisión exacta y verifica el hash.
3. Antes de cambiar, deja una línea base con el modelo actual:
   `GLUBIA_API_KEY=glb_… python3 scripts/evaluar.py`.
4. Cambia `GLUBIA_MODELO_DIR` en `.env` y `docker compose up -d`.
5. `python3 scripts/evaluar.py` otra vez: compara con la ejecución anterior y sale con error si
   bajan los aciertos o la velocidad cae más de un 20 %. Si falla, vuelve a la carpeta anterior.

Los casos están en `scripts/eval_casos.json`: código, Linux y systemd. (Los del portafolio se fueron
con él a su repo.) Añade un caso cada vez que veas una respuesta mala: así no vuelve.

## 6. Dependencias

Dependabot abre cada lunes PR agrupados (OpenVINO por un lado, FastAPI/Uvicorn por otro, imagen base
y acciones de GitHub). El CI los prueba con OpenVINO real antes de que decidas fusionarlos.
`requirements.txt` está fijado a versiones exactas: un build de hoy y uno de dentro de seis meses
dan la misma imagen.

## 7. Copias de seguridad

Lo único que no se puede regenerar está en el volumen `glubia-datos` (conversaciones, claves,
secreto de sesión) y en `.env`:

```bash
docker run --rm -v glubia_glubia-datos:/datos -v "$PWD":/copia alpine \
  tar czf "/copia/glubia-datos-$(date +%F).tar.gz" -C /datos .
```

El modelo y la imagen se vuelven a descargar.
