# -*- coding: utf-8 -*-
"""D9 (sócio de credor na folha PCRJ) passa pela régua única de identidade (`identidade_pessoa`).

Medido em 20/11/2026: 189 de 506 vereditos da triagem do Opus = provável falso positivo, quase todos
"match só por nome, sem CPF" — o casamento sócio×folha era só pelo nome normalizado. Aqui:
  - CPF mascarado do QSA × CPF da folha INCOMPATÍVEIS → homônimo, não alerta (controle negativo);
  - janelas COMPATÍVEIS → alerta mais forte, `match_tipo` CPF (controle positivo);
  - folha sem CPF (a da Prefeitura do Rio: contracheque não publica CPF) → alerta como antes,
    declarando que é só o nome e qual dado falta;
  - sócio de 0 a 12 anos (Receita) × servidor ATIVO → homônimo; × aposentado/pensionista → mantém.
CPFs são SINTÉTICOS e mascarados (LGPD).
"""
from __future__ import annotations

import sqlite3

import pytest

import compliance_agent.pcrj.pericia_gastos as P

NOME = "maria da silva souza"


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
      create table pcrj_despesa (exercicio integer, credor_documento text, credor_nome text, pago real);
      create table socios_receita (cnpj_basico text, nome_norm text, nome_socio text, data_entrada text,
                                   doc_socio text, faixa_etaria text);
      insert into pcrj_despesa values (2021, '11111111000111', 'ALFA LTDA', 100000.0);
    """)
    return c


def _socio(con, doc="***123456**", faixa="5"):
    con.execute("insert into socios_receita values ('11111111',?,?,'20190301',?,?)",
                (NOME, NOME.upper(), doc, faixa))
    con.commit()


def _folha(cpf="", fonte="pcrj_folha_pref", tipo_folha="NORMAL", n_pessoas=1):
    return {NOME: {"orgao": "SMS", "cpf": cpf, "fonte": fonte, "tipo_folha": tipo_folha,
                   "n_pessoas": n_pessoas}}


def test_cpf_incompativel_e_homonimo_nao_alerta(con):
    """O caso dos FP: mesmo nome, dígitos do CPF diferentes nas duas bases (QSA 4–9 × folha 4–9)."""
    _socio(con, doc="***123456**")
    assert P.d9_socio_na_folha(con, folha_norm=_folha(cpf="XX999999XXX", fonte="gesperj_estado")) == []


def test_cpf_compativel_continua_alertando_mais_forte(con):
    """Controle positivo: janelas compatíveis → identidade conferida, alerta mais forte que o só-nome."""
    _socio(con, doc="***123456**")
    a = P.d9_socio_na_folha(con, folha_norm=_folha(cpf="XX123456XXX", fonte="gesperj_estado"))
    assert len(a) == 1
    ev = a[0]["evidencias"]
    assert ev["identidade"] in ("VERIFICADO", "PROVAVEL") and ev["match_tipo"] == "CPF"
    assert a[0]["risco"] > 5
    assert "123456" not in a[0]["descricao"]          # nunca expõe dígito além da máscara do QSA


def test_folha_pcrj_sem_cpf_segue_indicio_so_nome(con):
    """A folha da Prefeitura não publica CPF: INDETERMINADO, alerta como antes e diz o que falta."""
    _socio(con)
    a = P.d9_socio_na_folha(con, folha_norm=_folha())
    assert len(a) == 1
    ev = a[0]["evidencias"]
    assert ev["identidade"] == "INDETERMINADO" and ev["match_tipo"] == "NOME"
    assert a[0]["risco"] == 5
    assert "não publica CPF" in a[0]["descricao"] and "homônim" in a[0]["descricao"].lower()


def test_socio_crianca_x_servidor_ativo_e_homonimo(con):
    _socio(con, faixa="1")
    assert P.d9_socio_na_folha(con, folha_norm=_folha(tipo_folha="NORMAL")) == []


def test_socio_crianca_x_pensionista_nao_descarta(con):
    """PREVNORMAL (FUNPREVI) = aposentado/pensionista: criança pode ser pensionista — não descarta."""
    _socio(con, faixa="1")
    a = P.d9_socio_na_folha(con, folha_norm=_folha(tipo_folha="PREVNORMAL"))
    assert len(a) == 1 and a[0]["evidencias"]["identidade"] == "INDETERMINADO"


def test_credor_sem_pagamento_nao_acusa(con):
    """21 dos 189 FP da triagem: o credor recebeu R$ 0,00 da PCRJ — sem dinheiro, sem conflito na despesa."""
    con.execute("update pcrj_despesa set pago=0")
    _socio(con)
    a = P.d9_socio_na_folha(con, folha_norm=_folha())
    assert len(a) == 1 and a[0]["risco"] == 3
    assert a[0]["descricao"].startswith("NÃO é acusação")
