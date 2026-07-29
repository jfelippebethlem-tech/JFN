# -*- coding: utf-8 -*-
"""G.3 — beneficiário final sobre o acervo REAL, e os dois defeitos que só o dado real revelou.

O motor de `osint/vinculos.py` era bom e nunca tinha rodado: o pacote `osint/` inteiro estava sem
caller em produção. Ao ligá-lo em `osint/fonte_grafo.py` e apontá-lo para `socios_receita`, dois
defeitos apareceram na primeira empresa com cadeia PJ→PJ de verdade (MEDICALDECK × BHIO SUPPLY):

  1. **Ciclo falso.** O grafo é não-direcionado, e a subida seguia a MESMA aresta de volta:
     `A → B → A` era relatado como participação cruzada circular. E participação cruzada circular
     não é um detalhe — o próprio módulo a trata como ACHADO ("estrutura que costuma existir para
     dificultar a identificação"). Um detector de achado disparando em toda cadeia de dois degraus
     é o mesmo defeito do laranja que marcava 55% da base.
  2. **Descida indevida.** Ao chegar numa holding, a travessia seguia para as OUTRAS empresas de
     que a holding é sócia — e devolvia os sócios delas como beneficiários finais da empresa de
     origem. Vínculo lateral virava vínculo vertical.

Ambos têm a mesma raiz: `beneficiario_final` ignorava a DIREÇÃO da aresta. `Aresta(origem=sócio,
destino=empresa)`; subir a cadeia é seguir só as arestas em que o nó atual é o DESTINO.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_osint_fonte_grafo.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.vinculos import GrafoVinculos, no_pf, no_pj

_FONTE = "QSA/Receita Federal (teste)"


def _grafo_a_sob_b() -> GrafoVinculos:
    """ALFA tem a holding BETA como sócia; BETA tem uma PF. Cadeia de dois degraus, sem ciclo."""
    g = GrafoVinculos()
    alfa, beta = no_pj("11111111000100"), no_pj("22222222000100")
    pf = no_pf("", "MARIA DA SILVA|123456")
    g.rotular(alfa, "ALFA LTDA"); g.rotular(beta, "BETA HOLDING"); g.rotular(pf, "MARIA DA SILVA")
    g.ligar(beta, alfa, "socio_de", fonte=_FONTE)   # BETA é sócia de ALFA
    g.ligar(pf, beta, "socio_de", fonte=_FONTE)     # MARIA é sócia de BETA
    return g


def test_cadeia_de_dois_degraus_nao_e_ciclo():
    g = _grafo_a_sob_b()
    out = g.beneficiario_final(no_pj("11111111000100"))
    assert out["ciclos"] == [], (
        "cadeia simples A←B←PF relatada como participação cruzada circular — "
        f"ciclos={out['ciclos']}"
    )
    assert out["n_pessoas"] == 1
    assert out["pessoas"][0]["rotulo"] == "MARIA DA SILVA"
    assert out["pessoas"][0]["saltos"] == 2, "MARIA está a dois degraus de ALFA"
    assert out["pessoas"][0]["documentado"] is False, "CPF mascarado não é CPF documentado"


def test_ciclo_de_verdade_ainda_e_detectado():
    """A é sócia de B e B é sócia de A — aí sim é participação cruzada, e tem de aparecer."""
    g = GrafoVinculos()
    a, b = no_pj("11111111000100"), no_pj("22222222000100")
    g.rotular(a, "ALFA"); g.rotular(b, "BETA")
    g.ligar(b, a, "socio_de", fonte=_FONTE)
    g.ligar(a, b, "socio_de", fonte=_FONTE)
    out = g.beneficiario_final(a)
    assert out["ciclos"], "participação cruzada circular real deixou de ser detectada"


def test_nao_desce_para_as_irmas_da_holding():
    """BETA é sócia de ALFA e também da GAMA. Os sócios da GAMA NÃO são beneficiários da ALFA."""
    g = _grafo_a_sob_b()
    gama = no_pj("33333333000100")
    intruso = no_pf("", "JOAO INTRUSO|999999")
    g.rotular(gama, "GAMA LTDA"); g.rotular(intruso, "JOAO INTRUSO")
    g.ligar(no_pj("22222222000100"), gama, "socio_de", fonte=_FONTE)  # BETA é sócia da GAMA
    g.ligar(intruso, gama, "socio_de", fonte=_FONTE)

    out = g.beneficiario_final(no_pj("11111111000100"))
    nomes = {p["rotulo"] for p in out["pessoas"]}
    assert "JOAO INTRUSO" not in nomes, (
        "sócio de empresa IRMÃ apareceu como beneficiário final — vínculo lateral virou vertical: "
        f"{sorted(nomes)}"
    )
    assert nomes == {"MARIA DA SILVA"}


# ── integração com o acervo real ─────────────────────────────────────────────

def _tem_base() -> bool:
    from pathlib import Path

    from compliance_agent.reporting.intel_base import _DB
    return Path(_DB).exists()


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_cobertura_declara_a_ausencia_de_serie_temporal():
    """A base é snapshot único: sem dois `fonte_mes`, saída de sócio é inobservável — e o produto
    tem de dizer isso, em vez de deixar o leitor supor que o vínculo é atual."""
    from compliance_agent.osint.fonte_grafo import cobertura_qsa

    c = cobertura_qsa()
    assert c["socios"] > 0 and c["raizes_com_qsa"] > 0
    assert c["serie_temporal"] is (len(c["snapshots"]) > 1)
    assert "SAÍDA" in c["nota"].upper()


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_beneficiario_final_roda_sobre_cadeia_real():
    """Sobe uma cadeia PJ→PJ que existe de fato na base (há 2.449 elos encadeáveis)."""
    from compliance_agent.osint.fonte_grafo import beneficiario_final_do_cnpj
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    try:
        linha = con.execute(
            "SELECT s.cnpj_basico FROM socios_receita s JOIN socios_receita t "
            "ON substr(replace(s.doc_socio,'.',''),1,8)=t.cnpj_basico WHERE s.ident='1' LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if not linha:
        pytest.skip("nenhuma cadeia PJ→PJ encadeável na base")

    out = beneficiario_final_do_cnpj(linha[0] + "000100")
    assert out["ok"] is True
    assert out["n_arestas"] > 0, "o grafo saiu vazio sobre uma raiz que tem QSA"
    # honestidade obrigatória no produto
    assert out["temporalidade"]["tem_data_saida"] is False
    assert out["documentacao"]["cpf_mascarado"] is True
    assert 0.0 <= out["cobertura"]["pct"] <= 100.0
    assert "CAPTURA" in out["cobertura"]["nota"].upper()
