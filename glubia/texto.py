"""Utilidades de texto para la salida del modelo.

Algunos modelos (Qwen3, Qwen3.5, DeepSeek-R1...) empiezan la respuesta con un
bloque <think>...</think> de razonamiento. Aunque GlubIA lo desactiva en la
plantilla cuando puede, este filtro garantiza que nunca llegue al usuario ni al
historial: solo se elimina si aparece al PRINCIPIO de la respuesta.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BeforeValidator

ABRE = "<think>"
CIERRA = "</think>"
_BLOQUE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


def quitar_pensamiento(texto: str) -> str:
    """Quita un bloque de razonamiento inicial. Si nunca se cerro, no queda respuesta."""
    if not texto.lstrip().startswith(ABRE):
        return texto
    if CIERRA not in texto:
        return ""
    return _BLOQUE.sub("", texto, count=1)


class FiltroPensamiento:
    """La misma regla que quitar_pensamiento, pero trozo a trozo (streaming).

    Las etiquetas pueden llegar partidas entre trozos ("<th" + "ink>"), asi que
    se retiene lo minimo necesario para decidir.
    """

    def __init__(self) -> None:
        self._estado = "inicio"   # inicio | dentro | despues | fuera
        self._buf = ""

    def agregar(self, trozo: str) -> str:
        if self._estado == "fuera":
            return trozo
        self._buf += trozo
        return self._procesar()

    def _procesar(self) -> str:
        if self._estado == "inicio":
            limpio = self._buf.lstrip()
            if limpio.startswith(ABRE):
                self._estado = "dentro"
                self._buf = limpio[len(ABRE):]
            elif ABRE.startswith(limpio):
                return ""                      # aun puede ser "<think>": esperar
            else:
                self._estado = "fuera"
                salida, self._buf = self._buf, ""
                return salida
        if self._estado == "dentro":
            pos = self._buf.find(CIERRA)
            if pos < 0:
                self._buf = self._buf[-(len(CIERRA) - 1):]   # por si la etiqueta llega partida
                return ""
            self._estado = "despues"
            self._buf = self._buf[pos + len(CIERRA):]
        if self._estado == "despues":
            limpio = self._buf.lstrip()
            if not limpio:
                self._buf = ""
                return ""
            self._estado = "fuera"
            self._buf = ""
            return limpio
        return ""

    def fin(self) -> str:
        """Lo retenido al terminar. Un razonamiento sin cerrar se descarta."""
        salida = self._buf if self._estado == "inicio" else ""
        self._buf = ""
        return salida


def sin_sustitutos(texto: str) -> str:
    """Reemplaza sustitutos UTF-16 sueltos (p. ej. "\\ud83d" sin pareja en un JSON) por U+FFFD.

    JSON los admite, pero no son UTF-8 valido: al devolver la respuesta reventaban
    con un error 500 o cortaban el stream a mitad.
    """
    try:
        texto.encode("utf-8")
        return texto
    except UnicodeEncodeError:
        return texto.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


# Tipo para los campos de texto de las peticiones. Tiene que ser un validador ANTERIOR:
# pydantic rechaza los sustitutos sueltos al validar `str` (422) antes de que corra uno posterior,
# y lo que queremos es aceptar el texto con el caracter roto reemplazado.
Texto = Annotated[str, BeforeValidator(lambda v: sin_sustitutos(v) if isinstance(v, str) else v)]


def aviso_codigo(nombre: str) -> str:
    corto = nombre.split()[0] if nombre and not nombre.startswith("la persona") else "su dueño"
    return (f"Aquí no escribo código: soy el asistente de {corto} y solo hablo de su trabajo. "
            "Si quieres, te cuento en qué proyectos trabaja.")


class GuardiaCodigo:
    """Corta la respuesta del asistente publico si empieza un bloque de codigo (```).

    La persona del portafolio no debe programar para los visitantes, pero un modelo de codigo
    (Qwen2.5-Coder) a veces lo hace igual cuando se lo piden en ingles. Las instrucciones no
    bastan con modelos pequenos; esto es la red de seguridad. Trozo a trozo, porque la marca
    puede llegar partida ("``" + "`python").

    Solo detecta bloques con ```: codigo con ~~~, sangrado o suelto pasa. Es una red de
    seguridad para el caso tipico, no un filtro completo.
    """

    MARCA = "```"

    def __init__(self) -> None:
        self._pendiente = ""
        self.disparada = False

    def agregar(self, trozo: str) -> str:
        if self.disparada:
            return ""
        texto = self._pendiente + trozo
        pos = texto.find(self.MARCA)
        if pos >= 0:
            self.disparada = True
            self._pendiente = ""
            return texto[:pos].rstrip(" :\n")
        retener = next((n for n in (2, 1) if texto.endswith(self.MARCA[:n])), 0)
        self._pendiente = texto[len(texto) - retener:] if retener else ""
        return texto[:len(texto) - retener]

    def fin(self) -> str:
        salida, self._pendiente = ("" if self.disparada else self._pendiente), ""
        return salida
