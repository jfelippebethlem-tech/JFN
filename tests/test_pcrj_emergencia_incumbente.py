# -*- coding: utf-8 -*-
"""Emergência à incumbente (17/09/2026): fundamento lido × contrato anterior no mesmo órgão × certame × prorrogação."""
from __future__ import annotations

import sqlite3

from tools.pcrj_emergencia_incumbente import calcular, eh_emergencia, graduar, incumbencia, listar


def test_fundamento_de_emergencia():
    assert eh_emergencia(["art. 124 Lei 14.133/2021", "Art. 75, inciso VIII Lei 14.133/2021"]).startswith("Art. 75")
    assert eh_emergencia(["art. 24, IV Lei 8.666/93"]) is not None
    assert eh_emergencia(["art. 75, inciso IX Lei 14.133/2021", "art. 74, I Lei 14.133/2021"]) is None


def test_incumbencia_exige_contrato_anterior_no_mesmo_orgao_dentro_da_janela():
    ant = [{"contrato": "A", "vigencia_ini": "01/07/2022", "vigencia_fim": "30/06/2024"},
           {"contrato": "B", "vigencia_ini": "01/01/2019", "vigencia_fim": "31/12/2019"}]
    inc = incumbencia(ant, "01/07/2025")
    assert inc and inc["contrato"] == "A"          # B terminou há mais de 2 anos
    assert incumbencia(ant, "01/07/2027") is None
    assert incumbencia([], "01/07/2025") is None and incumbencia(ant, None) is None


def test_graduacao():
    assert graduar(None, {"contrato": "A"}, "90209/2025", True) is None
    assert graduar("art. 75, VIII", {"contrato": "A"}, "90209/2025", False) == "🔴"
    assert graduar("art. 75, VIII", {"contrato": "A"}, None, True) == "🔴"
    assert graduar("art. 75, VIII", {"contrato": "A"}, None, False) == "🟡"
    assert graduar("art. 75, VIII", None, "x", True) == "⚪"


def test_calcular_no_caso_agile(tmp_path):
    db = tmp_path / "pcrj.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE contasrio_contrato (contrato, favorecido_doc, favorecido_nome, orgao, ug, ano, numero_instrumento, data_publicacao,
        objeto, situacao, vigencia_ini, vigencia_fim, processo, forma_contratacao, valor_atualizado, total_pago, url_ccon);
    INSERT INTO contasrio_contrato VALUES ('2509437','00801512000157','AGILE CORP','1601 - SME','x',2025,'167/2025','01/07/2025','merenda',
        'Vencida','01/01/2026','30/06/2026','SME-PRO-2025/38233','Contratação Direta - Dispensa',24000000,23633526.63,NULL);
    INSERT INTO contasrio_contrato VALUES ('2409356','00801512000157','AGILE CORP','1601 - SME','x',2024,'x','x','merenda','Assinado',
        '01/01/2024','31/12/2025','SME-PRO-2023/59040','Licitação - Pregão',300000000,66000000,NULL);
    CREATE TABLE pcrj_doc_campos (numero_processo, seq, campo, valor, trecho, lido_em);
    INSERT INTO pcrj_doc_campos VALUES ('SME-PRO-2025/38233',12408,'fundamento','Art. 75, inciso VIII Lei 14.133/2021','t','x');
    INSERT INTO pcrj_doc_campos VALUES ('SME-PRO-2025/38233',12408,'pregao','90209/2025','t','x');
    INSERT INTO pcrj_doc_campos VALUES ('SME-PRO-2025/38233',3618,'termo_aditivo','1º TA 119/2025','t','x');
    CREATE TABLE pcrj_processo_doc (numero_processo, seq, tipo, titulo, texto, url, coletado_em);
    INSERT INTO pcrj_processo_doc VALUES ('SME-PRO-2025/38233',12408,'ccon_termo_de_referencia','TR',
        'TERMO DE REFERÊNCIA … DISPENSA DE LICITAÇÃO POR EMERGÊNCIA, com fundamento legal no art. 75, inciso VIII, da Lei Federal nº 14.133/2021 … processo administrativo SME-PRO- 2025/38233','u','x');
    """)
    c.commit(); c.close()
    r = calcular(db)
    assert r["sinais"]["🔴"] == 1
    s = listar(5, db)[0]
    assert s["grau"] == "🔴" and s["incumbente_contrato"] == "2409356" and s["certame_citado"] == "90209/2025" and s["prorrogada"] == 1


def test_fundamento_do_vizinho_na_pagina_do_diario_nao_conta():
    from tools.pcrj_emergencia_incumbente import fundamento_ancorado
    # página COLETIVA do D.O.: quatro extratos, só o último é emergência
    pagina = ("EXTRATO Processo 005600.000386/2026-51 Partes: GEO-RIO e R T C ENGENHARIA Objeto: contenção. Fundamento: art. 74, I "
              "da Lei 14.133/2021. Valor R$ 1,00. " + "x" * 200 +
              " EXTRATO Processo 005600.000111/2026-11 Partes: GEO-RIO e A LTDA. Fundamento: art. 74, III. " + "y" * 200 +
              " EXTRATO Processo 005600.000222/2026-22 Partes: GEO-RIO e B LTDA. Fundamento: art. 74, I. " + "z" * 200 +
              " EXTRATO Processo 005600.000999/2026-00 Partes: GEO-RIO e OUTRA LTDA Objeto: ventilação, conforme o que preceitua o "
              "Art. 75, Inciso VIII da Lei 14.133/2021 e AUTORIZO.")
    assert fundamento_ancorado(pagina, "005600.000386/2026-51") is None          # o 75, VIII é do vizinho
    assert fundamento_ancorado(pagina, "005600.000999/2026-00").startswith("Art. 75")
    # documento próprio do contrato (não coletivo): aceita mesmo sem o número, ou com o número quebrado na linha
    assert fundamento_ancorado("com base no art. 75, VIII da Lei 14.133", "X") is not None
    assert fundamento_ancorado("TR … art. 75, inciso VIII … processo SME-PRO- 2025/38233", "SME-PRO-2025/38233") is not None
