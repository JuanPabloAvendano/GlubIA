# Portafolio con IA: qué hay listo y qué falta

## Lo que ya está

- **`portafolio/sitio/`**: la página. HTML, CSS y JS sin dependencias ni rastreadores; la fuente
  (Archivo, licencia OFL) va incluida, así que no se llama a ningún servicio externo.
  La conversación con la IA ocupa el centro: muestra si está despierta, ocupada o dormida, acepta
  preguntas sugeridas y responde en streaming.
- **`portafolio/perfil/perfil.md`**: todo lo que la IA sabe de ti. Se relee al guardarlo.
- **`portafolio/Caddyfile`**: sirve la página y expone de GlubIA solo `/api/preguntar` y `/api/info`.
- **El endpoint público** en GlubIA, con persona fija, límites por IP y cola de baja prioridad
  (ver `docs/API.md`).

Para verlo hoy en tu Windows, sin Docker y sin cargar el modelo:

```powershell
cd C:\Users\juanp\GlubIA
# consola 1: GlubIA con el motor simulado y el asistente publico activo
$env:GLUBIA_MOTOR="falso"; $env:GLUBIA_PUBLICO="1"; .\openvino_env\Scripts\python.exe glubia_server.py
# consola 2: la pagina, con las mismas rutas que pondra Caddy
.\openvino_env\Scripts\python.exe scripts\vista_portafolio.py
```

Abre `http://127.0.0.1:8080`. Sin `GLUBIA_MOTOR=falso` responde el modelo de verdad.

## Lo que necesito de ti

1. **Contenido de `perfil.md`.** Las líneas `REVISAR` son un borrador con lo que ya me contaste;
   las `COMPLETAR`, huecos: ciudad, a qué te dedicas y qué buscas, habilidades reales, formación y
   experiencia, y el canal de contacto que prefieres. Solo información que no te importe que sea
   pública: un visitante insistente puede lograr que la IA repita cualquier línea.
2. **Textos de la página** (`index.html`, marcados `EDITAR`/`REVISAR`): la frase de presentación, los
   tres proyectos y tus enlaces (correo, GitHub, LinkedIn).
3. **Una foto o imagen tuya** si quieres (`portafolio/sitio/img/`); la página funciona sin ella.
4. **El dominio.**
5. **Cuenta de Cloudflare** (gratis) para DNS y el túnel.

## El dominio

- A tu nombre, corto y fácil de dictar: `juanpabloavendano.com`, `avendano.dev`, `jpavendano.co`…
  (comprueba disponibilidad; la ñ en dominios existe pero da problemas al escribirla y compartirla).
- **Cloudflare Registrar** vende al costo, sin margen, y deja DNS y túnel en el mismo sitio.
  Soporta `.com`, `.co` y `.dev`. Mira el precio de **renovación**, no solo el del primer año:
  `.co` suele renovar bastante más caro que `.com`.
- `.dev` obliga a usar HTTPS: no es problema, Cloudflare lo pone.
- Si lo compras en otro registrador, cambia sus DNS a Cloudflare y todo lo demás es igual.

Con el dominio, "ubicador" fijo de tus servicios: `tu-dominio.com` (portafolio) y, si quieres,
`ia.tu-dominio.com` (tu GlubIA privado detrás de Cloudflare Access). La URL deja de cambiar en cada
reinicio, que era la limitación de `trycloudflare.com`.

## ¿Local o nube?

| Opción | Cómo | A favor | En contra |
|---|---|---|---|
| **A. Todo en Omarchy** | compose + túnel | 0 € al mes aparte del dominio; tus datos no salen | si apagas el equipo, cae también la página |
| **B. Híbrida (recomendada)** | página en Cloudflare Pages; IA en Omarchy por el túnel | la página no cae nunca; si el equipo duerme, el chat lo dice y ofrece tu contacto | un paso más de configuración |
| C. Todo en la nube | VPS de 8–16 GB con CPU | siempre encendido | pagas cada mes; el 7B en CPU va lento; los datos salen de casa |

**B, paso a paso:** sube `portafolio/sitio` a Cloudflare Pages (proyecto de "subida directa", sin
build) con tu dominio; en el túnel publica `api.tu-dominio.com → http://web:8080`; en `index.html`
activa `<meta name="glubia-api" content="https://api.tu-dominio.com">`; en `.env`,
`GLUBIA_CORS=https://tu-dominio.com`. La página ya maneja el estado "dormida".

Empezar con A es lo más rápido (ya funciona con `docker compose --profile tunel up -d`) y pasar a B
es mover una carpeta.

## Privacidad y avisos

- La página no usa cookies ni analítica, y las preguntas no se guardan: el servidor solo registra
  la hora y una IP recortada (`181.52.x.x`) para detectar abusos.
- Si algún día añades analítica, formularios o guardas conversaciones, en Colombia aplica la Ley
  1581 de 2012 (protección de datos personales): necesitarías un aviso de privacidad.
- El modelo puede equivocarse. Pide en `perfil.md` lo que no debe decir y añade casos a
  `scripts/eval_casos.json` cuando veas una respuesta mala.

## Modelo para la persona

Qwen2.5-Coder-7B es un modelo de código: en conversación general en español funciona, pero no es su
fuerte. Si las respuestas del portafolio te parecen rígidas, prueba un instruct general de la misma
familia en formato OpenVINO (por ejemplo los de la organización `OpenVINO` en Hugging Face) con el
flujo de `docs/PIPELINE.md` §5: descargar, evaluar y comparar antes de cambiar.
