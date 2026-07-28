#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Varredura por CERTAME — a camada que levanta a cobertura de detectores.

    .venv/bin/python tools/varredura_certames_sweep.py [--ano 2025] [--limite 200] [--gravar]
    .venv/bin/python tools/varredura_certames_sweep.py --com-clausulas --gravar

LEIA A COBERTURA, NÃO SÓ OS ACHADOS. A varredura por ÓRGÃO alcança 3 detectores de 41, porque a
maioria é por certame. Esta alcança 8 — e mesmo assim quantos deles conseguem opinar depende do
que existe para aquele certame específico. Certame sem achado pode ser certame limpo ou certame
sem dado, e a saída distingue as duas coisas.

`--com-clausulas` restringe aos certames que têm cláusula de edital extraída (1.331 medidos em
2026-07-28). É onde a cobertura é maior — bom para medir o teto real do que hoje é possível.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent import varredura_certames as V  # noqa: E402


def _com_clausulas(con, limite=None):
    sql = """SELECT ec.numero_controle_pncp c, SUM(COALESCE(pr.valor_homologado,0)) v
             FROM edital_clausula ec
             JOIN pncp_resultado pr ON pr.certame = ec.numero_controle_pncp
             GROUP BY ec.numero_controle_pncp ORDER BY v DESC"""
    if limite:
        sql += f" LIMIT {int(limite)}"
    return [r["c"] for r in con.execute(sql)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int)
    ap.add_argument("--orgao")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--com-clausulas", action="store_true",
                    help="só certames com cláusula de edital extraída (maior cobertura)")
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--com-ia", action="store_true",
                    help="liga a camada 2 (rubrica fechada na cadeia grátis)")
    a = ap.parse_args()

    gerar = None
    if a.com_ia:
        from compliance_agent.llm.camada_triagem import gerar_triagem, status
        st = status()
        if st["pausado"]:
            print(f"CAMADA 2 pausada por {st['arquivo_pause']} — seguindo só determinística")
        else:
            gerar = gerar_triagem()
            print(f"CAMADA 2 ligada · {st['restante']} de {st['teto_dia']} chamadas hoje")

    con = V.abrir_leitura()
    achados = V.abrir_achados() if a.gravar else None
    certames = (_com_clausulas(con, a.limite) if a.com_clausulas
                else V.certames_com_resultado(con, ano=a.ano, orgao=a.orgao, limite=a.limite))
    print(f"{len(certames)} certame(s) na fila\n")

    t0 = time.time()
    n_av = n_tot = n_ach = 0
    por_detector: Counter = Counter()
    fontes = Counter()
    for i, c in enumerate(certames, 1):
        r = V.varrer_certame(con, c, gerar=gerar, con_achados=achados)
        n_av += r["n_avaliaveis"]
        n_tot += r["n_detectores"]
        n_ach += r["n_confirmados"]
        fontes["edital"] += int(r["tem_edital"])
        fontes["clausulas"] += int(r["tem_clausulas"])
        for x in r["achados"]:
            por_detector[x.detector] += 1
        if r["n_confirmados"]:
            print(f"  [{i}/{len(certames)}] {c[:42]:44} {r['n_confirmados']} achado(s) · "
                  f"aval {r['n_avaliaveis']}/{r['n_detectores']}")
            for x in r["achados"][:4]:
                print(f"        {x.detector:4} score={x.score:.2f} "
                      f"{(x.motivo_refutacao or '')[:78]}")
        elif i % 100 == 0:
            print(f"  [{i}/{len(certames)}] …")

    print(f"\n{len(certames)} certames · {n_ach} achado(s) confirmado(s) em {time.time()-t0:.0f}s")
    print(f"COBERTURA: {n_av}/{n_tot} avaliações possíveis "
          f"({(n_av*100//n_tot) if n_tot else 0}%) — o resto é campo que a base não tem")
    print(f"  com edital: {fontes['edital']} · com cláusulas: {fontes['clausulas']}")
    if por_detector:
        print("  achados por detector: " +
              ", ".join(f"{d}={n}" for d, n in por_detector.most_common()))
    if achados is not None:
        achados.close()
    print("\nLembrete: achado é INDÍCIO. Certame sem achado pode ser certame sem dado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
