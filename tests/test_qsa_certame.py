# -*- coding: utf-8 -*-
"""O alimentador do direcionamento consumado — e o erro que ele existe para não cometer.

O maior deles: chamar de "perdedora" a empresa que venceu OUTRO item. Num certame multi-item isso
é o resultado normal, e tratá-lo como disputa inflaria a cobertura em quase 7× (4.549 certames com
mais de um fornecedor × 684 itens com disputa registrada de verdade).

O segundo: devolver "sem vínculo" para certame que simplesmente não tem classificado além do 1º
lugar registrado. Ausência de registro não é ausência de disputa.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint import qsa_certame as qc


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE pncp_resultado(certame TEXT, item TEXT, fornecedor_cnpj TEXT, "
              "fornecedor_nome TEXT, ordem_classificacao INT, valor_homologado REAL)")
    c.execute("CREATE TABLE socios_receita(cnpj_basico TEXT, nome_socio TEXT, nome_norm TEXT, "
              "doc_socio TEXT, qualificacao_txt TEXT, data_entrada TEXT, faixa_etaria TEXT)")
    c.execute("CREATE TABLE endereco_verificacao(cnpj TEXT, evidencia TEXT)")
    return c


def _res(c, certame, item, cnpj, nome, ordem):
    c.execute("INSERT INTO pncp_resultado VALUES(?,?,?,?,?,?)",
              (certame, item, cnpj, nome, ordem, 1000.0))


def _socio(c, cnpj, nome, doc):
    c.execute("INSERT INTO socios_receita VALUES(?,?,?,?,?,?,?)",
              (cnpj[:8], nome, nome, doc, "49-Sócio-Administrador", "20200101", "5"))


# ─────────────────── quem é perdedor: mesmo ITEM, ordem > 1 ───────────────────────────────────

def test_vencedor_de_OUTRO_item_nao_e_perdedora(con):
    """Certame multi-item com adjudicatários diferentes é o resultado normal, não disputa."""
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "2", "22222222000192", "BETA", 1)
    p = qc.participantes(con, "C1")
    assert p["perdedores"] == [], "adjudicatária de outro item entrou como perdedora"
    assert p["itens_no_certame"] == 2


def test_classificado_em_segundo_no_MESMO_item_e_perdedora(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "22222222000192", "BETA", 2)
    p = qc.participantes(con, "C1")
    assert [x["cnpj"] for x in p["perdedores"]] == ["22222222000192"]


def test_escolhe_o_item_com_mais_participantes_distintos(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "2", "11111111000191", "ALFA", 1)
    _res(con, "C1", "2", "22222222000192", "BETA", 2)
    _res(con, "C1", "2", "33333333000193", "GAMA", 3)
    p = qc.participantes(con, "C1")
    assert p["item"] == "2" and len(p["perdedores"]) == 2


def test_item_pode_ser_fixado_pelo_chamador(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "2", "22222222000192", "BETA", 1)
    _res(con, "C1", "2", "33333333000193", "GAMA", 2)
    assert qc.participantes(con, "C1", item="1")["perdedores"] == []


def test_mesmo_CNPJ_em_duas_linhas_nao_vira_perdedora_de_si_mesmo(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "11111111000191", "ALFA", 2)
    assert qc.participantes(con, "C1")["perdedores"] == []


# ─────────────────── ausência de registro ≠ ausência de disputa ───────────────────────────────

def test_certame_sem_classificado_alem_do_primeiro_e_NAO_OBSERVADO(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    r = qc.avaliar_certame(con, "C1")
    assert r["veredito"] == "nao_observado"
    assert "não certame sem disputa" in r["motivo"]


def test_certame_inexistente_e_nao_observado_e_nao_limpo(con):
    r = qc.avaliar_certame(con, "NAO_EXISTE")
    assert r["veredito"] == "nao_observado" and r["cobertura"]["perdedoras"] == 0


def test_cobertura_declara_a_fracao_com_disputa(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C2", "1", "11111111000191", "ALFA", 1)
    _res(con, "C2", "1", "22222222000192", "BETA", 2)
    cv = qc.cobertura(con)
    assert cv["certames"] == 2 and cv["certames_com_disputa"] == 1
    assert cv["frac"] == pytest.approx(0.5)
    assert "NÃO OBSERVADO" in cv["ressalva"]


# ─────────────────── o cruzamento de QSA propriamente ─────────────────────────────────────────

def test_perdedora_com_socio_COMUM_ao_vencedor_e_ligada(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "22222222000192", "BETA", 2)
    _socio(con, "11111111000191", "JOSE COMUM", "***123456**")
    _socio(con, "22222222000192", "JOSE COMUM", "***123456**")
    r = qc.avaliar_certame(con, "C1")
    assert r["cobertura"]["com_dado"] == 1
    assert r["ligadas"], "sócio comum não produziu caminho"


def test_vinculo_SEM_restritividade_nao_vira_direcionamento(con):
    """A virada de natureza exige restrição + vínculo. Vínculo sozinho é competição aparente."""
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "22222222000192", "BETA", 2)
    _socio(con, "11111111000191", "JOSE COMUM", "***123456**")
    _socio(con, "22222222000192", "JOSE COMUM", "***123456**")
    assert qc.avaliar_certame(con, "C1")["veredito"] == "competicao_aparente"


def test_vinculo_COM_restritividade_vira_direcionamento_consumado(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "22222222000192", "BETA", 2)
    _socio(con, "11111111000191", "JOSE COMUM", "***123456**")
    _socio(con, "22222222000192", "JOSE COMUM", "***123456**")
    r = qc.avaliar_certame(con, "C1", clausula_restritiva=True)
    assert r["veredito"] == "direcionamento_consumado"


def test_perdedora_sem_QSA_conta_como_SEM_DADO_e_nao_como_limpa(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "22222222000192", "BETA", 2)
    _socio(con, "11111111000191", "JOSE COMUM", "***123456**")
    r = qc.avaliar_certame(con, "C1")
    assert r["cobertura"]["sem_dado"] == 1 and r["cobertura"]["com_dado"] == 0


def test_empresas_sem_nada_em_comum_nao_produzem_vinculo(con):
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "22222222000192", "BETA", 2)
    _socio(con, "11111111000191", "PESSOA A", "***111111**")
    _socio(con, "22222222000192", "PESSOA B", "***222222**")
    r = qc.avaliar_certame(con, "C1")
    assert not r["ligadas"]


def test_o_item_avaliado_sai_declarado(con):
    """Veredito sobre o item 7 apresentado como veredito do certame seria falso."""
    _res(con, "C1", "7", "11111111000191", "ALFA", 1)
    _res(con, "C1", "7", "22222222000192", "BETA", 2)
    r = qc.avaliar_certame(con, "C1")
    assert r["item"] == "7" and r["itens_no_certame"] == 1


def test_prefere_o_item_que_TEM_disputa_ao_de_adjudicacao_multipla(con):
    """Medido: ordenar só por 'mais participantes' devolvia `nao_observado` em 45 de 114 certames
    que TINHAM disputa registrada — em outro item."""
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)      # item 1: três adjudicatárias, todas 1º
    _res(con, "C1", "1", "22222222000192", "BETA", 1)
    _res(con, "C1", "1", "33333333000193", "GAMA", 1)
    _res(con, "C1", "2", "11111111000191", "ALFA", 1)      # item 2: disputa de verdade
    _res(con, "C1", "2", "44444444000194", "DELTA", 2)
    p = qc.participantes(con, "C1")
    assert p["item"] == "2" and [x["cnpj"] for x in p["perdedores"]] == ["44444444000194"]


def test_ordem_maior_que_um_com_o_PROPRIO_vencedor_nao_e_disputa(con):
    """Medido: em 45 dos 114 certames com `ordem > 1`, a linha traz o mesmo CNPJ do vencedor — o
    PNCP registra o fornecedor em mais de uma posição. Contar isso como concorrente inventaria
    disputa onde não houve."""
    _res(con, "C1", "1", "11111111000191", "ALFA", 1)
    _res(con, "C1", "1", "11111111000191", "ALFA", 2)
    r = qc.avaliar_certame(con, "C1")
    assert r["veredito"] == "nao_observado"
    assert "próprio vencedor" in r["motivo"]
