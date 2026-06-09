#!/usr/bin/env python3
"""
Massare — BACKTEST honesto: reproduz como os mercados de fato se moveram e pontua as previsões
do ensemble em TODOS os pregões possíveis (walk-forward, só passado → out-of-sample por construção).

Pedido do dono (Loop 10, 2026-06-09): "reproduza como backtest de suas previsões como os mercados
agiram; avalie todos os pregões possíveis."

O que mede (por ativo × horizonte, agregando):
  - ensemble_hit_rate (OOS): acerto direcional do ensemble adaptativo em cada pregão avaliado.
  - base_naive_rate: o palpite INGÊNUO (sempre na direção majoritária do período). É o piso a bater.
  - edge = hit_rate − base_naive_rate: SKILL REAL (positivo = o modelo agrega valor; ~0/negativo = não).
  - n: nº de pregões avaliados (a amostra OOS).
Honestidade: NÃO há Brier calibrado aqui porque o ensemble produz direção, não probabilidade
calibrada — reportar Brier seria inventar. O edge vs. taxa-base é a medida honesta de skill.

Saídas: massare/data/backtest_<stamp>.json + massare/data/backtest.md (legível, com o ranking de edge).
Também roda learning.grade_due() p/ carimbar previsões LOGADAS cujo alvo já venceu (as pendentes com
alvo no futuro permanecem pendentes — honesto).

Uso:  PYTHONPATH=. .venv/bin/python -m massare.backtest --stamp "2026-06-09T02:00:00" [--horizons 5,10,21]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from massare.engine import walk_forward
from massare import learning

_DB = Path(__file__).resolve().parent / "data" / "massare.db"
_OUT = Path(__file__).resolve().parent / "data"


def _ativos_negociaveis() -> list[str]:
    """Símbolos com série de preços suficiente (todos os assets com preço)."""
    with sqlite3.connect(str(_DB)) as c:
        rows = c.execute(
            "SELECT symbol, COUNT(*) n FROM prices GROUP BY symbol HAVING n >= 320 ORDER BY symbol"
        ).fetchall()
    return [r[0] for r in rows]


def run(symbols: list[str] | None = None, horizons: tuple[int, ...] = (5, 10, 21)) -> dict:
    symbols = symbols or _ativos_negociaveis()
    por_ativo: list[dict] = []
    for sym in symbols:
        for h in horizons:
            try:
                wf = walk_forward(sym, horizon=h)
            except Exception as exc:  # noqa: BLE001
                por_ativo.append({"symbol": sym, "horizon": h, "erro": str(exc)[:80]})
                continue
            if wf.get("erro") or not wf.get("ensemble_n"):
                por_ativo.append({"symbol": sym, "horizon": h, "erro": wf.get("erro", "sem amostra")})
                continue
            hr = wf["ensemble_hit_rate"]
            base = wf.get("base_naive_rate")
            edge = round(hr - base, 4) if (hr is not None and base is not None) else None
            por_ativo.append({
                "symbol": sym, "horizon": h, "hit_rate": hr, "base_naive_rate": base,
                "edge": edge, "n": wf["ensemble_n"], "base_up_rate": wf.get("base_up_rate"),
            })

    validos = [r for r in por_ativo if r.get("n")]
    n_total = sum(r["n"] for r in validos)
    # agregados ponderados pela amostra (n)
    def _wavg(campo):
        num = sum((r[campo] or 0) * r["n"] for r in validos if r.get(campo) is not None)
        den = sum(r["n"] for r in validos if r.get(campo) is not None)
        return round(num / den, 4) if den else None
    overall = {
        "n_pregoes_avaliados": n_total,
        "n_series": len(validos),
        "hit_rate_oos": _wavg("hit_rate"),
        "base_naive_rate": _wavg("base_naive_rate"),
        "edge_medio": _wavg("edge"),
        "series_com_edge_positivo": sum(1 for r in validos if (r.get("edge") or 0) > 0),
    }
    # resolve previsões logadas cujo alvo já venceu (honesto)
    try:
        grade = learning.grade_due()
    except Exception as exc:  # noqa: BLE001
        grade = {"erro": str(exc)[:80]}
    try:
        scoreboard = learning.scoreboard()
    except Exception as exc:  # noqa: BLE001
        scoreboard = {"erro": str(exc)[:80]}

    return {"overall": overall, "por_ativo": por_ativo, "horizons": list(horizons),
            "grade_due": grade, "scoreboard_logado": scoreboard}


def _render_md(res: dict, stamp: str) -> str:
    o = res["overall"]
    L = [
        "# Massare — Backtest OOS (todos os pregões)",
        "",
        f"> Snapshot `{stamp}` · `massare/backtest.py`. Walk-forward (só passado) sobre toda a série de preços.",
        "",
        "## Agregado (ponderado pela amostra)",
        f"- **Pregões avaliados:** {o['n_pregoes_avaliados']:,} em {o['n_series']} séries (ativo×horizonte)",
        f"- **Hit-rate OOS do ensemble:** {o['hit_rate_oos']}",
        f"- **Piso ingênuo (direção majoritária):** {o['base_naive_rate']}",
        f"- **Edge médio (skill acima do ingênuo):** {o['edge_medio']}  "
        f"→ {o['series_com_edge_positivo']}/{o['n_series']} séries com edge positivo",
        "",
        "> Honestidade: edge ≈ 0 ou negativo = o ensemble NÃO supera o palpite ingênuo naquela série. "
        "Sem Brier calibrado (o sinal é direcional, não probabilístico) — reportá-lo seria inventar.",
        "",
        "## Ranking por edge (skill real) — top 15",
        "| Ativo | Horiz. | Hit-rate | Piso ingênuo | Edge | Pregões |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    validos = sorted([r for r in res["por_ativo"] if r.get("edge") is not None],
                     key=lambda r: -r["edge"])
    for r in validos[:15]:
        L.append(f"| {r['symbol']} | {r['horizon']}d | {r['hit_rate']} | {r['base_naive_rate']} "
                 f"| {r['edge']:+.4f} | {r['n']:,} |")
    g = res.get("grade_due") or {}
    sb = res.get("scoreboard_logado") or {}
    L += [
        "",
        "## Previsões logadas (diário de previsões)",
        f"- grade_due (carimbadas agora que o alvo venceu): {g}",
        f"- scoreboard OOS logado: overall={sb.get('overall')} · pendentes={sb.get('pendentes')}",
        "",
        "> Pendentes com alvo no FUTURO (sem preço realizado ainda) permanecem pendentes — honesto. "
        "Elas são carimbadas automaticamente quando o pregão-alvo chega e o preço é coletado.",
    ]
    return "\n".join(L) + "\n"


def por_simbolo(symbol: str, horizon: int = 21) -> dict | None:
    """Track record OOS de UM ativo/horizonte a partir do último backtest (p/ as teses serem honestas).
    Retorna {hit_rate, base_naive_rate, edge, n, tem_skill} ou None."""
    f = _OUT / "backtest.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    for r in d.get("por_ativo") or []:
        if r.get("symbol") == symbol and r.get("horizon") == horizon and r.get("n"):
            edge = r.get("edge")
            return {"hit_rate": r.get("hit_rate"), "base_naive_rate": r.get("base_naive_rate"),
                    "edge": edge, "n": r.get("n"), "tem_skill": (edge is not None and edge > 0)}
    return None


def resumo_overall() -> dict | None:
    """Resumo do último backtest (p/ o /placar ser honesto). None se nunca rodou."""
    f = _OUT / "backtest.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        o = dict(d.get("overall") or {})
        o["stamp"] = d.get("stamp")
        return o
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="sem-data")
    ap.add_argument("--horizons", default="5,10,21")
    args = ap.parse_args()
    horizons = tuple(int(x) for x in args.horizons.split(",") if x.strip())
    res = run(horizons=horizons)
    res["stamp"] = args.stamp
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "backtest.md").write_text(_render_md(res, args.stamp), encoding="utf-8")
    # JSON estável (consumido pelo /placar) + cópia carimbada (histórico)
    payload = json.dumps(res, ensure_ascii=False, indent=2)
    (_OUT / "backtest.json").write_text(payload, encoding="utf-8")
    (_OUT / f"backtest_{args.stamp.replace(':', '').replace('-', '')}.json").write_text(payload, encoding="utf-8")
    print(_render_md(res, args.stamp))


if __name__ == "__main__":
    main()
