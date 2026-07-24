"""A página /controle tem de ter um botão de VOLTAR ao painel.

Pedido do dono (2026-07-23): sem ele, quem entra em /controle fica sem caminho de
volta ao /painel a não ser pelo botão do navegador.
"""
import re
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "rotas" / "investigacao.py"


def _controle_html() -> str:
    src = FONTE.read_text(encoding="utf-8")
    m = re.search(r'_CONTROLE_HTML\s*=\s*r?"""(.*?)"""', src, re.S)
    assert m, "não achei _CONTROLE_HTML"
    return m.group(1)


def test_tem_link_de_volta_ao_painel():
    html = _controle_html()
    assert '/painel' in html, "o botão de voltar tem de apontar para /painel"


def test_tem_rotulo_voltar_visivel():
    html = _controle_html()
    assert re.search(r"[Vv]oltar", html), "o botão precisa de um rótulo 'Voltar' visível"
