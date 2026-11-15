"""Guarda do navegador do Claude (CDP :9333): volta a about:blank só com página parada E CPU alta."""
from tools import vm_guard as g


def _pag(id_, url):
    return {"id": id_, "type": "page", "url": url, "webSocketDebuggerUrl": "ws://x"}


def test_pagina_parada_com_cpu_alta_volta_blank(tmp_path):
    est = str(tmp_path / "e.json")
    navegadas = []
    pag = [_pag("A", "https://higgsfield.ai")]
    r0 = g.guarda_navegador_claude(agora=1000, paginas=pag, cpu_pct=lambda: 90,
                                   navegar=lambda p: navegadas.append(p) or True, estado_path=est)
    assert r0["acao"] == "nenhuma" and not navegadas        # acabou de chegar: não mexe
    r1 = g.guarda_navegador_claude(agora=1000 + 31 * 60, paginas=pag, cpu_pct=lambda: 90,
                                   navegar=lambda p: navegadas.append(p) or True, estado_path=est)
    assert r1["acao"] == "about:blank" and len(navegadas) == 1


def test_cpu_baixa_nao_mexe(tmp_path):
    est = str(tmp_path / "e.json")
    pag = [_pag("A", "https://exemplo.gov.br")]
    g.guarda_navegador_claude(agora=0, paginas=pag, cpu_pct=lambda: 2, navegar=lambda p: True, estado_path=est)
    r = g.guarda_navegador_claude(agora=3 * 3600, paginas=pag, cpu_pct=lambda: 2,
                                  navegar=lambda p: (_ for _ in ()).throw(AssertionError("navegou")),
                                  estado_path=est)
    assert r["acao"] == "nenhuma" and r["paradas"] == 1


def test_trocar_de_url_zera_o_relogio(tmp_path):
    est = str(tmp_path / "e.json")
    g.guarda_navegador_claude(agora=0, paginas=[_pag("A", "https://a")], cpu_pct=lambda: 90,
                              navegar=lambda p: True, estado_path=est)
    r = g.guarda_navegador_claude(agora=40 * 60, paginas=[_pag("A", "https://b")], cpu_pct=lambda: 90,
                                  navegar=lambda p: (_ for _ in ()).throw(AssertionError("navegou")),
                                  estado_path=est)
    assert r["acao"] == "nenhuma"


def test_about_blank_ignorada(tmp_path):
    r = g.guarda_navegador_claude(agora=0, paginas=[_pag("A", "about:blank")], cpu_pct=lambda: 99,
                                  navegar=lambda p: True, estado_path=str(tmp_path / "e.json"))
    assert r["paginas"] == 0
