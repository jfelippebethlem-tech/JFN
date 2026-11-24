"""Linha de base da refatoração (O1.3): cada número com a consulta e o estado; INDISPONÍVEL ≠ 0."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest

from tools import baseline_refatoracao as B


@pytest.fixture
def banco(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE ordens_bancarias(id INTEGER PRIMARY KEY, data_emissao TEXT);
        INSERT INTO ordens_bancarias(data_emissao) VALUES ('2026-09-30'), ('2026-10-01');
        CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, status TEXT);
        INSERT INTO alertas(tipo, status) VALUES ('a', 'novo'), ('a', 'descartado'), ('b', 'novo');
        CREATE TABLE pericia_integral(id INTEGER PRIMARY KEY, processo TEXT, eixo TEXT, provedor TEXT,
          modelo TEXT, conferido_opus INTEGER);
        INSERT INTO pericia_integral(processo, eixo, provedor, modelo, conferido_opus) VALUES
          ('p1', '_global', 'gemini', 'g', 0), ('p1', 'A', 'gemini', 'g', 0),
          ('p2', '_global', 'claude', 'c', 1), ('p3', '_global', 'openrouter', 'o', 0);
        CREATE TABLE decisoes_tce(id INTEGER PRIMARY KEY, created_at TEXT);
    """)
    con.commit()
    con.close()
    return p


def _u(tmp_path, comp, agora=datetime(2026, 11, 24, 12, 0, 0)):
    return {"nome": "teste", "agora": agora, "imutavel": False, "compliance": comp,
            "opus": tmp_path / "conferencia_opus.db", "propagacao": tmp_path / "propagacao.db", "pg_dump": None}


def _por_id(ms):
    return {m["id"]: m for m in ms}


def test_medir_sql_mede_e_registra_a_consulta(banco):
    con = B.abrir_sqlite(banco, imutavel=False)
    m = B.medir_sql(con, "x", "SELECT COUNT(*) FROM alertas", grupo="g", origem="o")
    assert (m["estado"], m["valor"], m["consulta"]) == (B.MEDIDO, 3, "SELECT COUNT(*) FROM alertas")


def test_tabela_ausente_e_indisponivel_nunca_zero(banco):
    con = B.abrir_sqlite(banco, imutavel=False)
    m = B.medir_sql(con, "x", "SELECT COUNT(*) FROM nao_existe", grupo="g", origem="o")
    assert m["estado"] == B.INDISPONIVEL and m["valor"] is None
    assert "no such table" in m["motivo"]


def test_banco_que_nao_abre_e_indisponivel(tmp_path):
    assert B.abrir_sqlite(tmp_path / "nada.db", imutavel=True) is None
    m = B.medir_sql(None, "x", "SELECT 1", grupo="g", origem="o")
    assert m["estado"] == B.INDISPONIVEL and m["valor"] is None


def test_compliance_sintetico(tmp_path, banco):
    ms = _por_id(B.medir_compliance(_u(tmp_path, banco)))
    assert ms["tabela.ordens_bancarias.linhas"]["valor"] == 2
    assert ms["alertas.por_status"]["valor"] == {"descartado": 1, "novo": 2}
    assert ms["pericia.laudos"]["valor"] == 3
    assert ms["pericia.laudos_cascata"]["valor"] == 2                 # gemini + openrouter
    assert ms["pericia.frac_laudos_cascata"]["valor"] == round(2 / 3, 4)
    assert ms["pericia.frac_laudos_conferidos_opus"]["valor"] == round(1 / 3, 4)
    assert ms["frescor.tfe_ob"]["valor"] == "2026-10-01"
    # tabela que não existe no banco sintético: INDISPONIVEL, nunca 0
    for mid in ("tabela.lex_execucao.linhas", "tabela.sei_fila_captura.linhas", "frescor.siafe_ob"):
        assert ms[mid]["estado"] == B.INDISPONIVEL and ms[mid]["valor"] is None, mid
    # tabela existe mas vazia: frescor sem valor também é INDISPONIVEL
    assert ms["frescor.tce_decisoes"]["estado"] == B.INDISPONIVEL
    assert all(not (m["estado"] == B.MEDIDO and m["valor"] is None) for m in ms.values() if m["grupo"] == "frescor")


def test_universo_sem_banco_nao_vira_zero(tmp_path):
    ms = B.medir_compliance(_u(tmp_path, tmp_path / "sumiu.db"))
    assert ms and all(m["estado"] == B.INDISPONIVEL and m["valor"] is None for m in ms)


def test_derivada_propaga_indisponivel():
    a = B.metrica("a", 1, consulta="q", grupo="g")
    b = B.indisponivel("b", "falhou", grupo="g")
    zero = B.metrica("z", 0, consulta="q", grupo="g")
    assert B.derivada("r", a, b, grupo="g", descricao="")["estado"] == B.INDISPONIVEL
    assert B.derivada("r", a, zero, grupo="g", descricao="")["estado"] == B.INDISPONIVEL
    assert B.derivada("r", a, B.metrica("d", 4, consulta="q", grupo="g"), grupo="g", descricao="")["valor"] == 0.25


def test_opus_janela_de_7_dias_no_agora_do_universo_com_iso_T(tmp_path):
    p = tmp_path / "conferencia_opus.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE fila(id INTEGER PRIMARY KEY, tarefa TEXT, status TEXT, criado_em TEXT, "
                "conferido_em TEXT, concorda INTEGER)")
    con.executemany("INSERT INTO fila(tarefa, status, criado_em, conferido_em, concorda) VALUES (?,?,?,?,?)", [
        ("t", "pendente", "2026-11-23T10:00:00", None, None),          # dentro
        ("t", "conferido", "2026-11-20T10:00:00", "2026-11-22T09:00:00", 1),
        ("t", "conferido", "2026-11-01T10:00:00", "2026-11-02T10:00:00", 0),   # fora da janela
        ("t", "pendente", "2026-11-25T10:00:00", None, None),          # depois do "agora": fora
    ])
    con.commit()
    con.close()
    ms = _por_id(B.medir_opus(_u(tmp_path, tmp_path / "x.db")))
    assert ms["opus.entradas_7d"]["valor"] == 2
    assert ms["opus.saidas_7d"]["valor"] == 1
    assert ms["opus.pendentes"]["valor"] == 2
    assert ms["opus.concordancia"]["valor"] == 0.5


def test_opus_sem_banco_e_indisponivel(tmp_path):
    ms = B.medir_opus(_u(tmp_path, tmp_path / "x.db"))
    assert all(m["estado"] == B.INDISPONIVEL for m in ms)


def test_resumir_copy_do_pg_restore():
    texto = [
        "SET statement_timeout = 0;",
        "COPY public.leituras (processo, estagio, versao, em) FROM stdin;",
        "p1\ta\tv1\t2026-11-23 10:00:00",
        "p1\tb\tv1\t2026-11-23 11:00:00",
        "p2\ta\tv1\t\\N",
        "\\.",
        "COPY public.jobs (id, tipo, chave) FROM stdin;",
        "\\.",
    ]
    r = B.resumir_copy(texto)
    assert r["leituras"] == {"linhas": 3, "processos": 2, "max_em": "2026-11-23 11:00:00"}
    assert r["jobs"] == {"linhas": 0, "processos": None, "max_em": None}


def test_avaliar_detectores():
    reg = {"detectores": {
        "a": {"manchete": True, "fp_medida": None, "controle_positivo": "t::p", "controle_negativo": None},
        "b": {"manchete": True, "fp_medida": 0.1, "controle_positivo": None, "controle_negativo": "t::n"},
        "c": {"manchete": False, "fp_medida": None},
    }}
    assert B.avaliar_detectores(reg) == {"total": 3, "sem_fp_medida": 2, "manchetes": 2, "manchetes_sem_fp_medida": 1,
                                         "sem_controle_positivo": 2, "sem_controle_negativo": 2}


def test_captura_sei_corta_no_agora(tmp_path):
    arq = tmp_path / "rodadas.jsonl"
    linhas = [
        {"ts": "2026-11-22 10:00:00", "procs": {"p1": {"status": "ok", "segundos": 10, "arvore": "h1"}}},
        {"ts": "2026-11-23 10:00:00", "procs": {"p1": {"status": "ok", "segundos": 30, "arvore": "h1"},
                                                "p2": {"status": "sem_arvore", "segundos": 5}}},
        {"ts": "2026-11-25 10:00:00", "procs": {"p9": {"status": "ok", "segundos": 99, "arvore": "x"}}},
    ]
    arq.write_text("\n".join(json.dumps(x) for x in linhas) + "\nlinha corrompida\n")
    ms = _por_id(B.medir_captura_sei(_u(tmp_path, tmp_path / "x.db"), arq))
    assert ms["captura.rodadas"]["valor"] == 2                        # a de 25/11 fica fora
    assert ms["captura.processos_distintos_por_dia"]["valor"] == 1.0  # {p1, p2} ÷ 2 dias
    assert ms["captura.frac_recaptura_igual"]["valor"] == 0.5         # 1 de 2 capturas ok
    assert ms["captura.frac_tempo_recaptura_igual"]["valor"] == 0.75  # 30 s de 40 s


def test_captura_sem_log_e_indisponivel(tmp_path):
    ms = B.medir_captura_sei(_u(tmp_path, tmp_path / "x.db"), tmp_path / "nada.jsonl")
    assert ms and all(m["estado"] == B.INDISPONIVEL for m in ms)


def test_comparar_ignora_dinamicas():
    a = {"metricas": [B.metrica("s", 1, consulta="q", grupo="g"),
                      B.metrica("d", 5, consulta="q", grupo="g", dinamico=True)]}
    b = {"metricas": [B.metrica("s", 1, consulta="q", grupo="g"),
                      B.metrica("d", 9, consulta="q", grupo="g", dinamico=True)]}
    assert B.comparar(a, b) == []
    b["metricas"][0] = B.indisponivel("s", "falhou", grupo="g")
    assert B.comparar(a, b) and "s:" in B.comparar(a, b)[0]


def test_interpretar_linux_so_chaves_conhecidas():
    v = B.interpretar_linux("NPROC 2\nLOAD 1.0 2.0 3.0\nPSI_cpu 55.7\nSWAP 3200 4095\nDISCO 70\nDRIVE_C 1 2\nlixo\n")
    assert v == {"nproc": 2, "load": [1.0, 2.0, 3.0], "psi_cpu_some_avg300": 55.7, "swap_usado_mb": 3200,
                 "swap_total_mb": 4095, "disco_pct": 70.0}


def test_agora_do_snapshot(tmp_path):
    (tmp_path / "estado.log").write_text("2026-11-24 12:24:31 inicio\n2026-11-24 12:39:07 FIM\n")
    assert B.agora_do_snapshot(tmp_path) == datetime(2026, 11, 24, 12, 24, 31)
    assert B.agora_do_snapshot(tmp_path / "nada") is None
