"""Buzon: subida por partes con verificacion de identidad."""

import hashlib
import os
import time

import pytest
from conftest import PASS

from glubia.buzon import Buzon, ErrorBuzon, sanear_nombre
from glubia.identidad import Identidad, codigo_totp, generar_secreto

MB = 1024 * 1024


@pytest.fixture
def buzon(fabricar, tmp_path):
    """Cliente con sesion verificada y partes de 1 MiB."""
    c = fabricar(GLUBIA_BUZON_PARTE_MB="1", GLUBIA_BUZON_MAX_MB="20", GLUBIA_BUZON_CUOTA_GB="0.1",
                 GLUBIA_BUZON_RESERVA_GB="0", GLUBIA_API_KEYS="glb_k")
    s = generar_secreto()
    Identidad(tmp_path / "datos" / "identidad.json").activar(s)
    r = c.post("/api/login", json={"password": PASS, "codigo": codigo_totp(s, int(time.time() // 30))})
    assert r.status_code == 200, r.text
    return c


def _subir(c, datos: bytes, nombre="prueba.bin", orden=None, **extra):
    r = c.post("/api/buzon/envios", json={"nombre": nombre, "tamano": len(datos), **extra})
    assert r.status_code == 200, r.text
    e = r.json()
    partes = range(e["partes"]) if orden is None else orden
    for n in partes:
        trozo = datos[n * e["parte_bytes"]:(n + 1) * e["parte_bytes"]]
        r = c.put(f"/api/buzon/envios/{e['id']}/partes/{n}", content=trozo,
                  headers={"Content-Type": "application/octet-stream"})
        assert r.status_code == 200, r.text
    return e


def test_sin_verificacion_no_hay_buzon(fabricar):
    c = fabricar()
    c.post("/api/login", json={"password": PASS})
    r = c.get("/api/buzon")
    assert r.status_code == 403 and "glubia.identidad activar" in r.json()["detail"]


def test_sesion_sin_codigo_no_entra(fabricar, tmp_path):
    c = fabricar()
    sesiones = c.app.state.glubia.sesiones
    Identidad(tmp_path / "datos" / "identidad.json").activar(generar_secreto())
    c.cookies.set("glubia_sesion", sesiones.crear_token(1))     # sesion antigua, solo contrasena
    assert c.get("/api/buzon").status_code == 401
    c.cookies.set("glubia_sesion", sesiones.crear_token(2))
    assert c.get("/api/buzon").status_code == 200


def test_clave_de_api_no_abre_el_buzon(buzon):
    buzon.cookies.clear()
    assert buzon.get("/api/buzon", headers={"Authorization": "Bearer glb_k"}).status_code == 401


def test_subida_completa_desordenada_y_descarga(buzon):
    datos = os.urandom(int(2.5 * MB))
    e = _subir(buzon, datos, "informe final.pdf", orden=[2, 0, 1])
    estado = buzon.get(f"/api/buzon/envios/{e['id']}").json()
    assert estado["faltan"] == [] and estado["partes_recibidas"] == 3
    fin = buzon.post(f"/api/buzon/envios/{e['id']}/completar").json()
    assert fin["estado"] == "completo" and fin["sha256"] == hashlib.sha256(datos).hexdigest()

    r = buzon.get(f"/api/buzon/envios/{e['id']}/descargar")
    assert r.status_code == 200 and r.content == datos
    assert r.headers["content-type"] == "application/octet-stream"
    assert "attachment" in r.headers["content-disposition"] and "informe" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]

    lista = buzon.get("/api/buzon").json()
    assert lista["envios"][0]["nombre"] == "informe final.pdf"
    assert lista["uso"]["usado"] == len(datos)
    assert buzon.delete(f"/api/buzon/envios/{e['id']}").status_code == 200
    assert buzon.get(f"/api/buzon/envios/{e['id']}").status_code == 404


def test_reanudar(buzon):
    datos = os.urandom(3 * MB + 10)
    e = _subir(buzon, datos, orden=[0, 3])
    faltan = buzon.get(f"/api/buzon/envios/{e['id']}").json()["faltan"]
    assert faltan == [1, 2]
    assert buzon.post(f"/api/buzon/envios/{e['id']}/completar").status_code == 409
    for n in faltan:
        buzon.put(f"/api/buzon/envios/{e['id']}/partes/{n}", content=datos[n * MB:(n + 1) * MB])
    assert buzon.post(f"/api/buzon/envios/{e['id']}/completar").json()["sha256"] == hashlib.sha256(datos).hexdigest()


def test_partes_invalidas(buzon):
    e = buzon.post("/api/buzon/envios", json={"nombre": "x", "tamano": 2 * MB}).json()
    url = f"/api/buzon/envios/{e['id']}/partes"
    assert buzon.put(f"{url}/0", content=b"corto").status_code == 400
    assert buzon.put(f"{url}/5", content=b"x" * MB).status_code == 400
    assert buzon.put(f"{url}/0", content=b"x" * MB, headers={"X-Parte-Sha256": "0" * 64}).status_code == 422
    ok = buzon.put(f"{url}/0", content=b"x" * MB, headers={"X-Parte-Sha256": hashlib.sha256(b"x" * MB).hexdigest()})
    assert ok.status_code == 200
    assert buzon.put(f"{url}/1", content=b"x" * (MB + 200 * 1024)).status_code == 413   # el middleware lo corta
    assert buzon.put("/api/buzon/envios/noexiste123/partes/0", content=b"x").status_code == 404


def test_sha_del_cliente_debe_coincidir(buzon):
    datos = b"hola" * 1000
    e = _subir(buzon, datos, sha256="a" * 64)
    r = buzon.post(f"/api/buzon/envios/{e['id']}/completar")
    assert r.status_code == 422


def test_limites_de_tamano_y_cuota(buzon):
    assert buzon.post("/api/buzon/envios", json={"nombre": "x", "tamano": 21 * MB}).status_code == 413
    for _ in range(5):                                                    # cuota 0.1 GB ~ 102 MB
        assert buzon.post("/api/buzon/envios", json={"nombre": "x", "tamano": 20 * MB}).status_code == 200
    assert buzon.post("/api/buzon/envios", json={"nombre": "x", "tamano": 20 * MB}).status_code == 507


def test_archivo_vacio_y_nota(buzon):
    e = _subir(buzon, b"", "vacio.txt")
    assert buzon.post(f"/api/buzon/envios/{e['id']}/completar").json()["tamano"] == 0
    n = buzon.post("/api/buzon/notas", json={"titulo": "Chat con cliente", "texto": "Hola **mundo**"}).json()
    assert n["nombre"] == "Chat con cliente.md" and n["tipo"] == "nota"
    contenido = buzon.get(f"/api/buzon/envios/{n['id']}/descargar").content.decode()
    assert contenido.startswith("# Chat con cliente") and "Hola **mundo**" in contenido


def test_origen_ajeno_rechazado(buzon):
    r = buzon.post("/api/buzon/notas", json={"texto": "x"}, headers={"Origin": "https://malo.example"})
    assert r.status_code == 403


def test_pagina_del_buzon(buzon):
    r = buzon.get("/buzon")
    assert r.status_code == 200 and "Buzón" in r.text and r.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("entrada,esperado", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\x\\nota.txt", "nota.txt"),
    ("CON.txt", "_CON.txt"),
    ("<script>alert(1)</script>.html", "script.html"),      # la "/" cuenta como carpeta
    ("...", "archivo"),
    ("", "archivo"),
    (".bashrc", "bashrc"),
    ("a" * 300 + ".tar.gz", "a" * 147 + ".gz"),
    ("informe\x00\x07.pdf", "informe.pdf"),
    ("año 2026 · fotos.zip", "año 2026 · fotos.zip"),
])
def test_sanear_nombre(entrada, esperado):
    assert sanear_nombre(entrada) == esperado


def test_rutas_siempre_dentro_del_buzon(tmp_path):
    b = Buzon(tmp_path / "bz", 1024, 10 * MB, 100 * MB, 0)
    e = b.crear("../../../fuera.txt", 3)
    b.escribir_parte(e["id"], 0, b"abc")
    fin = b.completar(e["id"])
    ruta, _ = b.archivo(fin["id"])
    assert ruta.resolve().is_relative_to((tmp_path / "bz" / "archivos").resolve())
    with pytest.raises(ErrorBuzon):
        b.estado("../../x")


def test_limpia_subidas_abandonadas(tmp_path):
    b = Buzon(tmp_path / "bz", 1024, 10 * MB, 100 * MB, 0)
    e = b.crear("viejo.bin", 10)
    parcial = tmp_path / "bz" / "parciales" / f"{e['id']}.part"
    hace_dos_dias = time.time() - 48 * 3600
    os.utime(parcial, (hace_dos_dias, hace_dos_dias))
    import sqlite3
    with sqlite3.connect(tmp_path / "bz" / "indice.db") as con:
        con.execute("UPDATE envios SET creado = ? WHERE id = ?", (int(hace_dos_dias), e["id"]))
    assert b.limpiar_abandonados() == 1 and not parcial.exists()
