#!/usr/bin/env python3
"""
Construye el portafolio a partir de portafolio/contenido/ (una sola fuente):

    sitio/index.html   la pagina, con el chat de la IA
    sitio/cv.html      CV imprimible (Imprimir -> Guardar como PDF) con enlace a tu dominio
    sitio/404.html, sitio/_headers, sitio/robots.txt, sitio/sitemap.xml
    perfil/perfil.md   lo que sabe la IA (GlubIA lo relee solo al cambiar)

Uso:
    python portafolio/construir.py              construir
    python portafolio/construir.py --comprobar  ¿esta todo generado y al dia? (lo usa el CI)
    python portafolio/construir.py --publicar   construir y fallar si queda algo por completar

Solo biblioteca estandar (Python 3.11+). Para el codigo QR del CV usa 'segno' si esta.
Cada tipo de contenido nuevo (documentos, audio, video...) es un dato en sitio.toml,
no un cambio de diseno: asi el portafolio puede crecer sin rehacerse.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent
CONTENIDO = RAIZ / "contenido"
SALIDAS = {
    "index.html": RAIZ / "sitio" / "index.html",
    "cv.html": RAIZ / "sitio" / "cv.html",
    "404.html": RAIZ / "sitio" / "404.html",
    "_headers": RAIZ / "sitio" / "_headers",
    "robots.txt": RAIZ / "sitio" / "robots.txt",
    "sitemap.xml": RAIZ / "sitio" / "sitemap.xml",
    "perfil.md": RAIZ / "perfil" / "perfil.md",
}
PENDIENTES = re.compile(r"COMPLETAR|tu-dominio|tu-usuario|ejemplo\.com|example\.com", re.IGNORECASE)
YOUTUBE = re.compile(r"^[A-Za-z0-9_-]{11}$")
e = html.escape


class ErrorContenido(Exception):
    pass


# ----------------------------------------------------------------------------
# Lectura y validacion
# ----------------------------------------------------------------------------

def _https(url: str, campo: str, relativa: bool = False) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if relativa and url.startswith("/") and not url.startswith("//"):
        return url
    if url.startswith("mailto:"):
        return url
    p = urlparse(url)
    local = p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")   # solo para probar en tu equipo
    if (p.scheme != "https" and not local) or not p.netloc:
        raise ErrorContenido(f"{campo}: '{url}' debe empezar por https:// (o mailto:)")
    return url


def cargar(carpeta: Path = CONTENIDO) -> dict:
    with open(carpeta / "sitio.toml", "rb") as f:
        datos = tomllib.load(f)
    sitio = datos.setdefault("sitio", {})
    persona = datos.setdefault("persona", {})
    if not persona.get("nombre"):
        raise ErrorContenido("[persona] necesita 'nombre'")
    persona.setdefault("titular", [persona["nombre"]])
    sitio["url"] = _https(sitio.get("url", ""), "sitio.url").rstrip("/")
    sitio["api"] = _https(sitio.get("api", ""), "sitio.api").rstrip("/")
    for i, p in enumerate(datos.setdefault("proyectos", [])):
        if not p.get("nombre"):
            raise ErrorContenido(f"proyecto #{i + 1} sin nombre")
        p["enlaces"] = [dict(x, url=_https(x.get("url", ""), f"{p['nombre']}.enlaces", True))
                        for x in p.get("enlaces", []) if x.get("url")]
    contactos = []
    for c in datos.get("contacto", []):
        if c.get("url"):
            contactos.append(dict(c, url=_https(c["url"], f"contacto {c.get('tipo', '')}")))
    datos["contacto"] = contactos
    medios = []
    for m in datos.get("medios", []):
        tipo = m.get("tipo", "")
        if tipo == "video":
            if not YOUTUBE.match(m.get("youtube", "")):
                raise ErrorContenido(f"video '{m.get('titulo', '')}': 'youtube' debe ser el ID de 11 caracteres")
        elif tipo in ("audio", "documento", "enlace"):
            m["url"] = _https(m.get("url", ""), f"medio '{m.get('titulo', '')}'", True)
            if not m["url"]:
                continue
        else:
            raise ErrorContenido(f"tipo de medio desconocido: '{tipo}'")
        medios.append(m)
    datos["medios"] = medios
    ia = datos.setdefault("ia", {})
    extra = ia.get("conocimiento")
    ia["texto_extra"] = (carpeta / extra).read_text(encoding="utf-8") if extra and (carpeta / extra).exists() else ""
    return datos


def pendientes(datos: dict, carpeta: Path = CONTENIDO) -> list:
    """Lo que impide publicar: marcas COMPLETAR y direcciones de ejemplo en campos usados."""
    problemas = []
    for linea in (carpeta / "sitio.toml").read_text(encoding="utf-8").splitlines():
        codigo = linea.split("#", 1)[0]
        if PENDIENTES.search(codigo):
            problemas.append(linea.strip())
    if not datos["sitio"]["url"]:
        problemas.append("[sitio] url vacia: pon tu dominio")
    for campo in ("url", "api"):
        if datos["sitio"][campo].startswith("http://"):
            problemas.append(f"[sitio] {campo} apunta a tu equipo (http://): solo vale para probar")
    if not datos["contacto"]:
        problemas.append("no hay ningun medio de contacto con url")
    return problemas


# ----------------------------------------------------------------------------
# Piezas comunes
# ----------------------------------------------------------------------------

def _origen(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def csp(datos: dict) -> str:
    """Politica de contenido calculada a partir de lo que la pagina usa de verdad."""
    conectar, imagenes, medios_src, marcos = ["'self'"], ["'self'", "data:"], ["'self'"], []
    if datos["sitio"]["api"]:
        conectar.append(_origen(datos["sitio"]["api"]))
    for m in datos["medios"]:
        if m["tipo"] == "video":
            imagenes.append("https://i.ytimg.com")
            marcos.append("https://www.youtube-nocookie.com")
        elif m["tipo"] == "audio" and m["url"].startswith("https://"):
            medios_src.append(_origen(m["url"]))
    unicos = lambda xs: " ".join(dict.fromkeys(xs))  # noqa: E731
    partes = ["default-src 'self'", "script-src 'self'", "style-src 'self'", f"img-src {unicos(imagenes)}",
              "font-src 'self'", f"connect-src {unicos(conectar)}", f"media-src {unicos(medios_src)}",
              f"frame-src {unicos(marcos) or chr(39) + 'none' + chr(39)}", "object-src 'none'",
              "base-uri 'self'", "form-action 'self'"]
    return "; ".join(partes)


def _parrafos(texto: str) -> str:
    bloques = [b.strip() for b in re.split(r"\n\s*\n", texto or "") if b.strip()]
    return "".join(f"<p>{e(b)}</p>" for b in bloques)


def _enlace(texto: str, url: str, clase: str = "") -> str:
    externo = url.startswith("http")
    extra = ' rel="noopener"' if externo else ""
    c = f' class="{clase}"' if clase else ""
    return f'<a{c} href="{e(url)}"{extra}>{e(texto)}</a>'


def _cabecera(datos: dict, titulo: str, descripcion: str, ruta: str = "", raiz: str = "") -> str:
    """`raiz="/"` para paginas que pueden servirse en cualquier ruta (la 404): sus recursos
    tienen que pedirse desde la raiz, no relativos a /lo/que/sea/."""
    sitio, persona = datos["sitio"], datos["persona"]
    canonica = f'<link rel="canonical" href="{e(sitio["url"] + ruta)}">\n' if sitio["url"] else ""
    og_url = f'<meta property="og:url" content="{e(sitio["url"] + ruta)}">\n' if sitio["url"] else ""
    api = f'<meta name="glubia-api" content="{e(sitio["api"])}">\n' if sitio["api"] else ""
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{e(csp(datos))}">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descripcion)}">
<meta name="author" content="{e(persona['nombre'])}">
<meta name="color-scheme" content="light dark">
<meta property="og:title" content="{e(titulo)}">
<meta property="og:description" content="{e(descripcion)}">
<meta property="og:type" content="profile">
{og_url}{canonica}{api}<link rel="icon" href="{raiz}favicon.svg" type="image/svg+xml">
<link rel="preload" href="{raiz}fuentes/archivo.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{raiz}estilo.css">"""


# ----------------------------------------------------------------------------
# Pagina principal
# ----------------------------------------------------------------------------

def _proyectos(datos: dict) -> str:
    salida = []
    for p in datos["proyectos"]:
        etiquetas = "".join(f"<li>{e(t)}</li>" for t in p.get("etiquetas", []))
        enlaces = " ".join(_enlace(x["texto"], x["url"]) for x in p["enlaces"])
        estado = f' <span class="estado-proyecto">{e(p["estado"])}</span>' if p.get("estado") else ""
        salida.append(f"""
    <article class="proyecto">
      <h3>{e(p['nombre'])}{estado}</h3>
      <div>
        <p>{e(p.get('resumen', ''))}</p>
        {f'<ul class="etiquetas" aria-label="Tecnologías">{etiquetas}</ul>' if etiquetas else ''}
        {f'<p class="enlaces-proyecto">{enlaces}</p>' if enlaces else ''}
      </div>
    </article>""")
    return "".join(salida)


def _habilidades(datos: dict) -> str:
    grupos = datos.get("habilidades") or {}
    if not grupos:
        return ""
    filas = "".join(f"<div><dt>{e(g)}</dt><dd>{e(', '.join(v))}</dd></div>" for g, v in grupos.items() if v)
    return f"""
  <section class="seccion" aria-labelledby="t-habilidades">
    <h2 id="t-habilidades">Habilidades</h2>
    <dl class="habilidades">{filas}</dl>
  </section>"""


def _medios(datos: dict) -> str:
    if not datos["medios"]:
        return ""
    items = []
    for m in datos["medios"]:
        titulo, desc = e(m.get("titulo", "")), m.get("descripcion", "")
        texto = f"<p>{e(desc)}</p>" if desc else ""
        if m["tipo"] == "video":
            vid = m["youtube"]
            items.append(f"""
      <li class="medio">
        <a class="video" href="https://www.youtube.com/watch?v={vid}" data-youtube="{vid}">
          <img src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="" loading="lazy" width="480" height="360">
          <span class="play" aria-hidden="true">▶</span><span class="oculto">Ver el video: </span>
        </a>
        <h3>{titulo}</h3>{texto}
      </li>""")
        elif m["tipo"] == "audio":
            items.append(f"""
      <li class="medio">
        <h3>{titulo}</h3>{texto}
        <audio controls preload="none" src="{e(m['url'])}"></audio>
      </li>""")
        else:
            meta = " · ".join(x for x in (m.get("formato", ""), m.get("peso", "")) if x)
            items.append(f"""
      <li class="medio">
        <h3>{_enlace(m.get('titulo', m['url']), m['url'])}{f' <span class="meta-medio">{e(meta)}</span>' if meta else ''}</h3>{texto}
      </li>""")
    return f"""
  <section class="seccion" aria-labelledby="t-medios">
    <h2 id="t-medios">Escucha, mira y descarga</h2>
    <ul class="medios">{''.join(items)}
    </ul>
  </section>"""


def _contacto(datos: dict) -> str:
    if not datos["contacto"]:
        return ""
    lista = "".join(f'<li>{_enlace(c.get("texto") or c.get("tipo", c["url"]), c["url"])}</li>'
                    for c in datos["contacto"])
    return f"""
  <section class="seccion contacto" aria-labelledby="t-contacto" id="contacto">
    <h2 id="t-contacto">Escríbeme</h2>
    <p>Si quieres trabajar conmigo o tienes una pregunta que la IA no supo responder:</p>
    <ul class="enlaces">{lista}</ul>
  </section>"""


def pagina(datos: dict) -> str:
    persona, sitio = datos["persona"], datos["sitio"]
    titular = "".join(f"<span>{e(linea)}</span> " for linea in persona["titular"]).strip()
    sobre = _parrafos(persona.get("sobre_mi", ""))
    tiene_videos = any(m["tipo"] == "video" for m in datos["medios"])
    scripts = '<script src="chat.js" defer></script>' + ('\n<script src="medios.js" defer></script>' if tiene_videos else "")
    hay_contacto = "1" if datos["contacto"] else "0"
    return f"""<!doctype html>
<!-- GENERADO por portafolio/construir.py desde portafolio/contenido/. No lo edites a mano. -->
<html lang="{e(sitio.get('idioma', 'es'))}">
<head>
{_cabecera(datos, " ".join(persona['titular']), sitio.get('descripcion', ''))}
{scripts}
</head>
<body data-contacto="{hay_contacto}">
<a class="saltar" href="#pregunta">Ir a preguntarle a la IA</a>

<header class="cabecera">
  <h1 class="nombre">{titular}</h1>
  <p class="bajada">{e(persona.get('bajada', ''))}</p>
</header>

<main>
  <section class="charla" aria-labelledby="t-charla">
    <div class="charla-cabeza">
      <h2 id="t-charla">Pregúntale a mi IA</h2>
      <p class="estado" id="estado" data-estado="comprobando">
        <span class="luz" aria-hidden="true"></span>
        <span id="estado-texto" role="status">Comprobando si está despierta…</span>
      </p>
    </div>
    <p class="explica">Responde un modelo que vive en mi equipo, no un servicio en la nube. Sabe lo que yo le conté sobre mí y, si algo no lo sabe, te lo dice.</p>

    <div class="transcripcion" id="transcripcion"></div>
    <p class="oculto" id="anuncio" aria-live="polite"></p>
    <div class="sugerencias" id="sugerencias" role="group" aria-label="Preguntas sugeridas"></div>

    <form class="pregunta" id="formulario">
      <label for="pregunta" class="oculto">Tu pregunta</label>
      <textarea id="pregunta" name="pregunta" rows="2" maxlength="600" required
                placeholder="¿En qué está trabajando ahora?"></textarea>
      <div class="pregunta-pie">
        <span id="contador" class="contador">0 / 600</span>
        <button type="submit" id="enviar">Preguntar</button>
      </div>
    </form>
  </section>

  <section class="seccion trabajo" aria-labelledby="t-trabajo">
    <h2 id="t-trabajo">En qué trabajo</h2>{_proyectos(datos)}
  </section>
{f'''
  <section class="seccion sobre" aria-labelledby="t-sobre">
    <h2 id="t-sobre">Sobre mí</h2>
    {sobre}
  </section>''' if sobre else ''}{_habilidades(datos)}{_medios(datos)}{_contacto(datos)}
</main>

<footer class="pie">
  <p>Esta página no usa cookies ni rastreadores. Las preguntas a la IA no se guardan en mi equipo.
  <a href="cv.html">CV imprimible</a></p>
</footer>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# CV imprimible
# ----------------------------------------------------------------------------

def _qr_svg(url: str) -> str:
    try:
        import io

        import segno
    except ImportError:
        return ""
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=3, border=0, xmldecl=False, svgns=True,
                                    dark="#1c2a52", nl=False)
    return buf.getvalue().decode("utf-8")


def _periodo(item: dict) -> str:
    desde, hasta = item.get("desde", ""), item.get("hasta", "")
    if desde and not hasta:
        return f"{desde} – actualidad"
    return " – ".join(x for x in (desde, hasta) if x)


def cv(datos: dict) -> str:
    persona, sitio = datos["persona"], datos["sitio"]
    contactos = "".join(f"<li>{e(c.get('tipo', ''))}: {_enlace(c.get('texto') or c['url'], c['url'])}</li>"
                        for c in datos["contacto"])
    if sitio["url"]:
        dominio = urlparse(sitio["url"]).netloc
        contactos = f'<li>Web: {_enlace(dominio, sitio["url"])}</li>' + contactos
    qr = _qr_svg(sitio["url"]) if sitio["url"] else ""
    ia = (f'<aside class="cv-ia">{qr}<p><strong>Pregúntale a mi IA.</strong> En '
          f'{_enlace(urlparse(sitio["url"]).netloc, sitio["url"])} hay un asistente que responde sobre mi trabajo, '
          f'corriendo en mi propio equipo.</p></aside>') if sitio["url"] else ""
    trozos = []
    for p in datos["proyectos"]:
        estado = f" <span>{e(p['estado'])}</span>" if p.get("estado") else ""
        enlaces = " · ".join(_enlace(x["texto"], x["url"]) for x in p["enlaces"])
        trozos.append(f"<li><h3>{e(p['nombre'])}{estado}</h3><p>{e(p.get('resumen', ''))}</p>"
                      + (f"<p class='cv-enlaces'>{enlaces}</p>" if enlaces else "") + "</li>")
    proyectos = "".join(trozos)

    def bloque(titulo: str, items: list, cabeza, cuerpo) -> str:
        if not items:
            return ""
        lis = "".join(f"<li><h3>{e(cabeza(i))} <span>{e(_periodo(i))}</span></h3>"
                      f"{f'<p>{e(cuerpo(i))}</p>' if cuerpo(i) else ''}</li>" for i in items)
        return f"<section><h2>{titulo}</h2><ul>{lis}</ul></section>"

    experiencia = bloque("Experiencia", datos.get("experiencia", []),
                         lambda i: " · ".join(x for x in (i.get("cargo", ""), i.get("organizacion", "")) if x),
                         lambda i: i.get("descripcion", ""))
    formacion = bloque("Formación", [f for f in datos.get("formacion", []) if f.get("titulo")],
                       lambda i: " · ".join(x for x in (i.get("titulo", ""), i.get("institucion", "")) if x),
                       lambda i: i.get("descripcion", ""))
    grupos = datos.get("habilidades") or {}
    habilidades = ("<section><h2>Habilidades</h2><dl class='habilidades'>" + "".join(
        f"<div><dt>{e(g)}</dt><dd>{e(', '.join(v))}</dd></div>" for g, v in grupos.items() if v)
        + "</dl></section>") if grupos else ""
    sobre = _parrafos(persona.get("sobre_mi", ""))
    return f"""<!doctype html>
<!-- GENERADO por portafolio/construir.py desde portafolio/contenido/. No lo edites a mano. -->
<html lang="{e(sitio.get('idioma', 'es'))}">
<head>
{_cabecera(datos, f"CV · {persona['nombre']}", sitio.get('descripcion', ''), '/cv.html')}
</head>
<body class="cv">
<main class="hoja">
  <header>
    <h1>{e(persona['nombre'])}</h1>
    <p class="cv-bajada">{e(persona.get('bajada', ''))}</p>
    <ul class="cv-contacto">{f"<li>{e(persona.get('ubicacion', ''))}</li>" if persona.get('ubicacion') else ''}{contactos}</ul>
  </header>
  {ia}
  {f'<section><h2>Perfil</h2>{sobre}</section>' if sobre else ''}
  <section><h2>Proyectos</h2><ul>{proyectos}</ul></section>
  {experiencia}{formacion}{habilidades}
</main>
<footer class="no-imprimir"><p><a href="./">← Volver</a> · Para guardarlo en PDF: Imprimir → Guardar como PDF.</p></footer>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# Lo que sabe la IA
# ----------------------------------------------------------------------------

def perfil_ia(datos: dict) -> str:
    persona, sitio = datos["persona"], datos["sitio"]
    lineas = [f"# {persona['nombre']}", "",
              "<!-- GENERADO por portafolio/construir.py desde portafolio/contenido/. No lo edites a mano. -->", "",
              "## Quién es", ""]
    if persona.get("bajada"):
        lineas.append(f"En sus palabras: «{persona['bajada']}»")
    if persona.get("ubicacion"):
        lineas.append(f"Vive y trabaja en {persona['ubicacion']}.")
    if persona.get("sobre_mi", "").strip():
        lineas += ["", "Sobre sí mismo, Juan escribe: «" + " ".join(persona["sobre_mi"].split()) + "»"]
    lineas += ["", "## Proyectos"]
    for p in datos["proyectos"]:
        lineas += ["", f"### {p['nombre']}"]
        if p.get("estado"):
            lineas.append(f"Estado: {p['estado']}.")
        if p.get("resumen", "").strip():
            lineas.append("Juan lo describe así: «" + " ".join(p["resumen"].split()) + "»")
        if p.get("para_ia", "").strip():
            lineas.append(p["para_ia"].strip())
        if p.get("etiquetas"):
            lineas.append("Tecnologías y temas: " + ", ".join(p["etiquetas"]) + ".")
        for x in p["enlaces"]:
            lineas.append(f"{x['texto']}: {x['url']}")
    grupos = datos.get("habilidades") or {}
    if grupos:
        lineas += ["", "## Habilidades"] + [f"- {g}: {', '.join(v)}" for g, v in grupos.items() if v]
    for titulo, clave in (("Experiencia", "experiencia"), ("Formación", "formacion")):
        items = [i for i in datos.get(clave, []) if i.get("titulo") or i.get("cargo")]
        if items:
            lineas += ["", f"## {titulo}"]
            for i in items:
                nombre = " · ".join(x for x in (i.get("cargo", i.get("titulo", "")),
                                                i.get("organizacion", i.get("institucion", ""))) if x)
                lineas.append(f"- {nombre} ({_periodo(i) or 'sin fechas'}). {i.get('descripcion', '')}".strip())
    lineas += ["", "## Contacto"]
    if datos["contacto"]:
        lineas += [f"- {c.get('tipo', '')}: {c['url'].removeprefix('mailto:')}" for c in datos["contacto"]]
    else:
        lineas.append("Por ahora no hay un medio de contacto publicado.")
    if sitio["url"]:
        lineas.append(f"- Web: {sitio['url']}")
    if datos["medios"]:
        lineas += ["", "## Material publicado"]
        for m in datos["medios"]:
            destino = f"https://www.youtube.com/watch?v={m['youtube']}" if m["tipo"] == "video" else m["url"]
            lineas.append(f"- {m['tipo'].capitalize()}: {m.get('titulo', '')} ({destino}) {m.get('descripcion', '')}".strip())
    if datos["ia"]["texto_extra"].strip():
        lineas += ["", datos["ia"]["texto_extra"].strip()]
    sugerencias = datos["ia"].get("sugerencias", [])
    if sugerencias:
        lineas += ["", "## Preguntas sugeridas", ""] + [f"- {s}" for s in sugerencias]
    return "\n".join(lineas) + "\n"


# ----------------------------------------------------------------------------
# Archivos auxiliares
# ----------------------------------------------------------------------------

def cabeceras_pages() -> str:
    return """# Cabeceras para Cloudflare Pages (GENERADO por construir.py).
# La politica de contenido (CSP) va dentro de cada HTML, calculada segun lo que usa.
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  X-Frame-Options: DENY
  Content-Security-Policy: frame-ancestors 'none'
/fuentes/*
  Cache-Control: public, max-age=31536000, immutable
"""


def robots(datos: dict) -> str:
    url = datos["sitio"]["url"]
    return "User-agent: *\nAllow: /\n" + (f"Sitemap: {url}/sitemap.xml\n" if url else "")


def sitemap(datos: dict) -> str:
    url = datos["sitio"]["url"]
    entradas = "".join(f"  <url><loc>{e(url + r)}</loc></url>\n" for r in ("/", "/cv.html")) if url else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + entradas + "</urlset>\n")


def pagina_404(datos: dict) -> str:
    return f"""<!doctype html>
<html lang="{e(datos['sitio'].get('idioma', 'es'))}">
<head>
{_cabecera(datos, "Página no encontrada", datos['sitio'].get('descripcion', ''), raiz="/")}
<meta name="robots" content="noindex">
</head>
<body>
<main class="no-encontrada">
  <h1>Esta página no existe</h1>
  <p><a href="/">Volver al inicio</a></p>
</main>
</body>
</html>
"""


def generar(datos: dict) -> dict:
    return {"index.html": pagina(datos), "cv.html": cv(datos), "404.html": pagina_404(datos),
            "_headers": cabeceras_pages(), "robots.txt": robots(datos), "sitemap.xml": sitemap(datos),
            "perfil.md": perfil_ia(datos)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comprobar", action="store_true", help="falla si los archivos generados no estan al dia")
    ap.add_argument("--publicar", action="store_true", help="falla si queda algo por completar")
    args = ap.parse_args(argv)
    try:
        datos = cargar()
    except (ErrorContenido, tomllib.TOMLDecodeError) as exc:
        print(f"Error en el contenido: {exc}", file=sys.stderr)
        return 1
    archivos = generar(datos)

    if args.comprobar:
        viejos = [n for n, ruta in SALIDAS.items()
                  if not ruta.exists() or ruta.read_text(encoding="utf-8") != archivos[n]]
        if viejos:
            print("Sin regenerar: " + ", ".join(viejos) + ". Ejecuta: python portafolio/construir.py",
                  file=sys.stderr)
            return 1
        print("Portafolio al dia.")
        return 0

    for nombre, contenido in archivos.items():
        destino = SALIDAS[nombre]
        destino.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False,
                                         dir=destino.parent, suffix=".tmp") as tmp:
            tmp.write(contenido)
        Path(tmp.name).chmod(0o644)        # legible por Caddy y por quien despliegue
        Path(tmp.name).replace(destino)
    print("Generado: " + ", ".join(SALIDAS))

    if datos["sitio"]["url"] and not _qr_svg("x"):
        print("Aviso: sin el paquete segno el CV sale sin codigo QR (pip install segno).", file=sys.stderr)

    faltan = pendientes(datos)
    if faltan:
        print("\nPendiente antes de publicar:\n  - " + "\n  - ".join(faltan))
        if args.publicar:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
