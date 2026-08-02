"""A página /controle tem de ter um botão de VOLTAR ao painel.

Pedido do dono (2026-07-23): sem ele, quem entra em /controle fica sem caminho de
volta ao /painel a não ser pelo botão do navegador.

2026-08-02: o markup saiu de `rotas/investigacao.py` (`_CONTROLE_HTML`) para
`static/jfn-controle.html` na v58 do painel. A GARANTIA é a mesma — o teste passou a ler a
tela onde ela vive agora, e falha se o arquivo sumir (a rota serve esse caminho fixo).
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TELA = RAIZ / "static" / "jfn-controle.html"
ROTA = RAIZ / "rotas" / "investigacao.py"


def _controle_html() -> str:
    assert TELA.exists(), f"a tela de /controle não está em {TELA} (a rota serve esse caminho)"
    return TELA.read_text(encoding="utf-8")


def test_a_rota_controle_aponta_para_a_tela_que_este_teste_verifica():
    """Trava o par rota↔arquivo: se a rota passar a servir outro caminho, este teste avisa em
    vez de continuar validando um arquivo que ninguém mais serve."""
    assert "jfn-controle.html" in ROTA.read_text(encoding="utf-8")


def test_tem_link_de_volta_ao_painel():
    html = _controle_html()
    assert re.search(r'href=["\']/painel', html), "o botão de voltar tem de apontar para /painel"


def test_tem_rotulo_voltar_visivel():
    html = _controle_html()
    assert re.search(r"[Vv]oltar|←\s*Painel", html), "o botão precisa de um rótulo de volta visível"
