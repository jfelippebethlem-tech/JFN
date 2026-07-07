"""pipelines_slo — vigia o FRESCOR do output de cada etapa (config/pipelines.yaml).

Complementa o /api/agenda (que mostra quando os gatilhos disparam): aqui o sinal é
"a etapa PRODUZIU resultado dentro do SLO?" (mtime do arquivo-sentinela). Pega
starvation/lock/loop silencioso — classe de falha que agenda verde não denuncia
(caso sei_supervisor, 2026-07-07: 28 dias starvando o downstream sem um erro no journal).

Uso:
    .venv/bin/python -m tools.pipelines_slo            # relatório no stdout (exit 1 se há stale)
    .venv/bin/python -m tools.pipelines_slo --alerta   # + Telegram na TRANSIÇÃO ok->stale e na recuperação
Cron: horário (7 * * * *). Debounce por estado em data/pipelines_slo_estado.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
CFG = BASE / "config/pipelines.yaml"
ESTADO = BASE / "data/pipelines_slo_estado.json"


def _idade_h(p: Path) -> float | None:
    try:
        return (time.time() - p.stat().st_mtime) / 3600.0
    except FileNotFoundError:
        return None


def checar() -> list[dict]:
    itens = yaml.safe_load(CFG.read_text())["pipelines"]
    out = []
    for it in itens:
        arq = Path(it["arquivo"])
        if not arq.is_absolute():
            arq = BASE / arq
        pausa = it.get("pausa")
        pausado = bool(pausa) and (BASE / pausa).exists()
        idade = _idade_h(arq)
        if pausado:
            status = "pausado"
        elif idade is None:
            status = "ausente"
        elif idade > float(it["max_stale_h"]):
            status = "stale"
        else:
            status = "ok"
        out.append({"nome": it["nome"], "grupo": it.get("grupo", "-"), "status": status,
                    "idade_h": None if idade is None else round(idade, 1),
                    "slo_h": it["max_stale_h"], "nota": it.get("nota", "")})
    return out


def _estado_prev() -> dict:
    try:
        return json.loads(ESTADO.read_text())
    except Exception:
        return {}


def main() -> int:
    res = checar()
    ruins = [r for r in res if r["status"] in ("stale", "ausente")]
    ico = {"ok": "✅", "pausado": "⏸", "stale": "🔴", "ausente": "⚠️"}
    for r in res:
        idade = "—" if r["idade_h"] is None else f"{r['idade_h']}h"
        print(f"{ico[r['status']]} {r['nome']:<22} [{r['grupo']}] idade={idade} slo={r['slo_h']}h")

    if "--alerta" in sys.argv:
        prev = _estado_prev()
        eventos = []
        for r in res:
            antes = prev.get(r["nome"], "ok")
            if r["status"] in ("stale", "ausente") and antes not in ("stale", "ausente"):
                eventos.append(f"🔴 <b>{r['nome']}</b> sem output há {r['idade_h']}h "
                               f"(SLO {r['slo_h']}h). {r['nota']}")
            elif r["status"] == "ok" and antes in ("stale", "ausente"):
                eventos.append(f"🟢 <b>{r['nome']}</b> voltou a produzir (idade {r['idade_h']}h).")
        if eventos:
            from tools.ronda import notificar
            notificar("🩺 <b>SLO de pipelines</b>\n" + "\n".join(eventos))
        ESTADO.write_text(json.dumps({r["nome"]: r["status"] for r in res}, ensure_ascii=False))

    return 1 if ruins else 0


if __name__ == "__main__":
    raise SystemExit(main())
