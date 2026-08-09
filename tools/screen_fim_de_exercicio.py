#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Credores cujo pagamento anual se concentra em NOVEMBRO e DEZEMBRO — a janela frouxa.

POR QUE EXISTE. Dezembro é quando o empenho precisa ser consumido, e é onde a liquidação costuma
afrouxar: o pagamento sai antes de a prova de entrega existir. O acervo já mostrava o padrão caso a
caso — a EVOLUÇÃO com 30 OBs num único 22/12, a NRTT com R$ 25,4 mi em 7 OBs no dia 28/12 — mas
ninguém media o CONJUNTO. Esta é a medida.

O QUE O SCREEN NÃO ACUSA (e é a maior parte do topo bruto):

  · **ente público** — repasse a Fundo Municipal de Saúde concentra-se no fim do ano por desenho do
    federalismo fiscal, não por vício. Vetado por natureza jurídica (`e_estatal`), não por nome.
  · **desenho de programa** — associação de apoio à escola, fundação de apoio universitária,
    cooperativa (`explicacao_institucional`). O mesmo vetador da fila de agente público.
  · **credor pequeno ou com poucas OBs** — concentração sobre 2 pagamentos não é padrão, é acaso.
    Daí os pisos de valor e de contagem.

Medido em 2026-08-09, DEPOIS de recoletar as UGs travadas: sem o veto, os 5 primeiros do ranking
eram fundos municipais de saúde — ruído que faria o fiscal desconfiar do resto da lista.

    python -m tools.screen_fim_de_exercicio                 # tabela
    python -m tools.screen_fim_de_exercicio --min-valor 20000000 --pct 90
    python -m tools.screen_fim_de_exercicio --md --gravar   # markdown p/ o dossiê
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
MESES_FIM = ("11", "12")


def _cadastro() -> tuple[dict, dict]:
    """{raiz: natureza} e {raiz: razão} do espelho da Receita — vazio se a base não existir."""
    alvo = _REPO / "data" / "receita_estab.db"
    if not alvo.exists():
        return {}, {}
    nat, razao = {}, {}
    con = sqlite3.connect(f"file:{alvo}?mode=ro", uri=True, timeout=30)
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'").fetchone():
            for raiz, natureza, rs in con.execute(
                    "SELECT cnpj_basico, natureza_cod, razao_social FROM empresas"):
                nat[raiz] = str(natureza or "")
                razao[raiz] = str(rs or "")
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return nat, razao


def medir(min_valor: float = 5_000_000, min_obs: int = 5, pct: float = 80.0,
          db: str = "") -> list[dict]:
    from compliance_agent.reporting.intel_base import _DB
    from tools.agente_publico_reverso import e_estatal, explicacao_institucional

    nat, razao = _cadastro()
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
    try:
        linhas = con.execute(
            "SELECT substr(credor,1,8) rz, MIN(nome_credor) nome, exercicio, SUM(valor) tot, "
            " SUM(CASE WHEN substr(data_emissao,4,2) IN (?,?) THEN valor ELSE 0 END) fim, COUNT(*) n "
            "FROM ob_orcamentaria_siafe "
            # `data_emissao` é TEXTO DD/MM/AAAA nesta base — o mês vive nas posições 4-5.
            "WHERE status='Contabilizado' AND length(credor)=14 AND length(data_emissao)=10 "
            "GROUP BY 1,3 HAVING tot >= ? AND n >= ?",
            (*MESES_FIM, min_valor, min_obs)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    fora = []
    for rz, nome, ano, tot, fim, n in linhas:
        if not tot or fim * 100.0 / tot < pct:
            continue
        natureza = nat.get(rz, "")
        if e_estatal(natureza) or explicacao_institucional(razao.get(rz, nome or ""), natureza):
            continue
        fora.append({"raiz": rz, "nome": nome or "", "exercicio": ano, "total": round(tot, 2),
                     "no_fim": round(fim, 2), "pct": round(fim * 100.0 / tot, 1), "obs": n})
    fora.sort(key=lambda x: -x["total"])
    return fora


def markdown(itens: list[dict], pct: float, min_valor: float) -> str:
    L = ["# Concentração de pagamento em novembro e dezembro", "",
         f"> Credores PRIVADOS com ≥ R$ {min_valor:,.0f} num exercício e ≥ {pct:.0f}% do valor pago "
         "nos dois últimos meses. **Indício, não acusação**: dezembro concentra execução por desenho "
         "orçamentário. O que o padrão sinaliza é ONDE olhar a prova de entrega — é na janela do "
         "fim do exercício que a liquidação costuma afrouxar.", "",
         "> Entes públicos (repasse a fundo municipal, autarquia) e desenho de programa (apoio a "
         "escola, fundação de apoio, cooperativa) são VETADOS — sem isso, o topo da lista era "
         "ruído institucional.", "",
         "| Ano | Credor | Total no ano | % em nov–dez | OBs |", "|---|---|---:|---:|---:|"]
    for x in itens:
        L.append(f"| {x['exercicio']} | {x['nome'][:44]} ({x['raiz']}) | "
                 f"R$ {x['total']:,.2f} | {x['pct']:.1f}% | {x['obs']} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-valor", type=float, default=5_000_000)
    ap.add_argument("--min-obs", type=int, default=5)
    ap.add_argument("--pct", type=float, default=80.0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args(argv)
    itens = medir(a.min_valor, a.min_obs, a.pct)[: a.top]
    if a.md or a.gravar:
        texto = markdown(itens, a.pct, a.min_valor)
        print(texto)
        if a.gravar:
            alvo = _REPO / "data" / "screen_fim_de_exercicio.md"
            alvo.write_text(texto, encoding="utf-8")
            print(f"gravado: {alvo}")
    else:
        print(f"{len(itens)} credor(es) privados com ≥ {a.pct:.0f}% do ano pago em nov–dez:")
        for x in itens:
            print(f"   {x['exercicio']} {x['raiz']} {x['nome'][:34]:34} "
                  f"R$ {x['total']:>13,.0f} · {x['pct']:5.1f}% ({x['obs']} OBs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
