"""IP real, limitador acotado y telemetria."""

import ipaddress
from types import SimpleNamespace

from glubia.seguridad import Limitador, anonimizar, ip_cliente
from glubia.telemetria import archivo_consentimiento, desactivar_telemetria_openvino


def _req(ip, **cab):
    return SimpleNamespace(client=SimpleNamespace(host=ip),
                           headers={k.lower().replace("_", "-"): v for k, v in cab.items()})


def test_ip_lan_no_puede_falsearse():
    r = _req("192.168.1.20", cf_connecting_ip="1.2.3.4", x_real_ip="5.6.7.8")
    assert ip_cliente(r, ()) == "192.168.1.20"


def test_ip_desde_cloudflared_local():
    assert ip_cliente(_req("127.0.0.1", cf_connecting_ip="1.2.3.4"), ()) == "1.2.3.4"


def test_ip_desde_proxy_de_confianza():
    proxies = (ipaddress.ip_network("172.31.0.20/32"),)
    assert ip_cliente(_req("172.31.0.20", x_real_ip="8.8.8.8", cf_connecting_ip="9.9.9.9"), proxies) == "8.8.8.8"
    # otro contenedor de la red no es de confianza
    assert ip_cliente(_req("172.31.0.30", x_real_ip="8.8.8.8"), proxies) == "172.31.0.30"


def test_limitador_ventana_y_memoria_acotada():
    lim = Limitador(max_claves=100)
    assert lim.permitir("a", 2, 60) == (True, 0)
    assert lim.permitir("a", 2, 60)[0] is True
    ok, espera = lim.permitir("a", 2, 60)
    assert ok is False and 0 < espera <= 61
    for i in range(5000):
        lim.registrar(f"ip-{i}")
    assert len(lim) == 100   # en la v1 el diccionario crecia sin limite


def test_telemetria_se_desactiva(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    desactivar_telemetria_openvino(False)
    assert archivo_consentimiento().read_text() == "0"


def test_telemetria_se_respeta_si_se_permite(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    desactivar_telemetria_openvino(True)
    assert not archivo_consentimiento().exists()


def test_ip_anonimizada_en_logs():
    assert anonimizar("181.52.33.7") == "181.52.x.x"
    assert anonimizar("2800:e2:8f80:1234::1") == "2800:00e2:8f80::x"
    assert anonimizar("no-es-ip") == "?"
