#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VARREDURA GERAL do SEI na VM-2 com o código ATUAL (clone `~/JFN-worker`), entregue à VM-1 por lote CONFERIDO.

Até 13/11/2026 a VM-2 varria a fatia 1/2 com a cópia rsync antiga `~/JFN` (sem a prioridade de contratação
direta de 13/11) e a VM-1 só colhia o cache dela pelo `colher_vm2.sh` — que se adia com load ≥ 4 (adiou o dia
todo em 13/11, load 20-27). Agora:

  (VM-1) exportar  → a fila da fatia 1/2 com o `_fila` da VM-1 (OB paga, contratação direta grande no topo,
                     dirigidos), porque o banco mora lá;
  (VM-2) rodar     → `tools.sei_sweep.run` com essa fila injetada (mesmo padrão do `sei_bombeiros_sweep`),
                     com o progresso e os restritos da VM-1 copiados para o `_pular` decidir igual;
  (VM-2) devolver  → lote `sweep` (cache CDP novo + delta de progresso e de restritos + juízo do Claude
                     sobre uma amostra) → `vm2_conferencia importar` na VM-1.

O que a VM-2 já entregou nas últimas 24 h não volta à fila dela (o progresso importado na VM-1 pode estar
pendente — `vm2_conferencia pendentes` — e a cópia que ela puxa ainda não o teria).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

DATA = RAIZ / "data"
FILA = DATA / "fila_sweep_vm2.json"
SNAP_PROG = DATA / ".vm2_prog_antes.json"
SNAP_RESTR = DATA / ".vm2_restritos_antes.json"
ENTREGUES = DATA / ".vm2_sweep_entregues.json"
RESUMO = DATA / "vm2_sweep_resumo.jsonl"
MAX_JUIZOS_LOTE = 3


def exportar(limite: int, fatia: str = "1/2") -> list:
    """(VM-1) Fila da FATIA 1/2 — a metade da VM-2 — com o critério do sweep da casa. O it-campo pede sub-fatias
    da metade da VM-1 (`2j/2m`: hash ≡ 2j mod 2m ⇒ par ⇒ dentro de 0/2), disjuntas entre as sessões dele."""
    import contextlib
    os.environ["JFN_SWEEP_FATIA"] = fatia
    import tools.sei_sweep as S
    with contextlib.redirect_stdout(sys.stderr):        # o `_log` do sweep imprime: o stdout é só o JSON
        rows = S._fila(None, limite)
    # 4º campo = estrato ("topo" | "vinculo" | ""): sem ele o teto do vínculo OB↔contrato não valeria no lote
    # da VM-2 (ela não tem o banco nem a lista). `carregar_fila` aceita também a linha antiga de 3 campos.
    def _marca(p) -> str:
        k = S._norm_proc_global(p)
        return "topo" if k in S._ESTRATOS["topo"] else "vinculo" if k in S._ESTRATOS["vinculo"] else ""
    return [list(x[:3]) + [_marca(x[0])] for x in rows[:limite]]


def _ler(p: Path, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _entregues_recentes() -> set[str]:
    d = _ler(ENTREGUES, {})
    agora = time.time()
    return {p for p, t in d.items() if agora - float(t) < 86400}


def carregar_fila(linhas: list) -> list[tuple]:
    """Linhas exportadas → tuplas (processo, nob, tot) do sweep; o 4º campo, quando há, repõe os estratos em
    `S._ESTRATOS` (o teto do vínculo OB↔contrato no lote depende deles)."""
    import tools.sei_sweep as S
    S._ESTRATOS["topo"] = {S._norm_proc_global(x[0]) for x in linhas if len(x) > 3 and x[3] == "topo"}
    S._ESTRATOS["vinculo"] = {S._norm_proc_global(x[0]) for x in linhas if len(x) > 3 and x[3] == "vinculo"}
    return [tuple(x[:3]) for x in linhas]


def rodar(max_n: int) -> None:
    """(VM-2) Um lote do sweep canônico sobre a fila exportada pela VM-1."""
    import tools.sei_sweep as S
    fila = carregar_fila([x for x in _ler(FILA, []) if x and x[0] not in _entregues_recentes()])
    S._fila = lambda ug, limite, cnpj=None: fila
    S._log(f"[vm2] fila da VM-1 (fatia {os.environ.get('JFN_SWEEP_FATIA', '1/2')}): {len(fila)} processos; "
           f"lote --max {max_n}")
    asyncio.run(S.run(max_n=max_n, ug=None))


def devolver(desde: float) -> dict:
    """(VM-2) Lote `sweep` com o cache CDP novo e o delta de progresso/restritos desde `desde`."""
    from tools import vm2_lote as L
    from tools.sei_sweep import CACHE
    L.reenviar_pendentes()
    novos = [f for f in CACHE.glob("cdp_*.json") if f.stat().st_mtime >= desde]
    prog = (_ler(CACHE / "sei_sweep_progress.json", {}) or {}).get("feitos", {})
    antes = (_ler(SNAP_PROG, {}) or {}).get("feitos", {})
    delta_prog = {k: v for k, v in prog.items() if antes.get(k) != v}
    restr = _ler(DATA / "sei_restritos.json", {}) or {}
    restr_antes = _ler(SNAP_RESTR, {}) or {}
    delta_restr = {k: v for k, v in restr.items() if restr_antes.get(k) != v}
    processos, n_juizo = {}, 0
    for f in novos:
        juizo = None
        c = _ler(f, {})
        conteudos = [d for d in (c.get("conteudo_documentos") or []) if isinstance(d, dict) and d.get("conteudo")]
        if conteudos and n_juizo < MAX_JUIZOS_LOTE:
            d = max(conteudos, key=lambda d: len(str(d.get("conteudo") or "")))
            juizo = L.julgar(str(c.get("numero") or f.stem), str(d.get("doc") or d.get("titulo") or ""),
                             str(d.get("conteudo") or ""))
            n_juizo += 1
        processos[f.name] = {"numero": c.get("numero"), "documentos": len(c.get("documentos") or []),
                             "juizo": juizo}
    if not (novos or delta_prog or delta_restr):
        return {"lote": None, "motivo": "nada novo"}
    base = L.montar("sweep", {f"cache/{f.name}": f for f in novos}, processos,
                    {"progresso": delta_prog, "restritos": delta_restr})
    for f in novos:
        f.unlink(missing_ok=True)       # a cópia está no lote, que fica aqui até a VM-1 conferir
    res = L.enviar(base)
    reg = _ler(ENTREGUES, {})
    for p in delta_prog:
        reg[p] = time.time()
    ENTREGUES.write_text(json.dumps({p: t for p, t in reg.items() if time.time() - t < 86400}), encoding="utf-8")
    resumo = {"ts": time.strftime("%F %T"), "cdp": len(novos), "progresso": len(delta_prog),
              "restritos": len(delta_restr), "com_docs": sum(1 for v in processos.values() if v["documentos"]),
              "lote": res}
    with RESUMO.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(resumo, ensure_ascii=False) + "\n")
    return resumo


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar"); e.add_argument("--max", type=int, default=200)
    e.add_argument("--fatia", default="1/2")
    r = sub.add_parser("rodar"); r.add_argument("--max", type=int, default=8)
    d = sub.add_parser("devolver"); d.add_argument("--desde", type=float, required=True)
    a = ap.parse_args()
    if a.cmd == "exportar":
        print(json.dumps(exportar(a.max, a.fatia), ensure_ascii=False))
    elif a.cmd == "rodar":
        rodar(a.max)
    else:
        print(json.dumps(devolver(a.desde), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
