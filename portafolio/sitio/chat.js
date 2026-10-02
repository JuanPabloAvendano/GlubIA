/* ==========================================================================
   Conversacion con la IA del portafolio.

   Habla con dos rutas del mismo dominio (Caddy las reenvia a GlubIA):
     GET  /api/info       estado (online, busy, loading) y preguntas sugeridas
     POST /api/preguntar  pregunta -> respuesta en streaming (SSE)

   Si el sitio vive en otro dominio, define <meta name="glubia-api" content="...">.
   Sin dependencias. Nada se guarda en el navegador.
   ========================================================================== */
"use strict";

(() => {
  const meta = document.querySelector('meta[name="glubia-api"]');
  const BASE = meta ? meta.content.trim().replace(/\/+$/, "") : "";
  const URL_INFO = BASE + "/api/info";
  const URL_PREGUNTAR = BASE + "/api/preguntar";
  const HISTORIAL_MAX = 6;
  const SUGERENCIAS_DEFECTO = ["¿Quién es Juan?", "¿En qué proyectos trabaja?", "¿Cómo lo contacto?"];

  const $ = (s) => document.querySelector(s);
  const transcripcion = $("#transcripcion");
  const formulario = $("#formulario");
  const entrada = $("#pregunta");
  const boton = $("#enviar");
  const contador = $("#contador");
  const sugerencias = $("#sugerencias");
  const estado = $("#estado");
  const estadoTexto = $("#estado-texto");
  const reducido = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const TEXTOS = {
    comprobando: "Comprobando si está despierta…",
    online: "Despierta. Suele responder en unos segundos.",
    busy: "Ocupada con otras preguntas. La tuya esperará su turno.",
    loading: "Despertando: el modelo se está cargando. Prueba en un minuto.",
    offline: "Dormida: mi computador está apagado ahora mismo. Puedes escribirme abajo.",
    off: "La IA no está disponible en este momento. Puedes escribirme abajo.",
  };

  let historial = [];       // [{role, content}] de esta visita; no se guarda
  let control = null;       // AbortController de la respuesta en curso
  let maxChars = 600;
  let estadoActual = "comprobando";

  class Aviso extends Error {}

  // ------------------------------------------------------------------ estado

  function ponerEstado(nuevo) {
    estadoActual = TEXTOS[nuevo] ? nuevo : "offline";
    estado.dataset.estado = estadoActual;
    estadoTexto.textContent = TEXTOS[estadoActual];
    actualizarBoton();
  }

  function puedePreguntar() {
    return estadoActual === "online" || estadoActual === "busy";
  }

  function actualizarBoton() {
    if (control) {
      boton.disabled = false;
      boton.type = "button";
      boton.dataset.modo = "detener";
      boton.textContent = "Detener";
    } else {
      boton.type = "submit";
      delete boton.dataset.modo;
      boton.textContent = "Preguntar";
      boton.disabled = !puedePreguntar() || !entrada.value.trim();
    }
  }

  async function revisar() {
    try {
      const r = await fetch(URL_INFO, { cache: "no-store" });
      if (r.status === 404) { ponerEstado("off"); return; }
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      if (j.limits && j.limits.max_chars) {
        maxChars = j.limits.max_chars;
        entrada.maxLength = maxChars;
        actualizarContador();
      }
      ponerEstado(j.status);
      if (!sugerencias.childElementCount) {
        pintarSugerencias(j.suggestions && j.suggestions.length ? j.suggestions : SUGERENCIAS_DEFECTO);
      }
    } catch (e) {
      ponerEstado("offline");
    }
  }

  function pintarSugerencias(lista) {
    sugerencias.textContent = "";
    lista.slice(0, 4).forEach((texto) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = texto;
      b.addEventListener("click", () => {
        if (!puedePreguntar() || control) return;
        preguntar(texto);
      });
      sugerencias.append(b);
    });
  }

  // ------------------------------------------------------------------ texto

  // Convierte la respuesta en nodos sin interpretar HTML del modelo:
  // **negrita**, saltos de linea, enlaces http(s) y correos.
  const PATRON = /(\*\*[^*\n]+\*\*|https?:\/\/[^\s<>()]+[^\s<>().,;:!?]|[\w.+-]+@[\w-]+\.[\w.-]*\w)/g;

  function enLinea(destino, texto) {
    let ultimo = 0;
    for (const m of texto.matchAll(PATRON)) {
      agregarTexto(destino, texto.slice(ultimo, m.index));
      const t = m[0];
      if (t.startsWith("**")) {
        const b = document.createElement("strong");
        b.textContent = t.slice(2, -2);
        destino.append(b);
      } else {
        const a = document.createElement("a");
        a.href = t.includes("@") && !t.startsWith("http") ? "mailto:" + t : t;
        a.textContent = t;
        a.rel = "noopener nofollow";
        if (a.href.startsWith("http")) a.target = "_blank";
        destino.append(a);
      }
      ultimo = m.index + t.length;
    }
    agregarTexto(destino, texto.slice(ultimo));
  }

  function agregarTexto(destino, texto) {
    texto.split("\n").forEach((linea, i) => {
      if (i) destino.append(document.createElement("br"));
      if (linea) destino.append(linea);
    });
  }

  function pintar(nodo, texto, enCurso) {
    nodo.textContent = "";
    const parrafos = texto.trim() ? texto.trim().split(/\n{2,}/) : [""];
    parrafos.forEach((par) => {
      const p = document.createElement("p");
      enLinea(p, par);
      nodo.append(p);
    });
    if (enCurso) {
      const c = document.createElement("span");
      c.className = "cursor";
      c.setAttribute("aria-hidden", "true");
      nodo.lastChild.append(c);
    }
  }

  function aviso(nodo, mensaje) {
    nodo.className = "aviso";
    nodo.textContent = mensaje;
  }

  // ------------------------------------------------------------------ preguntar

  async function preguntar(texto) {
    texto = texto.trim();
    if (!texto || control) return;

    const q = document.createElement("p");
    q.className = "q";
    const marca = document.createElement("mark");
    marca.textContent = texto;
    q.append(marca);
    const a = document.createElement("div");
    a.className = "a";
    pintar(a, "", true);
    transcripcion.append(q, a);
    transcripcion.setAttribute("aria-busy", "true");
    a.scrollIntoView({ block: "nearest", behavior: reducido ? "auto" : "smooth" });

    entrada.value = "";
    sugerencias.hidden = true;        // tras la primera pregunta, la conversacion manda
    actualizarContador();
    control = new AbortController();
    actualizarBoton();

    let acc = "";
    try {
      const r = await fetch(URL_PREGUNTAR, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: texto, history: historial.slice(-HISTORIAL_MAX) }),
        signal: control.signal,
      });
      if (!r.ok) {
        let msg = "No pude responder ahora mismo. Intenta de nuevo en un momento.";
        try { const j = await r.json(); msg = j.error || j.detail || msg; } catch (e) { /* cuerpo vacio */ }
        throw new Aviso(msg);
      }
      const lector = r.body.getReader();
      const dec = new TextDecoder();
      let resto = "";
      leer: for (;;) {
        const { value, done } = await lector.read();
        if (done) break;
        resto += dec.decode(value, { stream: true });
        const partes = resto.split("\n\n");
        resto = partes.pop();
        for (const parte of partes) {
          const linea = parte.trim();
          if (!linea.startsWith("data:")) continue;          // pings y comentarios
          let d;
          try { d = JSON.parse(linea.slice(5)); } catch (e) { continue; }
          if (d.queue > 0 && !acc) {
            a.innerHTML = "";
            const c = document.createElement("p");
            c.className = "cola";
            c.textContent = d.queue === 1 ? "Hay 1 pregunta antes que la tuya…" : `Hay ${d.queue} preguntas antes que la tuya…`;
            a.append(c);
          }
          if (d.delta) { acc += d.delta; pintar(a, acc, true); }
          else if (d.error) { throw new Aviso(d.error); }
          else if (d.done) { break leer; }
        }
      }
      if (acc.trim()) {
        pintar(a, acc, false);
        historial.push({ role: "user", content: texto }, { role: "assistant", content: acc.trim() });
      } else {
        aviso(a, "No obtuve respuesta. Prueba a preguntarlo de otra forma.");
      }
    } catch (e) {
      if (e.name === "AbortError") {
        if (acc.trim()) {
          pintar(a, acc, false);
          historial.push({ role: "user", content: texto }, { role: "assistant", content: acc.trim() });
        } else {
          aviso(a, "Pregunta cancelada.");
        }
      } else if (e instanceof Aviso) {
        aviso(a, e.message);
      } else {
        aviso(a, "No pude conectar con la IA. Puede que mi computador se haya apagado.");
        revisar();
      }
    } finally {
      control = null;
      transcripcion.removeAttribute("aria-busy");
      actualizarBoton();
      entrada.focus({ preventScroll: true });
    }
  }

  // ------------------------------------------------------------------ eventos

  function actualizarContador() {
    contador.textContent = `${entrada.value.length} / ${maxChars}`;
    actualizarBoton();
  }

  formulario.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (puedePreguntar()) preguntar(entrada.value);
  });
  boton.addEventListener("click", (ev) => {
    if (control) { ev.preventDefault(); control.abort(); }
  });
  entrada.addEventListener("input", actualizarContador);
  entrada.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      formulario.requestSubmit();
    }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !control) revisar(); });

  actualizarContador();
  revisar();
  setInterval(() => { if (!document.hidden && !control) revisar(); }, 30000);
})();
