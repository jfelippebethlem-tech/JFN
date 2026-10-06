# -*- coding: utf-8 -*-
"""OCP R052 (22/09/2026): compra pequena seguida de compra muito maior, cerca de Tukey, grau pela forma do 1º."""
from __future__ import annotations

import sqlite3

from tools.pcrj_ocp_redflags import calcular, cerca_tukey, graduar_r052, listar, pares


def test_cerca_de_tukey_e_graduacao():
    assert cerca_tukey([1, 2, 3]) is None
    assert cerca_tukey([0, 1, 1, 1, 2, 2, 3, 3]) == 3 + 1.5 * (3 - 1)
    assert graduar_r052("Contratação Direta - Dispensa", 47) == "🔴"
    assert graduar_r052("Contratação Direta - Dispensa", 900) == "🟡"
    assert graduar_r052("Licitação - Pregão", 10) == "🟡"


def test_pares_ordenam_por_inicio_e_separam_orgao():
    cs = [{"contrato": "2", "favorecido_doc": "X", "orgao": "1601 - SME", "valor_atualizado": 9e7, "vigencia_ini": "01/06/2025"},
          {"contrato": "1", "favorecido_doc": "X", "orgao": "1601 - SME", "valor_atualizado": 4e6, "vigencia_ini": "15/04/2025"},
          {"contrato": "3", "favorecido_doc": "X", "orgao": "1803 - FMS", "valor_atualizado": 1e6, "vigencia_ini": "01/01/2025"}]
    ps = pares(cs)
    assert len(ps) == 1 and ps[0][0]["contrato"] == "1" and ps[0][1]["contrato"] == "2"


def test_calcular_marca_o_fornecedor_teste_e_ignora_estatal(tmp_path):
    db = tmp_path / "pcrj.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE contasrio_contrato (contrato, favorecido_doc, favorecido_nome, orgao, ano, forma_contratacao, valor_atualizado, vigencia_ini, data_publicacao, processo)")
    linhas = [("A1", "11", "AVANTY LTDA", "1601 - SME", 2025, "Contratação Direta - Dispensa", 3.8e6, "15/04/2025", None, "P1"),
              ("A2", "11", "AVANTY LTDA", "1601 - SME", 2025, "Licitação - Pregão", 72.6e6, "01/06/2025", None, "P2"),
              ("C1", "22", "EMPRESA BRASILEIRA DE CORREIOS", "2901 - X", 2025, "Contratação Direta - Inexigibilidade", 6e5, "01/01/2025", None, "P3"),
              ("C2", "22", "EMPRESA BRASILEIRA DE CORREIOS", "2901 - X", 2025, "Contratação Direta - Inexigibilidade", 1e8, "01/01/2025", None, "P4")]
    linhas += [("S1", "33", "PLACEHOLDER LTDA", "1803 - FMS", 2025, "Contratação Direta - Dispensa", 1.0, "01/01/2025", None, "P5"),
               ("S2", "33", "PLACEHOLDER LTDA", "1803 - FMS", 2025, "Licitação - Pregão", 3e6, "01/03/2025", None, "P6"),
               ("D1", "44", "MESMO DIA LTDA", "1601 - SME", 2025, "Contratação Direta - Inexigibilidade", 2e4, "02/01/2024", None, "P7"),
               ("D2", "44", "MESMO DIA LTDA", "1601 - SME", 2025, "Contratação Direta - Inexigibilidade", 1.3e7, "02/01/2024", None, "P8")]
    for i in range(10):   # base para a cerca: pares de razão ~1
        linhas += [(f"N{i}a", f"n{i}", f"NORMAL {i}", "1101 - CASA", 2025, "Licitação - Pregão", 1e6, "01/01/2025", None, None),
                   (f"N{i}b", f"n{i}", f"NORMAL {i}", "1101 - CASA", 2025, "Licitação - Pregão", 1.2e6, "01/03/2025", None, None)]
    c.executemany("INSERT INTO contasrio_contrato VALUES (?,?,?,?,?,?,?,?,?,?)", linhas)
    c.commit(); c.close()
    r = calcular(db)
    assert r["sinais_r052"]["🔴"] == 1
    s = listar(5, db)
    assert len(s) == 1 and s[0]["contrato_2"] == "A2" and s[0]["dias"] == 47 and "19.1×" in s[0]["detalhe"]
