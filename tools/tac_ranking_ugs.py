#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ranking de TAC por unidade — quem paga FORA de contrato regular, e quanto fora da curva está.

POR QUE EXISTE. `detector_tac.tac_por_ug` responde por UMA unidade, dentro do `/orgao`. Ninguém
conseguia ver o **comparativo**, e sem comparativo um percentual não significa nada: 27% é muito?
É pouco? Medido em 2026-08-04, respondendo a essa pergunta pela primeira vez:

    294200 FUNDAÇÃO SAÚDE DO ESTADO DO RJ ....  27,0%  (R$ 2,81 bi de R$ 10,41 bi)
    310100 Secretaria de Transportes .........  15,8%
    370200 Encargos Gerais do Estado ........   10,1%
    296100 FUNDO ESTADUAL DA SAÚDE ..........    2,8%  (R$ 31,65 bi movimentados)
    ... 18 das 22 maiores unidades abaixo de 1% ...

A Fundação Saúde não é "a saúde sendo assim": a OUTRA unidade de saúde, três vezes maior, paga
2,8%. Dentro da própria saúde, a FSERJ está **dez vezes acima**. É a prevalência que decide o eixo
— um número sozinho não sustenta afirmação nenhuma.

CUSTO E DESENHO. O marcador de TAC mora no texto livre da observação da OB e a definição canônica
é a regex de `reporting.detector_tac` — que NÃO se reescreve em SQL, sob pena de duas definições
divergirem em silêncio. Então: UMA passada lendo (ug, valor, observação) e a regex aplicada em
Python, gravando um JSON. A rota lê o JSON; o cálculo nunca acontece dentro do request.

HONESTIDADE. O universo é o do espelho TFE, que é o único lugar onde a observação existe —
numerador e denominador saem da mesma fonte, então a proporção é internamente coerente, mas não é
o universo do SIAFE. Unidade sem observação preenchida sai como INDISPONÍVEL, nunca como 0%.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAIDA = REPO / "data" / "tac_ranking_ugs.json"
MIN_VALOR = 300_000_000.0
"""Piso de movimentação para entrar no ranking: abaixo disso o percentual é ruído — uma unidade
que pagou R$ 2 mi, sendo R$ 1 mi por TAC, "lidera" com 50% e não diz nada."""


def medir(db: str | Path | None = None, *, min_valor: float = MIN_VALOR) -> dict:
    from compliance_agent.reporting.detector_tac import _RX_TAC

    caminho = Path(db or os.environ.get("JFN_DB") or REPO / "data" / "compliance.db")
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}

    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(ordens_bancarias)")}
        if not cols:
            return {"ok": True, "indisponivel": True, "motivo": "`ordens_bancarias` ausente"}
        obs = "observacao" if "observacao" in cols else ""
        if not obs:
            return {"ok": True, "indisponivel": True,
                    "motivo": "coluna `observacao` ausente — o marcador de TAC só existe nela"}
        acc: dict[str, dict] = {}
        for ug, nome, valor, texto in con.execute(
                f"SELECT ug_codigo, ug_nome, valor, {obs} FROM ordens_bancarias"):
            d = acc.setdefault(str(ug or "?"), {"nome": "", "n": 0, "n_tac": 0,
                                                "total": 0.0, "total_tac": 0.0, "sem_obs": 0})
            if nome and not d["nome"]:
                d["nome"] = str(nome)
            v = float(valor or 0)
            d["n"] += 1
            d["total"] += v
            if not texto:
                d["sem_obs"] += 1
            elif _RX_TAC.search(str(texto)):
                d["n_tac"] += 1
                d["total_tac"] += v
    finally:
        con.close()

    linhas = []
    for ug, d in acc.items():
        if d["total"] < min_valor:
            continue
        com_obs = d["n"] - d["sem_obs"]
        linhas.append({
            "ug": ug, "nome": d["nome"],
            "n": d["n"], "n_tac": d["n_tac"],
            "total": round(d["total"], 2), "total_tac": round(d["total_tac"], 2),
            "pct": round(100 * d["total_tac"] / d["total"], 1) if d["total"] else None,
            # INDISPONÍVEL ≠ 0%: unidade sem observação preenchida não "paga 0% por TAC" — ela
            # simplesmente não tem o campo em que o marcador vive.
            "cobertura": (f"verificado ({com_obs}/{d['n']} OBs com observação)"
                          if com_obs else "INDISPONIVEL (nenhuma OB com observação)"),
        })
    linhas.sort(key=lambda x: (x["pct"] or 0), reverse=True)
    medianas = sorted(x["pct"] for x in linhas if x["pct"] is not None)
    mediana = medianas[len(medianas) // 2] if medianas else None
    return {
        "ok": True, "indisponivel": False,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "min_valor": min_valor,
        "unidades": linhas,
        "mediana_pct": mediana,
        "nota": ("Universo do espelho TFE — único lugar onde a observação da OB existe; numerador "
                 "e denominador saem da mesma fonte, então a proporção é coerente, mas não é o "
                 "universo do SIAFE. A régua é COMPARATIVA: um percentual sozinho não sustenta "
                 "afirmação — o que informa é a distância para as outras unidades, sobretudo para "
                 "as do mesmo setor."),
    }


def main() -> int:
    r = medir()
    SAIDA.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    if not r.get("ok") or r.get("indisponivel"):
        print(f"INDISPONÍVEL: {r.get('motivo')}")
        return 0
    print(f"{len(r['unidades'])} unidades acima de R$ {MIN_VALOR/1e6:,.0f} mi · "
          f"mediana {r['mediana_pct']}% · gravado em {SAIDA}")
    for u in r["unidades"][:6]:
        print(f"   {u['ug']} {str(u['nome'])[:36]:36s} {u['pct']:5.1f}%  "
              f"R$ {u['total_tac']/1e6:,.1f} mi de R$ {u['total']/1e6:,.1f} mi")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
