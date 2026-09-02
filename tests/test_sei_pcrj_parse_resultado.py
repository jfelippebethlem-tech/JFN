"""Parser do resultado da pesquisa pública do SEI municipal, sobre resposta REAL.

A fixture é o campo `html` de uma resposta {"itens":1,"html":…} capturada em 2026-09-02.
O que importa travar: o protocolo vem em `data-prot`, e o link `md_pesq_processo_exibir.php`
é o acesso à ÍNTEGRA — token opaco por sessão, que só existe colhido do resultado.
"""
from pathlib import Path

from compliance_agent.pcrj.sei_prefeitura import parse_resultado_html

FIXTURE = Path(__file__).parent / "fixtures" / "sei_pcrj_resultado.html"


def test_extrai_protocolo_unidade_e_data():
    itens = parse_resultado_html(FIXTURE.read_text(encoding="utf-8"))
    assert len(itens) == 1
    it = itens[0]
    assert it["protocolo"] == "000100.000244/2026-10"
    assert it["unidade"] == "CR-SEI.RIO"
    assert it["data"] == "12/01/2026"


def test_url_da_integra_e_absoluta_e_carrega_o_token():
    it = parse_resultado_html(FIXTURE.read_text(encoding="utf-8"))[0]
    assert it["url_integra"].startswith("https://prefeitura.sei.rio/sei/modulos/pesquisa/")
    # sem o token não se abre a íntegra; ele não se constrói, só se colhe
    assert len(it["url_integra"].split("md_pesq_processo_exibir.php?")[1]) > 40


def test_html_vazio_devolve_lista_vazia():
    """Resposta de captcha recusado traz html sem registro — não pode virar item fantasma."""
    assert parse_resultado_html("") == []
    assert parse_resultado_html('{"html":"<consultavazia>"}') == []
