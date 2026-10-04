#!/usr/bin/env python3
"""
Mide un modelo en ESTE equipo, con el mismo codigo que usa GlubIA: tiempo de carga,
memoria, primer token y velocidad. Sirve para decidir modelo y dispositivo con datos.

    python scripts/medir.py --modelo ./modelos/qwen2.5-coder-7b-int4-ov --dispositivo GPU
    python scripts/medir.py --modelo ./modelos/X --dispositivo NPU --ov-config '{"MAX_PROMPT_LEN": 2048, "MIN_RESPONSE_LEN": 512}'
    python scripts/medir.py --modelo ./modelos/X --dispositivo NPU --ov-config "MAX_PROMPT_LEN=2048,MIN_RESPONSE_LEN=512"
                            (esta forma, sin comillas internas, es la comoda en PowerShell)
    python scripts/medir.py --modelo ./modelos/X --dispositivo CPU --json medicion-cpu.json

Consejo: ciérralo todo menos lo que usas a diario y mide dos veces (la primera carga
en GPU/NPU compila; la segunda usa la cache y es la que vas a vivir cada dia).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PREGUNTAS = [
    ("persona", "Eres el asistente del portafolio de Juan. PERFIL: Juan vive en Colombia, creo la tienda "
                "American Urban y construye GlubIA, una IA local.",
     "¿Quién es Juan y en qué trabaja? Responde en 3 frases."),
    ("codigo", "Eres un arquitecto de software. Responde con codigo.",
     "Escribe en Python una funcion que valide un correo electronico con una expresion regular."),
    ("largo", "Resume con precision.", "Resume en dos frases este texto: " + ("GlubIA es una IA local que "
     "corre en un portatil con OpenVINO, sirve un portafolio y una API compatible con OpenAI. " * 40)),
]


def memoria_mb() -> dict:
    datos = {}
    try:
        import psutil  # opcional
        p = psutil.Process()
        datos["rss_mb"] = round(p.memory_info().rss / 1048576)
    except ImportError:
        try:
            for linea in Path("/proc/self/status").read_text().splitlines():
                if linea.startswith(("VmRSS", "VmHWM")):
                    clave = "rss_mb" if linea.startswith("VmRSS") else "pico_mb"
                    datos[clave] = round(int(linea.split()[1]) / 1024)
        except OSError:
            pass
    return datos


def leer_ov_config(texto: str) -> dict:
    """JSON ('{"A": 1}') o pares CLAVE=VALOR separados por comas (A=1,B=f16)."""
    texto = texto.strip()
    if not texto or texto.startswith("{"):
        return json.loads(texto or "{}")
    salida = {}
    for par in texto.split(","):
        clave, _, valor = par.partition("=")
        valor = valor.strip()
        salida[clave.strip()] = int(valor) if valor.lstrip("-").isdigit() else valor
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--dispositivo", default="GPU")
    ap.add_argument("--ov-config", default="{}",
                    help="propiedades extra de OpenVINO: JSON o CLAVE=VALOR,CLAVE=VALOR")
    ap.add_argument("--pipeline", default="auto", choices=["auto", "llm", "vlm"])
    ap.add_argument("--tokens", type=int, default=200)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--cache", default=str(RAIZ / "datos"), help="carpeta de datos (cache de OpenVINO)")
    ap.add_argument("--json", help="guardar el resultado en este archivo")
    args = ap.parse_args()

    from glubia.backend_openvino import BackendOpenVINO
    from glubia.motor import Parametros

    cfg = SimpleNamespace(
        telemetria_ov=False, model_path=Path(args.modelo), pipeline=args.pipeline, cache_ov=True,
        data_dir=Path(args.cache), ov_config=leer_ov_config(args.ov_config), device=args.dispositivo.upper(),
        nombre_modelo=Path(args.modelo).name, plantilla_extra=None)

    antes = memoria_mb()
    t0 = time.perf_counter()
    backend = BackendOpenVINO(cfg)
    carga = time.perf_counter() - t0
    tras_carga = memoria_mb()
    print(f"Modelo {cfg.nombre_modelo} ({backend.tipo}) en {backend.dispositivo}: carga {carga:.1f} s, "
          f"memoria {tras_carga.get('rss_mb', '?')} MB")

    resultados = []
    for nombre, sistema, pregunta in PREGUNTAS:
        for rep in range(args.repeticiones):
            mensajes = [{"role": "system", "content": sistema}, {"role": "user", "content": pregunta}]
            p = Parametros(max_new_tokens=args.tokens, temperature=0.0, repetition_penalty=1.05)
            t0 = time.perf_counter()
            res = backend.generar(mensajes, p, lambda _t: True)
            total = time.perf_counter() - t0
            ttft = (res.ttft_ms or 0) / 1000
            decod = max(total - ttft, 1e-6)
            fila = {"prueba": nombre, "repeticion": rep + 1, "tokens_entrada": res.tokens_entrada,
                    "tokens_salida": res.tokens_salida, "primer_token_s": round(ttft, 2),
                    "tok_s": round(max(res.tokens_salida - 1, 1) / decod, 1), "total_s": round(total, 1)}
            resultados.append(fila)
            print(f"  {nombre:<8} #{rep + 1}  entrada {fila['tokens_entrada']:>5}  salida {fila['tokens_salida']:>4}"
                  f"  primer token {fila['primer_token_s']:>5.2f} s  {fila['tok_s']:>5.1f} tok/s")

    informe = {
        "fecha": time.strftime("%Y-%m-%d %H:%M"), "equipo": platform.processor() or platform.machine(),
        "sistema": f"{platform.system()} {platform.release()}", "modelo": cfg.nombre_modelo,
        "tipo": backend.tipo, "dispositivo_pedido": cfg.device, "dispositivo": backend.dispositivo,
        "ov_config": cfg.ov_config, "carga_s": round(carga, 1), "memoria_antes": antes,
        "memoria_tras_carga": tras_carga, "memoria_final": memoria_mb(), "pruebas": resultados,
    }
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"### {cfg.nombre_modelo} en {backend.dispositivo}\n\ncarga {carga:.1f} s · memoria "
                    f"{tras_carga.get('rss_mb', '?')} MB\n\n| prueba | primer token (s) | tok/s |\n|---|---|---|\n")
            for r in resultados:
                f.write(f"| {r['prueba']} #{r['repeticion']} | {r['primer_token_s']} | {r['tok_s']} |\n")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Guardado en", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
