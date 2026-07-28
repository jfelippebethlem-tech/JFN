# -*- coding: utf-8 -*-
"""Varredura órgão a órgão — a camada determinística da fiscalização contínua.

Dois invariantes de arquitetura que os testes trancam, os dois nascidos de erro real:

1. **Nunca escreve na base de produção.** A primeira versão gravava lá e levou
   `database is locked` no primeiro teste — o servidor e os crons escrevem o tempo todo. Agora
   lê só-leitura e grava em banco próprio, o que também é o que permite rodar na VM-2.
2. **Registra a COBERTURA, não só os achados.** Uma UG sem achado pode ser uma UG sem dado, e
   confundir as duas coisas é o pior erro possível numa ferramenta de fiscalização.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import varredura_orgaos as V

_SIAFE_DDL = """
CREATE TABLE ob_orcamentaria_siafe (
    numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, credor TEXT, nome_credor TEXT,
    processo TEXT, re TEXT, valor REAL, exercicio INTEGER, status TEXT
);
CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT,
    socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT, cpf_resolvido TEXT);
CREATE TABLE doacoes_eleitorais (id INTEGER, cpf_cnpj_doador TEXT, nome_doador TEXT,
    nome_candidato TEXT, cargo_candidato TEXT, partido TEXT, uf TEXT, valor REAL);
"""


@pytest.fixture()
def base(tmp_path):
    """Base sintética com o mesmo schema da produção (subconjunto usado pela varredura)."""
    caminho = tmp_path / "compliance.db"
    con = sqlite3.connect(caminho)
    con.executescript(_SIAFE_DDL)
    for i in range(4):
        con.execute(
            "INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"2026OB{i:05d}", "133100", "10/03/2026", "11222333000144", "ACME LTDA",
             f"2026-0600{i}", f"2026NE{i}", 50000.0, 2026, "PAGO"))
    con.execute(
        "INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("2026OB99999", "999999", "10/03/2026", "44555666000177", "OUTRA LTDA",
         "2026-06099", "2026NE9", 10.0, 2026, "PAGO"))
    con.commit()
    con.close()
    return caminho


@pytest.fixture()
def leitura(base):
    return V.abrir_leitura(str(base))


@pytest.fixture()
def achados(tmp_path):
    return V.abrir_achados(str(tmp_path / "achados.db"))


# ───────────────────────────── separação de bancos ────────────────────────────────────────────

def test_conexao_de_leitura_e_somente_leitura(leitura):
    """Garante que a varredura não consegue escrever na produção nem por engano."""
    with pytest.raises(sqlite3.OperationalError):
        leitura.execute("CREATE TABLE nao_deveria (x INT)")


def test_banco_de_achados_e_separado_e_tem_o_schema(achados, tmp_path):
    tabelas = {r[0] for r in achados.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"achado_detector", "varredura_cobertura"} <= tabelas
    assert (tmp_path / "achados.db").exists()


def test_varredura_sem_conexao_de_achados_nao_grava_nada(leitura, base):
    """`con_achados=None` roda em memória — útil para inspecionar antes de materializar."""
    r = V.varrer_ug(leitura, "133100", exercicio=2026, max_fornecedores=1)
    assert r["ug"] == "133100"
    con = sqlite3.connect(base)
    tabelas = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "achado_detector" not in tabelas, "não pode criar tabela na base de produção"


# ───────────────────────────── seleção de UGs e fornecedores ──────────────────────────────────

def test_ugs_vem_ordenadas_por_volume_pago(leitura):
    """A fila sai do dinheiro, não do alfabeto: a UG que mais pagou é a primeira a ser olhada."""
    assert V.ugs_com_pagamento(leitura, exercicio=2026)[0] == "133100"


def test_exercicio_filtra(leitura):
    assert V.ugs_com_pagamento(leitura, exercicio=2020) == []


def test_min_obs_filtra_ug_com_pouco_movimento(leitura):
    assert "999999" not in V.ugs_com_pagamento(leitura, exercicio=2026, min_obs=2)


def test_so_cnpj_de_quatorze_digitos_e_fornecedor(base):
    """Código de fundo e de UG aparecem no campo `credor` e NÃO são fornecedor."""
    con = sqlite3.connect(base)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("2026OB88888", "133100", "10/03/2026", "CG0004700", "FUNDO X",
                 "2026-06088", "2026NE8", 90000.0, 2026, "PAGO"))
    con.commit()
    con.close()
    ro = V.abrir_leitura(str(base))
    assert V.fornecedores_da_ug(ro, "133100", exercicio=2026) == ["11222333000144"]


# ───────────────────────────── contexto do fornecedor ─────────────────────────────────────────

def test_contexto_vazio_quando_a_base_nao_tem_nada(leitura):
    """Campo que a base não tem fica AUSENTE — o detector responde nao_avaliavel, não score 0."""
    ctx = V.contexto_fornecedor(leitura, "11222333000144", "133100")
    assert "qsa" not in ctx
    assert "doacoes" not in ctx
    assert ctx["valor_contratado"] == pytest.approx(200000.0)


def test_contexto_traz_qsa_quando_existe(base):
    con = sqlite3.connect(base)
    con.execute("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?,?)",
                ("11222333000144", "ACME LTDA", "Fulano de Tal", "fulano de tal",
                 "12345678900", "sócio", "2026-01-01", "12345678900"))
    con.commit()
    con.close()
    ctx = V.contexto_fornecedor(V.abrir_leitura(str(base)), "11222333000144", "133100")
    assert ctx["qsa"] == [{"nome": "Fulano de Tal", "cpf": "12345678900"}]


def test_contexto_cruza_doacao_por_cpf_do_socio(base):
    con = sqlite3.connect(base)
    con.execute("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?,?)",
                ("11222333000144", "ACME LTDA", "Fulano de Tal", "fulano de tal",
                 "12345678900", "sócio", "2026-01-01", "12345678900"))
    con.execute("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?,?,?,?,?)",
                (1, "12345678900", "Fulano de Tal", "Candidato X", "Deputado Estadual",
                 "PXX", "RJ", 5000.0))
    con.commit()
    con.close()
    ctx = V.contexto_fornecedor(V.abrir_leitura(str(base)), "11222333000144", "133100")
    assert len(ctx["doacoes"]) == 1
    assert ctx["doacoes"][0]["beneficiario"] == "Candidato X"


def test_contexto_cruza_doacao_por_nome_quando_nao_ha_cpf(base):
    """Metade do QSA vem sem CPF resolvido — sem o cruzamento por nome o C6 nunca avaliaria."""
    con = sqlite3.connect(base)
    con.execute("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?,?)",
                ("11222333000144", "ACME LTDA", "Fulano de Tal", "fulano de tal",
                 None, "sócio", "2026-01-01", None))
    con.execute("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?,?,?,?,?)",
                (1, "00000000000", "FULANO DE TAL", "Candidato X", "Prefeito",
                 "PXX", "RJ", 3000.0))
    con.commit()
    con.close()
    ctx = V.contexto_fornecedor(V.abrir_leitura(str(base)), "11222333000144", "133100")
    assert len(ctx["doacoes"]) == 1


def test_tabela_ausente_nao_quebra_o_contexto(tmp_path):
    """Base sem `socios_fornecedor` (instalação nova) tem de degradar, não estourar."""
    caminho = tmp_path / "min.db"
    con = sqlite3.connect(caminho)
    con.executescript("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, ug_emitente TEXT, "
                      "valor REAL, exercicio INTEGER);")
    con.commit()
    con.close()
    ctx = V.contexto_fornecedor(V.abrir_leitura(str(caminho)), "11222333000144", "133100")
    assert ctx.get("qsa") is None


# ───────────────────────────── cobertura ──────────────────────────────────────────────────────

def test_resumo_declara_a_cobertura_e_nao_so_os_achados(leitura, achados):
    """O invariante que evita a leitura errada: 'sem achado' ≠ 'limpo'."""
    r = V.varrer_ug(leitura, "133100", exercicio=2026, max_fornecedores=1, con_achados=achados)
    for campo in ("n_detectores", "n_avaliaveis", "n_confirmados", "n_nao_avaliaveis"):
        assert campo in r
    assert r["n_detectores"] == r["n_avaliaveis"] + r["n_nao_avaliaveis"]


def test_cobertura_e_persistida(leitura, achados):
    V.varrer_ug(leitura, "133100", exercicio=2026, max_fornecedores=1, con_achados=achados)
    linha = achados.execute(
        "SELECT n_detectores, n_avaliaveis FROM varredura_cobertura WHERE ug='133100'").fetchone()
    assert linha is not None and linha[0] > 0


def test_persistencia_e_idempotente(leitura, achados):
    """Rodar duas vezes não duplica — INSERT OR REPLACE por (ug, detector, processo)."""
    V.varrer_ug(leitura, "133100", exercicio=2026, max_fornecedores=1, con_achados=achados)
    n1 = achados.execute("SELECT COUNT(*) FROM achado_detector").fetchone()[0]
    V.varrer_ug(leitura, "133100", exercicio=2026, max_fornecedores=1, con_achados=achados)
    n2 = achados.execute("SELECT COUNT(*) FROM achado_detector").fetchone()[0]
    assert n1 == n2


def test_grava_tambem_o_que_NAO_virou_achado(leitura, achados):
    """`descartado` e `nao_avaliavel` também são registrados: sem eles não se mede cobertura,
    e um 'nao_avaliavel' silencioso é indistinguível de detector que nunca rodou."""
    V.varrer_ug(leitura, "133100", exercicio=2026, max_fornecedores=1, con_achados=achados)
    status = {r[0] for r in achados.execute("SELECT DISTINCT status FROM achado_detector")}
    assert status - {"confirmado"}, "tem de registrar descartado/nao_avaliavel também"
