#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quem o Estado paga estando em RECUPERAÇÃO JUDICIAL — inclusive dentro de consórcio.

POR QUE EXISTE. A casa já tinha usado este sinal UMA vez, à mão, num dossiê (a LYTORANEA, aditada
em +R$ 17,3 mi em recuperação judicial e ainda sancionada). Nunca virou varredura. O caso da SECID
(2026-08-09) mostrou o custo disso: **seis consórcios da UG 660100 têm a mesma empresa em
recuperação judicial dentro**, somando R$ 415,5 mi pagos — e nenhum relatório da casa dizia isso,
porque a empresa não aparece como credora: ela aparece no QSA do consórcio que recebe.

**Estar em recuperação judicial NÃO impede contratar.** A jurisprudência admite a participação
mediante demonstração de viabilidade econômico-financeira e plano homologado; o que a lei exige é
que a habilitação seja **demonstrada**, certame a certame. Esta tela não acusa: ela diz **onde
conferir a habilitação econômico-financeira** — e a soma paga mede o tamanho do que depende dessa
conferência.

TRÊS LIMITES, todos declarados na saída:

  · **O sinal vem do NOME.** A Receita passa a registrar "EM RECUPERAÇÃO JUDICIAL" na razão social,
    mas quem não atualizou o registro **não aparece** — a lista é PISO, nunca teto.
  · **O nome não tem data.** Recuperação encerrada pode deixar o rótulo para trás; e pagamento
    ANTERIOR ao pedido de recuperação não descreve contratação de empresa em crise. Sem a data do
    deferimento não se afirma qual pagamento foi feito durante a recuperação — é a mesma armadilha
    de `situacao-cadastral-vigencia-na-data`, e aqui ela fica DECLARADA em vez de escondida.
  · **Consórcio é o caminho principal.** Somar só o credor direto perde o essencial: o membro em
    recuperação entra pelo quadro societário do consórcio, e foi assim que R$ 415,5 mi passaram
    despercebidos.

    python -m tools.screen_recuperacao_judicial
    python -m tools.screen_recuperacao_judicial --md --gravar
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
# Como a Receita grafa o rótulo na razão social. Aceita as duas grafias e a abreviação usual.
PADROES = ("%EM RECUPERACAO JUDICIAL%", "%EM RECUPERAÇÃO JUDICIAL%", "%EM RECUPERACAO JUD%",
           "%EM RECUPERAÇÃO JUD%")


def medir(db: str = "", min_valor: float = 100_000.0) -> list[dict[str, Any]]:
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
    try:
        ors = " OR ".join(["UPPER(nome_socio) LIKE ?"] * len(PADROES))
        try:
            membros: dict[str, list[str]] = {}
            for raiz, nome in con.execute(
                    f"SELECT cnpj_basico, nome_socio FROM socios_receita WHERE {ors}",
                    [p.upper() for p in PADROES]):
                membros.setdefault(raiz, []).append(str(nome or "").strip())
        except sqlite3.OperationalError:
            membros = {}

        ors_cred = " OR ".join(["UPPER(nome_credor) LIKE ?"] * len(PADROES))
        try:
            linhas = con.execute(
                "SELECT substr(credor,1,8) rz, MIN(NULLIF(nome_credor,'')) nome, SUM(valor) tot, "
                " COUNT(*) n, "
                " MIN(ug_emitente) ug, COUNT(DISTINCT ug_emitente) n_ug, "
                " MIN(substr(data_emissao,7,4)) ano_ini, MAX(substr(data_emissao,7,4)) ano_fim "
                "FROM ob_orcamentaria_siafe WHERE status='Contabilizado' AND length(credor)=14 "
                "GROUP BY 1").fetchall()
            proprios = {r[0] for r in con.execute(
                f"SELECT DISTINCT substr(credor,1,8) FROM ob_orcamentaria_siafe WHERE {ors_cred}",
                [p.upper() for p in PADROES])}
        except sqlite3.OperationalError:
            return []
    finally:
        con.close()

    fora = []
    for rz, nome, tot, n, ug, n_ug, ano_ini, ano_fim in linhas:
        via_membro = membros.get(rz) or []
        if not via_membro and rz not in proprios:
            continue
        if (tot or 0) < min_valor:
            continue
        fora.append({
            "raiz": rz, "nome": nome or "", "total": round(tot or 0, 2), "obs": n,
            "ug": ug, "n_ug": n_ug, "anos": f"{ano_ini}–{ano_fim}",
            # o próprio credor está em recuperação, ou é um consórcio que a carrega dentro?
            "via": "credor" if rz in proprios else "membro do consórcio",
            "membros_em_recuperacao": sorted(set(via_membro))[:3],
        })
    fora.sort(key=lambda d: -d["total"])
    return fora


RESSALVA = (
    "Estar em recuperação judicial NÃO impede contratar: a jurisprudência admite a participação "
    "mediante plano homologado e demonstração de viabilidade econômico-financeira. Esta lista diz "
    "ONDE conferir a habilitação, não que houve irregularidade. O sinal vem do NOME registrado na "
    "Receita — quem não atualizou não aparece, então a lista é PISO. E o nome não tem data: "
    "recuperação encerrada pode deixar o rótulo, e pagamento anterior ao deferimento não descreve "
    "contratação de empresa em crise; a data do deferimento tem de vir dos autos."
)


def markdown(itens: list[dict]) -> str:
    from compliance_agent.reporting.intel_base import moeda
    L = ["# Pagamentos a quem está em recuperação judicial (inclusive por dentro de consórcio)",
         "", f"> {RESSALVA}", "",
         "| Credor | UGs | Anos | Como aparece | Pago (OB) | OBs |", "|---|---:|---|---|---:|---:|"]
    for x in itens:
        L.append(f"| {x['nome'][:46]} ({x['raiz']}) | {x['n_ug']} | {x['anos']} | {x['via']} | "
                 f"R$ {moeda(x['total'])} | {x['obs']} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-valor", type=float, default=100_000.0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--gravar", action="store_true")
    a = ap.parse_args(argv)
    itens = medir(min_valor=a.min_valor)[: a.top]
    if a.md or a.gravar:
        texto = markdown(itens)
        print(texto)
        if a.gravar:
            alvo = _REPO / "data" / "recuperacao_judicial.md"
            alvo.write_text(texto, encoding="utf-8")
            print(f"gravado: {alvo}")
    else:
        soma = sum(x["total"] for x in itens)
        print(f"{len(itens)} credor(es) · R$ {soma:,.2f} pagos:")
        for x in itens:
            print(f"   {x['raiz']} {x['nome'][:38]:38} R$ {x['total']:>14,.2f} "
                  f"({x['obs']:3d} OBs, {x['n_ug']} UG) via {x['via']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
