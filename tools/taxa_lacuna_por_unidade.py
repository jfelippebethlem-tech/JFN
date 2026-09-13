#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Taxa de uma lacuna crítica por UNIDADE, controlada pela PROFUNDIDADE de leitura.

POR QUE ESTA FERRAMENTA EXISTE. Um achado repetido em muitos processos da mesma unidade só vira
peça quando se sabe a TAXA — e a taxa só vale quando tem denominador e sobrevive ao confundidor
óbvio, que é ler pouco. Medido em 2026-08-09 sobre 858 processos avaliáveis: a lacuna "pagamento
sem evidência de execução" aparece em 45,8% dos processos do Fundo Estadual da Saúde (260007) e em
**0% dos 44 do Fundo do Corpo de Bombeiros**. As duas unidades leem em profundidades diferentes
(mediana 7 × 10 documentos), então a comparação bruta não bastaria; controlada por faixa de
documentos lidos, a diferença AUMENTA — na faixa de 10 a 19 documentos, 65% contra 0% em 18
processos. É comportamento de unidade, não artefato do nosso gate.

REGRAS QUE ESTA MEDIDA SEGUE
  · `NAO_AVALIAVEL` fica FORA do denominador — captura insuficiente não é conclusão sobre a
    unidade (INDISPONÍVEL ≠ 0).
  · a taxa é sempre acompanhada do n; taxa sobre 3 processos não é taxa, é anedota.
  · a faixa de profundidade usa `n_com_texto` (documentos LIDOS), não o tamanho da árvore: o que
    limita a busca por prova é o que se leu.

    python -m tools.taxa_lacuna_por_unidade                 # lacuna de execução, tabela
    python -m tools.taxa_lacuna_por_unidade --termo atesto  # outra lacuna
    python -m tools.taxa_lacuna_por_unidade --md            # markdown para o dossiê
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
FAIXAS = ((1, 9), (10, 19), (20, 49), (50, 10**6))
MIN_N = 10          # abaixo disto a "taxa" não se sustenta — mostra-se o bruto, não o percentual


def _rotulo(a: int, b: int) -> str:
    return f"{a}-{b}" if b < 10**6 else f"{a}+"


def medir(termo: str = "execu", db: str = "") -> dict:
    """{unidade: {'n':…, 'com':…, 'faixas': {rótulo: [n, com]}}} — só processos AVALIÁVEIS."""
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    fora: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "com": 0, "faixas": defaultdict(lambda: [0, 0])})
    try:
        for numero, cobertura, lacunas in con.execute(
                "SELECT numero_sei, cobertura_json, lacunas_json FROM processo_avaliacao "
                "WHERE faixa != 'NAO_AVALIAVEL'"):
            unidade = (numero or "")[:6]
            if not unidade:
                continue
            try:
                cob = json.loads(cobertura or "{}")
                lac = json.loads(lacunas or "{}")
            except ValueError:
                continue
            lidos = int(cob.get("n_com_texto") or cob.get("n_docs") or 0)
            tem = any(x.get("gravidade") == "critica" and termo in (x.get("falta") or "").lower()
                      for x in (lac.get("processo") or []))
            reg = fora[unidade]
            reg["n"] += 1
            reg["com"] += int(tem)
            if lidos:
                rot = _rotulo(*next(f for f in FAIXAS if f[0] <= lidos <= f[1]))
                reg["faixas"][rot][0] += 1
                reg["faixas"][rot][1] += int(tem)
    finally:
        con.close()
    return {u: {"n": v["n"], "com": v["com"], "faixas": dict(v["faixas"])}
            for u, v in fora.items()}


def _pct(com: int, n: int) -> str:
    return f"{com}/{n} = {com * 100 / n:.0f}%" if n >= MIN_N else (f"{com}/{n}" if n else "—")


def markdown(dados: dict, termo: str) -> str:
    ordem = sorted(dados.items(), key=lambda kv: -kv[1]["n"])
    linhas = [f"# Taxa de lacuna crítica contendo `{termo}` por unidade", "",
              "> Denominador = processos AVALIÁVEIS (não-avaliável fica de fora: captura "
              "insuficiente não é conclusão). Taxa só é impressa com n ≥ "
              f"{MIN_N}.", "",
              "| Unidade | avaliados | com a lacuna | taxa | " +
              " | ".join(_rotulo(*f) + " docs" for f in FAIXAS) + " |",
              "|---|---:|---:|---:|" + "---|" * len(FAIXAS)]
    for unidade, v in ordem:
        if v["n"] < MIN_N:
            continue
        celas = []
        for f in FAIXAS:
            n, com = v["faixas"].get(_rotulo(*f), [0, 0])
            celas.append(_pct(com, n))
        linhas.append(f"| {unidade} | {v['n']} | {v['com']} | {v['com'] * 100 / v['n']:.1f}% | "
                      + " | ".join(celas) + " |")
    return "\n".join(linhas) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--termo", default="execu", help="trecho do texto da lacuna (default: execu)")
    ap.add_argument("--md", action="store_true", help="imprime markdown")
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args(argv)
    dados = medir(a.termo)
    texto = markdown(dados, a.termo)
    print(texto if a.md else texto)
    if a.gravar:
        alvo = _REPO / "data" / f"taxa_lacuna_{a.termo}.md"
        alvo.write_text(texto, encoding="utf-8")
        print(f"gravado: {alvo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
