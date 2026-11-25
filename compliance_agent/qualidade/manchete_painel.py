# -*- coding: utf-8 -*-
"""O que o painel pode pôr em MANCHETE agora (O7.3, plano mestre v2 §8 "Manchetes e score").

Regra: manchete de detector só com `manchete_efetiva` (manchete declarada E Tier 1, calculado HOJE pela régua da O5.1
em `compliance_agent/qualidade/detectores.py`, nunca o campo gravado). Medição do próprio sistema (OB paga do dia,
frescor, motores — `detector: null` no inventário) não é achado de detector e segue liberada.

Fonte das superfícies: `config/qualidade_inventario.yaml` (`manchetes`: id do elemento → detector). O JS
(`static/js/src/ui/manchete.js`) só pinta o número de uma superfície gated quando `liberada` é true; se esta rota
falha, TUDO o que é gated fica fechado (falha fechada, com o motivo na tela) — nunca uma manchete por omissão.

Com 0 detectores Tier 1 (estado de 24/11/2026) o painel mostra "nenhuma manchete calibrada" com o porquê de cada
uma (tier e o que falta) — nunca vazio silencioso, nunca manchete não calibrada.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from compliance_agent.qualidade import detectores as R

RAIZ = Path(__file__).resolve().parents[2]
INVENTARIO = RAIZ / "config" / "qualidade_inventario.yaml"
EXPLICA_TIER1 = ("Tier 1 = taxa de falso positivo medida em fonte primária, em amostra estratificada de pelo menos "
                 f"{R.TIER1_N_MIN} decididos, ponto ≤ {R.TIER1_PONTO_MAX:.0%}, IC95 superior ≤ {R.TIER1_IC_MAX:.0%}, "
                 f"cobertura ≥ {R.TIER1_COBERTURA_MIN:.0%}, elegibilidade declarada e nenhum erro grave aberto "
                 "(régua O5.1, compliance_agent/qualidade/detectores.py)")


def _det(e: dict | None, hoje: date | None) -> dict:
    if not e:
        return {"tier": None, "tier_motivo": "fora do registro de detectores", "fp_ic95": None,
                "manchete_declarada": False, "manchete_efetiva": False}
    c = R.campos_calculados(e, hoje)
    return {"tier": c["tier"], "tier_motivo": c["tier_motivo"], "fp_ic95": c["fp_ic95"],
            "manchete_declarada": bool(e.get("manchete")), "manchete_efetiva": c["manchete_efetiva"]}


def estado(hoje: date | None = None, inventario: Path | None = None) -> dict:
    reg = R.carregar()
    inv = yaml.safe_load(Path(inventario or INVENTARIO).read_text(encoding="utf-8")) or {}
    superficies = []
    for m in inv.get("manchetes") or []:
        det = m.get("detector")
        base = {"id": m["id"], "chip": m.get("chip"), "superficie": m.get("superficie"), "natureza": m.get("natureza"),
                "rota": m.get("rota"), "detector": det}
        if det is None:
            superficies.append({**base, "liberada": True, "tier": None,
                                "motivo": "medição do próprio sistema, lida agora na fonte — não é achado de detector"})
            continue
        d = _det(reg.get(det), hoje)
        motivo = ("manchete calibrada (Tier 1)" if d["manchete_efetiva"] else
                  f"detector {det} é Tier {d['tier'] if d['tier'] is not None else '—'} ({d['tier_motivo']}) — "
                  "não é manchete; o dado segue na aba como fila de triagem")
        superficies.append({**base, **d, "liberada": d["manchete_efetiva"], "motivo": motivo})
    detectores = {k: {**_det(e, hoje), "afirma": e.get("afirma")} for k, e in reg.items() if e.get("manchete")}
    por_tier = {str(t): sum(R.avaliar_tier(e, hoje)["tier"] == t for e in reg.values()) for t in (1, 2, 3)}
    efetivas = sorted(k for k, d in detectores.items() if d["manchete_efetiva"])
    gated = [s for s in superficies if s["detector"]]
    if efetivas:
        explicacao = f"{len(efetivas)} detector(es) com manchete calibrada (Tier 1): {', '.join(efetivas)}."
    else:
        explicacao = (f"Nenhuma manchete calibrada: 0 de {len(reg)} detectores do registro estão no Tier 1 "
                      f"(Tier 2: {por_tier['2']}, Tier 3: {por_tier['3']}). Os {len(detectores)} detectores que "
                      f"pediam manchete e as {len(gated)} superfícies que exibiam número de detector ficam fora da "
                      "capa até a calibração; os dados seguem nas abas como fila de triagem, não como achado.")
    return {"ok": True, "fonte": "config/qualidade_detectores.yaml (tier calculado hoje) × "
                                 "config/qualidade_inventario.yaml (superfícies)",
            "hoje": (hoje or date.today()).isoformat(), "regra": "manchete de detector só com Tier 1",
            "explica_tier1": EXPLICA_TIER1, "n_detectores": len(reg), "por_tier": por_tier,
            "n_manchete_declarada": len(detectores), "manchetes_efetivas": efetivas,
            "n_superficies_gated": len(gated), "n_superficies_liberadas": sum(s["liberada"] for s in gated),
            "explicacao": explicacao, "superficies": superficies, "detectores": detectores}
