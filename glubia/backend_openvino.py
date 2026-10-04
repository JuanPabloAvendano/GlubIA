"""Backend real: OpenVINO GenAI (LLMPipeline o VLMPipeline).

Correccion principal respecto a la version 1: el servidor armaba la plantilla
ChatML a mano y la pasaba como texto a generate(). Desde openvino_genai 2025.x
GenerationConfig.apply_chat_template vale True por defecto, asi que ese texto se
envolvia OTRA VEZ en la plantilla del tokenizer (el modelo veia "You are Qwen..."
como sistema real y todo el historial dentro de un solo mensaje de usuario).
Ahora se pasa un ChatHistory y la plantilla la aplica el tokenizer, una vez.

Tipos de modelo (GLUBIA_PIPELINE=auto los distingue solo):
  * llm: exportaciones de solo texto (openvino_model.xml) o un archivo .gguf.
  * vlm: modelos con vision exportados por optimum-intel
         (openvino_language_model.xml). Los modelos pequenos recientes
         (Gemma 4, Qwen3.5) se publican asi; GlubIA los usa solo con texto.

Plantillas con razonamiento ("thinking"): si la plantilla del modelo admite
enable_thinking, se desactiva por defecto (GLUBIA_PLANTILLA_EXTRA lo cambia).
Para un chat de portafolio interesa la respuesta directa, no el razonamiento.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .motor import Mensaje, Parametros, Resultado
from .telemetria import desactivar_telemetria_openvino

log = logging.getLogger("glubia.openvino")


def detectar_tipo(ruta: Path, pedido: str = "auto") -> str:
    """'llm' o 'vlm' segun los archivos del modelo (o lo que se pida)."""
    if pedido in ("llm", "vlm"):
        return pedido
    if ruta.is_file():
        return "llm"                        # .gguf y similares
    if (ruta / "openvino_language_model.xml").exists():
        return "vlm"
    return "llm"


class BackendOpenVINO:
    def __init__(self, cfg):
        desactivar_telemetria_openvino(cfg.telemetria_ov)
        import openvino_genai as ov_genai  # despues de apagar la telemetria, a proposito

        self._g = ov_genai
        self.nombre_modelo = cfg.nombre_modelo
        if not cfg.model_path.exists():
            raise RuntimeError(f"No encuentro el modelo en {cfg.model_path}")
        self.tipo = detectar_tipo(cfg.model_path, cfg.pipeline)

        propiedades: Dict[str, Any] = {}
        if cfg.cache_ov:
            # La GPU y la NPU compilan el modelo al cargarlo; con cache, los
            # arranques siguientes reutilizan lo compilado y cargan mucho antes.
            cache = cfg.data_dir / "ov_cache"
            try:
                cache.mkdir(parents=True, exist_ok=True)
                propiedades["CACHE_DIR"] = str(cache)
            except OSError as exc:
                log.warning("sin cache de modelo (%s)", exc)
        propiedades.update(cfg.ov_config)   # p. ej. KV_CACHE_PRECISION o MAX_PROMPT_LEN (NPU)

        clase = ov_genai.VLMPipeline if self.tipo == "vlm" else ov_genai.LLMPipeline
        self.pipe, self.dispositivo = self._cargar(clase, str(cfg.model_path), cfg.device, propiedades)
        self.tok = self.pipe.get_tokenizer()

        estado = getattr(ov_genai, "StreamingStatus", None)
        self._seguir = getattr(estado, "RUNNING", False)
        self._parar = getattr(estado, "STOP", True)
        self._chat_history = getattr(ov_genai, "ChatHistory", None)
        self.extra = self._extra_plantilla(cfg.plantilla_extra)
        self.overhead, self.tokens_generacion = self._medir_plantilla()
        log.info("modelo %s (%s) | plantilla extra %s | %d tokens por mensaje",
                 self.nombre_modelo, self.tipo, self.extra or "-", self.overhead)

    def _cargar(self, clase, ruta: str, pedido: str, propiedades: dict):
        candidatos = [pedido] if pedido == "CPU" else [pedido, "CPU"]
        ultimo = None
        for dev in candidatos:
            # Las propiedades propias de la NPU no las entiende la CPU.
            props = propiedades if dev == pedido else {
                k: v for k, v in propiedades.items() if k in ("CACHE_DIR", "KV_CACHE_PRECISION")}
            try:
                log.info("cargando modelo en %s...", dev)
                return clase(ruta, dev, **props), dev
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                log.warning("no se pudo usar %s: %s", dev, exc)
        raise RuntimeError(f"No se pudo cargar el modelo desde {ruta}: {ultimo}")

    # ------------------------------------------------------------ plantilla

    def _extra_plantilla(self, pedido: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if pedido is not None:
            return dict(pedido)
        plantilla = getattr(self.tok, "chat_template", "") or ""
        if "enable_thinking" in plantilla:
            return {"enable_thinking": False}
        return {}

    def _plantilla(self, mensajes: List[Mensaje], generacion: bool) -> str:
        try:
            return self.tok.apply_chat_template(mensajes, add_generation_prompt=generacion,
                                                extra_context=self.extra or None)
        except TypeError:   # openvino_genai antiguo sin extra_context
            return self.tok.apply_chat_template(mensajes, add_generation_prompt=generacion)

    def _medir_plantilla(self):
        """(tokens que anade la plantilla por mensaje, tokens del inicio de respuesta)."""
        try:
            # Siempre con mensaje de sistema: algunas plantillas (Qwen2.5) meten uno
            # propio cuando falta y falsearian la cuenta.
            dos = [{"role": "system", "content": "x"}, {"role": "user", "content": "x"}]
            cuatro = dos + [{"role": "assistant", "content": "x"}, {"role": "user", "content": "x"}]
            sin_gen = self.contar(self._plantilla(dos, False))
            por_mensaje = (self.contar(self._plantilla(cuatro, False)) - sin_gen - 2) // 2
            generacion = self.contar(self._plantilla(dos, True)) - sin_gen
            return max(1, por_mensaje), max(0, generacion)
        except Exception:  # noqa: BLE001
            return 6, 3

    # ------------------------------------------------------------ tokens

    def contar(self, texto: str) -> int:
        if not texto:
            return 0
        ids = self.tok.encode(texto, add_special_tokens=False).input_ids
        return int(ids.get_shape()[1])

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

    def _entrada(self, mensajes: List[Mensaje], cfg):
        if self._chat_history is not None:
            historia = self._chat_history(mensajes)
            if self.extra and hasattr(historia, "set_extra_context"):
                historia.set_extra_context(self.extra)
            return historia
        # openvino_genai antiguo sin ChatHistory: plantilla una sola vez, a mano.
        if hasattr(cfg, "apply_chat_template"):
            cfg.apply_chat_template = False
        return self._plantilla(mensajes, True)

    def generar(self, mensajes: List[Mensaje], p: Parametros, on_delta) -> Resultado:
        cfg = self._config(p)

        def streamer(subword: str):
            return self._seguir if on_delta(subword) else self._parar

        entrada = self._entrada(mensajes, cfg)
        if self.tipo == "vlm":
            res = self.pipe.generate(entrada, images=[], generation_config=cfg, streamer=streamer)
        else:
            res = self.pipe.generate(entrada, cfg, streamer)

        if isinstance(res, str):
            return Resultado(res.strip(), 0, self.contar(res), None)
        texto = res.texts[0] if getattr(res, "texts", None) else str(res)
        pm = getattr(res, "perf_metrics", None)
        if pm is not None:
            try:
                return Resultado(texto.strip(), int(pm.get_num_input_tokens()),
                                 int(pm.get_num_generated_tokens()), round(float(pm.get_ttft().mean), 1))
            except Exception:  # noqa: BLE001  (metricas incompletas en algunos pipelines)
                pass
        return Resultado(texto.strip(), 0, self.contar(texto), None)


def crear(cfg) -> BackendOpenVINO:
    return BackendOpenVINO(cfg)
