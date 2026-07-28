#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Emite as minutas de requisição, uma por órgão, em Markdown (e PDF opcional).

    .venv/bin/python tools/gerar_requisicoes.py [--saida output/requisicoes] [--pdf]
    .venv/bin/python tools/gerar_requisicoes.py --resumo      # só a conta, sem gerar arquivo

Fecha o pedido "queremos saber todos os processos em sigilo para buscarmos depois por meio
formal": a lista existe em `sei_sigilo` e em `sei_fila_captura`, e aqui ela vira peça
assinável pelo gabinete, agrupada por órgão.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.reporting.requisicao import markdown, minutas  # noqa: E402

DB = os.environ.get("JFN_DB", "data/compliance.db")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="output/requisicoes")
    ap.add_argument("--pdf", action="store_true", help="também gera PDF (usa o browser; caro)")
    ap.add_argument("--resumo", action="store_true", help="só imprime a conta")
    ap.add_argument("--limite-por-orgao", type=int, default=60)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    lista = minutas(con, limite_por_orgao=a.limite_por_orgao)
    con.close()

    if not lista:
        print("nenhum processo restrito ou pendente de captura — nada a requisitar")
        return 0

    tot_r = sum(m["n_restritos"] for m in lista)
    tot_f = sum(m["n_fila"] for m in lista)
    print(f"{len(lista)} órgão(s) · {tot_r} processo(s) com acesso restrito · "
          f"{tot_f} não localizado(s)\n")
    for m in lista:
        print(f"  {m['orgao']}  {m['nome'][:44]:46} restritos={m['n_restritos']:>3} "
              f"não localizados={m['n_fila']:>3}")
    if a.resumo:
        print("\n(--resumo: nenhum arquivo gerado)")
        return 0

    destino = pathlib.Path(a.saida)
    destino.mkdir(parents=True, exist_ok=True)
    gerados = []
    for m in lista:
        md = markdown(m)
        alvo = destino / f"requisicao_{m['orgao']}.md"
        alvo.write_text(md)
        gerados.append(alvo)

        if a.pdf:
            try:
                from compliance_agent.reporting.render_html import html_to_pdf, render_html
                html = render_html({"titulo": f"Requisição de Informação — {m['nome']}",
                                    "corpo_md": md, "analista": "Controle Externo"})
                asyncio.run(html_to_pdf(html, str(alvo.with_suffix(".pdf"))))
            except Exception as e:  # noqa: BLE001 — PDF é conveniência; o .md é o entregável
                print(f"    PDF de {m['orgao']} não saiu ({type(e).__name__}: {str(e)[:70]})")

    print(f"\n{len(gerados)} minuta(s) em {destino}/")
    print("Confira uma antes de encaminhar: a peça PEDE, não acusa — e o valor 'não informado' "
          "significa dado ausente, nunca ausência de pagamento.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
