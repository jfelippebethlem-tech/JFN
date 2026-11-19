"""Inscreve na fila de captura SEI (`sei_fila_captura`) os arquivos CORTADOS no teto de 40 documentos do cache.

Medido em 18/11/2026: 1.214 arquivos montados do cache do sweep param no teto de coleta (`docs_na_arvore` maior que os
documentos arquivados; ou 40 exatos no formato legado) — o gate canônico (`manifesto_norm.captura_integra`) os reprova
e eles sustentam afirmação de AUSÊNCIA sobre captura truncada. A fila de íntegras busca por número: basta inscrever.

Prioridade = valor PAGO no SIAFE (só OB paga pela regra canônica `cruzamentos_intel._ob_paga`, nunca empenho nem o
espelho TFE). O motivo começa com `recaptura:` (prefixo em massa de `sei_integra_fila._MOTIVOS_EM_MASSA`): entra
depois do alvo escolhido à mão e, entre os em massa, por `total_pago`. Processo já inscrito NÃO é tocado (o motivo e
o `visto_em` dele podem governar outra fila, ex.: a recaptura de execução).

    python -m tools.sei_inscrever_teto40            # ensaio: conta e lista os 10 maiores
    python -m tools.sei_inscrever_teto40 --aplicar
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from compliance_agent.sei.manifesto_norm import captura_integra  # noqa: E402

ARQUIVO = _REPO / "data" / "sei_arquivo"
DB = _REPO / "data" / "compliance.db"
_SEM_PASTA = Path("/nonexistent-jfn")       # o teto sai do manifesto; o texto em disco não entra nesta pergunta


def truncados(arquivo: Path = ARQUIVO) -> list[dict]:
    out = []
    for mp in sorted(arquivo.glob("*/manifest.json")):
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        _, ev = captura_integra(m, _SEM_PASTA)
        if ev.get("teto_de_coleta"):
            out.append({"processo": m.get("processo") or mp.parent.name.replace("_", "/"), "n_docs": ev["n_docs"],
                        "na_arvore": ev.get("docs_na_arvore")})
    return out


def pago_siafe(con, processos: list[str]) -> dict[str, float]:
    from compliance_agent.foto_quantitativo import chave_processo, mapa_obs_pagas
    mapa = mapa_obs_pagas(con, processos)
    return {p: round(sum(float(o.get("valor") or 0) for o in mapa.get(chave_processo(p) or "", [])), 2)
            for p in processos}


def inscrever(con, itens: list[dict], pago: dict[str, float], aplicar: bool) -> dict:
    ja = {r[0] for r in con.execute("SELECT numero_sei FROM sei_fila_captura")}
    agora = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    novos = []
    for e in itens:
        num = "SEI-" + e["processo"].removeprefix("SEI-")
        if num in ja:
            continue
        faltam = f"{e['n_docs']} de {e['na_arvore']} na árvore" if e.get("na_arvore") else f"{e['n_docs']} (teto legado)"
        novos.append((num, num.replace("SEI-", "").replace("/", ""),
                      f"recaptura: teto de 40 documentos do cache — {faltam}", pago.get(e["processo"], 0.0),
                      e["n_docs"], agora))
    if aplicar and novos:
        con.executemany("INSERT OR IGNORE INTO sei_fila_captura (numero_sei, sei_norm, motivo, total_pago, n_docs, "
                        "visto_em) VALUES (?,?,?,?,?,?)", novos)
        con.commit()
    return {"truncados": len(itens), "ja_inscritos": len(itens) - len(novos), "inscritos_agora": len(novos) if aplicar else 0,
            "a_inscrever": len(novos), "com_pago": sum(1 for n in novos if n[3] > 0),
            "pago_total": round(sum(n[3] for n in novos), 2),
            "maiores": sorted(((n[0], n[3]) for n in novos), key=lambda x: -x[1])[:10]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    itens = truncados()
    con = sqlite3.connect(str(DB), timeout=120)
    try:
        con.execute("PRAGMA busy_timeout=120000")
        res = inscrever(con, itens, pago_siafe(con, [e["processo"] for e in itens]), a.aplicar)
    finally:
        con.close()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
