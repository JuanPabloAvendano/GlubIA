"""Verificacion en dos pasos (TOTP) y niveles de sesion."""

import base64
import time

from conftest import PASS

from glubia.identidad import Identidad, codigo_totp, generar_secreto, uri_otpauth
from glubia.seguridad import Sesiones

# RFC 6238, apendice B (SHA-1, 8 digitos, semilla "12345678901234567890").
SEMILLA = base64.b32encode(b"12345678901234567890").decode()
VECTORES = {59: "94287082", 1111111109: "07081804", 1111111111: "14050471",
            1234567890: "89005924", 2000000000: "69279037", 20000000000: "65353130"}


def test_vectores_rfc6238():
    for t, esperado in VECTORES.items():
        assert codigo_totp(SEMILLA, t // 30, digitos=8) == esperado


def test_secreto_y_uri():
    s = generar_secreto()
    assert len(s) == 32 and s.isalnum()
    uri = uri_otpauth(s, "juan")
    assert uri.startswith("otpauth://totp/GlubIA%3Ajuan?secret=" + s) and "period=30" in uri


def test_verificar_ventana_y_repeticion(tmp_path):
    ident = Identidad(tmp_path / "identidad.json")
    assert not ident.activa and not ident.verificar("123456")
    s = generar_secreto()
    ident.activar(s)
    ahora = 1_800_000_000
    paso = ahora // 30
    assert ident.verificar(codigo_totp(s, paso), ahora)
    assert not ident.verificar(codigo_totp(s, paso), ahora), "un codigo no puede usarse dos veces"
    assert ident.verificar(codigo_totp(s, paso + 1), ahora), "se acepta el siguiente (reloj adelantado)"
    assert not ident.verificar(codigo_totp(s, paso - 1), ahora), "anterior a uno ya usado: no"
    assert not ident.verificar(codigo_totp(s, paso + 5), ahora), "fuera de la ventana"
    for basura in ("", "12345", "abcdef", "1234567", None):
        assert not ident.verificar(basura, ahora)
    assert ident.verificar(" ".join([codigo_totp(s, paso + 2)[:3], codigo_totp(s, paso + 2)[3:]]), ahora + 60)


def test_recarga_en_caliente(tmp_path):
    """Activar desde la consola con el servidor en marcha surte efecto sin reiniciar."""
    ruta = tmp_path / "identidad.json"
    servidor = Identidad(ruta)
    assert not servidor.activa
    Identidad(ruta).activar(generar_secreto())      # otra instancia = la consola
    time.sleep(0.01)
    assert servidor.activa


def test_niveles_de_token():
    ses = Sesiones(b"s" * 48, "x", True, 8)
    assert ses.nivel_token(ses.crear_token()) == 1
    assert ses.nivel_token(ses.crear_token(2)) == 2
    viejo = ses._firmar(f"{int(time.time()) + 60}:abc")       # formato de la v2.0
    assert ses.nivel_token(viejo) == 1 and ses.token_valido(viejo)
    manipulado = ses.crear_token(1).replace(":1.", ":2.")
    assert ses.nivel_token(manipulado) == 0, "subir el nivel a mano invalida la firma"


def _activar(cliente, tmp_path):
    s = generar_secreto()
    Identidad(tmp_path / "datos" / "identidad.json").activar(s)
    return s


def test_login_pide_codigo(fabricar, tmp_path):
    c = fabricar()
    assert c.get("/api/session").json()["totp_required"] is False
    s = _activar(c, tmp_path)
    j = c.get("/api/session").json()
    assert j["totp_required"] is True and j["verified"] is False

    r = c.post("/api/login", json={"password": PASS})
    assert r.status_code == 401 and r.json()["detail"] == "Contraseña o código incorrectos"
    r = c.post("/api/login", json={"password": PASS, "codigo": "000000"})
    assert r.status_code == 401
    r = c.post("/api/login", json={"password": "mala", "codigo": codigo_totp(s, int(time.time() // 30))})
    assert r.status_code == 401, "codigo bueno con contrasena mala: fuera"
    r = c.post("/api/login", json={"password": PASS, "codigo": codigo_totp(s, int(time.time() // 30) + 1)})
    assert r.status_code == 200
    j = c.get("/api/session").json()
    assert j["authenticated"] and j["verified"]


def test_codigo_cuenta_para_el_bloqueo(fabricar, tmp_path):
    c = fabricar()
    _activar(c, tmp_path)
    for _ in range(5):
        c.post("/api/login", json={"password": PASS, "codigo": "111111"})
    assert c.post("/api/login", json={"password": PASS, "codigo": "222222"}).status_code == 429
