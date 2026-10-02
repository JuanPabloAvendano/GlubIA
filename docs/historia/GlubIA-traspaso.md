# GlubIA — Documento de traspaso

Resumen del estado de la iniciativa para retomarla en un proyecto nuevo.

---

## 1. Qué es

Dos componentes independientes que conviven en la misma red doméstica:

| Componente | Archivo | Puerto | Dónde corre |
|---|---|---|---|
| Servidor de IA local | `api_win_openvino.py` | 11434 | Portátil Windows (`C:\Users\juanp\GlubIA`) |
| Cliente web universal | `GlubAI-client/` (React + Vite) | 5173 | Debian, accesible desde cualquier dispositivo |
| Nodo de transferencia | `nodo_red.py` | 8500 | Debian + Windows (simétrico) |

El modelo es **Qwen2.5-Coder-7B** convertido a OpenVINO (`modelo_qwen_7b_ov`), ejecutándose sobre la GPU integrada del portátil Windows con `openvino_genai.LLMPipeline`.

---

## 2. Servidor de IA (`api_win_openvino.py`)

### Estado
La versión funcional ya está aplicada en el portátil. **El archivo adjunto en este proyecto es la versión antigua con el bug de serialización** — no lo uses como referencia.

### Correcciones que fueron necesarias (importantes de recordar)

1. **`pipe.generate()` devuelve `DecodedResults`, no un string.** FastAPI no lo serializa y responde 500 en cada mensaje. Solución: `str(resultado).strip()`.
2. **`def`, no `async def`.** Con `async def` la generación bloquea el bucle de eventos de uvicorn: los health checks se encolan y el cliente parpadea a "sin enlace" justo mientras el modelo trabaja. Con `def`, FastAPI lo manda a un hilo aparte.
3. **`config.do_sample = True`.** Sin esto la temperatura se ignora y la salida es siempre greedy.
4. **`pipe_lock = threading.Lock()`.** El pipeline no es reentrante: una sola generación a la vez.
5. **`allow_credentials=False`** en CORS. Combinarlo con `allow_origins=["*"]` es conflictivo y no se usan cookies.

### Endpoints

- `GET /`, `/health`, `/api/chat/health` → estado, modelo, dispositivo, flag `streaming`
- `POST /api/chat` y `/api/chat/` → respuesta completa
- `POST /api/chat/stream` → SSE token a token (`data: {"delta": "..."}`, cierre con `{"done": true}`)
- `GET /api/chat` → fallback informativo

El `PromptRequest` acepta `prompt`, `history` (lista de `{role, content}`), `max_new_tokens` (1024) y `temperature` (0.2). La plantilla ChatML se arma **en el servidor**, no en el cliente.

Detalle de compatibilidad: el callback del streamer debe devolver `ov_genai.StreamingStatus.RUNNING` en versiones nuevas y `False` en las antiguas. Se resuelve con `getattr` defensivo.

### Arranque en Windows

La activación del venv falla por política de scripts de PowerShell. El comando recomendado evita el problema:

```powershell
cd C:\Users\juanp\GlubIA
.\openvino_env\Scripts\python.exe api_win_openvino.py
```

Regla de firewall, una sola vez como administrador:

```bat
netsh advfirewall firewall add rule name="GlubAI 11434" dir=in action=allow protocol=TCP localport=11434
```

---

## 3. Cliente web (`GlubAI-client`)

React + Vite, servido desde Debian con `npm run dev -- --host`.

**Decisiones de diseño que conviene no perder:**

- El endpoint del servidor es **configurable en caliente** desde la barra superior y se guarda en `localStorage`. Así la misma build funciona desde el portátil, desde Debian y desde el móvil sin recompilar. Orden de resolución: valor guardado → `VITE_API_URL` → host que sirve la página con puerto 11434.
- **Sin dependencias nuevas**: el resaltado de sintaxis y el parseo de vallas ` ``` ` van escritos a mano, incluyendo vallas sin cerrar mientras llega el stream. La app arranca sin internet.
- **Copiar código usa `document.execCommand` como respaldo**, porque `navigator.clipboard` no existe en contextos no seguros y en LAN se va por `http://`.
- Si `/api/chat/stream` responde 404, el cliente cae solo al endpoint clásico sin romperse.
- Interfaz tipo transcript con canaleta a la izquierda (no burbujas), porque para código se lee mejor. La barra superior muestra latencia con sparkline de las últimas 16 mediciones.
- Se envían los últimos 8 turnos de historial.

**Regla dura:** servir el cliente por `http://`, nunca por `https://`. Si no, el navegador bloquea las llamadas al backend por contenido mixto.

Archivos que se descartaron por innecesarios: `.env.example` (redundante con el selector de IP) y `README.md`.

---

## 4. Nodo de transferencia (`nodo_red.py`)

Empezó como intercambio P2P simétrico de código y archivos en LAN y evolucionó a un receptor con control de acceso. Probado de punta a punta contra el servidor real.

**Modelo de uso:** se instala en las máquinas que *reciben* (Debian y PC principal). Quien envía no necesita instalar nada: entra por la web UI.

**Características de la v2:**

- Descubrimiento mDNS y panel de aprobación de dispositivos.
- **PIN de 9 dígitos**, bloqueo de 15 min tras 5 fallos por IP.
- **Permisos que caducan a las 24 h** (`NODO_HORAS`), con botón `+24h` en el panel.
- Solicitudes sin responder mueren a los 15 min; máximo 5 por IP cada 10 min y 20 en cola.
- Sesión de admin de 8 h.
- `~/nodo_red/auditoria.log` con solicitudes, aprobaciones, envíos e intentos de PIN fallidos.
- IP real vía `CF-Connecting-IP`, pero solo si la conexión llega desde loopback (o sea, solo desde `cloudflared`). Evita que alguien de la LAN falsee su IP en el registro.
- **Sin ejecución remota, a propósito.** Los archivos se guardan en `inbox` y ya. Nombres saneados contra path traversal.
- `serve --tunel` levanta `cloudflared`, captura la URL `trycloudflare.com` y la cierra al salir. La LAN sigue funcionando en paralelo.

**Variables:** `NODO_TOKEN`, `NODO_PORT` (8500), `NODO_PEER`, `NODO_DIR` (`~/nodo_red`), `NODO_NOMBRE`, `NODO_HORAS`.

Dos advertencias del túnel: la URL cambia en cada reinicio (para una fija hace falta dominio en Cloudflare y túnel con nombre), y la URL no es secreta — la defensa real es el panel de aprobación, por eso el PIN no debe compartirse en el mismo mensaje que la URL.

---

## 5. Pendientes

- Ejecutar `nodo_red.py` como servicio (`systemd` en Debian, tarea programada en Windows) para que levante solo. Quedó ofrecido, no hecho.
- Túnel con URL fija si el acceso remoto pasa a ser permanente.
- Verificar que el portátil Windows tenga la versión con streaming (no la del archivo adjunto).

---

## 6. Prompt del sistema en uso

El modelo está configurado como Arquitecto de Software y Especialista en Linux Debian y Ciberseguridad, con instrucción de responder técnico y conciso, entregar código listo para copiar dentro de bloques ` ``` ` con el lenguaje indicado, y limitarse a desarrollo, administración de Linux y arquitectura de software.
