# -*- coding: utf-8 -*-
"""Gestão Couto — correções da revisão cética de 13/11/2026 (`~/vault/notas/revisao-cetica-2026-11-13.md` §6.1/§6.2).
Base sintética: nenhum nome, CPF ou CNPJ real."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import governo_couto_regras as GR

NOVA, FILIAL, VELHA = "11111111000111", "22222222000299", "22222222000122"
SANC_FED, SANC_RJ, SANC_PRAZO = "33333333000133", "44444444000144", "55555555000155"
SOCIO_OK, SOCIO_HOM, SOCIO_ALERJ = "66666666000166", "77777777000177", "88888888000188"


@pytest.fixture()
def base(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, nl TEXT,
        credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER, gd TEXT, status_envio TEXT);
    CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, valor REAL);
    CREATE TABLE despesa_execucao (ug TEXT, nome_ug TEXT);
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT, abrangencia TEXT,
        esfera_sancionador TEXT, data_publicacao TEXT);
    CREATE TABLE agente_publico_societario (nome_norm TEXT, nome_socio TEXT, doc_socio TEXT, cnpj_basico TEXT,
        qualif_cod TEXT, origem TEXT, cargo TEXT, vinculo TEXT, orgao TEXT, comissionado INTEGER, construido_em TEXT);
    CREATE TABLE registros_folha (nome TEXT, cpf TEXT, fonte TEXT);
    CREATE TABLE contratos_tcerj (processo TEXT, sei_norm TEXT, data_contratacao TEXT, valor_contrato REAL,
        status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT, cnpj TEXT);
    CREATE TABLE publicacoes_doerj (data_publicacao TEXT, texto TEXT);
    """)
    c.execute("INSERT INTO despesa_execucao VALUES ('100100','SECRETARIA FICTICIA')")
    O = "INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,NULL,?,?,'SEI-100001/000001/2026',?,?,?,?)"
    c.executemany(O, [
        # NOVA: R$ 6 mi pagos; uma linha-fantasma SEM número repete a OB (não pode somar)
        ("2026OB00001", "100100", "10/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026, "", ""),
        ("", "100100", "10/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026, "", ""),
        # e uma OB devolvida pelo banco (TFE 0,00) com a reemissão já contada acima
        ("2026OB00002", "100100", "09/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026,
         "2026GD00001", "Erro no Pagamento"),
        # FILIAL de raiz que já recebia em 2022 — não é credor sem histórico
        ("2022OB00009", "100100", "10/05/2022", "Contabilizado", VELHA, "VELHA SA", 1_000.0, 2022, "", ""),
        ("2026OB00003", "100100", "11/05/2026", "Contabilizado", FILIAL, "VELHA SA FILIAL", 7_000_000.0, 2026, "", ""),
        ("2026OB00004", "100100", "12/05/2026", "Contabilizado", SANC_FED, "FED LTDA", 500_000.0, 2026, "", ""),
        ("2026OB00005", "100100", "12/05/2026", "Contabilizado", SANC_RJ, "RJ LTDA", 400_000.0, 2026, "", ""),
        ("2026OB00006", "100100", "12/05/2026", "Contabilizado", SANC_PRAZO, "PRAZO LTDA", 300_000.0, 2026, "", ""),
        ("2026OB00007", "100100", "12/05/2026", "Contabilizado", SOCIO_OK, "SOCIO OK LTDA", 200_000.0, 2026, "", ""),
        ("2026OB00008", "100100", "12/05/2026", "Contabilizado", SOCIO_HOM, "HOMONIMO LTDA", 200_000.0, 2026, "", ""),
        ("2026OB00010", "100100", "12/05/2026", "Contabilizado", SOCIO_ALERJ, "ALERJ LTDA", 200_000.0, 2026, "", ""),
        ("2026OB00011", "100100", "10/11/2026", "Contabilizado", VELHA, "VELHA SA", 10.0, 2026, "", ""),
    ])
    c.execute("INSERT INTO ordens_bancarias VALUES ('2026OB00002','100100',0.0)")
    S = "INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    c.executemany(S, [
        ("CEIS", SANC_FED, "FED", "Suspensão", "2026-04-01", "2027-04-01", "Instituto Federal Ficticio", "RJ", "p",
         "LEI 8666 - ART. 87, III", "No órgão sancionador", "FEDERAL", None),
        ("CEIS", SANC_RJ, "RJ", "Impedimento/proibição de contratar com prazo determinado", "2026-04-01",
         "2027-04-01", "Secretaria de Estado Ficticia", "RJ", "p", "LEI 14133 - ART. 156, III",
         "Em todos os Poderes da Esfera do órgão sancionador", "ESTADUAL", None),
        ("CEIS", SANC_PRAZO, "PRAZO", "Impedimento/proibição de contratar com prazo determinado", "2026-04-01",
         None, "Secretaria de Estado Ficticia", "RJ", "p", "LEI 14133 - ART. 156, III",
         "Em todos os Poderes da Esfera do órgão sancionador", "ESTADUAL", None),
    ])
    A = "INSERT INTO agente_publico_societario VALUES (?,?,?,?,'49',?,'ASSESSOR','COMISSIONADO','SECRETARIA',1,'x')"
    c.executemany(A, [
        ("FULANO FICTICIO DA SILVA", "FULANO FICTICIO DA SILVA", "***456789**", SOCIO_OK[:8], "folha_estado"),
        ("BELTRANO FICTICIO SOUZA", "BELTRANO FICTICIO SOUZA", "***111111**", SOCIO_HOM[:8], "folha_estado"),
        ("SICRANO FICTICIO LIMA", "SICRANO FICTICIO LIMA", "***222222**", SOCIO_ALERJ[:8], "alerj"),
    ])
    c.executemany("INSERT INTO registros_folha VALUES (?,?,?)", [
        ("FULANO FICTICIO DA SILVA", "XX456789XXX", "gesperj_estado"),        # Executivo: dígitos 4–9 → confere
        ("BELTRANO FICTICIO SOUZA", "XX999999XXX", "gesperj_estado"),         # outra pessoa com o mesmo nome
    ])
    C = "INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?,?,?,?)"
    c.executemany(C, [
        # registrado no 3º dia, mas o DOERJ diz que a ATA foi assinada em fevereiro
        ("SEI-100001/000010/2026", "1000010000102026", "2026-03-25", 43_000_000.0, "Ativo", "UNIDADE X",
         "REGISTRO DE PREÇOS PARA EVENTOS", "FORN ATA", NOVA),
        # registrado no 5º dia, assinado antes da gestão (DOERJ)
        ("SEI-100001/000011/2026", "1000010000112026", "2026-03-27", 9_000_000.0, "Ativo", "UNIDADE X",
         "OBRA DE CONTENÇÃO", "FORN ANTES", FILIAL),
        # assinado de fato na gestão
        ("SEI-100001/000012/2026", "1000010000122026", "2026-03-30", 1_000_000.0, "Ativo", "UNIDADE X",
         "SERVIÇO DE LIMPEZA", "FORN GESTAO", VELHA),
    ])
    c.executemany("INSERT INTO publicacoes_doerj VALUES (?,?)", [
        ("2026-03-20", "EXTRATO DE ATA DE REGISTRO DE PREÇOS Nº 1/2026 PROCESSO Nº SEI-100001/000010/2026 "
                       "OBJETO: EVENTOS DATA DA ASSINATURA: 24/02/2026"),
        ("2026-04-14", "EXTRATO DE CONTRATO PROCESSO SEI-100001/000011/2026 OBJETO: OBRA "
                       "DATA DA ASSINATURA: 10/03/2026 VALOR R$ 9.000.000,00"),
    ])
    c.commit()
    c.close()
    return db


@pytest.fixture()
def ctx(base, tmp_path):
    c = GR.Ctx(base, receita=None, tse=None, dir_tmp=tmp_path)
    yield c
    c.fechar()


def test_ob_sem_numero_e_devolvida_nao_somam(ctx):
    d10 = {x["cnpj"]: x for x in GR.d10(ctx)["casos"]}
    assert d10[NOVA]["pago_ob"] == pytest.approx(6_000_000.0)       # nem a linha sem número nem a devolvida


def test_sem_historico_pela_raiz_do_cnpj_desde_2021(ctx):
    assert FILIAL not in {x["cnpj"] for x in GR.d10(ctx)["casos"]}  # a raiz recebeu em 2022


def test_d14_so_conta_sancao_vigente_com_alcance_sobre_o_estado(ctx):
    r = GR.d14(ctx)
    assert {x["cnpj"] for x in r["casos"]} == {SANC_RJ}
    assert r["n_sem_alcance"] == 1 and r["soma_sem_alcance"] == pytest.approx(500_000.0)   # suspensão do IFRJ-like


def test_d13_exige_digitos_visiveis_do_cpf(ctx):
    r = GR.d13(ctx)
    assert [x["cnpj_basico"] for x in r["casos"]] == [SOCIO_OK[:8]]
    assert r["n_homonimos_descartados"] == 1 and r["n_cnpj_nao_testavel"] == 1


def test_cpf_confere_respeita_a_posicao_por_fonte():
    assert GR.cpf_confere("***456789**", "XX456789XXX", "gesperj_estado") is True     # dígitos 4–9
    assert GR.cpf_confere("***456789**", "XX345678XXX", "dprj_transparencia") is True  # dígitos 3–8: sobreposição 4–8
    assert GR.cpf_confere("***456789**", "XX456789XXX", "dprj_transparencia") is False
    assert GR.cpf_confere("***456789**", "XX456789XXX", "fonte_sem_aferir") is None
    assert GR.cpf_confere("***456789**", None, "gesperj_estado") is None


def test_contrato_da_gestao_usa_a_data_do_doerj_e_tira_ata(ctx):
    r = GR.d08_09(ctx)["D08"]
    assert [x["processo"] for x in r["casos"]] == ["SEI-100001/000012/2026"]
    a = GR.ato_do_contrato(ctx, "1000010000112026", "", "2026-03-27")
    assert a["data"] == "2026-03-10" and a["fonte"].startswith("DOERJ")
    assert GR.ato_do_contrato(ctx, "1000010000102026", "", "2026-03-25")["nao_contrato"] is True


def test_curadoria_manual_nao_carrega_vermelho_fixo_e_refutado_vira_branco():
    t01 = GR.rebaixar_curadoria({"id": "T01", "top10": True, "grau": "🔴"})
    assert t01["grau"] == "🟡" and t01["grau_proposto"] == "🔴" and t01["revisao_cetica"]["veredito"] == "PARCIAL"
    t05 = GR.rebaixar_curadoria({"id": "T05", "top10": True, "grau": "🟡"})
    assert t05["grau"] == "⚪" and t05["revisao_cetica"]["veredito"] == "REFUTADA"


def test_d18_veredito_fachada_sem_registro_do_juizo_nao_e_confirmado(base, tmp_path):
    con = sqlite3.connect(base)
    con.executescript("""CREATE TABLE fantasma_score (cnpj TEXT, score INTEGER, classificacao TEXT);
        CREATE TABLE fachada_veredito (cnpj TEXT, status TEXT, veredito_raw TEXT);""")
    con.executemany("INSERT INTO fachada_veredito VALUES (?,?,?)", [(NOVA, "fachada", ""),
                                                                    (FILIAL, "fachada", "fachada — sede vazia (vistoria)")])
    con.commit()
    con.close()
    c = GR.Ctx(base, receita=None, tse=None, dir_tmp=tmp_path)
    try:
        r = {x["cnpj"]: x for x in GR.d18(c)["casos"]}
    finally:
        c.fechar()
    assert r[NOVA]["fachada_confirmada"] is False and r[FILIAL]["fachada_confirmada"] is True


def test_d18_score_alto_sem_fachada_registrada_nao_e_vermelho():
    res = {"D18": {"n": 1, "casos": [{"cnpj": NOVA, "credor": "X", "pago_ob": 1.0, "fantasma_alto": True, "score": 95,
                                      "fachada_confirmada": False}]}}
    a = [x for x in GR.achados_deterministicos(res) if x["id"].startswith("D18")]
    assert all(x["grau"] != "🔴" for x in a)
