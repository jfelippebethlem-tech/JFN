# -*- coding: utf-8 -*-
"""Testes da triagem de DD priorizada por órgão (investigacao_orgao_dd).

Determinísticos: SQLite temporário com `ordens_bancarias` + motor `investigar` monkeypatchado
(graus fixos). Cobrem filtro PJ-only, ranqueamento por grau/score e coleta de processos SEI."""
import sqlite3

import compliance_agent.investigacao_orgao_dd as mod


def _db(tmp_path, linhas):
    """linhas: (ug, cpf, nome, valor, numero_sei, numero_processo, exercicio)"""
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ordens_bancarias (ug_codigo TEXT, favorecido_cpf TEXT, favorecido_nome TEXT, "
                "valor REAL, data_pagamento TEXT, numero_sei TEXT, numero_processo TEXT, exercicio TEXT)")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?,?,?,?)",
                    [(ug, cpf, nm, v, "2020-01-01", sei, proc, ex) for ug, cpf, nm, v, sei, proc, ex in linhas])
    con.commit()
    con.close()
    return p


def test_top_fornecedores_so_pj(tmp_path):
    p = _db(tmp_path, [
        ("030100", "11222333000181", "EMPRESA A", 500_000, "SEI-1", "", "2020"),
        ("030100", "44555666000172", "EMPRESA B", 900_000, "SEI-2", "", "2020"),
        ("030100", "12345678901", "PESSOA FISICA", 800_000, "", "PROC-X", "2020"),  # PF → fora
    ])
    forns = mod.top_fornecedores_pj("030100", top_n=10, db_path=p)
    assert [f["cnpj"] for f in forns] == ["44555666000172", "11222333000181"]  # ordenado por total desc, sem PF


def test_processos_do_fornecedor_distintos(tmp_path):
    p = _db(tmp_path, [
        ("030100", "11222333000181", "EMPRESA A", 100, "SEI-1", "", "2020"),
        ("030100", "11222333000181", "EMPRESA A", 200, "SEI-1", "", "2020"),  # dup
        ("030100", "11222333000181", "EMPRESA A", 300, "", "PROC-2", "2020"),
    ])
    procs = mod._processos_do_fornecedor("030100", "11222333000181", db_path=p)
    assert set(procs) == {"SEI-1", "PROC-2"}


def test_ranking_por_grau_e_processos(tmp_path, monkeypatch):
    p = _db(tmp_path, [
        ("030100", "11222333000181", "FACHADA SA", 500_000, "SEI-RED", "", "2020"),
        ("030100", "44555666000172", "REGULAR SA", 900_000, "SEI-OK", "", "2020"),
    ])

    def fake_investigar(cnpj, **kw):
        if cnpj == "11222333000181":
            return {"grau": "🔴", "score": 60, "n_indicios": 2, "n_confirmados": 1,
                    "hipoteses": [{"codigo": "H-SITUACAO", "status": "CONFIRMADO"}]}
        return {"grau": "🟢", "score": 0, "n_indicios": 0, "n_confirmados": 0, "hipoteses": []}

    monkeypatch.setattr(mod, "investigar", fake_investigar)
    out = mod.investigar_orgao("030100", top_n=10, db_path=p)
    # 🔴 vem antes do 🟢 mesmo recebendo menos
    assert out["ranking"][0]["cnpj"] == "11222333000181"
    assert out["ranking"][0]["grau"] == "🔴"
    # só o alvo (não-🟢) coleta processos; o 🟢 não
    assert out["ranking"][0]["processos_sei"] == ["SEI-RED"]
    assert out["ranking"][1]["processos_sei"] == []
    assert out["processos_prioritarios"] == ["SEI-RED"]
    assert len(out["alvos_prioritarios"]) == 1
    assert "SEI-RED" in mod.render_md(out)
    # rodízio é GATED em teste (db_path setado) → não toca o DB real
    assert out["rodizio"] is None


def test_render_md_mostra_rodizio_quando_indicio():
    out = {"ug": "170100", "resumo": "x", "ranking": [], "processos_prioritarios": [],
           "rodizio": {"indicio": True, "score": 74.1, "n_campeoes": 6, "n_anos": 8,
                       "alternancia": 0.714, "share_ring": 0.639,
                       "campeoes": [{"nome": "Solazer", "n_vitorias": 2}]}}
    md = mod.render_md(out)
    assert "Rodízio temporal" in md and "score 74.1" in md and "Solazer" in md
