# -*- coding: utf-8 -*-
"""Perícia contábil de contratos — devido × pago (OB). Dados 100% sintéticos."""
import sqlite3
from datetime import date

import pytest

from compliance_agent import pericia_contabil as pc


# ───────────────────────── normalização ─────────────────────────

@pytest.mark.parametrize("bruto,esperado", [
    ("SEI-330002/031566/2024", "3300020315662024"),
    ("SEI-330002/031566/24", "3300020315662024"),       # ano com 2 dígitos no SIAFE
    ("sei-330003/002643/2024", "3300030026432024"),
    ("SEI 120001/000123/2025", "1200010001232025"),
    ("E-20/001.00226/2024", None),                       # numeração antiga: não é a mesma chave
    ("", None), (None, None), ("0", None),
])
def test_chave_sei(bruto, esperado):
    assert pc.chave_sei(bruto) == esperado


def test_chave_sei_aceita_sei_norm_de_16_digitos():
    assert pc.chave_sei("3300020315662024") == "3300020315662024"


@pytest.mark.parametrize("bruto,esperado", [
    ("11/02/2026", date(2026, 2, 11)),
    ("2024-03-21T00:00:00.000", date(2024, 3, 21)),
    ("2024-03-21", date(2024, 3, 21)),
    ("", None), (None, None), ("31/02/2026", None),
])
def test_parse_data(bruto, esperado):
    assert pc.parse_data(bruto) == esperado


def test_cpf_em_texto_livre_e_mascarado():
    r = pc._resultado_base(pc.ESTADO, objeto="PAGAMENTO A JOAO, CPF 123.456.789-01, REFERENTE", fornecedor="X")
    assert "123.456.789-01" not in r["objeto"] and "123.***.***-01" in r["objeto"]


def test_mascara_cpf_e_preserva_cnpj():
    assert pc.mascarar_doc("12345678901") == "123.***.***-01"
    assert pc.mascarar_doc("12345678000199") == "12.345.678/0001-99"


# ───────────────────────── natureza / regime ─────────────────────────

@pytest.mark.parametrize("objeto,continuada", [
    ("PRESTAÇÃO DE SERVIÇOS CONTÍNUOS DE LIMPEZA E CONSERVAÇÃO", True),
    ("SERVIÇO DE VIGILÂNCIA PATRIMONIAL ARMADA", True),
    ("LOCAÇÃO DE VEÍCULOS COM MOTORISTA", True),
    ("AQUISIÇÃO DE COLETES BALÍSTICOS", False),
    ("OBRA DE REFORMA DA SEDE", False),
    ("AQUISIÇÃO DE MATERIAL COM FORNECIMENTO CONTÍNUO", True),
    ("", False),
])
def test_continuada(objeto, continuada):
    assert pc.e_continuada(objeto) is continuada


def test_utilidade_publica_e_continuada_mesmo_com_fornecimento():
    assert pc.e_continuada("PRESTAÇÃO DE SERVIÇOS DE FORNECIMENTO DE ÁGUA E COLETA DE ESGOTO") is True
    assert pc.e_continuada("FORNECIMENTO DE ENERGIA ELÉTRICA") is True


def test_registro_de_termo_e_parceria():
    assert pc.e_registro_de_termo("O REEQUILÍBRIO ECONÔMICO FINANCEIRO DO VALOR CONTRATUAL")
    assert not pc.e_registro_de_termo("AQUISIÇÃO DE PAPEL")
    assert pc.e_parceria("GERENCIAMENTO, OPERACIONALIZAÇÃO E EXECUÇÃO DAS AÇÕES DE SAÚDE")
    assert pc.e_parceria("REPASSE DE RECURSOS À ASSOCIAÇÃO")


def test_desproporcional():
    assert pc.desproporcional(2_388_161_800.0, 2_388_161.80)
    assert pc.desproporcional(20_972.28, 5_936_838.44)
    assert not pc.desproporcional(100.0, 2.0)
    assert not pc.desproporcional(100.0, 0.0)          # pago zero não é razão — é outro caso


def test_sinais_duplicidade():
    d = date(2026, 1, 1)
    obs = [(d, "k", "1", 10.0, "NL1", "01/2026", "OB1"), (d, "k", "1", 10.0, "NL1", "01/2026", "OB2"),
           (d, "k", "1", 7.0, "NL2", "02/2026", "OB3"), (d, "k", "1", 7.0, "NL3", "02/2026", "OB4")]
    s = pc.sinais_duplicidade(obs)
    assert (s["obs_mesma_nl"], s["valor_mesma_nl"]) == (1, 10.0)
    assert (s["obs_mesma_competencia"], s["valor_mesma_competencia"]) == (1, 7.0)


def test_regime_legal_pela_data():
    assert pc.regime_legal(date(2020, 5, 1))[0] == "8666"
    assert pc.regime_legal(date(2025, 5, 1))[0] == "14133"
    assert pc.regime_legal(date(2022, 5, 1))[0] == "transicao"
    assert "art. 125" in pc.regime_legal(date(2025, 5, 1))[1]
    assert "art. 65" in pc.regime_legal(date(2020, 5, 1))[1]


# ───────────────────────── devido ─────────────────────────

def test_devido_pro_rata_de_continuada():
    v, crit = pc.valor_devido(1200.0, True, date(2026, 1, 1), date(2026, 12, 31), date(2026, 7, 2))
    assert v == pytest.approx(1200.0 * 183 / 365, rel=1e-9)
    assert "pró-rata" in crit


def test_devido_continuada_encerrada_e_integral():
    v, _ = pc.valor_devido(1200.0, True, date(2025, 1, 1), date(2025, 12, 31), date(2026, 7, 2))
    assert v == 1200.0


def test_devido_continuada_sem_vigencia_e_inaferivel():
    v, crit = pc.valor_devido(1200.0, True, None, None, date(2026, 7, 2))
    assert v is None and "vigência" in crit


def test_devido_nao_continuada_e_valor_global():
    v, crit = pc.valor_devido(500.0, False, date(2026, 1, 1), date(2026, 12, 31), date(2026, 2, 1))
    assert v == 500.0 and "global" in crit


def test_devido_continuada_que_nao_comecou_e_zero():
    v, _ = pc.valor_devido(1200.0, True, date(2027, 1, 1), date(2027, 12, 31), date(2026, 7, 2))
    assert v == 0.0


# ───────────────────────── classificação ─────────────────────────

def test_tolerancia_absoluta_e_percentual():
    # R$ 999,99 de diferença em contrato pequeno: conforme pela régua absoluta
    assert pc.classificar(10_999.99, 10_000.0, 10_000.0, encerrado=True)[0] == "CONFORME"
    # 0,9 % em contrato grande: conforme pela régua percentual
    assert pc.classificar(1_009_000.0, 1_000_000.0, 1_000_000.0, encerrado=True)[0] == "CONFORME"
    # 2 % e R$ 20 mil: fora das duas
    assert pc.classificar(1_020_000.0, 1_000_000.0, 1_000_000.0, encerrado=True)[0] == "A_MAIOR"


def test_a_maior_separa_global_de_pro_rata():
    cat, sub, dif = pc.classificar(900_000.0, 500_000.0, 1_000_000.0, encerrado=False)
    assert cat == "A_MAIOR" and sub == "acima_do_pro_rata" and dif == pytest.approx(400_000.0)
    cat, sub, _ = pc.classificar(1_200_000.0, 1_000_000.0, 1_000_000.0, encerrado=False)
    assert cat == "A_MAIOR" and sub == "acima_do_valor_global"


def test_a_menor_separa_encerrado_de_em_curso():
    assert pc.classificar(100.0, 900_000.0, 900_000.0, encerrado=True)[0] == "A_MENOR_ENCERRADO"
    assert pc.classificar(100.0, 900_000.0, 900_000.0, encerrado=False)[0] == "A_MENOR_EM_CURSO"


# ───────────────────────── base sintética (Estado) ─────────────────────────

def _base_estado(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE contratos_tcerj (id TEXT, processo TEXT, sei_norm TEXT, ano_processo INTEGER,
      data_contratacao TEXT, valor_contrato REAL, status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT,
      cnpj TEXT, vig_inicio TEXT, vig_fim TEXT, criterio_julgamento TEXT, num_contratacao TEXT,
      valor_empenhado REAL, valor_liquidado REAL, valor_pago REAL, ingerido_em TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT,
      status TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER,
      nl TEXT DEFAULT '', competencia TEXT DEFAULT '');
    CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, data_emissao TEXT);
    CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, sequencial_termo INTEGER, numero_termo TEXT,
      objeto TEXT, valor_acrescido REAL, valor_global REAL, prazo_aditado_dias INTEGER, vigencia_fim TEXT,
      qualif_acrescimo TEXT, qualif_vigencia TEXT, qualif_reajuste TEXT, fundamento_legal TEXT,
      coletado_em TEXT, data_assinatura TEXT, tipo_termo TEXT, processo TEXT);
    CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT PRIMARY KEY, fornecedor_documento TEXT,
      valor_inicial REAL, valor_global REAL, vigencia_fim TEXT);
    """)
    C = "INSERT INTO contratos_tcerj (id,processo,sei_norm,data_contratacao,valor_contrato,status,unidade,objeto,fornecedor,cnpj,vig_inicio,vig_fim) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    rows = [
        # A: aquisição paga acima do valor global (com OB anulada que NÃO pode somar)
        ("A", "SEI-100001/000001/2024", "1000010000012024", "2024-02-01T00:00:00.000", 100_000.0, "Ativo",
         "ORGAO X", "AQUISIÇÃO DE EQUIPAMENTOS", "FORNECEDOR A", "11111111000111", "01/02/2024", "31/01/2025"),
        # B e B2: mesmo credor e mesmo processo — ambíguo
        ("B", "SEI-100001/000002/2024", "1000010000022024", "2024-02-01T00:00:00.000", 50_000.0, "Ativo",
         "ORGAO X", "AQUISIÇÃO DE PAPEL", "FORNECEDOR B", "22222222000122", "01/02/2024", "31/01/2025"),
        ("B2", "SEI-100001/000002/2024", "1000010000022024", "2024-03-01T00:00:00.000", 70_000.0, "Ativo",
         "ORGAO X", "AQUISIÇÃO DE TONER", "FORNECEDOR B", "22222222000122", "01/03/2024", "28/02/2025"),
        # C: credor sem nenhuma OB no SIAFE, contrato encerrado → a menor (pago zero provado na base)
        ("C", "SEI-100001/000003/2024", "1000010000032024", "2024-02-01T00:00:00.000", 80_000.0, "Encerrado",
         "ORGAO Y", "AQUISIÇÃO DE CADEIRAS", "FORNECEDOR C", "33333333000133", "01/02/2024", "31/07/2024"),
        # D: credor recebe OB, mas em OUTRO processo → indeterminado
        ("D", "SEI-100001/000004/2024", "1000010000042024", "2024-02-01T00:00:00.000", 90_000.0, "Ativo",
         "ORGAO Y", "AQUISIÇÃO DE MESAS", "FORNECEDOR D", "44444444000144", "01/02/2024", "31/01/2025"),
        # E: vigência anterior à cobertura do SIAFE
        ("E", "SEI-100001/000005/2024", "1000010000052024", "2024-02-01T00:00:00.000", 90_000.0, "Ativo",
         "ORGAO Y", "LOCAÇÃO DE IMÓVEL", "FORNECEDOR E", "55555555000155", "01/01/2019", "31/12/2027"),
        # F: cancelado
        ("F", "SEI-100001/000006/2024", "1000010000062024", "2024-02-01T00:00:00.000", 10_000.0, "Cancelado",
         "ORGAO Y", "AQUISIÇÃO", "FORNECEDOR F", "66666666000166", "", ""),
        # G: continuada em curso, paga conforme o pró-rata
        ("G", "SEI-100001/000007/2026", "1000010000072026", "2026-01-01T00:00:00.000", 365_000.0, "Ativo",
         "ORGAO Z", "SERVIÇO DE VIGILÂNCIA", "FORNECEDOR G", "77777777000177", "01/01/2026", "31/12/2026"),
        # H: o registro é o TERMO de reequilíbrio, não o contrato — as OBs do processo pagam o contrato-mãe
        ("H", "SEI-100001/000008/2024", "1000010000082024", "2024-02-01T00:00:00.000", 10_000.0, "Ativo",
         "ORGAO W", "CONSTITUI OBJETO O REEQUILÍBRIO ECONÔMICO FINANCEIRO DO VALOR CONTRATUAL", "FORNECEDOR H",
         "88888888000188", "01/02/2024", "31/01/2025"),
        # I: aquisição com DUAS OBs para a mesma NL e o mesmo valor
        ("I", "SEI-100001/000009/2026", "1000010000092026", "2026-01-10T00:00:00.000", 50_000.0, "Ativo",
         "ORGAO W", "AQUISIÇÃO DE SERVIDOR", "FORNECEDOR I", "99999999000199", "10/01/2026", "10/07/2026"),
    ]
    con.executemany(C, rows)
    O = ("INSERT INTO ob_orcamentaria_siafe (numero_ob,ug_emitente,ug_pagadora,data_emissao,status,credor,"
         "nome_credor,processo,valor,exercicio) VALUES (?,?,?,?,?,?,?,?,?,?)")
    con.executemany(O, [
        ("2024OB00001", "100100", "100100", "10/03/2024", "Contabilizado", "11111111000111", "A",
         "SEI-100001/000001/24", 80_000.0, 2024),
        ("2024OB00002", "100100", "100100", "10/04/2024", "Contabilizado", "11111111000111", "A",
         "SEI-100001/000001/2024", 50_000.0, 2024),
        # mesmo número de OB em OUTRA UG: é outra OB e tem de somar
        ("2024OB00002", "200200", "200200", "10/04/2024", "Contabilizado", "11111111000111", "A",
         "SEI-100001/000001/2024", 5_000.0, 2024),
        # anulada: não soma
        ("2024OB00003", "100100", "100100", "11/04/2024", "Anulado", "11111111000111", "A",
         "SEI-100001/000001/2024", 999_999.0, 2024),
        # anterior ao contrato no mesmo processo: não soma
        ("2023OB00009", "100100", "100100", "10/03/2023", "Contabilizado", "11111111000111", "A",
         "SEI-100001/000001/2024", 7_777.0, 2023),
        ("2024OB00010", "100100", "100100", "10/04/2024", "Contabilizado", "22222222000122", "B",
         "SEI-100001/000002/2024", 60_000.0, 2024),
        ("2024OB00011", "300300", "300300", "10/04/2024", "Contabilizado", "44444444000144", "D",
         "SEI-999999/000001/2024", 60_000.0, 2024),
        ("2026OB00012", "400400", "400400", "30/06/2026", "Contabilizado", "77777777000177", "G",
         "SEI-100001/000007/2026", 181_500.0, 2026),
        ("2024OB00020", "500500", "500500", "10/03/2024", "Contabilizado", "88888888000188", "H",
         "SEI-100001/000008/2024", 900_000.0, 2024),
    ])
    con.executemany(
        "INSERT INTO ob_orcamentaria_siafe (numero_ob,ug_emitente,ug_pagadora,data_emissao,status,credor,"
        "nome_credor,processo,valor,exercicio,nl,competencia) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            ("2026OB00030", "600600", "600600", "20/02/2026", "Contabilizado", "99999999000199", "I",
             "SEI-100001/000009/2026", 50_000.0, 2026, "2026NL00001", "02/2026"),
            ("2026OB00031", "600600", "600600", "27/02/2026", "Contabilizado", "99999999000199", "I",
             "SEI-100001/000009/2026", 50_000.0, 2026, "2026NL00001", "02/2026"),
        ])
    con.commit()
    con.close()
    return db


def test_estado_fim_a_fim(tmp_path):
    db = _base_estado(tmp_path)
    res = {r["id"]: r for r in pc.avaliar_estado(db, corte=date(2026, 7, 1))}
    assert len(res) == 10                                  # todo contrato da base sai no resultado

    a = res["A"]
    assert a["pago"] == pytest.approx(135_000.0)            # 80k + 50k + 5k (outra UG); anulada e anterior fora
    assert a["categoria"] == "A_MAIOR" and a["subtipo"] == "acima_do_valor_global"
    assert a["obs_nao_contabilizadas"] == 1
    assert a["obs_anteriores_ao_contrato"] == 1

    assert res["B"]["categoria"] == res["B2"]["categoria"] == "INDETERMINADO"
    assert res["B"]["motivo"] == "vinculo_ambiguo"

    assert res["C"]["categoria"] == "A_MENOR_ENCERRADO"
    assert res["C"]["pago"] == 0.0 and res["C"]["vinculo"] == "credor_sem_ob"

    assert res["D"]["categoria"] == "INDETERMINADO"
    assert res["D"]["motivo"] == "ob_do_credor_fora_do_processo"
    assert res["D"]["pago"] is None                          # INDISPONÍVEL ≠ zero

    assert res["E"]["motivo"] == "vigencia_anterior_a_cobertura"
    assert res["F"]["motivo"] == "registro_cancelado"

    g = res["G"]
    assert g["categoria"] == "CONFORME", g
    assert g["devido"] == pytest.approx(365_000.0 * 182 / 365)

    assert res["H"]["categoria"] == "INDETERMINADO" and res["H"]["motivo"] == "registro_de_termo"

    i = res["I"]
    assert i["categoria"] == "A_MAIOR" and i["pago"] == pytest.approx(100_000.0)
    assert i["obs_mesma_nl"] == 1 and i["valor_mesma_nl"] == pytest.approx(50_000.0)
    assert "duplicidade" in i["ressalvas"]


def test_consolidacao_soma_so_o_determinado(tmp_path):
    db = _base_estado(tmp_path)
    res = pc.avaliar_estado(db, corte=date(2026, 7, 1))
    por_org = {c["chave"]: c for c in pc.consolidar(res, "orgao")}
    x = por_org["ORGAO X"]
    assert x["n"] == 3 and x["n_a_maior"] == 1 and x["n_indeterminado"] == 2
    assert x["excesso_a_maior"] == pytest.approx(35_000.0)


# ───────────────────────── Prefeitura ─────────────────────────

def _base_pcrj(tmp_path):
    db = tmp_path / "p.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE contasrio_contrato (contrato TEXT, favorecido_doc TEXT, favorecido_nome TEXT,
      orgao TEXT, ug TEXT, tipo_instrumento TEXT, ano INTEGER, numero_instrumento TEXT, data_publicacao TEXT,
      objeto TEXT, situacao TEXT, vigencia_ini TEXT, vigencia_fim TEXT, processo TEXT, forma_contratacao TEXT,
      valor_atualizado REAL, total_empenhado REAL, saldo_executar REAL, total_liquidado REAL, total_pago REAL,
      url_ccon TEXT, coletado_em TEXT)""")
    # 4: contrato de 2021 prorrogado — o Contas Rio mostra a vigência do período CORRENTE (2026–2027), mas
    #    valor e pago são acumulados desde 2021. Pró-rata tem de partir da publicação original.
    con.execute("INSERT INTO contasrio_contrato (contrato,favorecido_doc,favorecido_nome,orgao,ug,objeto,situacao,"
                "vigencia_ini,vigencia_fim,valor_atualizado,total_pago,coletado_em,data_publicacao) VALUES "
                "('4','12345678000199','EMPRESA','ORG P','UG P','SERVIÇO DE VIGILÂNCIA','Assinado','01/01/2026',"
                "'31/12/2026',600000.0,550000.0,'2026-07-01 02:00:00','01/01/2021')")
    I = ("INSERT INTO contasrio_contrato (contrato,favorecido_doc,favorecido_nome,orgao,ug,objeto,situacao,"
         "vigencia_ini,vigencia_fim,valor_atualizado,total_pago,coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
    con.executemany(I, [
        ("1", "12345678901", "PESSOA FISICA", "ORG P", "UG P", "AQUISIÇÃO", "Encerrado",
         "01/01/2024", "31/12/2024", 10_000.0, 30_000.0, "2026-07-01 02:00:00"),
        ("2", "12345678000199", "EMPRESA", "ORG P", "UG P", "AQUISIÇÃO", "Vencida",
         "01/01/2024", "31/12/2024", 100_000.0, 40_000.0, "2026-07-01 02:00:00"),
        # 5: valor registrado com vírgula deslocada (×1.000 o pago) — não pode virar "déficit" bilionário
        ("5", "12345678000199", "INSTITUTO HERMES TESTE", "ORG P", "UG P", "AQUISIÇÃO", "Vencida",
         "01/01/2024", "31/12/2024", 2_388_161_800.0, 2_388_161.80, "2026-07-01 02:00:00"),
        ("3", "12345678000199", "EMPRESA", "ORG P", "UG P", "AQUISIÇÃO", "Assinado",
         "01/01/2024", "31/12/2027", None, 1.0, "2026-07-01 02:00:00"),
    ])
    con.commit()
    con.close()
    return db


def test_relatorio_traz_todos_os_contratos_e_e_neutro(tmp_path):
    from compliance_agent.reporting.neutralidade import termos_proibidos
    from compliance_agent.reporting.render_html import render_html

    res = pc.avaliar_estado(_base_estado(tmp_path), corte=date(2026, 7, 1)) + pc.avaliar_prefeitura(
        _base_pcrj(tmp_path))
    html = render_html(pc.montar_ctx(res, n_base={pc.ESTADO: 10, pc.PREFEITURA: 5}))
    assert html.count(pc.MARCA_LINHA_ANEXO) == len(res) == 15     # nenhum contrato some do documento
    # nome de TERCEIRO que coincide com termo da lista não é vazamento; o texto próprio tem de sair limpo
    assert termos_proibidos(html) == ["hermes"]
    pc.garantir_neutro_exceto_dados(html, res)
    assert "12345678901" not in html and "123.***.***-01" in html  # CPF mascarado também no PDF
    assert "135.000,00" in html                                    # separador de milhar + 2 casas


def test_volumes_cobrem_todos_os_contratos_com_numeracao_continua(tmp_path):
    res = pc.avaliar_estado(_base_estado(tmp_path), corte=date(2026, 7, 1)) + pc.avaliar_prefeitura(
        _base_pcrj(tmp_path))
    vols = pc.planejar_volumes(res, por_volume=3)
    assert sum(v["linhas"] for v in vols) == len(res)
    est = [v for v in vols if v["esfera"] == pc.ESTADO]
    assert [v["inicio"] for v in est] == [1, 4, 7, 10]               # 10 contratos em fatias de 3
    assert len({v["arquivo"] for v in vols}) == len(vols)
    html = pc._tabela_anexo(est[1]["itens"], est[1]["inicio"])
    assert "<td class='n'>4</td>" in html and html.count(pc.MARCA_LINHA_ANEXO) == 3
    ctx = pc.montar_ctx(res, n_base={}, volumes=[{k: v for k, v in x.items() if k != "itens"} for x in vols])
    corpo = " ".join(s["html"] for s in ctx["secoes"])
    assert pc.MARCA_LINHA_ANEXO not in corpo and vols[-1]["arquivo"] in corpo


def test_gerar_sem_pdf_fecha_a_conta(tmp_path):
    out = pc.gerar(tmp_path / "saida", db=_base_estado(tmp_path), db_pcrj=_base_pcrj(tmp_path), pdf=False)
    assert out["linhas_anexo"] == sum(out["n_base"].values())
    assert all(p.endswith(".html") for p in out["arquivos"]) and len(out["arquivos"]) == 4  # principal + A1 + B1 + C


def test_csv_tem_uma_linha_por_contrato(tmp_path):
    res = pc.avaliar_prefeitura(_base_pcrj(tmp_path))
    destino = tmp_path / "x.csv"
    assert pc.escrever_csv(res, destino) == 5
    linhas = destino.read_text(encoding="utf-8-sig").splitlines()
    assert len(linhas) == 6 and "12345678901" not in destino.read_text(encoding="utf-8-sig")


def test_prefeitura(tmp_path):
    res = {r["id"]: r for r in pc.avaliar_prefeitura(_base_pcrj(tmp_path))}
    assert res["1"]["categoria"] == "A_MAIOR"
    assert res["1"]["fornecedor_doc"] == "123.***.***-01"     # CPF nunca sai em claro
    assert res["2"]["categoria"] == "A_MENOR_ENCERRADO"
    assert res["3"]["categoria"] == "INDETERMINADO" and res["3"]["motivo"] == "valor_contrato_ausente"
    assert all(r["esfera"] == "Prefeitura do Rio" for r in res.values())
    assert res["5"]["categoria"] == "INDETERMINADO" and res["5"]["motivo"] == "valor_desproporcional"
    q = res["4"]                                   # 2.008/2.191 dias desde 2021 → devido ≈ 549.931,54
    assert q["categoria"] == "CONFORME", q
    assert q["devido"] == pytest.approx(600_000.0 * 2008 / 2191, rel=1e-6)
