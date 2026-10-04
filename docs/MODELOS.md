# Qué modelo usar y cómo sacarle más al portátil

Equipo objetivo: Intel Core Ultra 5 115U (CPU + GPU integrada + NPU), 16 GB LPDDR5 **compartidos**
entre Omarchy, tus programas, la GPU y el modelo (RT-02: el modelo del portafolio debería quedarse
en ≤ 4 GB).

## Lo medido

Con el modelo actual, **Qwen2.5-Coder-7B INT4**, en CPU (entorno de pruebas Linux de 2 núcleos;
tu portátil con GPU irá más rápido, pero las proporciones se mantienen):

| Medida | Valor |
|---|---|
| Memoria tras cargar / pico | 4,6 GB / 5,8 GB |
| Velocidad de generación | 2,2–2,4 tokens/s |
| Prompt del asistente público (reglas + perfil) | ~1.350 tokens |
| Primer token con ese prompt, **en frío** | 45–52 s |
| Primer token, **siguientes preguntas** | ~1 s |
| Respuesta típica del portafolio (40–90 tokens) | 15–45 s |

Lo que más pesa no es generar sino **leer el prompt de la persona**. OpenVINO GenAI conserva la
caché entre llamadas y reutiliza el prefijo común (probado con y sin `enable_prefix_caching`: el
resultado es el mismo, ~1 s a partir de la segunda pregunta). Dos consecuencias:

1. **GlubIA ahora precalienta la persona** al cargar el modelo (`GLUBIA_PRECALENTAR=1`, por
   defecto con el asistente público activo). El primer visitante ya no paga los ~50 s.
   Mientras precalienta, la página ya muestra "despierta": quien pregunte en ese momento espera
   lo mismo que habría esperado sin precalentar. Si cambias el perfil, la siguiente pregunta vuelve a
   pagar la lectura completa una vez.
2. Si usas el **mismo modelo** para tu chat privado, cada conversación tuya invalida esa caché y la
   siguiente pregunta pública vuelve a pagar la lectura completa. Es otro argumento para separar
   modelos (abajo).

## Calidad del 7B como asistente del portafolio

Con la persona nueva (ver `PRUEBAS-AGENTES.md`):

- ✅ Ya no se hace pasar por ti, no convierte lo que falta en negativas ("no ha trabajado en
  ninguna empresa"), da los enlaces del perfil, rechaza opiniones e intentos de sacar sus
  instrucciones.
- ⚠️ Sigue adornando: "emprendedor colombiano", "conocido por…". No está en tu perfil.
- ⚠️ Escribe enlaces en formato markdown aunque se le pida que no (la página ya los convierte).
- ❌ Si le piden código **en inglés**, lo escribe, incluso con la regla explícita. Es un modelo de
  código: es lo que mejor sabe hacer. GlubIA ahora corta cualquier bloque de código en las respuestas
  públicas y explica que ahí no programa.

Conclusión: el 7B Coder sirve, pero **no es el modelo adecuado para el portafolio**. Es grande para
lo que hace, lento en frío, y su instinto va en contra de la persona.

## Recomendación

| Uso | Modelo | Por qué |
|---|---|---|
| **Portafolio** (siempre encendido) | **Gemma 4 E2B-it INT4** (`OpenVINO/gemma-4-E2B-it-int4-ov`) — candidato principal | modelo de conversación general, multilingüe, licencia Apache 2.0, ~2.300 M parámetros efectivos: cabe con holgura en RT-02 y deja la caché de la persona tranquila |
| Portafolio, si E2B se queda corto | Gemma 4 E4B-it INT4 o Qwen3.5-4B INT8 | más calidad, más memoria; medir antes |
| **Tu chat privado y código** | Qwen2.5-Coder-7B INT4 (el actual) | es el mejor de los probados para programar |
| Evitar | Qwen2.5-3B-Instruct | licencia de investigación de Qwen (no Apache) |

Gemma 4 y Qwen3.5 vienen en formato multimodal de OpenVINO (texto + imagen); GlubIA 2.1 lo detecta
solo (`GLUBIA_PIPELINE=auto`) y usa el pipeline correcto. Qwen3.5 razona con `<think>`: GlubIA lo
desactiva en la plantilla y, si aparece, lo filtra.

**No los pude medir aquí** (el entorno de pruebas no llega a Hugging Face). La decisión debe salir de
tu portátil:

```bash
scripts/descargar-modelo.sh gemma-4-e2b-it-int4-ov
python scripts/medir.py --modelo ./modelos/gemma-4-e2b-it-int4-ov --dispositivo GPU --json gemma-gpu.json
python scripts/medir.py --modelo ./modelos/qwen2.5-coder-7b-int4-ov --dispositivo GPU --json qwen7b-gpu.json
python3 scripts/evaluar.py --solo publica   # con GlubIA arrancado con cada modelo: las preguntas de scripts/eval_casos.json
```

Mide dos veces cada uno: la primera carga en GPU/NPU compila; la segunda usa la caché
(`datos/ov_cache`) y es la que vivirás cada día.

### ¿Uno o dos modelos?

- **Opción simple (recomendada para empezar):** un solo GlubIA en Omarchy con **Gemma 4 E2B**
  para todo. El portafolio queda rápido y ligero; para programar en serio usas el 7B en Windows.
- **Opción completa:** dos servicios en el `compose.yaml` de Omarchy, uno público con E2B y otro
  privado con el 7B. Cuesta ~2–3 GB más de RAM mientras los dos estén cargados; tiene sentido cuando
  RF-01 (modo limitado / modo completo) esté validado, para cargar el 7B solo con la pantalla apagada.

## El NPU (RF-02)

Lo que hay que saber antes de probarlo:

- OpenVINO GenAI ejecuta LLM en el NPU, pero con condiciones: el modelo debe estar cuantizado a
  **INT4 simétrico por canal**. Los modelos ya convertidos de Hugging Face no siempre lo están; la
  receta documentada por OpenVINO es exportarlo tú con
  `optimum-cli export openvino --weight-format int4 --sym --ratio 1.0 --group-size -1 ...`.
- El NPU compila el modelo para un **largo de prompt máximo** (`MAX_PROMPT_LEN`, 1.024 tokens por
  defecto). La persona ocupa ~1.350, así que hay que subirlo:
  `GLUBIA_OV_CONFIG='{"MAX_PROMPT_LEN": 2048, "MIN_RESPONSE_LEN": 256}'`.
- La primera compilación en el NPU es lenta; con `datos/ov_cache` las siguientes no.
- Si el NPU falla, GlubIA cae a CPU y lo registra.
- **Por verificar en tu equipo:** que los modelos multimodales (Gemma 4, Qwen3.5) funcionen en el
  NPU con la versión de OpenVINO del repositorio. Es la prueba nº 1 de RF-02.

Dónde encaja: el NPU gasta mucha menos energía que la GPU. Es el candidato natural para el **modo
limitado** de RF-01 (mientras usas el portátil), dejando la GPU libre para ti.

## Otras formas de ahorrar recursos

| Palanca | Efecto | Coste |
|---|---|---|
| Precalentar la persona (hecho) | el primer visitante no espera la lectura del perfil | ~50 s de CPU al arrancar |
| Perfil más corto | cada 100 tokens menos ≈ 3–4 s menos en frío (CPU) | menos información para la IA |
| `GLUBIA_PUBLICO_TOKENS` bajo (p. ej. 200) | respuestas más cortas y rápidas | respuestas más escuetas |
| `GLUBIA_CTX` bajo (p. ej. 4096) | menos memoria para la caché KV | historiales más cortos |
| `KV_CACHE_PRECISION=u8` en `GLUBIA_OV_CONFIG` | caché KV a la mitad | pérdida de calidad mínima, por medir |
| Modelo más pequeño | todo lo anterior a la vez | calidad: medir con `evaluar.py` |
