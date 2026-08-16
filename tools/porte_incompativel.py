#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PORTE DECLARADO × DINHEIRO RECEBIDO — a empresa cabe no contrato que assinou?

PEDIDO DO DONO (2026-08-15): "ver compatibilidade dos contratos com o número de empregados das
empresas; contrato alto e empresa sem funcionário registrado é empresa de fachada".

**Número de empregados NÃO EXISTE nesta base.** O coletor `compliance_agent/collectors/caged.py`
está escrito mas nunca alimentou tabela alguma — não há `caged`, `rais` nem `vinculos` no
`compliance.db`. Dizer "sem funcionário registrado" com o que existe aqui seria inventar.

O que existe é MELHOR para esta pergunta, e é oficial: o **porte** da Receita, presente em
`empresas_cadastro` para 36.192 empresas (100% preenchido). Porte não é opinião — é faixa de
RECEITA BRUTA ANUAL com teto em lei (LC 123/2006, art. 3º):

    · Microempresa .................. até R$    360.000,00/ano
    · Empresa de Pequeno Porte ...... até R$  4.800.000,00/ano

Uma ME que recebe R$ 78 milhões do Estado num ano está 217× acima do teto do próprio porte. Isso é
aritmética contra a lei, não suposição sobre quadro de pessoal.

**O QUE ISTO É E O QUE NÃO É.** É indício que pede exame; NÃO é prova de fachada. A hipótese
inocente mais forte, e comum: a empresa cresceu, deixou de ser ME de fato e **não comunicou a
Receita** — o registro fica velho sem que nada nele seja falso. Por isso a saída ordena por RAZÃO
(quantas vezes o teto) e mostra concentração por unidade pagadora: é a concentração, somada ao
salto de faturamento, que separa "cadastro desatualizado" de "empresa que só existe para um órgão".

RESSALVAS QUE INTEGRAM O RESULTADO:
  · o cadastro é uma foto de **2026-05**; para pagamento de 2022 o porte pode não ser o da época;
  · soma apenas OB com `status='Contabilizado'` — Anulado (R$ 3,79 bi) e Excluído (R$ 7,50 bi)
    NÃO são pagamento, e incluí-los inflava o total em R$ 147 mi só neste recorte;
  · agrega por CNPJ BÁSICO (8 dígitos), então matriz e filiais somam — que é o certo, porque o
    porte é da empresa, não do estabelecimento.

Uso:
    .venv/bin/python tools/porte_incompativel.py               # top 25
    .venv/bin/python tools/porte_incompativel.py --min-razao 10 --limite 50
    .venv/bin/python tools/porte_incompativel.py --ug 294200   # só uma unidade
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# LC 123/2006, art. 3º, I e II. FONTE ÚNICA — não duplicar noutro detector.
TETO_ANUAL = {
    "Microempresa": 360_000.00,
    "Empresa de Pequeno Porte": 4_800_000.00,
}


def _ano(data_emissao: str) -> str:
    """`data_emissao` do SIAFE é TEXTO `DD/MM/AAAA` — o ano são os 4 últimos, nunca `ORDER BY` cru."""
    m = re.search(r"/(\d{4})$", str(data_emissao or ""))
    return m.group(1) if m else ""


def incompativeis(con: sqlite3.Connection, min_razao: float = 1.0,
                  ug: str = "") -> list[dict]:
    """CNPJ×ano em que o pago supera o teto legal do porte declarado, do mais gritante ao menos."""
    porte = {str(b).zfill(8): (p, cap, rs) for b, p, cap, rs in con.execute(
        "SELECT cnpj_basico, porte_txt, capital_social, razao_social FROM empresas_cadastro")}

    sql = ("SELECT credor, data_emissao, valor, ug_emitente FROM ob_orcamentaria_siafe "
           "WHERE credor IS NOT NULL AND status='Contabilizado'")
    par: tuple = ()
    if ug:
        sql += " AND ug_emitente=?"
        par = (ug,)

    pago: dict = collections.defaultdict(float)
    ugs: dict = collections.defaultdict(collections.Counter)
    for credor, data, valor, ug_emit in con.execute(sql, par):
        dig = re.sub(r"\D", "", str(credor))
        if len(dig) < 14:
            continue
        ano = _ano(data)
        if not ano:
            continue
        chave = (dig[:8], ano)
        pago[chave] += (valor or 0)
        ugs[dig[:8]][str(ug_emit)] += (valor or 0)

    saida = []
    for (basico, ano), total in pago.items():
        info = porte.get(basico)
        if not info:
            continue
        porte_txt, capital, razao = info
        teto = TETO_ANUAL.get(porte_txt)
        if not teto or total <= teto:
            continue
        razao_teto = total / teto
        if razao_teto < min_razao:
            continue
        por_ug = ugs[basico]
        principal, valor_principal = por_ug.most_common(1)[0]
        saida.append({
            "cnpj_basico": basico, "razao_social": razao, "porte": porte_txt,
            "capital_social": capital or 0.0, "ano": ano, "pago": total,
            "teto": teto, "razao_teto": razao_teto,
            "ug_principal": principal,
            # concentração: quanto do que a empresa recebeu do Estado vem de UMA unidade
            "concentracao_ug": (valor_principal / sum(por_ug.values())) if sum(por_ug.values()) else 0.0,
        })
    saida.sort(key=lambda x: -x["razao_teto"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-razao", type=float, default=1.0,
                    help="só quem passou do teto ao menos N vezes (padrão: 1 = qualquer estouro)")
    ap.add_argument("--limite", type=int, default=25)
    ap.add_argument("--ug", default="", help="restringe a uma unidade pagadora")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    linhas = incompativeis(con, min_razao=a.min_razao, ug=a.ug)
    total = sum(x["pago"] for x in linhas)
    print(f"CNPJ×ano com pagamento acima do teto legal do porte: {len(linhas):,}")
    print(f"soma paga (apenas OB Contabilizado): R$ {total:,.2f}")
    print("\nINDÍCIO, NÃO PROVA: porte desatualizado na Receita produz o mesmo sinal. "
          "A concentração por unidade é o que separa um caso do outro.\n")
    print(f"{'razão':>7}  {'pago no ano':>17}  {'capital':>13}  {'UG':>7} {'conc':>5}  empresa (ano)")
    for x in linhas[:a.limite]:
        print(f"{x['razao_teto']:6.0f}x  R$ {x['pago']:14,.2f}  R$ {x['capital_social']:10,.0f}  "
              f"{x['ug_principal']:>7} {100*x['concentracao_ug']:4.0f}%  "
              f"{x['razao_social'][:34]} ({x['ano']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
