"""Lentes de detecção sobre a despesa da Prefeitura do Rio.

Cenários em banco temporário — nada depende do acervo real, que muda. Os testes que tocam
o acervo estão marcados e fazem `skip` se ele não existir.
"""
import sqlite3

import pytest

from compliance_agent.pcrj import universo
from tools import lentes_pcrj as L

DDL_DESPESA = """
CREATE TABLE pcrj_despesa (id INTEGER, exercicio INT, orgao TEXT, unidade TEXT,
  credor_documento TEXT, credor_nome TEXT, natureza TEXT, fonte_recurso TEXT,
  empenhado REAL, liquidado REAL, pago REAL, arquivo_origem TEXT, coletado_em TEXT)"""
DDL_CADASTRO = """
CREATE TABLE empresas_cadastro (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT,
  capital_social REAL, porte_cod TEXT, porte_txt TEXT, fonte_mes TEXT)"""
DDL_SANCOES = """
CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT,
  data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT)"""
DDL_EMPRESAS = """
CREATE TABLE empresas (id INTEGER, cnpj TEXT, razao_social TEXT, nome_fantasia TEXT,
  situacao TEXT, data_abertura TEXT, porte TEXT, natureza_jur TEXT, atividade_princ TEXT,
  cep TEXT, municipio TEXT, uf TEXT, capital_social REAL, raw_json TEXT, updated_at TEXT)"""


@pytest.fixture()
def banco(tmp_path):
    def _criar(despesas=(), cadastro=(), sancoes=(), empresas=()):
        p = tmp_path / "t.db"
        con = sqlite3.connect(p)
        for ddl in (DDL_DESPESA, DDL_CADASTRO, DDL_SANCOES, DDL_EMPRESAS):
            con.execute(ddl)
        con.executemany("INSERT INTO pcrj_despesa (exercicio,orgao,credor_documento,credor_nome,"
                        "natureza,empenhado,liquidado,pago) VALUES (?,?,?,?,?,?,?,?)", despesas)
        con.executemany("INSERT INTO empresas_cadastro (cnpj_basico,porte_cod,porte_txt) "
                        "VALUES (?,?,?)", cadastro)
        con.executemany("INSERT INTO sancoes_federais (cadastro,cpf_cnpj,categoria,data_inicio,"
                        "data_fim,orgao) VALUES (?,?,?,?,?,?)", sancoes)
        con.executemany("INSERT INTO empresas (cnpj,razao_social,natureza_jur,atividade_princ) "
                        "VALUES (?,?,?,?)", empresas)
        con.commit()
        con.close()
        return str(p)
    return _criar


def _d(ano, orgao, cnpj, nome, natureza, pago, liquidado=None, empenhado=None):
    return (ano, orgao, cnpj, nome, natureza, empenhado if empenhado is not None else pago,
            liquidado if liquidado is not None else pago, pago)


# ── o universo contratual ────────────────────────────────────────────────────────────────────

def test_universo_exclui_pessoal_intra_e_sentenca(banco):
    db = banco(despesas=[
        _d(2022, "SMS", "11111111000191", "FORNECEDOR", "33903901", 100.0),   # entra
        _d(2022, "SMS", "22222222000191", "SERVIDOR", "31901101", 900.0),     # grupo 1: fora
        _d(2022, "SMS", "33333333000191", "INTRA", "33919101", 900.0),        # modalidade 91: fora
        _d(2022, "SMS", "44444444000191", "SENTENCA", "33909101", 900.0),     # elemento 91: fora
        # natureza NNNNNNNN: 1=categoria 2=grupo 3-4=modalidade 5-6=elemento 7-8=subelemento.
        # `33905001` seria modalidade 90 com elemento 50 — o que ENTRA. A transferência é
        # `33503901`: modalidade 50. Errei o cenário na primeira escrita e o teste pegou.
        _d(2022, "SMS", "55555555000191", "TRANSFER", "33503901", 900.0),     # modalidade 50: fora
    ])
    r = universo.resumo(db)
    assert r["contratual"]["pago"] == pytest.approx(100.0)
    assert r["bruto"]["pago"] == pytest.approx(3700.0)  # 100 + 900 x 4


def test_universo_exige_pago_positivo(banco):
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 0.0, liquidado=500.0)])
    assert universo.resumo(db)["contratual"]["linhas"] == 0


# ── L1 · ME/EPP acima do teto ────────────────────────────────────────────────────────────────

def test_me_epp_le_o_porte_com_zero_a_esquerda(banco):
    """Regressão: `porte_cod` vem '01'/'03'; comparar com '1' zerava o universo inteiro."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "MICRO", "33903901", 5_000_000.0)],
               cadastro=[("11111111", "01", "Microempresa")])
    r = L.me_epp_acima_do_teto(db)
    assert r["universo"] == 1, "universo zero indicaria que o porte não foi lido"
    assert r["n"] == 1


def test_corte_forte_usa_o_teto_maximo_do_simples(banco):
    """ME que passou de R$ 360 mil mas não de R$ 4,8 mi é indício AMPLO, não FORTE."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "MICRO", "33903901", 1_000_000.0)],
               cadastro=[("11111111", "01", "Microempresa")])
    r = L.me_epp_acima_do_teto(db)
    assert r["n"] == 0, "abaixo de R$ 4,8 mi não entra no corte forte"
    assert r["corte_amplo"]["n"] == 1, "mas tem de aparecer no corte amplo, não sumir"


def test_teto_e_inclusivo(banco):
    """LC 123 diz 'até': receber exatamente o teto não é estouro."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "EPP", "33903901", L.TETO_EPP_ANUAL)],
               cadastro=[("11111111", "03", "Empresa de Pequeno Porte")])
    assert L.me_epp_acima_do_teto(db)["n"] == 0


def test_porte_demais_nao_tem_teto_a_violar(banco):
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "GRANDE", "33903901", 99_000_000.0)],
               cadastro=[("11111111", "05", "Demais")])
    r = L.me_epp_acima_do_teto(db)
    assert r["universo"] == 0 and r["n"] == 0
    assert r["prevalencia"] is None, "universo vazio devolve INDISPONÍVEL, nunca 0%"


# ── L2 · sanção de efeito amplo ──────────────────────────────────────────────────────────────

def test_so_sancao_de_efeito_amplo_entra(banco):
    db = banco(
        despesas=[_d(2022, "SMS", "11111111000191", "INIDONEA", "33903901", 1000.0),
                  _d(2022, "SMS", "22222222000191", "IMPEDIDA", "33903901", 1000.0),
                  _d(2022, "SMS", "33333333000191", "MULTADA", "33903901", 1000.0)],
        sancoes=[("CEIS", "11111111000191", "Declaração de Inidoneidade sem prazo determinado",
                  "2020-01-01", None, "Gov BA"),
                 ("CEIS", "22222222000191", "Impedimento/proibição de contratar com prazo determinado",
                  "2020-01-01", "2030-01-01", "Pref X"),
                 ("CNEP", "33333333000191", "Multa", "2020-01-01", None, "CGE")])
    r = L.sancao_de_efeito_amplo(db)
    assert [a["nome"] for a in r["achados"]] == ["INIDONEA"]


def test_sancao_encerrada_antes_do_exercicio_nao_conta(banco):
    db = banco(
        despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 1000.0)],
        sancoes=[("CEIS", "11111111000191", "Declaração de Inidoneidade com prazo determinado",
                  "2018-01-01", "2019-12-31", "Gov BA")])
    assert L.sancao_de_efeito_amplo(db)["n"] == 0


def test_documento_mascarado_fica_fora_do_universo_nao_como_sem_sancao(banco):
    """A máscara colide; tratá-la como 'CNPJ sem sanção' seria afirmar o que não se sabe."""
    db = banco(despesas=[_d(2022, "SMS", "***201901**", "ESTRANGEIRA", "33903901", 1000.0)])
    assert L.sancao_de_efeito_amplo(db)["universo"] == 0


# ── L6 · fornecedor quase-exclusivo ──────────────────────────────────────────────────────────

def test_ressalva_estrutural_tira_do_exame_mas_nao_some(banco):
    db = banco(
        despesas=[_d(2021, "Fundo Iluminação", "60444437000146", "LIGHT SERVICOS", "33903901",
                     9_000_000.0),
                  _d(2021, "Fundo Iluminação", "11111111000191", "OUTRO", "33903901", 500_000.0)],
        empresas=[("60444437000146", "LIGHT", "2054", "Distribuição de energia elétrica")])
    r = L.fornecedor_quase_exclusivo(db)
    assert r["n"] == 0, "monopólio natural não é captura de órgão"
    assert len(r["ressalvados"]) == 1
    assert "energia" in r["ressalvados"][0]["ressalva"]


def test_orgao_publico_como_credor_e_ressalvado(banco):
    db = banco(despesas=[_d(2022, "SMF", "28531230000155", "TRIBUNAL DE JUSTICA DO ESTADO",
                            "33903901", 9_000_000.0)])
    r = L.fornecedor_quase_exclusivo(db)
    assert r["n"] == 0 and "órgão público" in r["ressalvados"][0]["ressalva"]


def test_dois_denominadores_sao_devolvidos(banco):
    """Publicar só o share sobre compras engana quando há subsídio fora do universo."""
    db = banco(despesas=[
        _d(2023, "Transportes", "11111111000191", "COMPRA", "44905201", 8_000_000.0),
        _d(2023, "Transportes", "22222222000191", "SUBSIDIO", "33904101", 8_000_000.0)])
    r = L.fornecedor_quase_exclusivo(db)
    a = r["achados"][0]
    assert a["share"] == pytest.approx(1.0)
    assert a["share_orcamento_total"] == pytest.approx(0.5)


def test_piso_de_orgao_evita_orgao_minusculo(banco):
    db = banco(despesas=[_d(2022, "Orgao Pequeno", "11111111000191", "X", "33903901", 1000.0)])
    r = L.fornecedor_quase_exclusivo(db)
    assert r["universo"] == 0 and r["prevalencia"] is None


# ── L4 · salto de faturamento ────────────────────────────────────────────────────────────────

def test_salto_exige_base_minima(banco):
    """Sem piso, R$ 100 -> R$ 5.000 vira 'salto de 50x' — ruído aritmético, não sinal."""
    db = banco(despesas=[_d(2021, "SMS", "11111111000191", "X", "33903901", 100.0),
                         _d(2022, "SMS", "11111111000191", "X", "33903901", 5_000.0)])
    assert L.salto_de_faturamento(db)["n"] == 0


def test_salto_so_entre_exercicios_consecutivos(banco):
    db = banco(despesas=[_d(2019, "SMS", "11111111000191", "X", "33903901", 2_000_000.0),
                         _d(2023, "SMS", "11111111000191", "X", "33903901", 90_000_000.0)])
    assert L.salto_de_faturamento(db)["n"] == 0, "crescimento em 4 anos é expansão, não salto"


def test_salto_detectado_em_anos_consecutivos(banco):
    db = banco(despesas=[_d(2021, "SMS", "11111111000191", "X", "33903901", 2_000_000.0),
                         _d(2022, "SMS", "11111111000191", "X", "33903901", 40_000_000.0)])
    r = L.salto_de_faturamento(db)
    assert r["n"] == 1 and r["achados"][0]["razao"] == pytest.approx(20.0)


# ── L5 · liquidado sem pagamento ─────────────────────────────────────────────────────────────

def test_liquidado_sem_pagamento_nao_aplica_o_filtro_de_pago(banco):
    """A lente procura justamente pago=0; herdar o filtro do universo a esvaziaria."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 0.0,
                            liquidado=500_000.0)])
    r = L.liquidado_sem_pagamento(db)
    assert r["n"] == 1 and r["achados"][0]["liquidado"] == pytest.approx(500_000.0)


# ── L3 · pessoa física em elemento de PJ ─────────────────────────────────────────────────────

def test_pf_em_elemento_de_pj_e_cpf_nao_e_exposto(banco):
    db = banco(despesas=[_d(2022, "SMS", "12345678901", "FULANO", "33903901", 90_000.0),
                         _d(2022, "SMS", "11111111000191", "EMPRESA", "33903901", 90_000.0)])
    r = L.pessoa_fisica_em_elemento_de_pj(db)
    assert r["n"] == 1 and r["achados"][0]["credor"] == "FULANO"
    assert "cpf" not in r["achados"][0] and "documento" not in r["achados"][0]


def test_elemento_de_material_de_consumo_nao_e_tipico_de_pj(banco):
    db = banco(despesas=[_d(2022, "SMS", "12345678901", "FULANO", "33903001", 90_000.0)])
    assert L.pessoa_fisica_em_elemento_de_pj(db)["n"] == 0


# ── contrato comum das lentes ────────────────────────────────────────────────────────────────

def test_toda_lente_declara_universo_prevalencia_e_massa(banco):
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 1000.0)])
    for f in L.LENTES:
        r = f(db)
        assert {"lente", "universo", "n", "prevalencia", "massa", "achados"} <= set(r), f.__name__
        assert isinstance(r["lente"], str) and len(r["lente"]) > 10
        if r["universo"] == 0:
            assert r["prevalencia"] is None, f"{f.__name__}: universo vazio virou 0%, não INDISPONÍVEL"
