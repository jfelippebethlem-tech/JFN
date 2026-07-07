# -*- coding: utf-8 -*-
"""Testes do sweep de fracionamento em lote (tools/sweep_fracionamento_tcerj.py).

Padrão da casa: contexto em dicts puros, sem rede/LLM; DB de fixture em tmp_path (não toca compliance.db).
"""
from __future__ import annotations

import sqlite3

from tools.sweep_fracionamento_tcerj import _inciso_valor, _tipo_obj, carregar_grupos, rodar_sweep


def _db_fixture(tmp_path, rows):
    db = tmp_path / "fixture.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE compras_diretas_tcerj (
        id TEXT, processo TEXT, sei_norm TEXT, ano_processo INT, valor REAL, objeto TEXT,
        afastamento TEXT, enquadramento_legal TEXT, unidade TEXT, fornecedor TEXT,
        item TEXT, quantidade REAL, valor_unitario REAL, ingerido_em TEXT)""")
    con.executemany(
        "INSERT INTO compras_diretas_tcerj (processo, ano_processo, valor, objeto, afastamento, unidade, fornecedor)"
        " VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def test_carregar_grupos_dedupe_por_processo(tmp_path):
    # 3 linhas de ITEM do MESMO processo (valor total repetido) → 1 contratação
    db = _db_fixture(tmp_path, [
        ("P-1/2024", 2024, 50_000.0, "material de escritório", "Dispensa de Licitação", "UG A", "EMP LTDA"),
        ("P-1/2024", 2024, 50_000.0, "material de escritório", "Dispensa de Licitação", "UG A", "EMP LTDA"),
        ("P-1/2024", 2024, 50_000.0, "material de escritório", "Dispensa de Licitação", "UG A", "EMP LTDA"),
        ("P-2/2024", 2024, 30_000.0, "material de escritório e papelaria", "Dispensa de Licitação", "UG A", "EMP LTDA"),
    ])
    grupos = carregar_grupos(db_path=db)
    assert list(grupos) == [("UG A", 2024)]
    contratacoes = grupos[("UG A", 2024)]
    assert len(contratacoes) == 2  # dedupe: 4 linhas → 2 processos
    assert {c["valor"] for c in contratacoes} == {50_000.0, 30_000.0}
    assert all(c["modalidade"] == "Dispensa de Licitação" for c in contratacoes)


def test_sweep_confirma_fracionamento_e_registra_processos(tmp_path):
    # 2 dispensas do mesmo objeto somando ACIMA do limite 2024 (compras: 59.906,02) → P4 forte (0.85)
    db = _db_fixture(tmp_path, [
        ("P-10/2024", 2024, 40_000.0, "aquisição de toner para impressoras", "Dispensa - Pequenas Compras", "UG B", "X LTDA"),
        ("P-11/2024", 2024, 35_000.0, "aquisição de toner para impressoras laser", "Dispensa - Pequenas Compras", "UG B", "Y LTDA"),
    ])
    achados = rodar_sweep(carregar_grupos(db_path=db))
    assert len(achados) == 1
    a = achados[0]
    assert a["status"] == "confirmado"
    assert a["score"] >= 0.85
    assert a["unidade"] == "UG B" and a["exercicio"] == 2024
    assert sorted(a["valores"]["processos_cluster"]) == ["P-10/2024", "P-11/2024"]
    # honestidade: sem LLM a previsibilidade fica nao_avaliavel (indício, não acusação)
    assert a["valores"]["previsibilidade"] == "nao_avaliavel"


def test_sweep_inexigibilidade_nao_conta_como_dispensa(tmp_path):
    # inexigibilidades somando acima do limite NÃO são fracionamento por valor (art. 75 I/II)
    db = _db_fixture(tmp_path, [
        ("P-20/2024", 2024, 40_000.0, "show artístico regional", "Inexigibilidade - 14.133/2021", "UG C", "A LTDA"),
        ("P-21/2024", 2024, 35_000.0, "show artístico regional gospel", "Inexigibilidade - 14.133/2021", "UG C", "B LTDA"),
    ])
    achados = rodar_sweep(carregar_grupos(db_path=db))
    assert achados == []


def test_sweep_extrai_multiplos_clusters_do_mesmo_grupo(tmp_path):
    # 2 clusters independentes de fracionamento na MESMA unidade/ano → 2 achados (loop de remoção)
    db = _db_fixture(tmp_path, [
        ("P-30/2024", 2024, 40_000.0, "aquisição de toner para impressoras", "Dispensa de Licitação", "UG D", "X"),
        ("P-31/2024", 2024, 35_000.0, "aquisição de toner para impressoras laser", "Dispensa de Licitação", "UG D", "Y"),
        ("P-32/2024", 2024, 45_000.0, "serviço de manutenção de elevadores predial", "Dispensa de Licitação", "UG D", "Z"),
        ("P-33/2024", 2024, 44_000.0, "serviço de manutenção de elevadores do prédio", "Dispensa de Licitação", "UG D", "W"),
    ])
    achados = rodar_sweep(carregar_grupos(db_path=db))
    assert len(achados) == 2
    procs = {p for a in achados for p in a["valores"]["processos_cluster"]}
    assert procs == {"P-30/2024", "P-31/2024", "P-32/2024", "P-33/2024"}


def test_inciso_valor_parse_formatos_reais_tcerj():
    # formatos reais observados em compras_diretas_tcerj.enquadramento_legal
    assert _inciso_valor("Lei nº 14.133/2021, Art. 75º, II") is True
    assert _inciso_valor("Lei n 14.133/2021, Art. 75, VIII") is False       # emergência ≠ por valor
    assert _inciso_valor("Em conformidade com o Inciso IV, do Art. 24 da lei 8666/93") is False
    assert _inciso_valor("LEI8666/93ART24II.") is True
    assert _inciso_valor("Lei 13.303/2016, Art. 29, II") is True
    assert _inciso_valor("Lei 13.303/2016, Art. 29, VII") is False
    assert _inciso_valor("LEI 8.666/93") is None                            # sem inciso → não parseável
    assert _inciso_valor(None) is None


def test_sweep_dispensa_emergencial_nao_e_fracionamento(tmp_path):
    # dispensas art. 75 VIII (emergência, R$ milhões) NÃO são fuga de teto por valor → sem achado P4
    db = _db_fixture(tmp_path, [
        ("P-40/2024", 2024, 60_000_000.0, "gestão hospitalar unidade norte", "Dispensa de Licitação", "UG E", "OS A"),
        ("P-41/2024", 2024, 55_000_000.0, "gestão hospitalar unidade sul", "Dispensa de Licitação", "UG E", "OS B"),
    ])
    con = sqlite3.connect(db)
    con.execute("UPDATE compras_diretas_tcerj SET enquadramento_legal='Lei n 14.133/2021, Art. 75, VIII'")
    con.commit(); con.close()
    assert rodar_sweep(carregar_grupos(db_path=db)) == []


def test_tipo_obj_obras_vs_compras():
    assert _tipo_obj("reforma predial e obra de engenharia") == "obras"
    assert _tipo_obj("aquisição de café") == "compras"
    assert _tipo_obj(None) == "compras"
