# -*- coding: utf-8 -*-
"""sancao_abrangencia — tipo + abrangência de cada sanção; se veda de fato o ente-alvo."""
from __future__ import annotations

import sqlite3

from compliance_agent import sancao_abrangencia as SA


def test_multa_e_publicacao_nao_vedam():
    assert SA.classificar_sancao("Multa")["veda_contratacao"] is False
    assert SA.classificar_sancao("Publicação extraordinária da decisão condenatória")["veda_contratacao"] is False
    assert SA.classificar_sancao("Advertência")["abrangencia"] == "nenhuma"


def test_inidoneidade_e_total():
    c = SA.classificar_sancao("Declaração de Inidoneidade com prazo determinado")
    assert c["veda_contratacao"] is True and c["abrangencia"] == "total"
    # também pela fundamentação (art. 87 IV) mesmo com categoria genérica
    c2 = SA.classificar_sancao("Sanção", "LEI 8666 - ART. 87, IV - inexecução")
    assert c2["abrangencia"] == "total"


def test_impedimento_e_ente_suspensao_e_orgao():
    imp = SA.classificar_sancao("Impedimento/proibição de contratar com prazo determinado")
    assert imp["abrangencia"] == "ente"
    susp = SA.classificar_sancao("Suspensão")
    assert susp["abrangencia"] == "orgao"


def test_ente_do_orgao_deriva_esfera():
    assert SA.ente_do_orgao("1º Grau - TRF2 / Seção Judiciária", "RJ")["esfera"] == "federal"
    assert SA.ente_do_orgao("Tribunal de Justiça do Estado de São Paulo", "SP")["esfera"] == "estadual"
    assert SA.ente_do_orgao("Prefeitura Municipal de Niterói", "RJ")["esfera"] == "municipal"


def test_veda_ente_inidoneidade_sempre_veda_rj():
    s = {"categoria": "Declaração de Inidoneidade sem prazo determinado",
         "orgao": "TRF2", "uf": "SP", "fundamentacao": ""}
    assert SA.veda_ente(s, "estadual", "RJ")["veda"] is True    # total alcança RJ


def test_veda_ente_impedimento_federal_nao_veda_estado_rj():
    # impedimento por órgão FEDERAL não proíbe contratar com o Estado do RJ
    s = {"categoria": "Impedimento/proibição de contratar com prazo determinado",
         "orgao": "Tribunal Regional Federal da 3ª Região", "uf": "SP", "fundamentacao": ""}
    v = SA.veda_ente(s, "estadual", "RJ")
    assert v["veda"] is False and "reputacional" in v["motivo"]


def test_veda_ente_impedimento_estadual_rj_veda():
    s = {"categoria": "Impedimento/proibição de contratar com prazo determinado",
         "orgao": "Controladoria-Geral do Estado do Rio de Janeiro", "uf": "RJ", "fundamentacao": ""}
    assert SA.veda_ente(s, "estadual", "RJ")["veda"] is True


def test_detalhar_lista_e_marca_veda(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT,
        categoria TEXT, data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT,
        fundamentacao TEXT)""")
    con.executemany("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("CEIS", "X", "E", "Multa", "2025-01-01", "2026-01-01", "Orgao Y", "RJ", "p1", ""),
        ("CEIS", "X", "E", "Impedimento/proibição de contratar com prazo determinado",
         "2025-01-01", "2027-01-01", "TRF3", "SP", "p2", ""),
        ("CEIS", "X", "E", "Declaração de Inidoneidade sem prazo determinado",
         "2025-01-01", "", "TCU", "DF", "p3", ""),
    ])
    con.commit()
    d = SA.detalhar("X", con, "estadual", "RJ")
    con.close()
    assert d["n"] == 3 and d["veda_contrato_alvo"] is True     # a inidoneidade veda
    # a inidoneidade (total) vem primeiro (veda=True), a multa por último (não veda)
    assert d["sancoes"][0]["tipo"] == "inidoneidade"
    multa = [s for s in d["sancoes"] if s["tipo"] == "multa"][0]
    assert multa["veda_alvo"] is False
    imp = [s for s in d["sancoes"] if s["tipo"] == "impedimento"][0]
    assert imp["veda_alvo"] is False                            # impedimento federal não veda RJ


# ── revisão cética 13/11/2026: fundamentação ANTES da categoria; abrangência declarada no CEIS ──

def test_lei_13019_art73_ii_nao_e_interdicao_total():
    # parceria com OSC suspensa por município: alcance do ente sancionador, não toda a Administração
    c = SA.classificar_sancao("Suspensão/Interdição das atividades com prazo determinado",
                              "ESTABELECE O REGIME JURÍDICO DAS PARCERIAS ENTRE A ADMINISTRAÇÃO PÚBLICA E AS "
                              "ORGANIZAÇÕES DA SOCIEDADE CIVIL. - ART. 73, II - ART. 73. PELA EXECUÇÃO DA PARCERIA")
    assert c["tipo"] == "suspensao" and c["abrangencia"] == "ente"
    s = {"categoria": "Declaração de Inidoneidade sem prazo determinado", "orgao": "Fundo Municipal Ficticio",
         "uf": "RJ", "fundamentacao": "LEI 13019 - ART. 73, II - SUSPENSÃO TEMPORÁRIA"}
    assert SA.veda_ente(s, "estadual", "RJ")["veda"] is False


def test_impedimento_com_base_no_art_87_iii_e_suspensao_so_no_orgao():
    c = SA.classificar_sancao("Impedimento/proibição de contratar com prazo determinado",
                              "LEI 8666 - ART. 87, III - PELA INEXECUÇÃO TOTAL OU PARCIAL DO CONTRATO")
    assert c["tipo"] == "suspensao" and c["abrangencia"] == "orgao"


def test_abrangencia_declarada_no_ceis_prevalece():
    base = {"categoria": "Impedimento/proibição de contratar com prazo determinado",
            "orgao": "Secretaria de Estado Ficticia", "uf": "RJ", "fundamentacao": ""}
    assert SA.veda_ente({**base, "abrangencia": "No órgão sancionador"}, "estadual", "RJ")["veda"] is False
    assert SA.veda_ente({**base, "abrangencia": "Em todos os Poderes da Esfera do órgão sancionador",
                         "esfera_sancionador": "ESTADUAL"}, "estadual", "RJ")["veda"] is True
    fed = {**base, "orgao": "Instituto Federal Ficticio", "abrangencia": "Todas as Esferas em todos os Poderes",
           "esfera_sancionador": "FEDERAL"}
    assert SA.veda_ente(fed, "estadual", "RJ")["veda"] is True
    # esfera declarada pela fonte vence o palpite pelo nome do órgão
    mun = {**base, "orgao": "Secretaria de Estado Ficticia", "esfera_sancionador": "MUNICIPAL",
           "abrangencia": "Em todos os Poderes da Esfera do órgão sancionador"}
    assert SA.veda_ente(mun, "estadual", "RJ")["veda"] is False
    # "na Esfera e no Poder": Judiciário estadual não alcança o Executivo
    jud = {**base, "orgao": "Tribunal de Justiça do Estado Ficticio", "esfera_sancionador": "ESTADUAL",
           "abrangencia": "Na Esfera e no Poder do órgão sancionador"}
    assert SA.veda_ente(jud, "estadual", "RJ")["veda"] is False


def test_abrangencia_declarada_nao_alarga_o_teto_da_lei():
    # CEIS real: "Inidoneidade" + Lei 13.019 art. 73, II + "Todas as Esferas" — a lei limita a suspensão à esfera
    # do ente sancionador; a declaração só pode ESTREITAR o alcance legal, nunca alargar
    s = {"categoria": "Declaração de Inidoneidade sem prazo determinado", "orgao": "Fundo Municipal Ficticio",
         "uf": "RJ", "fundamentacao": "PARCERIAS ... ORGANIZAÇÕES DA SOCIEDADE CIVIL. - ART. 73, II - ART. 73.",
         "abrangencia": "Todas as Esferas em todos os Poderes", "esfera_sancionador": "MUNICIPAL"}
    assert SA.veda_ente(s, "estadual", "RJ")["veda"] is False
    imp = {"categoria": "Impedimento/proibição de contratar com prazo determinado", "orgao": "Prefeitura Ficticia",
           "uf": "RS", "fundamentacao": "LEI 14133 - ART. 156, III - IMPEDIMENTO DE LICITAR E CONTRATAR",
           "abrangencia": "Todas as Esferas em todos os Poderes", "esfera_sancionador": "MUNICIPAL"}
    assert SA.veda_ente(imp, "estadual", "RJ")["veda"] is False
    # sem teto legal na fundamentação (cautelar penal), a declaração "todas as esferas" vale
    caut = {**imp, "fundamentacao": "CÓDIGO DE PROCESSO PENAL - ART. 319, VI", "esfera_sancionador": "FEDERAL"}
    assert SA.veda_ente(caut, "estadual", "RJ")["veda"] is True


def test_vigencia_na_data():
    s = {"data_inicio": "2026-01-01", "data_fim": "2026-06-30", "categoria": "Impedimento com prazo determinado"}
    assert SA.vigente_em(s, "2026-03-01") is True
    assert SA.vigente_em(s, "2026-07-01") is False
    assert SA.vigente_em(s, "2025-12-31") is False
    assert SA.vigente_em({"data_inicio": "2026-01-01", "data_fim": None,
                          "categoria": "Declaração de Inidoneidade sem prazo determinado"}, "2026-03-01") is True
    # "com prazo determinado" sem data final: vigência não se afirma
    assert SA.vigente_em({"data_inicio": "2026-01-01", "data_fim": None,
                          "categoria": "Impedimento/proibição de contratar com prazo determinado"},
                         "2026-03-01") is False
    assert SA.vigente_em({"data_inicio": None, "data_fim": None, "categoria": "x"}, "2026-03-01") is False
