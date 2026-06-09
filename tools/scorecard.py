#!/usr/bin/env python3
"""
SCORECARD do ecossistema JFN — o artefato único do loop de melhoria.

Roda os benchmarks objetivos (Eixo A engenharia + Eixo D regressão factual) e emite:
  - data/scorecard.json   (snapshot com timestamp passado por --stamp)
  - data/scorecard.md      (tabela legível com delta vs. snapshot anterior)

Filosofia: substituir o "acho que melhorou" por número comparável a cada checkpoint.
NÃO consome cota da sessão da IA (roda em subprocesso). Ver
docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md.

Uso:
    .venv/bin/python tools/scorecard.py --stamp "2026-06-09T01:00:00"
    (o --stamp evita Date.now(); se omitido, usa 'sem-data')
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "compliance.db"
OUT_JSON = REPO / "data" / "scorecard.json"
OUT_MD = REPO / "data" / "scorecard.md"
HIST = REPO / "data" / "scorecard_hist.jsonl"

GOD_FILES = [
    "server.py",
    "compliance_agent/reporting/inteligencia.py",
    "compliance_agent/reporting/inteligencia_orgao.py",
    "compliance_agent/lex.py",
]


def _ruff_count() -> int:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        return len(json.loads(r.stdout or "[]"))
    except Exception:
        return -1


def _loc(rel: str) -> int:
    p = REPO / rel
    if not p.exists():
        return 0
    return sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))


def _py_totais() -> dict:
    arquivos = [p for p in REPO.rglob("*.py")
                if ".venv" not in p.parts and "_SANDBOX" not in p.parts]
    loc = 0
    for p in arquivos:
        try:
            loc += sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    testes = list((REPO / "tests").glob("test_*.py"))
    return {"arquivos_py": len(arquivos), "loc_py": loc, "arquivos_teste": len(testes)}


def _golden() -> dict:
    if not DB.exists():
        return {"erro": "db ausente"}
    norm = "replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')"
    with sqlite3.connect(str(DB)) as c:
        total = c.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0]
        com_cnpj = c.execute(
            f"SELECT SUM(CASE WHEN length({norm})=14 THEN 1 ELSE 0 END) FROM ordens_bancarias"
        ).fetchone()[0] or 0
        mgs = c.execute(
            f"SELECT COUNT(*), ROUND(SUM(valor),2) FROM ordens_bancarias WHERE {norm}=?",
            ("19088605000104",),
        ).fetchone()
        iterj = c.execute(
            "SELECT COUNT(*), ROUND(SUM(valor),2) FROM ordens_bancarias WHERE ug_codigo=?",
            ("133100",),
        ).fetchone()
    return {
        "total_obs": total,
        "pct_cnpj": round(100 * com_cnpj / total, 1) if total else 0,
        "mgs_obs": mgs[0], "mgs_total": mgs[1],
        "iterj_obs": iterj[0], "iterj_total": iterj[1],
    }


def coletar(stamp: str) -> dict:
    py = _py_totais()
    sc = {
        "stamp": stamp,
        "ruff_errors": _ruff_count(),
        **py,
        "god_files_loc": {f: _loc(f) for f in GOD_FILES},
        "golden": _golden(),
    }
    return sc


def _prev() -> dict | None:
    if OUT_JSON.exists():
        try:
            return json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _delta(novo, velho) -> str:
    if velho is None or not isinstance(novo, (int, float)) or not isinstance(velho, (int, float)):
        return ""
    d = novo - velho
    if d == 0:
        return " (=)"
    seta = "▼" if d < 0 else "▲"
    return f" ({seta}{abs(d):g})"


def render_md(sc: dict, prev: dict | None) -> str:
    pv = prev or {}
    L = [
        "# Scorecard JFN — benchmarks objetivos",
        "",
        f"> Snapshot: `{sc['stamp']}` · gerado por `tools/scorecard.py`. Delta vs. snapshot anterior.",
        "",
        "## Engenharia (Eixo A)",
        "| Métrica | Valor | Meta |",
        "|---|---|---|",
        f"| Erros ruff | {sc['ruff_errors']}{_delta(sc['ruff_errors'], pv.get('ruff_errors'))} | ↓ (CI falha em erro novo) |",
        f"| Arquivos .py | {sc['arquivos_py']} | — |",
        f"| LOC Python | {sc['loc_py']}{_delta(sc['loc_py'], pv.get('loc_py'))} | god-files não crescem |",
        f"| Arquivos de teste | {sc['arquivos_teste']}{_delta(sc['arquivos_teste'], pv.get('arquivos_teste'))} | ↑ |",
        "",
        "### God-files (LOC — não devem crescer)",
        "| Arquivo | LOC |",
        "|---|---|",
    ]
    pgf = pv.get("god_files_loc", {})
    for f, loc in sc["god_files_loc"].items():
        L.append(f"| `{f}` | {loc}{_delta(loc, pgf.get(f))} |")
    g = sc["golden"]
    pg = pv.get("golden", {})
    L += [
        "",
        "## Regressão factual (Eixo D) — golden numbers",
        "| Fato canônico | Valor |",
        "|---|---|",
        f"| Cobertura (OBs) | {g.get('total_obs')}{_delta(g.get('total_obs'), pg.get('total_obs'))} |",
        f"| % com CNPJ | {g.get('pct_cnpj')}% |",
        f"| MGS Clean | {g.get('mgs_obs')} OBs · R$ {g.get('mgs_total')} |",
        f"| ITERJ (UG 133100) | {g.get('iterj_obs')} OBs · R$ {g.get('iterj_total')} |",
        "",
        "> Eixos B (qualidade de output: /relatorio, /orgao, Lex) e C (roteamento de IAs) "
        "têm harness próprio. Ver o plano.",
    ]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="sem-data")
    args = ap.parse_args()

    prev = _prev()
    sc = coletar(args.stamp)
    OUT_MD.write_text(render_md(sc, prev), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8")
    with HIST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sc, ensure_ascii=False) + "\n")
    print(OUT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
