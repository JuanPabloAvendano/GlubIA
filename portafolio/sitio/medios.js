/* Videos de YouTube sin cargar YouTube hasta que el visitante pulsa (privacidad y velocidad).
   Sin JavaScript, el enlace abre el video en YouTube. */
"use strict";
document.querySelectorAll("a.video[data-youtube]").forEach((enlace) => {
  enlace.addEventListener("click", (ev) => {
    const id = enlace.dataset.youtube;
    if (!/^[A-Za-z0-9_-]{11}$/.test(id)) return;
    ev.preventDefault();
    const marco = document.createElement("iframe");
    marco.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1";
    marco.title = enlace.closest(".medio")?.querySelector("h3")?.textContent || "Video";
    marco.allow = "autoplay; encrypted-media; picture-in-picture";
    marco.allowFullscreen = true;
    marco.referrerPolicy = "strict-origin-when-cross-origin";
    enlace.replaceChildren(marco);
    enlace.removeAttribute("href");
  });
});
