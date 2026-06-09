# -*- coding: utf-8 -*-
"""
Onda 3 — Calibração do score de anomalia + detecção de drift.

A eval (eval_groundtruth) mostrou que o score médio por órgão é dominado por UGs pequenas (1 fornecedor → score
trivialmente alto). Aqui calibramos o uso do score como **fila de investigação**:

  • percentis()        — distribuição global do score (onde está a massa; onde cortar)
  • fila_investigacao()— top-N OBs por score, com opção BALANCEADA por UG (evita o motor só olhar UG gigante)
  • drift()            — média/p90 do score por exercício (o modelo está estável no tempo?)

Princípio: o corte define uma FILA de apuração interna (ex.: top-50, marcar 10-15 p/ revisão humana), nunca um
veredito. Score alto = prioridade de olhar, não culpa.

CLI:
    python -m compliance_agent.calibrar --percentis
    python -m compliance_agent.calibrar --fila 50
    python -m compliance_agent.calibrar --fila 50 --por-ug
    python -m compliance_agent.calibrar --drift
"""
from __future__ import annotations

import argparse
import json

from compliance_agent.duckdb_util import conectar


def percentis() -> dict:
    con = conectar()
    try:
        r = con.execute("""
            SELECT COUNT(*) n, AVG(score) media,
                   quantile_cont(score, 0.50) p50, quantile_cont(score, 0.90) p90,
                   quantile_cont(score, 0.95) p95, quantile_cont(score, 0.99) p99,
                   MAX(score) maxv
            FROM db.ob_anomaly
        """).fetchone()
        n, media, p50, p90, p95, p99, maxv = r
        # quantos OBs acima de cada corte
        cortes = {}
        for c in (0.90, 0.95, 0.99):
            cortes[f">={c}"] = con.execute("SELECT COUNT(*) FROM db.ob_anomaly WHERE score>=?", [c]).fetchone()[0]
        return {"n": n, "media": round(media or 0, 4), "p50": round(p50 or 0, 4),
                "p90": round(p90 or 0, 4), "p95": round(p95 or 0, 4), "p99": round(p99 or 0, 4),
                "max": round(maxv or 0, 4), "ob_acima_do_corte": cortes,
                "sugestao": "corte p99 dá uma fila enxuta p/ revisão humana; combine com red flags determinísticas."}
    finally:
        con.close()


def fila_investigacao(top: int = 50, por_ug: bool = False) -> list[dict]:
    """Fila priorizada de OBs para apuração. `por_ug` balanceia (top por UG) — evita a fila inteira cair numa UG
    gigante e dá cobertura entre órgãos (responde ao viés que a eval revelou)."""
    con = conectar()
    try:
        base = """
            SELECT o.numero_ob, o.ug_codigo, o.ug_nome, o.favorecido_nome, o.favorecido_cpf,
                   o.valor, o.data_emissao, a.score, a.top_features
            FROM db.ob_anomaly a JOIN db.ordens_bancarias o ON o.id=a.ob_id
        """
        if por_ug:
            # top 3 por UG, depois os melhores globais até `top` (cobertura entre órgãos)
            q = f"""
                WITH ranked AS (
                    SELECT *, row_number() OVER (PARTITION BY ug_codigo ORDER BY score DESC) rk
                    FROM ({base})
                )
                SELECT * FROM ranked WHERE rk<=3 ORDER BY score DESC LIMIT ?
            """
            rows = con.execute(q, [top]).fetchall()
        else:
            rows = con.execute(base + " ORDER BY a.score DESC LIMIT ?", [top]).fetchall()
        cols = ["numero_ob", "ug", "ug_nome", "fornecedor", "cnpj", "valor", "data", "score", "top_features"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                d["top_features"] = json.loads(d["top_features"]) if d["top_features"] else []
            except Exception:
                d["top_features"] = []
            d["valor"] = float(d["valor"] or 0)
            d["score"] = round(d["score"] or 0, 4)
            out.append(d)
        return out
    finally:
        con.close()


def fila_relativa_ug(top: int = 50, min_ob_ug: int = 30) -> list[dict]:
    """Onda 4 — fila por score RELATIVO À UG: percentil do score da OB DENTRO do próprio órgão. Corrige o viés
    que a eval revelou (score global dominado por UGs pequenas). Só UGs com >= min_ob_ug OBs (base estatística)."""
    con = conectar()
    try:
        rows = con.execute("""
            WITH base AS (
                SELECT o.numero_ob, o.ug_codigo, o.ug_nome, o.favorecido_nome, o.favorecido_cpf,
                       o.valor, o.data_emissao, a.score,
                       COUNT(*) OVER (PARTITION BY o.ug_codigo) n_ug,
                       percent_rank() OVER (PARTITION BY o.ug_codigo ORDER BY a.score) pr_ug
                FROM db.ob_anomaly a JOIN db.ordens_bancarias o ON o.id=a.ob_id
            )
            SELECT numero_ob, ug_codigo, ug_nome, favorecido_nome, favorecido_cpf, valor, data_emissao,
                   score, pr_ug
            FROM base WHERE n_ug >= ? ORDER BY pr_ug DESC, score DESC LIMIT ?
        """, [min_ob_ug, top]).fetchall()
        cols = ["numero_ob", "ug", "ug_nome", "fornecedor", "cnpj", "valor", "data", "score", "percentil_ug"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["valor"] = float(d["valor"] or 0)
            d["score"] = round(d["score"] or 0, 4)
            d["percentil_ug"] = round((d["percentil_ug"] or 0) * 100, 1)
            out.append(d)
        return out
    finally:
        con.close()


def drift() -> list[dict]:
    """Estatística do score por exercício — detecta deriva do modelo/dado ao longo do tempo."""
    con = conectar()
    try:
        rows = con.execute("""
            SELECT o.exercicio, COUNT(*) n, AVG(a.score) media,
                   quantile_cont(a.score, 0.90) p90, AVG(o.valor) valor_medio
            FROM db.ob_anomaly a JOIN db.ordens_bancarias o ON o.id=a.ob_id
            WHERE o.exercicio IS NOT NULL
            GROUP BY o.exercicio ORDER BY o.exercicio
        """).fetchall()
        return [{"exercicio": e, "n": n, "score_medio": round(m or 0, 4),
                 "score_p90": round(p or 0, 4), "valor_medio": round(v or 0, 2)} for e, n, m, p, v in rows]
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Calibração do score de anomalia + drift (Onda 3).")
    ap.add_argument("--percentis", action="store_true")
    ap.add_argument("--fila", type=int, metavar="N", help="fila de investigação top-N")
    ap.add_argument("--por-ug", action="store_true", help="balanceia a fila por UG")
    ap.add_argument("--fila-rel", type=int, metavar="N", help="fila por score RELATIVO à UG (Onda 4)")
    ap.add_argument("--drift", action="store_true")
    a = ap.parse_args()
    if a.percentis:
        print(json.dumps(percentis(), ensure_ascii=False, indent=2))
    if a.fila:
        print(json.dumps(fila_investigacao(a.fila, a.por_ug), ensure_ascii=False, indent=2, default=str))
    if a.fila_rel:
        print(json.dumps(fila_relativa_ug(a.fila_rel), ensure_ascii=False, indent=2, default=str))
    if a.drift:
        print(json.dumps(drift(), ensure_ascii=False, indent=2))
