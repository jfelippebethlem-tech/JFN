# -*- coding: utf-8 -*-
"""A vigência do contrato faltava em 100% dos processos — e o dado existia o tempo todo.

Medido em 2026-08-04 sobre os 2.174 processos avaliados: `vigencia_inicio`/`vigencia_fim_atual`
estavam ausentes em TODOS, e com isso o **X2** (teto de 60 meses, art. 57) nunca avaliou nada. Não
era detector quebrado nem dado inexistente: era FIO SOLTO. A tabela `contratos_tcerj` guarda
`vig_inicio`/`vig_fim`, o `varredura_execucao_ctx` já a usa no caminho do TCE — e o caminho do SEI
não a consultava.

São **195 processos** com contrato registrado. Em amostra de 60, o X2 passou a avaliar em 52.

⚠️ O X8 (termo retroativo) continua `nao_avaliavel` DE PROPÓSITO: ele pede a vigência ORIGINAL, e
`contratos_tcerj` guarda um único par de datas sem distinguir a original da já prorrogada. Medir
retroatividade contra a baseline errada é pior do que não medir.
"""
import sqlite3

import pytest

from compliance_agent import processo_360 as P


def _db(tmp_path, linhas):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE contratos_tcerj (sei_norm TEXT, vig_inicio TEXT, vig_fim TEXT, "
                "valor_contrato REAL)")
    for l in linhas:
        con.execute("INSERT INTO contratos_tcerj VALUES (?,?,?,?)", l)
    con.commit(); con.close()
    return p


def test_liga_vigencia_e_valor_pelo_numero_do_processo(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_DB", _db(tmp_path, [
        ("0700020009912022", "10/02/2023", "10/05/2025", 69_792_944.31)]))
    r = P._contrato_registrado("SEI-070002/000991/2022")
    assert r["vigencia_inicio"] == "10/02/2023"
    assert r["vigencia_fim_atual"] == "10/05/2025"
    assert r["valor_contrato_registrado"] == 69_792_944.31
    assert "contratos_tcerj" in r["fonte_contrato_registrado"]


def test_NAO_preenche_vigencia_fim_que_o_X8_espera(tmp_path, monkeypatch):
    """O X8 pede a vigência ORIGINAL; a tabela não a distingue da prorrogada. Alimentar o campo
    faria o detector medir retroatividade contra a baseline errada."""
    monkeypatch.setattr(P, "_DB", _db(tmp_path, [
        ("0700020009912022", "10/02/2023", "10/05/2025", 1.0)]))
    assert "vigencia_fim" not in P._contrato_registrado("SEI-070002/000991/2022")


def test_processo_sem_contrato_registrado_devolve_vazio(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_DB", _db(tmp_path, []))
    assert P._contrato_registrado("SEI-070002/000991/2022") == {}


def test_base_ausente_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_DB", tmp_path / "nao_existe.db")
    assert P._contrato_registrado("SEI-070002/000991/2022") == {}


def test_numero_sem_digitos_nao_consulta(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_DB", _db(tmp_path, [("0700020009912022", "a", "b", 1.0)]))
    assert P._contrato_registrado("") == {}


@pytest.mark.slow
def test_no_acervo_real_o_X2_passa_a_avaliar():
    """Catraca: se o fio se soltar de novo, o X2 volta a nunca avaliar e ninguém percebe."""
    import pathlib
    db = pathlib.Path.home() / "JFN" / "data" / "compliance.db"
    if not db.exists():
        pytest.skip("compliance.db ausente")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        n = con.execute(
            "SELECT COUNT(DISTINCT p.numero_sei) FROM processo_avaliacao p "
            "JOIN contratos_tcerj t ON t.sei_norm = "
            "replace(replace(p.numero_sei,'/',''),'SEI-','')").fetchone()[0]
    finally:
        con.close()
    assert n >= 100, f"só {n} processos ligados ao contrato registrado — a ligação regrediu"
