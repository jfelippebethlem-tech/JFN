# -*- coding: utf-8 -*-
"""E.3.2 municipal — o eixo que devolvia zero por falta de DADO, e a cadeia que o destravou.

O E.3.2 (vencedor × perdedoras com sócio em comum) existia, era testado e devolvia zero. A causa
nunca foi o motor: eram **114 certames** com classificado além do 1º lugar em todo o acervo (0,66% de
17.242). Cada degrau da cadeia foi medido:

    coleta TCE-RJ (nunca havia rodado) ......... 15.436 certames · 82.941 perdedores
    resolução nome → CNPJ, catálogo NACIONAL ...  60,3%  (era 13,9% no catálogo local)
    vencedor E perdedora resolvidos .............  5.220 certames
    com QSA nos dois lados ......................  4.074 certames  ← universo do cruzamento
    pares com sócio em comum ....................     42, em 31 certames (0,76%)

**0,76% é a marca de um sinal que discrimina.** O que este teste protege são as três ressalvas, sem
as quais o número engana — e a principal veio de olhar um certame de verdade: em pregão multi-item a
MESMA empresa é vencedora de um item e perdedora de outro.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_qsa_certame_municipal.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.qsa_certame_municipal import (
    RESSALVAS,
    cobertura_cruzamento,
    cruzar_certames,
)

_DDL = """
CREATE TABLE tcerj_licitante (
  ente TEXT, ano INTEGER, mes INTEGER, processo TEXT, participante TEXT, resultado TEXT,
  tipo_participacao TEXT, data_homologacao TEXT, modalidade TEXT, objeto TEXT,
  qtd_participantes INTEGER, valor_homologacao REAL, valor_estimado REAL, tipologia TEXT,
  coletado_em TEXT);
CREATE TABLE nome_cnpj_resolvido (
  nome_norm TEXT PRIMARY KEY, nome_original TEXT, cnpj_basico TEXT, razao_social TEXT,
  n_candidatos INTEGER, origem TEXT, resolvido_em TEXT);
CREATE TABLE socios_receita (
  cnpj_basico TEXT, ident TEXT, nome_socio TEXT, nome_norm TEXT, doc_socio TEXT,
  qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT, faixa_etaria TEXT,
  fonte_mes TEXT);
"""


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    yield c
    c.close()


def _lic(con, ente, proc, participante, resultado, ano=2025):
    con.execute("INSERT INTO tcerj_licitante VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ente, ano, 5, proc, participante, resultado, "COMUM", "2025-05-01",
                 "PREGÃO", "objeto", 3, 1.0, 2.0, "t", "hoje"))
    con.commit()


def _resolver(con, nome_norm, raiz):
    con.execute("INSERT OR REPLACE INTO nome_cnpj_resolvido VALUES (?,?,?,?,?,?,?)",
                (nome_norm, nome_norm, raiz, nome_norm, 1, "teste", "hoje"))
    con.commit()


def _socio(con, raiz, nome, doc):
    con.execute("INSERT INTO socios_receita VALUES (?,'2',?,?,?,'49','Sócio-Adm','20200101','5','2026-07')",
                (raiz, nome, nome.upper(), doc))
    con.commit()


def test_socio_em_comum_entre_vencedor_e_perdedora_e_achado(con):
    _lic(con, "ANGRA", "1/2025", "ALFA COMERCIO LTDA", "VENCEDOR")
    _lic(con, "ANGRA", "1/2025", "BETA COMERCIO LTDA", "PERDEDOR")
    _resolver(con, "ALFA COMERCIO", "11111111")
    _resolver(con, "BETA COMERCIO", "22222222")
    _socio(con, "11111111", "VANIA VIDAL", "***609007**")
    _socio(con, "22222222", "VANIA VIDAL", "***609007**")

    r = cruzar_certames(con)
    assert r["ok"] and r["n_pares"] == 1
    a = r["achados"][0]
    assert a["socios_em_comum"] == ["VANIA VIDAL"]
    assert a["veredito"] == "indicio_a_confirmar_no_item", (
        "veredito fechado num certame multi-item seria falso"
    )
    assert a["tipo_aresta"] == "mesmo_socio_doc_parcial", (
        "o documento é a MÁSCARA da Receita — a aresta não pode valer como documento pleno"
    )
    assert a["explicacao_inocente"]


def test_multi_item_a_mesma_empresa_nos_dois_lados_nao_e_par(con):
    """Foi o que o dado real mostrou: num certame de 45 participantes, ALFA vence um item e perde
    outro. Parear a empresa consigo mesma seria fabricar concorrência fictícia."""
    _lic(con, "ANGRA", "2/2025", "ALFA COMERCIO LTDA", "VENCEDOR")
    _lic(con, "ANGRA", "2/2025", "ALFA COMERCIO LTDA", "PERDEDOR")
    _resolver(con, "ALFA COMERCIO", "11111111")
    _socio(con, "11111111", "VANIA VIDAL", "***609007**")

    r = cruzar_certames(con)
    assert r["n_pares"] == 0


def test_sem_socio_em_comum_nao_inventa(con):
    _lic(con, "ANGRA", "3/2025", "ALFA COMERCIO LTDA", "VENCEDOR")
    _lic(con, "ANGRA", "3/2025", "BETA COMERCIO LTDA", "PERDEDOR")
    _resolver(con, "ALFA COMERCIO", "11111111")
    _resolver(con, "BETA COMERCIO", "22222222")
    _socio(con, "11111111", "PESSOA A", "***111111**")
    _socio(con, "22222222", "PESSOA B", "***222222**")

    r = cruzar_certames(con)
    assert r["n_pares"] == 0
    assert r["cobertura"]["cruzaveis_com_qsa_dos_dois_lados"] == 1, (
        "o certame FOI cruzado e nada foi achado — isso é diferente de não ter sido cruzado"
    )


def test_certame_sem_qsa_nao_conta_como_limpo(con):
    """A distinção que a casa mais erra: não cruzado ≠ cruzado e limpo."""
    _lic(con, "ANGRA", "4/2025", "ALFA COMERCIO LTDA", "VENCEDOR")
    _lic(con, "ANGRA", "4/2025", "BETA COMERCIO LTDA", "PERDEDOR")
    _resolver(con, "ALFA COMERCIO", "11111111")
    _resolver(con, "BETA COMERCIO", "22222222")
    # nenhum QSA cadastrado
    r = cruzar_certames(con)
    cob = r["cobertura"]
    assert cob["com_vencedor_e_perdedora_resolvidos"] == 1
    assert cob["cruzaveis_com_qsa_dos_dois_lados"] == 0
    assert "INDISPONÍVEL, não ausência" in cob["nota"]


def test_sem_resolucao_o_modulo_se_declara_incapaz(con):
    _lic(con, "ANGRA", "5/2025", "ALFA COMERCIO LTDA", "VENCEDOR")
    r = cruzar_certames(con)
    assert r["ok"] is False and "resolver_nome_cnpj" in r["motivo"]


def test_as_tres_ressalvas_viajam_com_o_achado(con):
    _lic(con, "ANGRA", "6/2025", "ALFA COMERCIO LTDA", "VENCEDOR")
    _lic(con, "ANGRA", "6/2025", "BETA COMERCIO LTDA", "PERDEDOR")
    _resolver(con, "ALFA COMERCIO", "11111111")
    _resolver(con, "BETA COMERCIO", "22222222")
    _socio(con, "11111111", "VANIA VIDAL", "***609007**")
    _socio(con, "22222222", "VANIA VIDAL", "***609007**")

    r = cruzar_certames(con)
    assert r["ressalvas"] == list(RESSALVAS)
    texto = " ".join(RESSALVAS)
    assert "multi-item" in texto
    assert "4%" in texto, "a colisão da máscara tem de estar declarada"
    assert "não é ilícito" in texto, "sócio comum entre concorrentes é lícito em muitos arranjos"


def test_cobertura_traz_o_antes(con):
    c = cobertura_cruzamento(con)
    assert "114 certames" in c["antes"], "o ponto de partida tem de ficar registrado"
