# -*- coding: utf-8 -*-
"""Estrato VÍNCULO OB↔CONTRATO na fila do sweep (14/11/2026).

A perícia contábil deixa ~35 mil contratos INDETERMINADOS porque o processo de PAGAMENTO não está no acervo.
`compliance_agent.vinculo_ob_contrato fila` grava `data/sei_fila_vinculo_ob.json` (processos de pagamento
priorizados). A fila do sweep — a mesma que a VM-1 exporta para a VM-2 — consome essa lista como estrato
PRÓPRIO: depois do enfileirado à mão e da contratação direta grande, antes do resto; e com TETO de
participação (no máximo metade de cada lote), para não matar o resto da varredura.

Tudo sintético (repositório público): processos, CNPJs e valores inventados.
"""
from __future__ import annotations

import json
import sqlite3

import tools.sei_sweep as S
import tools.vm2_sweep_geral as G

N = S._norm_proc_global


def _rows(*procs):
    return [(p, 1, 1000.0) for p in procs]


# ── intercalação (ordem da fila) ──────────────────────────────────────────────────────────────────
def test_topo_fica_na_frente_e_estrato_alterna_com_o_resto():
    rows = _rows("SEI-700000/000001/2024", "SEI-800000/000001/2024", "SEI-900000/000001/2024", "SEI-800000/000002/2024", "SEI-900000/000002/2024", "SEI-900000/000003/2024", "SEI-800000/000003/2024")
    out = S._intercalar_estrato(rows, estrato=[N("SEI-900000/000001/2024"), N("SEI-900000/000002/2024"), N("SEI-900000/000003/2024")], topo={N("SEI-700000/000001/2024")},
                                fracao=0.5)
    assert [r[0] for r in out] == ["SEI-700000/000001/2024", "SEI-900000/000001/2024", "SEI-800000/000001/2024", "SEI-900000/000002/2024", "SEI-800000/000002/2024", "SEI-900000/000003/2024", "SEI-800000/000003/2024"]


def test_estrato_na_ordem_do_proprio_escore_nao_na_do_valor():
    rows = _rows("SEI-900000/000002/2024", "SEI-800000/000001/2024", "SEI-900000/000001/2024")
    out = S._intercalar_estrato(rows, estrato=[N("SEI-900000/000001/2024"), N("SEI-900000/000002/2024")], topo=set(), fracao=0.5)
    assert [r[0] for r in out] == ["SEI-900000/000001/2024", "SEI-800000/000001/2024", "SEI-900000/000002/2024"]


def test_nenhum_prefixo_passa_do_teto():
    rows = _rows(*[f"SEI-900000/{i:06d}/2024" for i in range(40)], *[f"SEI-800000/{i:06d}/2024" for i in range(15)])
    est = [N(f"SEI-900000/{i:06d}/2024") for i in range(40)]
    out = S._intercalar_estrato(rows, estrato=est, topo=set(), fracao=0.5)
    assert sorted(r[0] for r in out) == sorted(r[0] for r in rows), "reordena, nunca perde processo"
    for k in range(1, 31):                       # enquanto há resto, o estrato não passa de metade
        nv = sum(1 for r in out[:k] if N(r[0]) in set(est))
        assert nv <= (k + 1) // 2, (k, nv)


def test_sem_resto_o_estrato_completa_a_fila():
    """A cota limita concorrência, não trabalho: acabou o resto, o estrato segue."""
    rows = _rows("SEI-900000/000001/2024", "SEI-900000/000002/2024", "SEI-900000/000003/2024")
    out = S._intercalar_estrato(rows, estrato=[N(p) for p, *_ in rows], topo=set(), fracao=0.5)
    assert len(out) == 3


def test_teto_zero_desliga_o_estrato():
    rows = _rows("SEI-800000/000001/2024", "SEI-900000/000001/2024", "SEI-800000/000002/2024")
    assert S._intercalar_estrato(rows, estrato=[N("SEI-900000/000001/2024")], topo=set(), fracao=0) == rows


# ── teto no LOTE (depois do _pular, que tira o resto já lido e deixa o estrato, nunca arquivado) ──────────
def test_lote_respeita_metade_mesmo_quando_o_pular_comeu_o_resto():
    est = {N(f"SEI-900000/{i:06d}/2024") for i in range(10)}
    lote = _rows(*[f"SEI-900000/{i:06d}/2024" for i in range(7)], "SEI-800000/000001/2024")
    candidatos = lote + _rows("SEI-900000/000007/2024", "SEI-800000/000002/2024", "SEI-800000/000003/2024", "SEI-800000/000004/2024")
    out = S._teto_estrato_no_lote(lote, candidatos, est, max_n=8, fracao=0.5)
    assert len(out) == 8
    assert sum(1 for r in out if N(r[0]) in est) == 4
    assert {"SEI-800000/000001/2024", "SEI-800000/000002/2024", "SEI-800000/000003/2024", "SEI-800000/000004/2024"} <= {r[0] for r in out}


def test_lote_impar_arredonda_para_baixo():
    est = {N(f"SEI-900000/{i:06d}/2024") for i in range(5)}
    lote = _rows("SEI-900000/000000/2024", "SEI-900000/000001/2024", "SEI-900000/000002/2024", "SEI-800000/000001/2024", "SEI-800000/000002/2024")
    out = S._teto_estrato_no_lote(lote, lote + _rows("SEI-800000/000003/2024"), est, max_n=5, fracao=0.5)
    assert sum(1 for r in out if N(r[0]) in est) == 2 and len(out) == 5


def test_lote_sem_resto_disponivel_completa_com_estrato():
    est = {N(f"SEI-900000/{i:06d}/2024") for i in range(8)}
    lote = _rows(*[f"SEI-900000/{i:06d}/2024" for i in range(8)])
    out = S._teto_estrato_no_lote(lote, lote, est, max_n=8, fracao=0.5)
    assert len(out) == 8


# ── _fila de ponta a ponta, base sintética ───────────────────────────────────────────────────────────
def _ob(tmp_path, linhas):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, credor TEXT, nome_credor TEXT,"
                " valor REAL, status TEXT, ug_emitente TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,'12345678000199','',?,'Contabilizado','010100')",
                    linhas)
    con.commit()
    con.close()
    return p


def _ne(tmp_path, linhas):
    p = tmp_path / "d.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE cge_ne_credor (tipo_de_licitacao TEXT, processos_sei TEXT, historico TEXT)")
    con.executemany("INSERT INTO cge_ne_credor VALUES (?,?,?)", linhas)
    con.commit()
    con.close()
    return p


def _isola(monkeypatch, tmp_path, vinculo: list[str] | None, dirigidos=()):
    db = _ob(tmp_path, [
        ("SEI-080002/000001/2024", 90_000_000.0),   # resto, grande, unidade legível
        ("SEI-080002/000002/2024", 80_000_000.0),   # resto
        ("SEI-080002/000003/2024", 70_000_000.0),   # resto
        ("SEI-150013/000138/2026", 3_000_000.0),    # contratação direta grande
        ("SEI-210001/000500/2024", 10_000.0),       # vínculo (pequeno e de unidade nunca lida)
        ("SEI-210001/000600/2024", 20_000.0),       # vínculo
        ("SEI-310001/000700/2024", 5_000.0),        # enfileirado à mão
    ])
    ne = _ne(tmp_path, [("Inexigibilidade", '["SEI-150013/000138/2026"]', "x")])
    monkeypatch.setattr(S, "DB", db)
    monkeypatch.setattr(S, "DB_DADOS_ABERTOS", ne)
    monkeypatch.setattr(S, "_unidades_legiveis", lambda: {"080002"})
    monkeypatch.setattr(S, "_raizes_com_sinal_osint", lambda: set())
    monkeypatch.setattr(S, "_fila_com_lacuna_provada", lambda con: set())
    monkeypatch.setattr(S, "_dirigidos", lambda con: set(dirigidos))
    monkeypatch.setattr(S, "fatia_desta_maquina", lambda: (0, 1))
    alvo = tmp_path / "sei_fila_vinculo_ob.json"
    if vinculo is not None:
        alvo.write_text(json.dumps([{"sei": p, "score": 1.0, "tipo": "VINCULO_OB"} for p in vinculo]),
                        encoding="utf-8")
    monkeypatch.setattr(S, "FILA_VINCULO_OB", alvo)


def test_fila_poe_o_vinculo_depois_da_direta_e_antes_do_resto(tmp_path, monkeypatch):
    _isola(monkeypatch, tmp_path, ["SEI-210001/000600/2024", "SEI-210001/000500/2024"],
           dirigidos={"SEI-310001/000700/2024"})
    fila = [r[0] for r in S._fila(None, 50)]
    assert fila[:2] == ["SEI-310001/000700/2024", "SEI-150013/000138/2026"], "à mão e direta grande na frente"
    assert fila[2] == "SEI-210001/000600/2024", "o estrato abre logo depois, na ordem do escore dele"
    assert fila[3] == "SEI-080002/000001/2024", "teto: o resto não é empurrado para o fim"
    assert fila[4] == "SEI-210001/000500/2024"
    assert S._ESTRATOS["vinculo"] == {N("SEI-210001/000600/2024"), N("SEI-210001/000500/2024")}
    assert N("SEI-310001/000700/2024") in S._ESTRATOS["topo"]


def test_sem_o_arquivo_a_fila_e_a_de_antes(tmp_path, monkeypatch):
    _isola(monkeypatch, tmp_path, None)
    fila = [r[0] for r in S._fila(None, 50)]
    assert fila[:4] == ["SEI-150013/000138/2026", "SEI-080002/000001/2024", "SEI-080002/000002/2024",
                        "SEI-080002/000003/2024"]
    assert S._ESTRATOS["vinculo"] == set()


def test_arquivo_ilegivel_nao_quebra(tmp_path, monkeypatch):
    _isola(monkeypatch, tmp_path, None)
    (tmp_path / "sei_fila_vinculo_ob.json").write_text("{quebrado", encoding="utf-8")
    assert len(S._fila(None, 50)) == 7


def test_filtro_por_ug_nao_usa_o_estrato(tmp_path, monkeypatch):
    _isola(monkeypatch, tmp_path, ["SEI-210001/000500/2024"])
    S._fila("010100", 50)
    assert S._ESTRATOS["vinculo"] == set()


# ── exportação VM-1 → VM-2 leva o estrato junto ──────────────────────────────────────────────────────
def test_exportar_marca_o_estrato_e_rodar_le_os_dois_formatos(tmp_path, monkeypatch):
    _isola(monkeypatch, tmp_path, ["SEI-210001/000600/2024"], dirigidos={"SEI-310001/000700/2024"})
    monkeypatch.setenv("JFN_SWEEP_FATIA", "0/1")      # exportar fixa 1/2 no ambiente; o monkeypatch o devolve
    rows = G.exportar(50)
    marca = {r[0]: r[3] for r in rows}
    assert marca["SEI-210001/000600/2024"] == "vinculo"
    assert marca["SEI-310001/000700/2024"] == "topo"
    assert marca["SEI-080002/000001/2024"] == ""
    S._ESTRATOS["vinculo"], S._ESTRATOS["topo"] = set(), set()
    fila = G.carregar_fila(rows + [["SEI-999999/000001/2024", 1, 1.0]])   # linha antiga (3 campos) vale
    assert all(len(x) == 3 for x in fila)
    assert S._ESTRATOS["vinculo"] == {N("SEI-210001/000600/2024")}
    assert N("SEI-310001/000700/2024") in S._ESTRATOS["topo"]
