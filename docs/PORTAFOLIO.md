# Portafolio: cómo se edita y cómo se publica

## La idea

Todo el portafolio sale de **un solo archivo de datos** que editas tú:

```
portafolio/contenido/sitio.toml   ← quién eres, proyectos, contacto, medios, sugerencias
portafolio/contenido/ia.md        ← (opcional) lo que solo usa la IA
        │
        └─ python portafolio/construir.py
                ├─► sitio/index.html     la página (chat + proyectos + sobre mí + contacto)
                ├─► sitio/cv.html        CV imprimible (Imprimir → Guardar como PDF), con QR a tu dominio
                ├─► sitio/404.html       página de error
                ├─► sitio/_headers       cabeceras de seguridad para Cloudflare Pages
                ├─► sitio/robots.txt, sitemap.xml
                └─► perfil/perfil.md     lo que sabe la IA (se recarga solo, sin reiniciar GlubIA)
```

Así la página, el CV y la IA nunca se contradicen, y añadir algo (un proyecto, un video de YouTube,
un audio, un PDF) es **añadir datos, no rediseñar** (RT-03).

**Todo lo que pongas ahí es público** (RF-03): se publica en la página y la IA lo puede repetir. No
hay forma de "ocultarle" algo al modelo; si no quieres que se sepa, no lo escribas.

## Editar

1. Abre `portafolio/contenido/sitio.toml`. Cada sección tiene comentarios con ejemplos.
   - Los textos marcados `REVISAR` son un borrador general con lo que me contaste: reescríbelos con
     tu voz.
   - Un campo vacío (`""`) no se muestra.
   - En `para_ia` de cada proyecto va lo que quieres que la IA sepa pero que no hace falta en la
     página.
   - `habilidades`, `experiencia`, `formacion` y `medios` aparecen en la página y en el CV en cuanto
     les pongas contenido.
2. Genera:
   ```powershell
   .\openvino_env\Scripts\python.exe portafolio\construir.py
   ```
   Basta Python 3.11 o superior. Para el código QR del CV hace falta `segno` (está en
   `requirements.txt`: `pip install segno`); sin él, el CV sale sin QR y el CI lo marcará como desactualizado.
3. Míralo:
   ```powershell
   # consola 1: GlubIA con el motor simulado y el asistente público
   $env:GLUBIA_MOTOR="falso"; $env:GLUBIA_PUBLICO="1"; .\openvino_env\Scripts\python.exe glubia_server.py
   # consola 2: la página con las mismas rutas que pondrá Caddy
   .\openvino_env\Scripts\python.exe scripts\vista_portafolio.py
   ```
   Abre `http://127.0.0.1:8080`. Sin `GLUBIA_MOTOR=falso` responde el modelo de verdad.
4. Haz commit de `contenido/` **y** de lo generado. El CI comprueba que lo generado esté al día
   (`construir.py --comprobar`) y falla si editaste a mano un archivo generado.

### Medios (videos, audios, documentos)

```toml
[[medios]]
tipo = "video"
titulo = "Cómo funciona GlubIA"
youtube = "ID-de-11-caracteres"     # se carga solo al pulsar (youtube-nocookie): sin rastreo hasta entonces

[[medios]]
tipo = "documento"
titulo = "CV en PDF"
url = "https://archivos.tu-dominio.com/cv.pdf"   # Cloudflare R2 o el propio Pages si es pequeño
formato = "PDF"
peso = "180 KB"
```

`construir.py` ajusta la política de seguridad de la página según lo que uses (YouTube, audios de
otro dominio, la API en `api.tu-dominio.com`…). No hay que tocarla a mano.

## Publicar

Para publicar en tu dominio (pasos completos en `CLOUDFLARE.md`):

1. En `sitio.toml`: `url = "https://tu-dominio.com"` y, con la página en Cloudflare Pages,
   `api = "https://api.tu-dominio.com"`.
2. `python portafolio/construir.py --publicar` — falla si queda algo por completar (por ejemplo, la
   URL vacía, una marca `COMPLETAR` o la API apuntando a `http://`).
3. Sube la carpeta `portafolio/sitio` a Cloudflare Pages.
4. En el `.env` de Omarchy: `GLUBIA_PUBLICO=1` y `GLUBIA_CORS=https://tu-dominio.com`.

| Dónde vive | Cómo | A favor | En contra |
|---|---|---|---|
| **Pages + IA en Omarchy (recomendado)** | página en Pages; `api.` por el túnel | la página no cae nunca; si el equipo duerme, el chat lo dice y ofrece tu contacto | un paso más de configuración |
| Todo en Omarchy | Caddy sirve la página y la IA | lo más rápido de montar (`docker compose --profile tunel up -d`) | si apagas el equipo cae también la página |

Pasar de una a otra es mover la carpeta `sitio` y cambiar `api` en `sitio.toml`.

## Pendiente de tu parte

1. Revisar los textos `REVISAR` de `sitio.toml` con tu voz.
2. Correo y LinkedIn en `[[contacto]]` (con Email Routing puedes tener `hola@tu-dominio.com` gratis).
3. Si quieres, más proyectos: Lilatex POS, Small-POS-Project, FlorLogic, Kioskeo Intenso… Con una
   línea de cada uno basta para empezar.
4. El dominio.

## Privacidad

- La página no usa cookies ni analítica; las preguntas no se guardan. El servidor solo registra la
  hora y una IP recortada (`181.52.x.x`) para frenar abusos.
- Si algún día añades analítica con cookies, formularios o guardas conversaciones, en Colombia aplica
  la Ley 1581 de 2012: necesitarías un aviso de privacidad. Cloudflare Web Analytics no usa cookies.
- El modelo puede equivocarse. Cuando veas una respuesta mala, añade el caso a
  `scripts/eval_casos.json` (ver `MODELOS.md` y `PRUEBAS-AGENTES.md`).
