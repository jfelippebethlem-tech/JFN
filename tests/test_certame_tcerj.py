# -*- coding: utf-8 -*-
"""Ponte TCE-RJ → detector de julgamento, e os DOIS artefatos que o dado real pegou.

A coleta é ganho real: de **0** para 13.021 certames municipais com 34.659 perdedores nominados (o
coletor existia, era testado com `buscar` injetado e nunca havia rodado contra a API). O que este
teste protege é a leitura, porque nela houve dois erros meus, os dois de ler ausência como fato:

  1. **Nominação parcial lida como afunilamento.** A primeira versão entregava
     `licitantes_classificados` sempre, e o J4 confirmou "forte" em Teresópolis 2244/2025 com
     "129 inscritos ⇒ 1 classificado". Os nominados eram UM — o vencedor. Os outros 128 não foram
     desclassificados: não foram nominados.
  2. **`PERDEDOR` lido como INABILITADO.** A API não distingue quem foi inabilitado de quem perdeu no
     preço. O J4 mede seletividade na habilitação, não resultado de disputa — mapear um no outro
     faria toda licitação competitiva normal (71 licitantes, 1 vencedor) parecer afunilamento.

Conclusão medida: esta fonte **não** alimenta o funil do J4 nem o cruzamento de QSA do E.3.2 (que
exige CNPJ, e a API traz só o nome). O que ela sustenta é `licitantes_inscritos` declarado — e com
ele o licitante único, que a casa não podia apurar.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_certame_tcerj.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.editais.certame_tcerj import (
    LIMITE_SEM_CNPJ,
    certames_disponiveis,
    cobertura_tcerj,
    contexto_j4,
)

_DDL = """
CREATE TABLE tcerj_licitante (
  ente TEXT, ano INTEGER, mes INTEGER, processo TEXT, participante TEXT, resultado TEXT,
  tipo_participacao TEXT, data_homologacao TEXT, modalidade TEXT, objeto TEXT,
  qtd_participantes INTEGER, valor_homologacao REAL, valor_estimado REAL, tipologia TEXT,
  coletado_em TEXT);
"""


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    yield c
    c.close()


def _ins(con, ente, processo, participante, resultado, qtd, ano=2025):
    con.execute("INSERT INTO tcerj_licitante VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ente, ano, 5, processo, participante, resultado, "COMUM", "2025-05-28",
                 "PREGÃO ELETRÔNICO", "objeto", qtd, 1000.0, 1200.0, "tip", "hoje"))
    con.commit()


def test_nominacao_parcial_nao_e_afunilamento(con):
    """O caso Teresópolis: 129 declarados, 1 nominado. O funil é INOBSERVÁVEL."""
    _ins(con, "TERESOPOLIS", "2244/2025", "VENCEDORA LTDA", "VENCEDOR", 129)
    ctx = contexto_j4(con, "TERESOPOLIS", 2025, "2244/2025")
    cob = ctx["cobertura"]
    assert cob["inscritos_declarados_pela_fonte"] == 129
    assert cob["licitantes_nominados"] == 1
    assert cob["nao_nominados"] == 128
    assert cob["funil_observavel"] is False
    assert "não têm nome publicado" in ctx["motivo_funil_nao_observavel"]


def test_o_funil_nunca_e_alimentado_por_esta_fonte(con):
    """Mesmo com todos nominados: `PERDEDOR` não é `INABILITADO`. Sem o campo, o J4 degrada para
    `nao_avaliavel`, que é o comportamento correto — e não para um achado forte."""
    _ins(con, "NITEROI", "1/2025", "A LTDA", "VENCEDOR", 3)
    _ins(con, "NITEROI", "1/2025", "B LTDA", "PERDEDOR", 3)
    _ins(con, "NITEROI", "1/2025", "C LTDA", "PERDEDOR", 3)
    ctx = contexto_j4(con, "NITEROI", 2025, "1/2025")
    assert ctx["cobertura"]["funil_observavel"] is True, "os três estão nominados"
    assert "licitantes_classificados" not in ctx, (
        "o funil não pode ser alimentado: a fonte não separa inabilitação de derrota no preço"
    )
    assert "seletividade na habilitação" in ctx["funil_nao_alimentado"]


def test_j4_degrada_para_nao_avaliavel(con):
    """A prova de ponta: sem o funil, o detector se declara incapaz em vez de inventar."""
    from compliance_agent.detectores import REGISTRO

    _ins(con, "NITEROI", "1/2025", "A LTDA", "VENCEDOR", 71)
    for i in range(70):
        _ins(con, "NITEROI", "1/2025", f"P{i} LTDA", "PERDEDOR", 71)
    ctx = contexto_j4(con, "NITEROI", 2025, "1/2025")
    r = REGISTRO["J4"].avaliar({"processo": ctx["processo"], **ctx})
    assert r.status == "nao_avaliavel", (
        f"J4 concluiu {r.status} sobre uma licitação competitiva NORMAL (71 licitantes, 1 vencedor)"
    )


def test_licitante_unico_e_declarado_pela_fonte(con):
    """O que a fonte SUSTENTA: `QuantidadeParticipante = 1`. 'Um fornecedor no resultado do PNCP'
    nunca provou isso — podia ser adjudicação múltipla ou falta de captura."""
    _ins(con, "PORCIUNCULA", "595/24", "UNICA LTDA", "VENCEDOR", 1)
    ctx = contexto_j4(con, "PORCIUNCULA", 2025, "595/24")
    assert ctx["licitante_unico_declarado"] is True
    assert ctx["licitantes_inscritos"] == 1

    _ins(con, "PORCIUNCULA", "596/24", "A LTDA", "VENCEDOR", 4)
    ctx2 = contexto_j4(con, "PORCIUNCULA", 2025, "596/24")
    assert ctx2["licitante_unico_declarado"] is False


def test_o_limite_de_cnpj_viaja_com_o_resultado(con):
    """Sem CNPJ não há QSA, e sem QSA não há E.3.2. O limite tem de estar na saída, não na memória
    de quem escreveu o módulo."""
    _ins(con, "NITEROI", "1/2025", "A LTDA", "VENCEDOR", 2)
    ctx = contexto_j4(con, "NITEROI", 2025, "1/2025")
    assert ctx["limite"] == LIMITE_SEM_CNPJ
    assert "resolução de entidade" in LIMITE_SEM_CNPJ


def test_certame_ausente_diz_o_motivo(con):
    ctx = contexto_j4(con, "NAO_EXISTE", 2025, "0/0")
    assert "sem licitante na base" in ctx["motivo"]


def test_listagem_e_cobertura(con):
    _ins(con, "NITEROI", "1/2025", "A LTDA", "VENCEDOR", 5)
    _ins(con, "NITEROI", "1/2025", "B LTDA", "PERDEDOR", 5)
    _ins(con, "MARICA", "2/2025", "C LTDA", "VENCEDOR", 1)

    lista = certames_disponiveis(con, limite=10)
    assert len(lista) == 2
    assert lista[0]["inscritos"] == 5, "ordenado do mais disputado ao menos"

    so_um = certames_disponiveis(con, min_participantes=5, limite=10)
    assert len(so_um) == 1

    c = cobertura_tcerj(con)
    assert c["ok"] and c["certames"] == 2 and c["perdedores_nominados"] == 1
    assert c["licitante_unico_apuravel"] == 1
    assert "0,66%" in c["antes"], "o antes/depois tem de ficar registrado"
