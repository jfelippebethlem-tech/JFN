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
    assert r["achados"][0]["veredito"] == "CONCLUSIVO"


def test_sancao_que_cobre_so_parte_do_exercicio_e_inconclusiva(banco):
    """A base não tem data de pagamento. Sanção que começa em agosto não permite afirmar que a
    OB de março caiu dentro da vigência — vira fila de conferência, não achado."""
    db = banco(
        despesas=[_d(2019, "SMS", "11111111000191", "PARCIAL", "33903901", 2_000_000.0),
                  _d(2022, "SMS", "11111111000191", "PARCIAL", "33903901", 60_000.0)],
        sancoes=[("CEIS", "11111111000191", "Declaração de Inidoneidade sem prazo determinado",
                  "2019-08-26", None, "TJRJ")])
    r = L.sancao_de_efeito_amplo(db)
    assert [a["exercicio"] for a in r["achados"]] == [2022], "2019 tem sobreposição parcial"
    assert [a["exercicio"] for a in r["inconclusivos"]] == [2019]
    assert r["inconclusivos"][0]["veredito"] == "INCONCLUSIVO"
    assert "data da OB" in r["inconclusivos"][0]["motivo"]
    assert r["massa"] == pytest.approx(60_000.0), "a massa só soma o que é conclusivo"


def test_inconclusivo_fica_visivel_e_nao_e_descartado(banco):
    db = banco(
        despesas=[_d(2019, "SMS", "11111111000191", "X", "33903901", 500.0)],
        sancoes=[("CEIS", "11111111000191", "Declaração de Inidoneidade sem prazo determinado",
                  "2019-08-26", None, "TJRJ")])
    r = L.sancao_de_efeito_amplo(db)
    assert r["n"] == 0
    assert len(r["inconclusivos"]) == 1, "sumir com ele perderia a fila de conferência"


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


# ── L7 · sócio comum ─────────────────────────────────────────────────────────────────────────

DDL_SOCIOS = """
CREATE TABLE socios_receita (cnpj_basico TEXT, ident TEXT, nome_socio TEXT, nome_norm TEXT,
  doc_socio TEXT, qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT,
  faixa_etaria TEXT, fonte_mes TEXT)"""


@pytest.fixture()
def banco_socios(tmp_path):
    def _criar(despesas, socios):
        p = tmp_path / "s.db"
        con = sqlite3.connect(p)
        for ddl in (DDL_DESPESA, DDL_CADASTRO, DDL_SANCOES, DDL_EMPRESAS, DDL_SOCIOS):
            con.execute(ddl)
        con.executemany("INSERT INTO pcrj_despesa (exercicio,orgao,credor_documento,credor_nome,"
                        "natureza,empenhado,liquidado,pago) VALUES (?,?,?,?,?,?,?,?)", despesas)
        con.executemany("INSERT INTO socios_receita (cnpj_basico,nome_norm) VALUES (?,?)", socios)
        con.commit()
        con.close()
        return str(p)
    return _criar


def test_socio_comum_exige_o_minimo_de_empresas(banco_socios):
    db = banco_socios(
        despesas=[_d(2022, "SMS", "11111111000191", "ALFA", "33903901", 1000.0),
                  _d(2022, "SMS", "22222222000191", "BETA", "33903901", 1000.0)],
        socios=[("11111111", "JOAO DA SILVA SANTOS"), ("22222222", "JOAO DA SILVA SANTOS")])
    assert L.socio_comum_a_fornecedores(db, minimo=3)["n"] == 0
    assert L.socio_comum_a_fornecedores(db, minimo=2)["n"] == 1


def test_consorcio_e_consorciada_e_ressalvado(banco_socios):
    """O consórcio partilha sócio com a consorciada por definição — vínculo declarado."""
    db = banco_socios(
        despesas=[_d(2022, "SMS", "11111111000191", "CONSORCIO VIEIRA BRT", "33903901", 1000.0),
                  _d(2022, "SMS", "22222222000191", "F P VIEIRA ENGENHARIA LTDA", "33903901", 1000.0),
                  _d(2022, "SMS", "33333333000191", "FMV CONSTRUCOES LTDA", "33903901", 1000.0)],
        socios=[("11111111", "MARIA VIEIRA DE SOUZA"), ("22222222", "MARIA VIEIRA DE SOUZA"),
                ("33333333", "MARIA VIEIRA DE SOUZA")])
    r = L.socio_comum_a_fornecedores(db)
    assert r["n"] == 0 and len(r["ressalvados"]) == 1
    assert "consórcio" in r["ressalvados"][0]["ressalva"]


def test_radical_comum_e_grupo_declarado_no_nome(banco_socios):
    db = banco_socios(
        despesas=[_d(2022, "SMS", "11111111000191", "CLARO S. A.", "33903901", 1000.0),
                  _d(2022, "SMS", "22222222000191", "CLARO NXT TELECOMUNICACOES SA", "33903901", 1000.0),
                  _d(2022, "SMS", "33333333000191", "CLARO PARTICIPACOES LTDA", "33903901", 1000.0)],
        socios=[(f"{i}" * 8, "ACIONISTA CONTROLADOR UNICO") for i in (1, 2, 3)])
    r = L.socio_comum_a_fornecedores(db)
    assert r["n"] == 0, "grupo anunciado no nome não é rede oculta"
    assert "radical" in r["ressalvados"][0]["ressalva"]


def test_empresas_de_nomes_distintos_ficam_para_exame(banco_socios):
    """O corte tem de DEIXAR PASSAR o que interessa: nomes sem parentesco aparente."""
    db = banco_socios(
        despesas=[_d(2022, "SMS", "11111111000191", "OBRA PRIMA CONSTRUCAO LTDA", "33903901", 1000.0),
                  _d(2022, "SMS", "22222222000191", "MASSIMO OBRAS EIRELI", "33903901", 1000.0),
                  _d(2022, "SMS", "33333333000191", "ARIA COMERCIO HOSPITALAR", "33903901", 1000.0)],
        socios=[(f"{i}" * 8, "PESSOA COM NOME COMPRIDO") for i in (1, 2, 3)])
    r = L.socio_comum_a_fornecedores(db)
    assert r["n"] == 1 and r["achados"][0]["ressalva"] is None


def test_homonimia_sem_folha_publica_e_indisponivel(banco_socios):
    """Sem a base de agentes não se sabe quantos portadores o nome tem — INDISPONÍVEL."""
    db = banco_socios(
        despesas=[_d(2022, "SMS", f"{i}" * 8 + "000191", f"EMPRESA {i}", "33903901", 1000.0)
                  for i in (1, 2, 3)],
        socios=[(f"{i}" * 8, "JOSE SILVA") for i in (1, 2, 3)])
    a = L.socio_comum_a_fornecedores(db)["achados"][0]
    assert a["risco_homonimia"] == "INDISPONIVEL" and a["portadores_do_nome"] is None


# ── L8 · capital social ──────────────────────────────────────────────────────────────────────

def test_capital_ausente_fica_fora_do_universo(banco):
    """Sem capital declarado nada se conclui — INDISPONÍVEL, não 'capital baixo'."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 9_000_000.0)],
               cadastro=[])
    r = L.pago_muito_acima_do_capital(db)
    assert r["universo"] == 0 and r["prevalencia"] is None


def test_piso_de_pagamento_evita_ruido_aritmetico(banco, tmp_path):
    con = sqlite3.connect(tmp_path / "c.db")
    for ddl in (DDL_DESPESA, DDL_CADASTRO, DDL_SANCOES, DDL_EMPRESAS):
        con.execute(ddl)
    con.execute("INSERT INTO pcrj_despesa (exercicio,orgao,credor_documento,credor_nome,natureza,"
                "empenhado,liquidado,pago) VALUES (2022,'SMS','11111111000191','X','33903901',"
                "150000,150000,150000)")
    con.execute("INSERT INTO empresas_cadastro (cnpj_basico,capital_social) VALUES ('11111111',1000)")
    con.commit()
    con.close()
    r = L.pago_muito_acima_do_capital(str(tmp_path / "c.db"))
    assert r["n"] == 0, "R$ 150 mil sobre capital de R$ 1 mil é 150x, mas está abaixo do piso"


# ── lente descartada ─────────────────────────────────────────────────────────────────────────

def test_mono_cliente_esta_fora_das_lentes_ativas():
    """Descartada por prevalência: 8,8% mesmo no corte mais severo. Fica registrada."""
    assert L.fornecedor_mono_cliente not in L.LENTES
    assert L.fornecedor_mono_cliente in L.DESCARTADAS
    assert "DESCARTADA" in L.fornecedor_mono_cliente.__doc__


def test_fonte_de_socios_ausente_devolve_indisponivel_nao_zero(banco):
    """Sem `socios_receita`, a resposta honesta é INDISPONÍVEL — não 'nenhum sócio comum'."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 1000.0)])
    r = L.socio_comum_a_fornecedores(db)
    assert r["prevalencia"] is None
    assert "indisponível" in r["_indisponivel"].lower()


# ── L9 · agente público estadual administrando fornecedor municipal ─────────────────────────

DDL_AGENTE = """
CREATE TABLE agente_publico_societario (nome_norm TEXT, nome_socio TEXT, doc_socio TEXT,
  cnpj_basico TEXT, qualif_cod TEXT, origem TEXT, cargo TEXT, vinculo TEXT, orgao TEXT,
  comissionado INT, construido_em TEXT)"""


@pytest.fixture()
def banco_agente(tmp_path):
    def _criar(despesas, agentes, empresas=()):
        p = tmp_path / "a.db"
        con = sqlite3.connect(p)
        for ddl in (DDL_DESPESA, DDL_CADASTRO, DDL_SANCOES, DDL_EMPRESAS, DDL_SOCIOS, DDL_AGENTE):
            con.execute(ddl)
        con.executemany("INSERT INTO pcrj_despesa (exercicio,orgao,credor_documento,credor_nome,"
                        "natureza,empenhado,liquidado,pago) VALUES (?,?,?,?,?,?,?,?)", despesas)
        con.executemany("INSERT INTO agente_publico_societario (cnpj_basico,nome_socio,qualif_cod,"
                        "cargo,vinculo,orgao,comissionado,origem) VALUES (?,?,?,?,?,?,?,?)", agentes)
        con.executemany("INSERT INTO empresas (cnpj,razao_social,natureza_jur,atividade_princ) "
                        "VALUES (?,?,?,?)", empresas)
        con.commit()
        con.close()
        return str(p)
    return _criar


def test_socio_quotista_simples_nao_viola_o_estatuto(banco_agente):
    """O estatuto veda GERÊNCIA, não a cota. 'Sócio' (código 22) fica fora por padrão."""
    db = banco_agente(
        despesas=[_d(2022, "SMS", "11111111000191", "ALFA LTDA", "33903901", 1_000_000.0)],
        agentes=[("11111111", "MARIA DE SOUZA LIMA COSTA", "22", "ANALISTA", "EFETIVO",
                  "SEC ESTADO", 0, "folha_estado")])
    assert L.servidor_estadual_socio_de_fornecedor(db)["corte_amplo"]["n"] == 0
    r = L.servidor_estadual_socio_de_fornecedor(db, so_gerencia=False)
    assert r["corte_amplo"]["n"] == 1, "com so_gerencia=False o quotista aparece"


def test_administrador_entra_e_comissionado_e_o_corte_forte(banco_agente):
    db = banco_agente(
        despesas=[_d(2022, "SMS", "11111111000191", "ALFA LTDA", "33903901", 1_000_000.0),
                  _d(2022, "SMS", "22222222000191", "BETA LTDA", "33903901", 2_000_000.0)],
        agentes=[("11111111", "MARIA DE SOUZA LIMA COSTA", "49", "ASSISTENTE", "CARGO COMISSAO",
                  "CASA CIVIL", 1, "folha_estado"),
                 ("22222222", "JOAO PEREIRA DOS SANTOS NETO", "49", "ANALISTA", "EFETIVO",
                  "SEC ESTADO", 0, "folha_estado")])
    r = L.servidor_estadual_socio_de_fornecedor(db)
    assert r["n"] == 1 and r["achados"][0]["fornecedor"] == "ALFA LTDA"
    assert r["corte_amplo"]["n"] == 2, "o efetivo não some — fica no corte amplo"
    assert r["massa"] == pytest.approx(1_000_000.0)


def test_banco_e_estatal_sao_ressalvados_por_homonimia(banco_agente):
    """Quadro numeroso + razão social notória = homônimo, não achado."""
    db = banco_agente(
        despesas=[_d(2022, "SMF", "60701190000104", "BANCO ITAU S A", "33903901", 9_000_000.0),
                  _d(2022, "SMF", "34028316000103", "EMPRESA BRASILEIRA DE CORREIOS",
                     "33903901", 9_000_000.0)],
        agentes=[("60701190", "JOSE DA SILVA PEREIRA JUNIOR", "10", "ASSISTENTE II",
                  "CARGO COMISSAO", "PGE", 1, "folha_estado"),
                 ("34028316", "ANTONIO CARLOS DE OLIVEIRA", "10", "SUBTENENTE PM", "EFETIVO",
                  "PMERJ", 0, "folha_estado")])
    r = L.servidor_estadual_socio_de_fornecedor(db)
    assert r["n"] == 0
    assert len(r["ressalvados"]) == 2


def test_homonimia_vem_do_numero_de_portadores_nao_do_tamanho_do_nome(banco_agente):
    """Contar palavras me enganou: 'LUIZ CARLOS DA SILVA' tem quatro e 1.779 portadores.
    O grau passa a vir do número de pessoas que carregam o nome na folha pública."""
    comum = [("11111111", "LUIZ CARLOS DA SILVA", "49", f"CARGO {i}", "CARGO COMISSAO", "X", 1,
              "folha_estado") for i in range(12)]
    raro = [("22222222", "PEDRO DANIEL STROZENBERG", "49", "DIRETOR", "CARGO COMISSAO", "Y", 1,
             "folha_estado")]
    db = banco_agente(
        despesas=[_d(2022, "SMS", "11111111000191", "ALFA LTDA", "33903901", 1_000_000.0),
                  _d(2022, "SMS", "22222222000191", "BETA LTDA", "33903901", 1_000_000.0)],
        agentes=comum + raro)
    por = {a["fornecedor"]: a for a in L.servidor_estadual_socio_de_fornecedor(db)["achados"]}
    assert por["ALFA LTDA"]["risco_homonimia"] == "ALTO"
    assert por["ALFA LTDA"]["portadores_do_nome"] == 12
    assert por["BETA LTDA"]["risco_homonimia"] == "baixo"


def test_um_unico_portador_e_baixo_nunca_nulo():
    """Um portador prova que NESTA base não há colisão — não prova identidade."""
    assert L._grau_homonimia(1) == "baixo"
    assert L._grau_homonimia(5) == "MEDIO"
    assert L._grau_homonimia(11) == "ALTO"
    assert L._grau_homonimia(None) == "INDISPONIVEL"


def test_fonte_de_agentes_ausente_e_indisponivel(banco):
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 1000.0)])
    r = L.servidor_estadual_socio_de_fornecedor(db)
    assert r["prevalencia"] is None and "indisponível" in r["_indisponivel"].lower()


# ── L10 · empresa recém-criada ───────────────────────────────────────────────────────────────

def test_idade_e_medida_contra_o_exercicio_pago_nao_contra_hoje(banco):
    """Usar 'hoje' faria toda empresa parecer velha com o passar do tempo."""
    db = banco(despesas=[_d(2021, "SMS", "11111111000191", "NOVA LTDA", "33903901", 5_000_000.0)],
               empresas=[("11111111000191", "NOVA LTDA", "2062", "Comércio")])
    con = sqlite3.connect(db)
    con.execute("UPDATE empresas SET data_abertura='2021-07-22'")
    con.commit()
    con.close()
    r = L.empresa_recem_criada(db)
    assert r["n"] == 1
    assert r["achados"][0]["idade_meses_no_fim_do_exercicio"] == 5


def test_spe_de_concessao_e_ressalvada(banco):
    """SPE é criada PARA o contrato: idade curta é a estrutura, não anomalia."""
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "AGUAS DO RIO 4 SPE S.A.",
                            "33903901", 80_000_000.0)],
               empresas=[("11111111000191", "AGUAS DO RIO 4 SPE S.A.", "2062", "Saneamento")])
    con = sqlite3.connect(db)
    con.execute("UPDATE empresas SET data_abertura='2021-07-08'")
    con.commit()
    con.close()
    r = L.empresa_recem_criada(db)
    assert r["n"] == 0 and len(r["ressalvados"]) == 1
    assert "propósito específico" in r["ressalvados"][0]["ressalva"]


def test_empresa_sem_data_conhecida_e_indisponivel_nao_antiga(banco):
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "X", "33903901", 5_000_000.0)])
    r = L.empresa_recem_criada(db)
    assert r["universo"] == 0 and r["prevalencia"] is None


# ── L11 · HHI ────────────────────────────────────────────────────────────────────────────────

def test_hhi_de_fornecedor_unico_e_um(banco):
    db = banco(despesas=[_d(2022, "SMS", "11111111000191", "UNICO", "33903901", 9_000_000.0)])
    r = L.concentracao_hhi(db)
    assert r["achados"][0]["hhi"] == pytest.approx(1.0)
    assert r["achados"][0]["equivalente_a_n_iguais"] == pytest.approx(1.0)


def test_hhi_pega_concentracao_que_o_corte_de_80_perde(banco):
    """Três fornecedores com 1/3 cada: nenhum tem 80%, mas o órgão é concentrado (HHI 0,33)."""
    db = banco(despesas=[_d(2022, "SMS", f"{i}" * 8 + "000191", f"F{i}", "33903901", 3_000_000.0)
                         for i in (1, 2, 3)])
    assert L.fornecedor_quase_exclusivo(db)["n"] == 0
    r = L.concentracao_hhi(db, limiar=0.30)
    assert r["n"] == 1 and r["achados"][0]["hhi"] == pytest.approx(1 / 3, abs=1e-3)


def test_hhi_disperso_nao_e_marcado(banco):
    db = banco(despesas=[_d(2022, "SMS", f"{i:08d}" + "000191", f"F{i}", "33903901", 1_000_000.0)
                         for i in range(1, 11)])
    assert L.concentracao_hhi(db)["n"] == 0, "dez fornecedores iguais dão HHI 0,10"


def test_hhi_ressalva_monopolio_natural(banco):
    db = banco(despesas=[_d(2021, "Fundo Iluminação", "60444437000146", "LIGHT SERVICOS",
                            "33903901", 9_000_000.0)],
               empresas=[("60444437000146", "LIGHT", "2054", "Distribuição de energia elétrica")])
    r = L.concentracao_hhi(db)
    assert r["n"] == 0 and len(r["ressalvados"]) == 1


def test_data_de_abertura_posterior_ao_primeiro_pagamento_e_descartada(banco):
    """Se a empresa já recebia antes da 'abertura', a data não é de constituição.
    Medido: só 0,3% dos pares, mas eram exatamente o topo da lente."""
    db = banco(despesas=[_d(2020, "SME", "11111111000191", "EBN COMERCIO", "33903001", 22_000_000.0),
                         _d(2021, "SME", "11111111000191", "EBN COMERCIO", "33903001", 62_000_000.0)],
               empresas=[("11111111000191", "EBN COMERCIO", "2062", "Comércio")])
    con = sqlite3.connect(db)
    con.execute("UPDATE empresas SET data_abertura='2021-07-22'")
    con.commit()
    con.close()
    r = L.empresa_recem_criada(db)
    assert r["n"] == 0, "pagou em 2020 e 'abriu' em 2021 — a data está errada"
    assert len(r["data_inconsistente"]) >= 1
    assert r["data_inconsistente"][0]["primeiro_exercicio_pago"] == 2020


def test_empresa_realmente_nova_sobrevive_a_guarda(banco):
    """A guarda não pode matar o achado legítimo: primeiro pagamento no ano da abertura."""
    db = banco(despesas=[_d(2021, "SME", "11111111000191", "NOVA DE VERDADE LTDA",
                            "33903001", 9_000_000.0)],
               empresas=[("11111111000191", "NOVA DE VERDADE LTDA", "2062", "Comércio")])
    con = sqlite3.connect(db)
    con.execute("UPDATE empresas SET data_abertura='2021-03-10'")
    con.commit()
    con.close()
    r = L.empresa_recem_criada(db)
    assert r["n"] == 1 and not r["data_inconsistente"]
