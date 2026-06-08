# -*- coding: utf-8 -*-
"""Carteira pessoal — modo MANUAL — JFN 2.0, Onda 9. Sem broker, sem credencial.

Lê posições de `data/carteira.json` (holdings declarados à mão), valoriza com dados grátis
(brapi/fundamentos) e cruza com as teses/regime do Massare. Sem API de corretora.

Honesto: sem `data/carteira.json` → vazia (não inventa posição). É leitura/alerta, não ordem.
"""
from __future__ import annotations

import json
from pathlib import Path

_CARTEIRA = Path(__file__).resolve().parent.parent / "data" / "carteira.json"


def _posicoes() -> list[dict]:
    if not _CARTEIRA.exists():
        return []
    try:
        d = json.loads(_CARTEIRA.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else d.get("posicoes", [])
    except Exception:  # noqa: BLE001
        return []


def carteira() -> dict:
    """Valoriza a carteira manual + cruza com as teses vivas. {ok, posicoes, valor_total, leitura}."""
    pos = _posicoes()
    if not pos:
        return {"ok": True, "posicoes": [], "valor_total": 0.0,
                "_nota": "INDISPONÍVEL: crie data/carteira.json com [{ticker,quantidade,preco_medio}]. "
                         "Modo manual, sem broker; nada foi fabricado."}

    from massare.fundamentos import fundamentos

    enriquecidas = []
    total = 0.0
    for p in pos:
        tk = str(p.get("ticker", "")).upper()
        qtd = float(p.get("quantidade", 0) or 0)
        pm = float(p.get("preco_medio", 0) or 0)
        f = fundamentos(tk)
        preco = f.get("preco") if f.get("ok") and f.get("preco") else None
        valor = (preco or pm) * qtd
        total += valor
        enriquecidas.append({
            "ticker": tk, "quantidade": qtd, "preco_medio": pm, "preco_atual": preco,
            "valor": round(valor, 2),
            "variacao_pct": round((preco / pm - 1) * 100, 2) if (preco and pm) else None,
        })

    # cruza com teses vivas (alerta de exposição alinhada/contrária à narrativa)
    alertas = []
    try:
        from massare.theses import atual
        teses = atual(registrar=False).get("teses", [])
        ativos_tese = {a for t in teses for a in t["ativos"]}
        for e in enriquecidas:
            if e["ticker"] in ativos_tese:
                alertas.append(f"{e['ticker']} aparece em tese viva — conferir direção/horizonte.")
    except Exception:  # noqa: BLE001
        pass

    return {"ok": True, "posicoes": enriquecidas, "valor_total": round(total, 2),
            "alertas": alertas, "_fonte": "data/carteira.json (manual) + brapi (preço)",
            "_nota": "Leitura/alerta de carteira; modo manual sem broker. NÃO é ordem nem recomendação."}
