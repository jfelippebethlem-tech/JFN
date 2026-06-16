#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sei_direcionamento_varre — MEMÓRIA CRUZADA de direcionamento por fornecedor (acumula a cada sweep).

Agrega, por fornecedor, TODAS as suas árvores SEI (`sei_arvore` + `sei_ficha`): nº de árvores, total pago,
red_flags acumuladas (dedup), risco máximo, lifecycle. Calcula um SCORE heurístico conservador (indício
interno, NUNCA acusação) e persiste em **`sei_direcionamento`** — assim o Lex "aprende num processo e volta
em outro" (revisita o fornecedor com o histórico inteiro à mão).

Filosofia: barato (pura agregação SQL, SEM LLM em massa) · recomputa a cada sweep · NÃO duplica `/api/cartel`
nem `investigacao_orgao_dd` (lá é GRUPO econômico/sócios; aqui é FORNECEDOR × processos SEI). O LLM
`direcionamento_cerebro.avaliar_direcionamento` fica on-demand, só p/ os top-score (não em milhares).

Uso: PYTHONPATH=. .venv/bin/python -m tools.sei_direcionamento_varre [--top N]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "compliance.db"

_DDL = """
CREATE TABLE IF NOT EXISTS sei_direcionamento (
  fornecedor_cnpj TEXT PRIMARY KEY,
  fornecedor_nome TEXT,
  n_arvores       INTEGER,
  total_pago      REAL,
  red_flags       TEXT,   -- JSON (dedup) das red_flags acumuladas nas árvores do fornecedor
  risco_max       TEXT,
  n_encerrado     INTEGER,
  n_ativo         INTEGER,
  score           INTEGER, -- 0-100 INDÍCIO interno (recorrência+risco+red_flags+valor); indício≠acusação
  arvores         TEXT,    -- JSON [numero_sei,...] p/ o Lex revisitar
  atualizado_em   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_sei_direc_score ON sei_direcionamento(score);
"""

_RISCO_PESO = {"alto": 3, "médio": 2, "medio": 2, "baixo": 1, "": 0}


def _score(n_arv: int, total: float, n_rf: int, risco_max: str) -> int:
    """Heurística transparente, conservadora (0-100). Recorrência + valor + red_flags + risco. Indício interno."""
    s = 0
    s += min(n_arv, 10) * 4          # recorrência do fornecedor em processos SEI (até 40)
    s += min(int(total / 1_000_000), 20)  # R$ (1 ponto/milhão, teto 20)
    s += min(n_rf, 10) * 3           # red_flags acumuladas (até 30)
    s += _RISCO_PESO.get((risco_max or "").lower(), 0) * 3  # risco (até 9)
    return min(s, 100)


def varrer() -> dict:
    if not DB.exists():
        return {"erro": "compliance.db ausente"}
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(_DDL)
    # red_flags por processo (sei_ficha)
    rf_por_proc: dict[str, list] = {}
    try:
        for numero, rfj in con.execute("SELECT numero_sei, red_flags FROM sei_ficha WHERE red_flags<>'[]' AND red_flags IS NOT NULL"):
            try:
                rf_por_proc[numero] = json.loads(rfj) or []
            except Exception:  # noqa: BLE001
                pass
    except sqlite3.OperationalError:
        pass
    # agrega por fornecedor a partir das árvores
    forn: dict[str, dict] = {}
    for numero, fjson, risco, life in con.execute(
            "SELECT numero_sei, fornecedores, nivel_risco, lifecycle FROM sei_arvore"):
        try:
            fornecedores = json.loads(fjson or "[]")
        except Exception:  # noqa: BLE001
            fornecedores = []
        # red_flags da árvore: tenta casar pelo nº (com/sem prefixo)
        rfs = rf_por_proc.get(numero) or rf_por_proc.get(numero.replace("SEI-", "")) or []
        for f in fornecedores:
            cnpj = (f.get("cnpj") or "").strip()
            if not cnpj:
                continue
            e = forn.setdefault(cnpj, {"nome": f.get("nome") or "", "arvores": set(), "total": 0.0,
                                       "rf": set(), "risco": "", "enc": 0, "ativo": 0})
            e["arvores"].add(numero)
            e["total"] += float(f.get("valor") or 0)
            for r in rfs:
                e["rf"].add(str(r)[:160])
            if _RISCO_PESO.get((risco or "").lower(), 0) > _RISCO_PESO.get(e["risco"], 0):
                e["risco"] = (risco or "").lower()
            if life == "encerrado_indicio":
                e["enc"] += 1
            elif life == "ativo":
                e["ativo"] += 1
    try:
        from compliance_agent.sede_google import e_ente_publico
    except Exception:  # noqa: BLE001
        def e_ente_publico(_n):  # fallback: não exclui ninguém
            return False
    gravados = 0
    for cnpj, e in forn.items():
        n_arv = len(e["arvores"])
        rf = sorted(e["rf"])
        # Ente PÚBLICO (Fundo/Secretaria/Município…) RECEBE repasse — não é alvo de direcionamento.
        # Presunção de regularidade: zera o score (mantém a linha p/ rastreio, mas fora do topo).
        score = 0 if e_ente_publico(e["nome"]) else _score(n_arv, e["total"], len(rf), e["risco"])
        con.execute(
            """INSERT INTO sei_direcionamento
               (fornecedor_cnpj,fornecedor_nome,n_arvores,total_pago,red_flags,risco_max,n_encerrado,n_ativo,score,arvores,atualizado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(fornecedor_cnpj) DO UPDATE SET fornecedor_nome=excluded.fornecedor_nome,
                 n_arvores=excluded.n_arvores,total_pago=excluded.total_pago,red_flags=excluded.red_flags,
                 risco_max=excluded.risco_max,n_encerrado=excluded.n_encerrado,n_ativo=excluded.n_ativo,
                 score=excluded.score,arvores=excluded.arvores,atualizado_em=datetime('now')""",
            (cnpj, e["nome"], n_arv, e["total"], json.dumps(rf, ensure_ascii=False), e["risco"],
             e["enc"], e["ativo"], score, json.dumps(sorted(e["arvores"]), ensure_ascii=False)))
        gravados += 1
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM sei_direcionamento").fetchone()[0]
    con.close()
    return {"fornecedores": gravados, "no_db": total}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=0, help="lista os N maiores scores")
    a = ap.parse_args()
    r = varrer()
    print(f"[sei_direc] fornecedores agregados={r.get('fornecedores')} · no_db={r.get('no_db')}")
    if a.top:
        con = sqlite3.connect(DB)
        for row in con.execute("SELECT fornecedor_cnpj,fornecedor_nome,n_arvores,score,risco_max "
                                "FROM sei_direcionamento ORDER BY score DESC LIMIT ?", (a.top,)):
            print(f"  score={row[3]:>3} · {row[2]} árvores · risco {row[4] or '-'} · {row[1]} ({row[0]})")
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
