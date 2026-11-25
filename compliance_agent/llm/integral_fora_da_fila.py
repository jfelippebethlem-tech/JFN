# -*- coding: utf-8 -*-
"""integral_fora_da_fila — a perícia integral sai da fila do Opus NA ORIGEM (decisão delegada D3, 24/11/2026).

Por quê (O6.6, ~/vault/refatoracao/o66-regua.md §3.3): a perícia integral é 85% da demanda da fila do Opus (210 s
por item no Opus) e a fila só fecha cortando-a na origem. O E11 roda só pela assinatura (camada 2) e não gera item de
contingência; o que a cascata grátis produzir de perícia integral vira `nao_julgado_proposta` ("NÃO JULGADO —
proposta", `llm/conferencia_opus.PROPOSTA`): visível, nunca VERIFICADO, e o Opus não o relê.

Para os PENDENTES que já estão na fila, este módulo só propõe (SOMBRA) e mede a vazão resultante pela régua de ritmo
(`conferente_sonnet.simular` + `ritmo_assinatura` via `capacidade_semanal_dias`); `aplicar` é o comando para a
religação — não roda sozinho.

    python -m compliance_agent.llm.integral_fora_da_fila sombra --risco data/conferencia_risco_proposta.json \
        --saida data/integral_fora_da_fila_proposta.json
    python -m compliance_agent.llm.integral_fora_da_fila aplicar --proposta data/integral_fora_da_fila_proposta.json
    # depois (ordem importa: o risco só mexe no que AINDA está pendente):
    python -m compliance_agent.llm.conferencia_risco aplicar --proposta data/conferencia_risco_proposta.json

Desfazer: `UPDATE fila SET status='pendente', risco=NULL WHERE status='nao_julgado_proposta' AND
risco='integral_fora_da_fila'` (o que o `aplicar` mudou fica listado na proposta) + `JFN_INTEGRAL_NA_FILA=1`.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from compliance_agent.llm import conferencia_opus as CO
from compliance_agent.llm import conferente_sonnet as CS

MOTIVO = "integral_fora_da_fila"
_REPO = Path(__file__).resolve().parents[2]


def ler_pendentes(con: sqlite3.Connection) -> list[dict]:
    return [{"id": i, "chave": c, "tarefa": t, "item": it} for i, c, t, it in
            con.execute("SELECT id, chave, tarefa, item FROM fila WHERE status='pendente' ORDER BY id")]


def entrada_por_dia(con: sqlite3.Connection, fim: date, dias: int = 8) -> dict[str, float]:
    """Média diária de itens que ENTRARAM na fila por tarefa, nos `dias` dias completos antes de `fim`."""
    ini = fim - timedelta(days=dias)
    tot: Counter = Counter()
    for t, n in con.execute("SELECT tarefa, COUNT(*) FROM fila WHERE substr(criado_em,1,10) >= ? AND "
                            "substr(criado_em,1,10) < ? GROUP BY tarefa", (ini.isoformat(), fim.isoformat())):
        tot[t] += n
    return {t: round(n / dias, 1) for t, n in tot.items()}


def propor(pendentes: list[dict], risco_itens: list[dict] | None) -> list[dict]:
    """Decisão por pendente: integral ⇒ PROPOSTA; o resto segue a proposta de risco da O6.5 (se dada)."""
    por_id = {i["id"]: i for i in (risco_itens or [])}
    out = []
    for p in pendentes:
        r = por_id.get(p["id"])
        if CO.fora_da_fila(p["tarefa"]):
            dec, mot = CO.PROPOSTA, [MOTIVO]
        elif r is not None and r.get("chave") == p["chave"]:
            dec, mot = ("pendente" if r["decisao"] == "fila" else r["decisao"]), list(r.get("motivos") or [])
        else:
            dec, mot = "pendente", []
        out.append({**p, "decisao": dec, "motivos": mot, "valor": (r or {}).get("valor"),
                    "nivel": (r or {}).get("nivel")})
    return out


def vazao(itens: list[dict], entrada_dia: dict[str, float], *, caps=(47.0, 71.0), pesos=(1.0, 0.5, 0.2)) -> dict:
    """Vazão diária depois do corte, na mesma régua da O6.6 (segundos-Opus de assinatura, capacidade fixa no mix de
    HOJE). Fração retida = a da proposta de risco nas tarefas que FICAM; entrada = a medida da fila."""
    fica = [i for i in itens if i["decisao"] != CO.PROPOSTA]
    por = defaultdict(lambda: {"retidos": 0, "total": 0})
    for i in fica:
        por[i["tarefa"]]["total"] += 1
        por[i["tarefa"]]["retidos"] += i["decisao"] == "pendente"
    frac = (sum(d["retidos"] for d in por.values()) / sum(d["total"] for d in por.values())) if fica else 0.0
    ent_antes = sum(entrada_dia.values())
    ent_depois = sum(v for t, v in entrada_dia.items() if not CO.fora_da_fila(t))
    # capacidade em segundos-Opus no mix retido de HOJE (antes do corte), como na O6.6; o mix de depois é o que fica
    mix_hoje = CS.mix_da_proposta([{**i, "decisao": "fila"} for i in itens
                                   if i["decisao"] == "pendente" or (i["decisao"] == CO.PROPOSTA and i.get("_retido"))])
    mix = CS.mix_da_proposta([{**i, "decisao": "fila"} for i in fica if i["decisao"] == "pendente"])
    out = {"entrada_dia_antes": round(ent_antes, 1), "entrada_dia_depois": round(ent_depois, 1),
           "fracao_retida_depois": round(frac, 4), "retidos_dia_depois": round(ent_depois * frac, 1),
           "mix_retido_depois": mix, "dias_equivalentes_semana": round(CS.capacidade_semanal_dias(), 3),
           "cenarios": []}
    for cap in caps:
        cs = CS.capacidade_s(mix_hoje, cap)
        s0 = CS.simular(mix, retidos_dia=ent_depois * frac, cap_s=cs, peso_sonnet=0)
        backlog_s = sum(d["retidos"] * CS.TEMPOS_S.get(t, CS.TEMPOS_S["outros"])["opus"] for t, d in mix.items())
        sobra = cs - s0["demanda_s"]
        out["cenarios"].append({"cenario": "so_opus", "cap_opus_dia": cap, **s0, "backlog_retido": sum(
            d["retidos"] for d in mix.values()), "backlog_s": round(backlog_s),
            "dias_para_zerar_backlog": round(backlog_s / sobra, 1) if sobra > 0 else None})
        for w in pesos:
            out["cenarios"].append({"cenario": "sonnet_grave", "cap_opus_dia": cap, **CS.simular(
                mix, retidos_dia=ent_depois * frac, cap_s=cs, peso_sonnet=w, modo="grave")})
    return out


def sombra(con: sqlite3.Connection, risco_itens: list[dict] | None, *, hoje: date | None = None) -> tuple[dict, list]:
    pend = ler_pendentes(con)
    itens = propor(pend, risco_itens)
    # retido HOJE (antes do corte): o que a proposta de risco deixa na fila; sem proposta, todo pendente
    retido_antes = {i["id"] for i in (risco_itens or []) if i.get("decisao") == "fila"}
    for i in itens:
        i["_retido"] = (i["id"] in retido_antes) if risco_itens else True
    ent = entrada_por_dia(con, hoje or date.today())
    por_tarefa = defaultdict(Counter)
    for i in itens:
        por_tarefa[i["tarefa"]][i["decisao"]] += 1
    rel = {"em": datetime.now().isoformat(timespec="seconds"), "pendentes": len(itens),
           "viram_proposta": sum(i["decisao"] == CO.PROPOSTA for i in itens),
           "ficam_na_fila": sum(i["decisao"] == "pendente" for i in itens),
           "viram_nao_julgado_risco": sum(i["decisao"] == "nao_julgado" for i in itens),
           "por_tarefa": {t: dict(c) for t, c in sorted(por_tarefa.items())}, "entrada_por_dia": ent,
           "proposta_de_risco": bool(risco_itens), "vazao": vazao(itens, ent)}
    return rel, itens


def gravar(caminho: Path, rel: dict, itens: list[dict]) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps({"resumo": rel, "itens": [
        {k: i.get(k) for k in ("id", "chave", "tarefa", "item", "decisao", "motivos")}
        for i in itens if i["decisao"] == CO.PROPOSTA]}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(caminho, 0o600)
    return caminho


def aplicar(proposta: Path, con: sqlite3.Connection) -> dict:
    """Só mexe em linha AINDA pendente, da tarefa cortada, com a MESMA chave da sombra."""
    d = json.loads(Path(proposta).read_text(encoding="utf-8"))
    CO.garantir_origem(con)
    n = Counter()
    for it in d["itens"]:
        if it["decisao"] != CO.PROPOSTA or not CO.fora_da_fila(it["tarefa"]):
            n["ignorado"] += 1
            continue
        cur = con.execute("UPDATE fila SET status=?, risco=? WHERE id=? AND chave=? AND tarefa=? AND status='pendente'",
                          (CO.PROPOSTA, MOTIVO, it["id"], it["chave"], it["tarefa"]))
        n[CO.PROPOSTA if cur.rowcount else "ignorado"] += 1
    con.commit()
    return dict(n)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Perícia integral fora da fila do Opus (sombra / aplicação)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sombra", help="proposta + vazão; NÃO altera a fila")
    s.add_argument("--risco", help="proposta da O6.5 (conferencia_risco sombra) para as tarefas que ficam")
    s.add_argument("--hoje", help="AAAA-MM-DD: fim (exclusivo) da janela de entrada por dia")
    s.add_argument("--saida", default=str(_REPO / "data" / "integral_fora_da_fila_proposta.json"))
    a_ = sub.add_parser("aplicar", help="aplica a proposta à fila real (religação)")
    a_.add_argument("--proposta", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "sombra":
        risco_itens = json.loads(Path(a.risco).read_text(encoding="utf-8"))["itens"] if a.risco else None
        con = sqlite3.connect(f"file:{CO.caminho()}?mode=ro", uri=True, timeout=30)
        try:
            rel, itens = sombra(con, risco_itens, hoje=date.fromisoformat(a.hoje) if a.hoje else None)
        finally:
            con.close()
        destino = gravar(Path(a.saida), rel, itens)
        print(json.dumps(rel, ensure_ascii=False, indent=1))
        print(f"proposta: {destino}\naplicar (religação): python -m compliance_agent.llm.integral_fora_da_fila "
              f"aplicar --proposta {destino}")
        return 0
    con = CO.conectar()
    try:
        print(json.dumps(aplicar(Path(a.proposta), con), ensure_ascii=False))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
