# -*- coding: utf-8 -*-
"""Testes da lógica pura do coletor CCPAR (``pcrj/ppp_ccpar.py``)."""
from compliance_agent.pcrj.ppp_ccpar import parsear_projeto

HTML = """
<html><head><title>Complexo Hospitalar Souza Aguiar - CCPAR</title></head>
<body>
  <div>Andamento do projeto: Autorização de PMI / MIP, Estudos Concluídos,
       Consulta Pública, Audiência Pública, Edital, Assinatura do Contrato — Concluído</div>
  <p>Investimentos previstos de R$ 850 milhões ao longo de 30 anos.</p>
  <span>EDITAL – 03/04/2023</span> <span>11/05/2023</span>
  <ul>
    <li><a href="https://api.mziq.com/mzfilemanager/v2/d/AAA/111?origin=2">EDITAL DE LICITAÇÃO E ANEXOS</a></li>
    <li><a href="https://api.mziq.com/mzfilemanager/v2/d/AAA/222?origin=2">CONTRATOS E ANEXOS</a></li>
    <li><a href="https://api.mziq.com/mzfilemanager/v2/d/AAA/222?origin=2">CONTRATOS E ANEXOS</a></li>
    <li><a href="https://www.ccpar.rio/mapa/">voltar</a></li>
  </ul>
</body></html>
"""


def test_nome_e_orgao():
    r = parsear_projeto(HTML, "complexo-hospitalar-souza-aguiar")
    assert r["nome"] == "Complexo Hospitalar Souza Aguiar"
    assert r["orgao_gestor"] == "CCPAR"


def test_investimento_convertido():
    r = parsear_projeto(HTML, "x")
    assert r["valor_investimento"] == 850_000_000.0


def test_fase_corrente_e_concluido():
    r = parsear_projeto(HTML, "x")
    assert r["fase"] == "Assinatura do Contrato"
    assert r["concluido"] is True


def test_docs_dedup_e_ignora_navegacao():
    r = parsear_projeto(HTML, "x")
    urls = [d["url"] for d in r["docs"]]
    assert len(urls) == 2                      # dedup do CONTRATOS repetido; ignora link interno
    assert all("mziq" in u for u in urls)
    assert {d["titulo"] for d in r["docs"]} == {"EDITAL DE LICITAÇÃO E ANEXOS", "CONTRATOS E ANEXOS"}


def test_datas_extraidas():
    r = parsear_projeto(HTML, "x")
    assert "03/04/2023" in r["datas"]
