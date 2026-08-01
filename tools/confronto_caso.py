#!/usr/bin/env python3
"""Confronto — análise profunda × motores do sistema, por CNPJ (ferramenta de bancada).

Roda em série os motores determinísticos (perícia T01–T25, DD de fachada, detectores de
fornecedor; Lex só com --com-lex, único que gasta LLM) e emite JSON + MD com os achados por
dimensão, para diff manual contra a nota do vault (--nota cola a nota numa seção final).
Motor que falha vira "INDISPONIVEL: <erro>" — nunca some calado.

Uso: tools/confronto_caso.py <CNPJ> [--ug UG] [--nota ~/vault/casos/x.md] [--com-lex]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REPO = Path(__file__).resolve().parent.parent


def _ugs_de(cnpj: str) -> list[str]:
    import sqlite3
    con = sqlite3.connect(f"file:{REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "select ug_pagadora, sum(valor) t from ob_orcamentaria_siafe "
            "where credor=? and status='Contabilizado' group by 1 order by t desc", (cnpj,))]
    finally:
        con.close()


def confrontar(cnpj: str, ug: str | None = None, com_lex: bool = False) -> dict:
    out: dict = {"cnpj": cnpj, "quando": datetime.now().isoformat(timespec="seconds"), "motores": {}}

    ugs = [ug] if ug else _ugs_de(cnpj)
    out["ugs"] = ugs
    try:
        from compliance_agent.pericia_sweep import periciar
        out["motores"]["pericia"] = periciar(cnpj, ugs[0]) if ugs else "INDISPONIVEL: sem OB SIAFE"
    except Exception as e:
        out["motores"]["pericia"] = f"INDISPONIVEL: {e}"

    try:
        from compliance_agent.investigacao_dd import investigar
        out["motores"]["dd"] = investigar(cnpj, geocode=False)
    except Exception as e:
        out["motores"]["dd"] = f"INDISPONIVEL: {e}"

    try:
        from compliance_agent.detectores import rodar_fornecedor
        out["motores"]["detectores"] = [
            {"id": r.detector, "status": r.status, "score": r.score,
             "resumo": (r.explicacao_inocente or "")[:200]}
            for r in rodar_fornecedor(cnpj)]
    except Exception as e:
        out["motores"]["detectores"] = f"INDISPONIVEL: {e}"

    if com_lex:
        try:
            from compliance_agent import lex
            out["motores"]["lex"] = lex.gerar({"cnpj": cnpj, "nome": "", "ug": ugs[0] if ugs else "",
                                               "data": datetime.now().date().isoformat()})
        except Exception as e:
            out["motores"]["lex"] = f"INDISPONIVEL: {e}"
    return out


def _md(out: dict, nota_path: str | None) -> str:
    linhas = [f"# Confronto — {out['cnpj']} ({out['quando']})", ""]
    p = out["motores"].get("pericia")
    if isinstance(p, dict):
        linhas += [f"## Perícia (UG {p.get('ug')}) — grau {p.get('grau')} score {p.get('score')}",
                   f"- OB: {p.get('n_obs')} · pago R$ {p.get('total_pago', 0):,.2f}"]
        for a in (p.get("achados") or []):
            if isinstance(a, dict):
                linhas.append(f"- {a.get('id') or a.get('teste')}: {str(a.get('resumo') or a.get('detalhe') or a)[:180]}")
            else:
                linhas.append(f"- {str(a)[:180]}")
    else:
        linhas += ["## Perícia", f"- {p}"]
    d = out["motores"].get("dd")
    if isinstance(d, dict):
        linhas += ["", f"## DD fachada/laranja — grau {d.get('grau')} score {d.get('score')} "
                       f"({d.get('n_confirmados')}/{d.get('n_indicios')} confirmados)",
                   f"- {d.get('resumo', '')[:300]}"]
    else:
        linhas += ["", "## DD", f"- {d}"]
    det = out["motores"].get("detectores")
    linhas += ["", "## Detectores de fornecedor"]
    if isinstance(det, list):
        for r in det:
            linhas.append(f"- {r['id']} [{r['status']}] score={r['score']} — {r['resumo']}")
    else:
        linhas.append(f"- {det}")
    if "lex" in out["motores"]:
        lx = out["motores"]["lex"]
        lx_txt = f"grau {lx.get('grau')} · {lx.get('path_lex_md')}" if isinstance(lx, dict) else str(lx)
        linhas += ["", "## Lex", f"- {lx_txt}"]
    if nota_path and Path(nota_path).expanduser().exists():
        linhas += ["", "---", "## Análise profunda (nota do vault, para diff)", "",
                   Path(nota_path).expanduser().read_text(encoding="utf-8")]
    return "\n".join(linhas) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cnpj")
    ap.add_argument("--ug")
    ap.add_argument("--nota")
    ap.add_argument("--com-lex", action="store_true")
    args = ap.parse_args()
    cnpj = "".join(ch for ch in args.cnpj if ch.isdigit())

    out = confrontar(cnpj, args.ug, com_lex=args.com_lex)
    hoje = datetime.now().date()
    base = REPO / "reports" / f"confronto_{cnpj}_{hoje}"
    base.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                         encoding="utf-8")
    base.with_suffix(".md").write_text(_md(out, args.nota), encoding="utf-8")
    print(base.with_suffix(".md"))


if __name__ == "__main__":
    main()
