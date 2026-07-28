#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Varredura órgão a órgão — a camada determinística da fiscalização contínua.

    .venv/bin/python tools/varredura_orgaos_sweep.py --exercicio 2026 [--limite-ugs 20] [--gravar]

LEIA A COBERTURA, NÃO SÓ OS ACHADOS. A saída informa quantos detectores puderam de fato ser
avaliados por UG. Medido em 2026-07-27 na UG 294200: **3 de 41**. Uma UG sem achado pode ser uma
UG limpa — ou uma UG sem dado, e as duas coisas são muito diferentes para quem fiscaliza.

Por que a cobertura é baixa e o que a levanta: a maioria dos 31 detectores é **por CERTAME**
(exige edital, matriz de pontuação, lista de propostas, ata de julgamento). A varredura por UG só
alcança os que se alimentam de pagamento, cadastro e QSA — J1, C6, C, P3, P2. Para os demais é
preciso uma varredura por certame, alimentada por `edital_documento`/`pncp_resultado`, que é
trabalho à parte e está declarado como tal.

Roda em banco PRÓPRIO (`data/achados.db`) lendo a produção só-leitura — não disputa lock com o
servidor nem com o cron, e é o que permite rodar isto na VM-2.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent import varredura_orgaos as V  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int)
    ap.add_argument("--ug", help="varre uma única UG")
    ap.add_argument("--limite-ugs", type=int)
    ap.add_argument("--max-fornecedores", type=int, default=15)
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--com-ia", action="store_true",
                    help="liga a CAMADA 2 (rubrica fechada na cadeia grátis). Respeita o "
                         "kill-switch data/.pause_llm_triagem e o teto diário.")
    a = ap.parse_args()

    gerar = None
    if a.com_ia:
        from compliance_agent.llm.camada_triagem import gerar_triagem, status
        st = status()
        if st["pausado"]:
            print(f"CAMADA 2 pausada por {st['arquivo_pause']} — seguindo só com a determinística")
        else:
            gerar = gerar_triagem()
            print(f"CAMADA 2 ligada · {st['restante']} de {st['teto_dia']} chamadas disponíveis hoje")

    ro = V.abrir_leitura()
    achados = V.abrir_achados() if a.gravar else None
    t0 = time.time()

    if a.ug:
        r = V.varrer_ug(ro, a.ug, exercicio=a.exercicio, gerar=gerar,
                        max_fornecedores=a.max_fornecedores, con_achados=achados)
        print(f"UG {r['ug']}: {r['n_confirmados']} achado(s) · avaliáveis "
              f"{r['n_avaliaveis']}/{r['n_detectores']} · {r['n_fornecedores']} fornecedores")
        for x in r["achados"][:20]:
            print(f"   {x.detector:5} score={x.score:.2f} {str(x.processo)[:18]:20} "
                  f"{x.motivo_refutacao[:70]}")
    else:
        res = V.varrer_todas(ro, exercicio=a.exercicio, limite_ugs=a.limite_ugs,
                             max_fornecedores=a.max_fornecedores, con_achados=achados,
                             gerar=gerar, log=print)
        n_av = sum(u["n_avaliaveis"] for u in res["por_ug"])
        n_tot = sum(u["n_detectores"] for u in res["por_ug"])
        print(f"\n{res['n_ugs']} UGs · {res['total_achados']} achado(s) confirmado(s)")
        print(f"COBERTURA: {n_av}/{n_tot} avaliações possíveis "
              f"({(n_av * 100 // n_tot) if n_tot else 0}%) — o resto é campo que a base não tem")

    if gerar is not None:
        from compliance_agent.llm.camada_triagem import status as _st
        u = _st()
        print(f"camada 2: {u['chamadas_hoje']} chamada(s) hoje · {u['ok']} com resposta · "
              f"{u['vazias']} vazias · {u['erros']} erro(s) · restam {u['restante']}")
    if achados is not None:
        achados.close()
    print(f"tempo: {time.time() - t0:.0f}s")
    print("Lembrete: achado é INDÍCIO; UG sem achado pode ser UG sem dado (leia a cobertura).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
