"""Backend real: openvino_genai.LLMPipeline.

Correccion principal respecto a la version 1: el servidor armaba la plantilla
ChatML a mano y la pasaba como texto a generate(). Desde openvino_genai 2025.x
GenerationConfig.apply_chat_template vale True por defecto, asi que ese texto se
envolvia OTRA VEZ en la plantilla del tokenizer. Verificado con 2026.3 y el
tokenizer de modelo_qwen_7b_ov, el modelo recibia:

    <|im_start|>system
    You are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>
    <|im_start|>user
    <|im_start|>system
    Eres un Arquitecto de Software...<|im_end|>
    <|im_start|>user
    Hola<|im_end|>
    <|im_start|>assistant
    <|im_end|>
    <|im_start|>assistant

Es decir: el prompt de sistema real era el de Qwen, todo tu historial llegaba
metido dentro de UN mensaje de usuario y ademas habia un turno vacio del
asistente (53 tokens de entrada en vez de 24 para un simple "Hola").

Ahora se pasa un ChatHistory y la plantilla la aplica el propio tokenizer del
modelo, una sola vez. Bonus: si cambias de modelo, su plantilla viene con el.
"""

from __future__ import annotations

import logging
from typing import List

from .motor import Mensaje, Parametros, Resultado
from .telemetria import desactivar_telemetria_openvino

log = logging.getLogger("glubia.openvino")


class BackendOpenVINO:
    def __init__(self, cfg):
        desactivar_telemetria_openvino(cfg.telemetria_ov)
        import openvino_genai as ov_genai  # despues de apagar la telemetria, a proposito

        self._g = ov_genai
        self.nombre_modelo = cfg.nombre_modelo
        if not cfg.model_path.exists():
            raise RuntimeError(f"No encuentro el modelo en {cfg.model_path}")

        propiedades = {}
        if cfg.cache_ov:
            # La GPU compila sus kernels al cargar; con cache, los arranques
            # siguientes reutilizan lo compilado y cargan mucho mas rapido.
            cache = cfg.data_dir / "ov_cache"
            try:
                cache.mkdir(parents=True, exist_ok=True)
                propiedades["CACHE_DIR"] = str(cache)
            except OSError as exc:
                log.warning("sin cache de modelo (%s)", exc)

        self.pipe, self.dispositivo = self._cargar(str(cfg.model_path), cfg.device, propiedades)
        self.tok = self.pipe.get_tokenizer()

        estado = getattr(ov_genai, "StreamingStatus", None)
        self._seguir = getattr(estado, "RUNNING", False)
        self._parar = getattr(estado, "STOP", True)
        self._chat_history = getattr(ov_genai, "ChatHistory", None)
        self.overhead = self._medir_overhead()

    def _cargar(self, ruta: str, pedido: str, propiedades: dict):
        candidatos = [pedido] if pedido == "CPU" else [pedido, "CPU"]
        ultimo = None
        for dev in candidatos:
            try:
                log.info("cargando modelo en %s...", dev)
                return self._g.LLMPipeline(ruta, dev, **propiedades), dev
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                log.warning("no se pudo usar %s: %s", dev, exc)
        raise RuntimeError(f"No se pudo cargar el modelo desde {ruta}: {ultimo}")

    def cerrar(self) -> None:
        """Suelta el pipeline (y su memoria de GPU) antes de cargar otro modelo."""
        self.tok = None
        self.pipe = None

    # ------------------------------------------------------------ tokens

    def contar(self, texto: str) -> int:
        if not texto:
            return 0
        ids = self.tok.encode(texto, add_special_tokens=False).input_ids
        return int(ids.get_shape()[1])

    def _medir_overhead(self) -> int:
        """Tokens que la plantilla anade por mensaje (en Qwen/ChatML son 5)."""
        try:
            plantilla = self.tok.apply_chat_template(
                [{"role": "system", "content": "x"}, {"role": "user", "content": "x"}],
                add_generation_prompt=False)
            return max(1, (self.contar(plantilla) - 2 * self.contar("x")) // 2)
        except Exception:  # noqa: BLE001
            return 6

    # ------------------------------------------------------------ generacion

    def _config(self, p: Parametros):
        cfg = self.pipe.get_generation_config()   # trae eos/stop tokens del modelo
        cfg.max_new_tokens = int(p.max_new_tokens)
        # Sin do_sample la temperatura se ignora y la salida es siempre greedy.
        cfg.do_sample = p.temperature > 0
        if cfg.do_sample:
            cfg.temperature = max(float(p.temperature), 0.01)
            cfg.top_p = float(p.top_p)
            if p.top_k:
                cfg.top_k = int(p.top_k)
        cfg.repetition_penalty = float(p.repetition_penalty)
        if p.stop:
            cfg.stop_strings = set(p.stop)
        return cfg

    def generar(self, mensajes: List[Mensaje], p: Parametros, on_delta) -> Resultado:
        cfg = self._config(p)

        def streamer(subword: str):
            return self._seguir if on_delta(subword) else self._parar

        if self._chat_history is not None:
            entrada = self._chat_history(mensajes)
        else:
            # openvino_genai antiguo sin ChatHistory: plantilla una sola vez, a mano.
            entrada = self.tok.apply_chat_template(mensajes, add_generation_prompt=True)
            if hasattr(cfg, "apply_chat_template"):
                cfg.apply_chat_template = False

        res = self.pipe.generate(entrada, cfg, streamer)

        if isinstance(res, str):
            texto = res
            return Resultado(texto.strip(), 0, self.contar(texto), None)
        texto = res.texts[0] if getattr(res, "texts", None) else str(res)
        pm = getattr(res, "perf_metrics", None)
        if pm is not None:
            ttft = pm.get_ttft().mean
            return Resultado(texto.strip(), int(pm.get_num_input_tokens()),
                             int(pm.get_num_generated_tokens()), round(float(ttft), 1))
        return Resultado(texto.strip(), 0, self.contar(texto), None)


def crear(cfg) -> BackendOpenVINO:
    return BackendOpenVINO(cfg)
