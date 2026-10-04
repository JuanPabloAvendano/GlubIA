# Cloudflare: qué comprar, qué activar y qué evitar

Precios y límites consultados el 2026-10-03 en la documentación oficial de Cloudflare (enlaces al
final). Cambian: revísalos el día que compres.

## Resumen

Para lo que estamos montando (página estática + IA en tu portátil + buzón privado), **lo único que
se paga es el dominio**. Todo lo demás cabe en los planes gratuitos.

| | Servicio | Para qué | Coste |
|---|---|---|---|
| **Obligatorio** | Registrar (dominio) | tu dirección fija | precio de coste: `.com` ≈ US$10,5/año, `.dev` ≈ US$12,2/año, `.co` ≈ US$30/año ¹ |
| **Obligatorio** | DNS | viene con el dominio | gratis |
| **Obligatorio** | Tunnel (`cloudflared`) | publicar tu equipo sin abrir puertos ni IP fija | gratis |
| **Obligatorio** | Pages | la página, siempre encendida aunque el portátil esté apagado | gratis |
| Recomendado | Zero Trust Access | segunda puerta delante de tu GlubIA privado y del buzón | gratis hasta 50 usuarios |
| Recomendado | Email Routing | `hola@tu-dominio.com` reenviado a tu Gmail | gratis |
| Recomendado | WAF: 1 regla de límite de peticiones | frenar abusos al chat antes de que lleguen a tu equipo | gratis (1 regla en Free) |
| Recomendado | Web Analytics | visitas sin cookies | gratis |
| Más adelante | R2 | PDFs, audios y otros archivos pesados del portafolio | 10 GB gratis al mes; sin coste de salida |
| Más adelante | Turnstile | si algún día pones un formulario de contacto | gratis |
| Opcional | Workers AI | respaldo en la nube cuando tu equipo duerma | 10.000 *neurons*/día gratis; ver abajo |
| Opcional | AI Gateway | registro y caché si usas modelos de la nube | funciones básicas gratis |
| No hace falta | Planes Pro/Business, Argo, Load Balancer, Workers Paid | | |

¹ Cloudflare vende al precio del registro, sin margen, y renueva al mismo precio. Las cifras salen
de un rastreador independiente (cfdomainpricing.com); Cloudflare no publica una tabla oficial.

## El dominio

- **`.com`** es la opción por defecto: barato, renueva igual, todo el mundo lo escribe bien.
- **`.dev`** obliga a HTTPS (Cloudflare ya lo pone) y suena a desarrollador.
- **`.co`** cuesta casi el triple cada año y Cloudflare solo permite registrarlo hasta 5 años.
- **Sin ñ:** Cloudflare Registrar no admite dominios internacionalizados. Usa `avendano`, no `avendaño`.
- El dominio queda con los servidores DNS de Cloudflare (obligatorio en su Registrar) y no se puede
  trasladar a otro registrador en los primeros 60 días (regla de ICANN).

Ideas: `juanpabloavendano.com`, `jpavendano.dev`, `avendano.dev`. Comprueba disponibilidad en el
panel de Cloudflare (*Domain Registration → Register Domains*).

## Cómo encaja cada pieza

```
visitante ──► tu-dominio.com           Cloudflare Pages (la página; nunca se apaga)
          └─► api.tu-dominio.com       Tunnel ──► Caddy :8080 en Omarchy ──► GlubIA (solo /api/preguntar y /api/info)
tú ─────────► ia.tu-dominio.com        Access (correo + código) ──► Tunnel ──► Caddy :8081 ──► GlubIA completo y /buzon
correo ─────► hola@tu-dominio.com      Email Routing ──► tu Gmail
```

Pasos, en orden:

1. **Comprar el dominio** en Cloudflare Registrar.
2. **Pages:** *Workers & Pages → Create → Pages → Upload assets*, sube la carpeta `portafolio/sitio`
   y asigna `tu-dominio.com`. Pages entiende el `_headers` y la `404.html` que genera
   `construir.py`. Antes, en `portafolio/contenido/sitio.toml` pon `url = "https://tu-dominio.com"`
   y `api = "https://api.tu-dominio.com"`, y ejecuta `python portafolio/construir.py --publicar`.
3. **Tunnel:** *Zero Trust → Networks → Tunnels → Create*, copia el token a `CF_TUNNEL_TOKEN`
   en el `.env` de Omarchy y arranca con `docker compose --profile tunel up -d`. Publica dos
   nombres: `api.tu-dominio.com → http://web:8080` e `ia.tu-dominio.com → http://web:8081`.
4. En `.env`: `GLUBIA_CORS=https://tu-dominio.com`.
5. **Access** para `ia.tu-dominio.com`: *Zero Trust → Access → Applications → Self-hosted*, política
   "Allow" solo para tu correo. Así, antes de ver siquiera el login de GlubIA, Cloudflare te pide
   un código enviado a tu correo. Con el TOTP de GlubIA son tres factores para el buzón.
6. **Límite de peticiones:** *Security → WAF → Rate limiting rules*, una regla para la ruta
   `/api/preguntar` de `api.tu-dominio.com` (en el plan Free el periodo es de 10 s). GlubIA ya
   limita por visitante; esto frena el abuso antes de que despierte tu equipo.
7. **Email Routing** y **Web Analytics** cuando quieras; no tocan nada del resto.

Límites a tener en cuenta:

- **100 MB por petición** en Free y Pro (413 si se pasa). El buzón sube por partes de 8 MiB, así
  que no te afecta (comprobado en `POC.md`).
- **Varios conectores del túnel:** si arrancas el túnel en Windows y en Omarchy a la vez, Cloudflare
  envía cada visita al conector más cercano, sin afinidad. Publica desde un solo equipo.
- **Pages Free:** 500 despliegues al mes, 20.000 archivos de hasta 25 MiB. Un video no cabe: va a
  YouTube; un PDF o un audio, en Pages si es pequeño o en R2.

## ¿Y la IA en la nube de Cloudflare?

**Workers AI** ejecuta modelos abiertos en la red de Cloudflare: Llama 3.2 1B/3B, Llama 3.1 8B,
Gemma 3 12B, Mistral 7B, entre otros. Cada día trae 10.000 *neurons* gratis; por encima cuestan
US$0,011 por cada 1.000 y exige Workers Paid (US$5/mes mínimo).

| A favor | En contra |
|---|---|
| Responde aunque tu portátil esté apagado | Rompe **RT-01 (soberanía)**: tu perfil y las preguntas se procesan en servidores de Cloudflare |
| Rápido, sin gastar tu batería ni tu RAM | Otro modelo, otra persona: hay que evaluar que respete las reglas igual |
| Gratis en volúmenes pequeños | Pasarse del gratuito obliga a pagar Workers Paid |

Mi recomendación: **no por ahora.** Cuando tu equipo duerme, la página ya lo dice y ofrece tu
contacto; es coherente con lo que GlubIA quiere demostrar ("una IA que corre en mi equipo"). Si
algún día quieres respaldo, el camino limpio es un Worker en `api.tu-dominio.com` que intente tu
túnel y, si no responde, use Workers AI **con el mismo perfil público** y avisando al visitante de
que está respondiendo la nube. Sería un requisito nuevo que tendrías que aprobar, porque cambia
RT-01.

## Otras posibilidades (fuera de Cloudflare)

| Opción | Cuándo tiene sentido |
|---|---|
| Comprar el dominio en otro registrador (Namecheap, Porkbun, GoDaddy) y apuntar los DNS a Cloudflare | si quieres un dominio con ñ o un TLD que Cloudflare no vende; el resto del montaje es idéntico |
| Tailscale en vez de Access para tu parte privada | si solo tú vas a entrar a `ia.` y prefieres una VPN entre tus equipos |
| Un VPS pequeño con el modelo | si necesitas la IA 24/7 sin depender del portátil; pagas cada mes y los datos salen de casa |
| GitHub Pages o Netlify para la página | equivalentes a Pages; Pages gana por tener DNS, túnel y Access en el mismo panel |

## Fuentes

- Registrar: https://developers.cloudflare.com/registrar/ · FAQ: https://developers.cloudflare.com/registrar/faq/ · dominios internacionalizados: https://developers.cloudflare.com/registrar/top-level-domains/ · traslados: https://developers.cloudflare.com/registrar/get-started/transfer-domain-to-cloudflare/
- Precios de dominios (no oficial): https://cfdomainpricing.com/
- Pages, límites: https://developers.cloudflare.com/pages/platform/limits/ · `_headers`: https://developers.cloudflare.com/pages/configuration/headers/ · 404: https://developers.cloudflare.com/pages/configuration/serving-pages/
- Tunnel, réplicas: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/tunnel-availability/
- Access: https://www.cloudflare.com/sase/products/access/
- Límite de tamaño de petición: https://developers.cloudflare.com/workers/platform/limits/
- R2: https://developers.cloudflare.com/r2/pricing/
- Workers: https://developers.cloudflare.com/workers/platform/pricing/
- Workers AI: https://developers.cloudflare.com/workers-ai/platform/pricing/ · modelos: https://developers.cloudflare.com/workers-ai/models/
- Turnstile: https://developers.cloudflare.com/turnstile/plans/ · Email Routing: https://developers.cloudflare.com/email-routing/ · Web Analytics: https://www.cloudflare.com/web-analytics/
- WAF, límite de peticiones: https://developers.cloudflare.com/waf/rate-limiting-rules/
- AI Gateway: https://developers.cloudflare.com/ai-gateway/reference/pricing/
