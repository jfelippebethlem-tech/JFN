# -*- coding: utf-8 -*-
"""A ponte compra → contrato → aditivo, que a documentação dava por inexistente.

`indice_certame.py:19-23` declara que "não há tabela-ponte compra→contrato → 0 casamentos", e por
isso a família EXECUÇÃO do índice sai INDISPONÍVEL por construção. A observação sobre as chaves
está certa — `-1-` é compra, `-2-` é contrato, e o join direto realmente dá zero. A conclusão é
que não se sustentava: `pcrj_contratos.numero_compra` guarda a chave da compra em 92% dos
contratos.

O que estes testes travam é o uso HONESTO dela: a ponte cobre 11,9% dos certames, e usá-la como
se fosse total produziria "nenhum contrato com aditivo excessivo" para 88% dos casos em que
simplesmente não se sabe. Por isso toda função devolve cobertura, e `elo_faltante` diz ONDE a
cadeia parou — que é o que separa "contrato regular" de "contrato não observado".
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.ponte_compra_contrato import (
    cadeia,
    certame_do_contrato,
    cobertura,
    contexto_execucao_do_certame,
    contratos_do_certame,
)

_COMPRA = "28305936000140-1-000273/2024"
_CONTRATO = "28305936000140-2-000008/2025"


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE pcrj_contratos (
            numero_controle_pncp TEXT, ano INT, orgao_cnpj TEXT, orgao_nome TEXT, unidade TEXT,
            fornecedor_documento TEXT, fornecedor_nome TEXT, tipo TEXT, objeto TEXT,
            valor_inicial REAL, valor_global REAL, data_assinatura TEXT, vigencia_ini TEXT,
            vigencia_fim TEXT, num_aditivos INT, numero_compra TEXT);
        CREATE TABLE contrato_aditivo (
            id INTEGER PRIMARY KEY, numero_controle_pncp TEXT, sequencial_termo INT,
            numero_termo TEXT, objeto TEXT, valor_acrescido REAL, valor_global REAL,
            prazo_aditado_dias INT, vigencia_fim TEXT, qualif_acrescimo TEXT,
            qualif_vigencia TEXT, qualif_reajuste TEXT, fundamento_legal TEXT);
        CREATE TABLE pncp_resultado (certame TEXT, valor_homologado REAL);
    """)
    return c


def _contrato(con, controle=_CONTRATO, compra=_COMPRA, *, valor=720000.0, num_aditivos=0):
    con.execute("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (controle, 2025, "283", "Órgão", "U", "111", "Alfa", "Contrato", "objeto",
                 valor, valor, "2025-01-01", "2025-01-10", "2026-01-09", num_aditivos, compra))
    con.execute("INSERT INTO pncp_resultado VALUES (?,?)", (compra, valor))
    con.commit()


def _aditivo(con, controle=_CONTRATO, **kw):
    d = {"id": None, "numero_controle_pncp": controle, "sequencial_termo": 1, "numero_termo": "1",
         "objeto": "acréscimo quantitativo", "valor_acrescido": 100000.0, "valor_global": 820000.0,
         "prazo_aditado_dias": 0, "vigencia_fim": "", "qualif_acrescimo": "1",
         "qualif_vigencia": "0", "qualif_reajuste": "0", "fundamento_legal": ""}
    d.update(kw)
    con.execute(f"INSERT INTO contrato_aditivo VALUES ({','.join('?' * len(d))})",
                tuple(d.values()))
    con.commit()


# ───────────────────────── a ponte existe ─────────────────────────────────────────────────────

def test_certame_encontra_o_contrato(con):
    _contrato(con)
    r = contratos_do_certame(con, _COMPRA)
    assert len(r) == 1 and r[0]["numero_controle_pncp"] == _CONTRATO


def test_contrato_encontra_o_certame(con):
    _contrato(con)
    assert certame_do_contrato(con, _CONTRATO) == _COMPRA


def test_cadeia_completa(con):
    _contrato(con, num_aditivos=1)
    _aditivo(con)
    r = cadeia(con, _COMPRA)
    assert r["n_contratos"] == 1 and r["n_aditivos"] == 1
    assert r["completa"] is True and r["elo_faltante"] is None


# ───────────────────────── onde a cadeia PAROU ────────────────────────────────────────────────

def test_certame_sem_contrato_diz_que_e_LACUNA_nao_ausencia(con):
    """A diferença entre 'contrato regular' e 'contrato não observado'."""
    r = cadeia(con, "certame-inexistente")
    assert r["elo_faltante"] == "contrato" and r["completa"] is False
    assert "lacuna de captura" in r["motivo"]


def test_contrato_que_DECLARA_aditivo_sem_termo_coletado_e_lacuna(con):
    """`num_aditivos=3` e zero termos: o dado diz que existem, e não foram capturados."""
    _contrato(con, num_aditivos=3)
    r = cadeia(con, _COMPRA)
    assert r["elo_faltante"] == "aditivo" and r["completa"] is False
    assert "lacuna de CAPTURA" in r["motivo"]


def test_contrato_sem_aditivo_declarado_fecha_a_cadeia(con):
    """Zero declarados e zero coletados é coerente — não é lacuna."""
    _contrato(con, num_aditivos=0)
    r = cadeia(con, _COMPRA)
    assert r["completa"] is True and r["elo_faltante"] is None


# ───────────────────────── vários contratos por certame ───────────────────────────────────────

def test_certame_com_varios_contratos_escolhe_o_MAIOR_e_declara(con):
    """Escolher o primeiro em silêncio faria o índice refletir um contrato arbitrário."""
    _contrato(con, controle="c-pequeno", valor=10_000.0)
    _contrato(con, controle="c-grande", valor=900_000.0)
    ctx = contexto_execucao_do_certame(con, _COMPRA)
    assert ctx["encontrado"] is True
    assert ctx["contrato"] == "c-grande"
    assert ctx["n_contratos_do_certame"] == 2 and ctx["contratos_nao_considerados"] == 1
    assert "NÃO entraram na análise" in ctx["ressalva"]


def test_contexto_de_certame_sem_contrato_e_honesto(con):
    ctx = contexto_execucao_do_certame(con, "nao-existe")
    assert ctx["encontrado"] is False and "lacuna de captura" in ctx["motivo"]


def test_contexto_alimenta_os_detectores_de_execucao(con):
    """Fecha o círculo: a saída tem de ser o que X1/X2/X7/X9 consomem."""
    from compliance_agent.detectores import REGISTRO

    _contrato(con, num_aditivos=1, valor=1_000_000.0)
    _aditivo(con, valor_acrescido=400_000.0)
    ctx = contexto_execucao_do_certame(con, _COMPRA)
    r = REGISTRO["X1"].avaliar(dict(ctx))
    assert r.status in {"confirmado", "descartado"}, r.motivo_refutacao


# ───────────────────────── cobertura declarada ────────────────────────────────────────────────

def test_cobertura_traz_os_numeros_que_acompanham_a_conclusao(con):
    _contrato(con, num_aditivos=1)
    _aditivo(con)
    c = cobertura(con)
    assert c["contratos"] == 1 and c["contratos_com_chave_de_compra"] == 1
    assert c["certames_com_contrato"] == 1 and c["cadeia_completa_com_aditivo"] == 1
    assert "chaves de entidades" in c["nota"]


def test_cobertura_explica_por_que_o_join_direto_da_zero(con):
    assert "'-1-' compra × '-2-' contrato" in cobertura(con)["nota"]


def test_base_sem_as_tabelas_nao_quebra():
    vazio = sqlite3.connect(":memory:")
    vazio.row_factory = sqlite3.Row
    assert contratos_do_certame(vazio, "x") == []
    assert certame_do_contrato(vazio, "x") is None
    assert cobertura(vazio)["contratos"] == 0
