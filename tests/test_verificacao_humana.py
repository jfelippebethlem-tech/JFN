"""Detecção de verificação humana (só detecta; quem resolve é o dono pelo noVNC)."""
from tools.verificacao_humana import ha_desafio


def test_desafio_detectado_por_iframe_ou_texto():
    assert ha_desafio(["https://www.google.com/recaptcha/api2/anchor?k=x"], "")
    assert ha_desafio(["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x"], "")
    assert ha_desafio([], "Verifique: Não sou um robô")
    assert ha_desafio([], "Checking your browser before accessing")


def test_pagina_comum_nao_e_desafio():
    assert not ha_desafio(["https://pncp.gov.br/app/atas", "about:blank"], "Atas de registro de preços — 1.234 resultados")
    assert not ha_desafio([], "")


def test_cofre_descarta_cookie_expirado_e_mantem_de_sessao(tmp_path, monkeypatch):
    from tools import verificacao_humana as V
    monkeypatch.setattr(V, "SESSOES", tmp_path)
    V.guardar_sessao("https://pncp.gov.br/app/x", [
        {"name": "a", "expires": 2000.0}, {"name": "b", "expires": 500.0}, {"name": "c", "expires": -1}])
    nomes = {c["name"] for c in V.carregar_sessao("https://pncp.gov.br/outra", agora=1000.0)}
    assert nomes == {"a", "c"}
    assert V.carregar_sessao("https://outro.gov.br/") == []


def test_aviso_no_maximo_um_a_cada_6h_por_site(tmp_path, monkeypatch):
    from tools import verificacao_humana as V
    monkeypatch.setattr(V, "SESSOES", tmp_path)
    assert V._pode_avisar("pncp.gov.br", 100_000.0)
    assert not V._pode_avisar("pncp.gov.br", 100_000.0 + 3600)
    assert V._pode_avisar("outro.gov.br", 100_000.0 + 3600)
    assert V._pode_avisar("pncp.gov.br", 100_000.0 + 6 * 3600 + 1)
