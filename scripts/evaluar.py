#!/usr/bin/env python3
"""
Evaluacion del modelo: la puerta de calidad antes de cambiar de modelo o de version.

Lanza un conjunto fijo de preguntas (scripts/eval_casos.json) contra un GlubIA en
marcha, comprueba cada respuesta con reglas sencillas y mide velocidad. Guarda el
resultado en evaluaciones/ y lo compara con la ultima ejecucion: si empeora la tasa
de aciertos o la velocidad cae mas de un 20 %, sale con codigo 1.

    GLUBIA_API_KEY=glb_... python3 scripts/evaluar.py
    python3 scripts/evaluar.py --privada http://127.0.0.1:8081

Solo usa la biblioteca estandar: corre con cualquier python3 >= 3.8.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _post(url: str, cuerpo: dict, clave: str = "", timeout: int = 300) -> dict:
    datos = json.dumps(cuerpo).encode()
    req = urllib.request.Request(url, data=datos, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {clave}"} if clave else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _get(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def comprobar(texto: str, reglas: dict) -> list:
    fallos = []
    bajo = texto.lower()
    for palabra in reglas.get("contiene", []):
        if palabra.lower() not in bajo:
            fallos.append(f"no contiene '{palabra}'")
    alguna = reglas.get("contiene_alguna", [])
    if alguna and not any(p.lower() in bajo for p in alguna):
        fallos.append(f"no contiene ninguna de {alguna}")
    for palabra in reglas.get("no_contiene", []):
        if palabra.lower() in bajo:
            fallos.append(f"contiene '{palabra}'")
    if "max_chars" in reglas and len(texto) > reglas["max_chars"]:
        fallos.append(f"{len(texto)} caracteres > {reglas['max_chars']}")
    if "regex_prohibida" in reglas and re.search(reglas["regex_prohibida"], texto):
        fallos.append(f"coincide con {reglas['regex_prohibida']}")
    return fallos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--privada", default=os.environ.get("URL_PRIVADA", "http://127.0.0.1:8081"))
    ap.add_argument("--clave", default=os.environ.get("GLUBIA_API_KEY", ""))
    ap.add_argument("--casos", default=str(RAIZ / "scripts" / "eval_casos.json"))
    ap.add_argument("--salida", default=str(RAIZ / "evaluaciones"))
    args = ap.parse_args()

    casos = json.loads(Path(args.casos).read_text(encoding="utf-8"))
    try:
        estado = _get(args.privada + "/readyz")
    except (urllib.error.URLError, OSError):
        estado = {"model": "?", "device": "?"}

    if not args.clave:
        print("Falta GLUBIA_API_KEY (o --clave).")
        return 1

    resultados = []
    for caso in casos:
        tipo = caso["tipo"]
        t0 = time.monotonic()
        try:
            r = _post(args.privada + "/v1/chat/completions",
                      {"messages": [{"role": "user", "content": caso["pregunta"]}],
                       "max_tokens": caso.get("max_tokens", 512), "temperature": 0}, args.clave)
            texto = r["choices"][0]["message"]["content"]
            tokens = r["usage"]["completion_tokens"]
            error = None
        except Exception as exc:  # noqa: BLE001
            texto, tokens, error = "", None, str(exc)
        seg = time.monotonic() - t0
        fallos = [error] if error else comprobar(texto, caso["reglas"])
        resultados.append({"id": caso["id"], "tipo": tipo, "ok": not fallos, "fallos": fallos,
                           "segundos": round(seg, 2), "tokens": tokens,
                           "tps": round(tokens / seg, 1) if tokens else None, "respuesta": texto[:600]})
        marca = "ok   " if not fallos else "FALLO"
        print(f"  {marca} {caso['id']:<28} {seg:6.1f}s  {'; '.join(fallos)}")

    if not resultados:
        print("No se ejecuto ningun caso.")
        return 1
    aciertos = sum(r["ok"] for r in resultados) / len(resultados)
    vel = [r["tps"] for r in resultados if r["tps"]]
    tps = round(sum(vel) / len(vel), 1) if vel else None
    informe = {"fecha": time.strftime("%Y-%m-%d %H:%M"), "modelo": estado.get("model"),
               "dispositivo": estado.get("device"), "version": estado.get("version"),
               "aciertos": round(aciertos, 3), "tps_medio": tps, "casos": resultados}

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    previos = sorted(salida.glob("*.json"))
    nombre = salida / f"{time.strftime('%Y%m%d-%H%M%S')}-{estado.get('model', 'modelo')}.json"
    nombre.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAciertos {aciertos:.0%}  |  {tps or '-'} tok/s  |  informe: {nombre}")

    if previos:
        anterior = json.loads(previos[-1].read_text(encoding="utf-8"))
        print(f"Anterior ({anterior['fecha']}, {anterior['modelo']}): aciertos {anterior['aciertos']:.0%}, "
              f"{anterior.get('tps_medio') or '-'} tok/s")
        if aciertos < anterior["aciertos"]:
            print("REGRESION: bajan los aciertos.")
            return 1
        if tps and anterior.get("tps_medio") and tps < 0.8 * anterior["tps_medio"]:
            print("REGRESION: la velocidad cae mas de un 20 %.")
            return 1
    return 0 if aciertos == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
