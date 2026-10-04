   # Buzón privado: enviarte cualquier cosa a tu equipo

`/buzon` (en el GlubIA privado, puerto 8081 o `ia.tu-dominio.com`) es una página para mandarte a tu
propio equipo **lo que sea**: documentos, comprimidos, exportaciones de chats, fotos, notas de
texto. Sirve desde el móvil, desde otro computador o desde Windows hacia Omarchy.

Solo lo puede usar quien tenga **tu contraseña y tu teléfono** (verificación en dos pasos).

## Activar la verificación en dos pasos (una vez)

En la consola del equipo donde corre GlubIA. Tener acceso a esa consola es la prueba de identidad
para dar de alta el teléfono.

```bash
# Omarchy (contenedor)
docker compose exec glubia python -m glubia.identidad activar
# Windows / sin contenedor
.\openvino_env\Scripts\python.exe -m glubia.identidad activar
```

1. Sale un código QR en la consola. Escanéalo con tu aplicación de autenticación (Aegis,
   Google Authenticator, Bitwarden, 1Password…). Si la consola no muestra bien el QR, copia la
   clave de texto que aparece debajo.
2. Escribe el código de 6 dígitos que muestra la aplicación para confirmar.
3. Desde ese momento, el login de GlubIA pide **contraseña y código**, en la interfaz y en el buzón.

`python -m glubia.identidad estado` dice si está activa; `desactivar` la quita. El secreto vive en
`datos/identidad.json` con permisos 600: **no lo subas a ningún sitio y no lo copies a otro equipo**
si no quieres que ese equipo también acepte tus códigos.

Si pierdes el teléfono: entra a la consola del equipo y ejecuta `activar --forzar` con el nuevo.

## Cómo se usa

1. Abre `https://ia.tu-dominio.com/buzon` (o `http://IP-de-Omarchy:8081/buzon` en tu red).
2. Contraseña + código de 6 dígitos.
3. Arrastra archivos o escribe una nota. Ves el progreso de cada archivo; si se corta la conexión
   reintenta solo, y si cierras la página puedes **reanudar** seleccionando el mismo archivo.
4. Lo recibido aparece en la lista con su huella sha256, para descargarlo o borrarlo.

En el equipo, todo queda en la carpeta del buzón (`./buzon` junto al `compose.yaml`, o
`GLUBIA_BUZON_HOST`):

```
buzon/
├── archivos/2026-10-03/3f2a9c1b-informe.pdf
├── archivos/2026-10-03/7be01d44-nota-ideas.md
├── parciales/          subidas a medias (las de más de 24 h se borran al arrancar o al empezar otro envío)
└── indice.db           qué llegó, cuándo, tamaño y huella
```

## Por qué está hecho así

| Decisión | Motivo |
|---|---|
| Subida en **partes de 8 MiB** | Cloudflare corta cualquier petición de más de **100 MB** en los planes Free y Pro (413). Por partes no hay límite práctico de tamaño y un corte solo repite la parte que faltaba. |
| sha256 de cada parte y del archivo | Detecta corrupción en el camino; la huella final te permite comprobar el archivo. |
| **Nada se ejecuta ni se descomprime** | Un comprimido se guarda tal cual. Abrirlo es decisión tuya, en tu equipo. |
| Descarga como `application/octet-stream` con `nosniff` y sandbox | Un HTML o SVG recibido no puede ejecutarse en el navegador con tu sesión. |
| Nombres saneados y prefijo aleatorio | Ningún nombre de archivo puede escribir fuera de la carpeta ni pisar otro. |
| Exige sesión **verificada** (contraseña + código) | Una contraseña filtrada no basta. Las claves de API tampoco sirven aquí. |
| Rechaza peticiones de otro origen | Otra web no puede hacer que tu navegador suba o borre cosas. |
| Cuota y reserva de disco | El buzón nunca llena el disco de Omarchy. |

## Ajustes

| Variable | Por defecto | Para qué |
|---|---|---|
| `GLUBIA_BUZON` | `1` | `0` desactiva el buzón |
| `GLUBIA_BUZON_DIR` | `datos/buzon` (`/buzon` en el contenedor) | dónde se guarda |
| `GLUBIA_BUZON_HOST` | `./buzon` | carpeta del equipo montada en el contenedor |
| `GLUBIA_BUZON_MAX_MB` | `10240` | tamaño máximo de un envío (10 GB) |
| `GLUBIA_BUZON_CUOTA_GB` | `100` | total que puede ocupar el buzón |
| `GLUBIA_BUZON_RESERVA_GB` | `10` | espacio libre que siempre se deja en el disco |
| `GLUBIA_BUZON_PARTE_MB` | `8` | tamaño de cada parte (1–90; por debajo del límite de Cloudflare) |

## Sobre la privacidad

El buzón **no es para la IA**: lo que envías ahí no lo lee el modelo ni el asistente público. Eso
respeta RF-03: lo único que la IA puede leer es lo que tú pones en `portafolio/contenido/`.

Por el túnel, Cloudflare termina el HTTPS en su borde y vuelve a cifrar hasta tu equipo; es decir,
técnicamente ve el tráfico en claro al pasar. Para documentos muy sensibles, cífralos antes de
enviarlos (por ejemplo un `.7z` con contraseña) o usa el buzón solo dentro de tu red.

## API (para scripts)

Todas las rutas exigen la cookie de una sesión verificada; si la petición trae cabecera `Origin`, tiene que ser la del propio sitio.

| Método y ruta | Qué hace |
|---|---|
| `GET /api/buzon` | lista de envíos y uso del disco |
| `POST /api/buzon/envios` | `{nombre, tamano, tipo?, sha256?}` → `{id, parte_bytes, partes}` |
| `PUT /api/buzon/envios/{id}/partes/{n}` | cuerpo binario de la parte `n`; cabecera opcional `X-Parte-Sha256` |
| `GET /api/buzon/envios/{id}` | estado y partes que faltan (para reanudar) |
| `POST /api/buzon/envios/{id}/completar` | une las partes y devuelve la sha256 |
| `GET /api/buzon/envios/{id}/descargar` | descarga |
| `DELETE /api/buzon/envios/{id}` | borra |
| `POST /api/buzon/notas` | `{titulo?, texto}` → se guarda como `.md` |
