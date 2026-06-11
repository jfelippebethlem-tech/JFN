# -*- coding: utf-8 -*-
"""Sweep de Due Diligence na CAUDA de um órgão (UG) — caça a fachada/laranja nos fornecedores PJ.

Roda o motor `investigacao_dd.investigar` em TODOS os fornecedores PJ de uma UG (cauda fachada-prone
primeiro: menores valores), de forma **resumível** (checkpoint JSONL — uma linha por CNPJ concluído) e
educada (cache SQLite TTL 1d + RateLimiter dos providers). Gera relatório ranqueado incremental dos
candidatos (🔴/🟡) e dos processos SEI a priorizar.

Network-light: `usar_beneficios=False` (PEP/benefício fica no /relatorio do alvo), `usar_rede=True`
(co-endereço local), sem geocode. HONESTO: 🟢 = sem indício verificável (não é atestado de regularidade);
indício ≠ acusação. Resumível/idempotente (padrão dos sweeps do projeto): re-rodar pula o que já foi feito.

Uso:  python -m tools.dd_sweep_orgao 036100 [--ordem asc|desc] [--max-valor N] [--limite N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from compliance_agent.investigacao_dd import investigar
from compliance_agent.investigacao_orgao_dd import (
    _moeda, _processos_do_fornecedor, top_fornecedores_pj,
)

_DIR = Path("data") / "dd_sweep"
_ORDEM_GRAU = {"🔴": 0, "🟡": 1, "🟢": 2}


def _carrega_feitos(ckpt: Path) -> dict:
    feitos: dict[str, dict] = {}
    if ckpt.exists():
        for ln in ckpt.read_text("utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                feitos[r["cnpj"]] = r
            except Exception:
                continue
    return feitos


def _escreve_relatorio(rel: Path, ug: str, resultados: list[dict], total: int) -> None:
    rank = sorted(resultados, key=lambda r: (_ORDEM_GRAU.get(r["grau"], 9), -r["score"], -r["total_pago"]))
    alvos = [r for r in rank if r["grau"] != "🟢"]
    procs = sorted({p for r in alvos for p in (r.get("processos_sei") or [])})
    n_red = sum(1 for r in rank if r["grau"] == "🔴")
    n_yel = sum(1 for r in rank if r["grau"] == "🟡")
    L = [f"# Sweep de DD — cauda da UG {ug}", "",
         f"{len(resultados)}/{total} fornecedor(es) PJ avaliado(s) · **{n_red} 🔴 · {n_yel} 🟡** · "
         f"{len(procs)} processo(s) a priorizar no sweep SEI.",
         "", "*🟢 = sem indício nas hipóteses verificáveis (não é atestado de regularidade); "
         "indício merece apuração, não é acusação. CPF de PF mascarado (LGPD).*", "",
         "| Grau | Score | Fornecedor | Total pago | Indícios | Proc.SEI |",
         "|:--:|--:|---|--:|---|--:|"]
    for r in alvos:
        cods = ", ".join(c.replace("H-", "") for c in (r.get("codigos") or [])) or "—"
        L.append(f"| {r['grau']} | {r['score']} | {r['nome'][:42]} | {_moeda(r['total_pago'])} "
                 f"| {cods} | {len(r.get('processos_sei') or [])} |")
    if not alvos:
        L.append("| 🟢 | — | *(nenhum candidato 🔴/🟡 até agora)* | — | — | — |")
    if procs:
        L += ["", "**Processos a priorizar no sweep SEI:** " + ", ".join(procs[:50])]
    rel.write_text("\n".join(L), "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sweep de DD na cauda de uma UG (fachada/laranja)")
    ap.add_argument("ug", help="código da UG (ex.: 036100 Fundo Especial TJ)")
    ap.add_argument("--ordem", choices=["asc", "desc"], default="asc", help="asc = menores primeiro (cauda)")
    ap.add_argument("--max-valor", type=float, default=0.0, help="só fornecedores com total ≤ este valor")
    ap.add_argument("--limite", type=int, default=0, help="máximo de fornecedores a avaliar (0=todos)")
    ap.add_argument("--pausa", type=float, default=0.2, help="pausa entre lookups (s)")
    a = ap.parse_args()
    load_dotenv(".env")

    _DIR.mkdir(parents=True, exist_ok=True)
    ckpt = _DIR / f"dd_sweep_{a.ug}.jsonl"
    rel = _DIR / f"dd_sweep_{a.ug}.md"

    forns = top_fornecedores_pj(a.ug, top_n=None, ordem=a.ordem)
    if a.max_valor > 0:
        forns = [f for f in forns if f["total_pago"] <= a.max_valor]
    if a.limite > 0:
        forns = forns[:a.limite]
    total = len(forns)

    feitos = _carrega_feitos(ckpt)
    resultados = list(feitos.values())
    print(f"[dd_sweep {a.ug}] {total} fornecedor(es) PJ · {len(feitos)} já feito(s) · ordem={a.ordem}",
          flush=True)

    t0 = time.time()
    with ckpt.open("a", encoding="utf-8") as fck:
        for i, f in enumerate(forns, 1):
            if f["cnpj"] in feitos:
                continue
            try:
                inv = investigar(f["cnpj"], pagamentos={"total_pago": f["total_pago"],
                                 "primeira_data": f["primeira_data"]},
                                 usar_rede=True, geocode=False, usar_beneficios=False)
                grau, score = inv["grau"], inv["score"]
                codigos = sorted({h["codigo"] for h in inv["hipoteses"]
                                  if h["status"] in ("CONFIRMADO", "INDICIO")})
                procs = _processos_do_fornecedor(a.ug, f["cnpj"]) if grau != "🟢" else []
            except Exception as e:  # noqa: BLE001 — degrada honesto, não derruba o sweep
                grau, score, codigos, procs = "🟢", 0, [], []
                print(f"  ! {f['cnpj']} erro: {str(e)[:60]}", flush=True)
            rec = {**f, "grau": grau, "score": score, "codigos": codigos, "processos_sei": procs}
            fck.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fck.flush()
            feitos[f["cnpj"]] = rec
            resultados.append(rec)
            if grau != "🟢":
                print(f"  → {grau} score {score} {f['nome'][:40]} ({_moeda(f['total_pago'])}) "
                      f"[{','.join(c.replace('H-', '') for c in codigos)}]", flush=True)
            if i % 25 == 0 or grau != "🟢":
                _escreve_relatorio(rel, a.ug, resultados, total)
                if i % 25 == 0:
                    feito_n = len(feitos)
                    taxa = (time.time() - t0) / max(1, feito_n - len(feitos) + i)
                    print(f"  ...{feito_n}/{total} ({100 * feito_n // total}%) ~{taxa:.1f}s/forn", flush=True)
            time.sleep(a.pausa)

    _escreve_relatorio(rel, a.ug, resultados, total)
    alvos = [r for r in resultados if r["grau"] != "🟢"]
    print(f"[dd_sweep {a.ug}] CONCLUÍDO {len(feitos)}/{total} · {len(alvos)} candidato(s) 🔴/🟡 · "
          f"relatório: {rel} · {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
