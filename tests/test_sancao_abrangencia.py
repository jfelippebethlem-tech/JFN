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
