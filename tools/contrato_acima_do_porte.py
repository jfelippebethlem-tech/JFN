#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CONTRATO acima do teto do PORTE — o critério legal na sua forma literal.

**A diferença para as duas lentes irmãs.** `porte_incompativel` mede o que a empresa RECEBEU
(OB paga) contra o teto do porte; `porte_declarado_certame` mede o porte que ela DECLAROU ao
licitar. Esta mede o **valor do contrato celebrado** — e é a que fala a língua da lei:

> Lei 14.133/2021: o licitante ME/EPP declara que, no ano-calendário, **não celebrou contratos**
> com a Administração cujos **valores somados** extrapolem a receita bruta máxima de EPP.

O critério legal é sobre CONTRATO CELEBRADO, não sobre dinheiro recebido. Um contrato de R$ 87 mi
com uma microempresa é incompatível com o porte no dia da assinatura, mesmo que a execução venha a
ser menor — e o TCU firmou que a declaração falsa de enquadramento já é fraude à licitação,
independentemente de vantagem obtida (Ac. 2695/2025-Plenário).

**FONTE: `contratos_tcerj`** — o espelho de contratos do próprio Tribunal de Contas do Estado
(37.673 linhas). Não é inferência nossa: é o registro do órgão de controle.

**PREVALÊNCIA** (medida em 2026-08-23): 840 contratos de 13.903 com CNPJ de ME/EPP conhecido,
**451 empresas — 1,87% do cadastro ME/EPP**, somando R$ 3,91 bi. É corte que ordena fila; compare
com a `estrutura_magra`, retirada da convergência no mesmo dia por marcar 55,3%.

**A HIPÓTESE DA ATA FOI TESTADA E DESCARTADA.** "Contratação de estabelecimentos" no plural sugere
ata de registro de preços cujo valor global seria rateado entre vários fornecedores — o que
esvaziaria o achado. Não é o caso: o contrato de R$ 87 mi da MAJU tem fornecedor único e
`num_contratacao` exclusivo, e apenas **12 de 37.661** números de contratação se repetem (0,03%).

RESSALVAS que viajam com o número:
  · **valor contratado ≠ executado.** O contrato de R$ 87 mi da MAJU tem R$ 7,91 mi empenhados e
    R$ 2,98 mi pagos. Para o critério legal isso não importa (ele fala em celebrar); para medir
    dano, importa muito — e o dano NÃO é o que esta lente mede;
  · o porte vem do cadastro da Receita (`fonte_mes` mais recente), não da declaração no certame;
    para o ato datado da empresa, ver `porte_declarado_certame`;
  · contrato plurianual dilui o valor por exercício — a lente NÃO faz esse rateio, e o campo
    `vig_inicio`/`vig_fim` está no espelho para quem quiser fazê-lo caso a caso;
  · indício para apuração. Só o edital diz se a empresa fruiu benefício de ME/EPP naquele certame.

Uso:
    .venv/bin/python tools/contrato_acima_do_porte.py
    .venv/bin/python tools/contrato_acima_do_porte.py --min-razao 10 --limite 30
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.reporting.intel_base import moeda

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# LC 123/2006, art. 3º — receita bruta anual máxima de cada porte.
TETO_ANUAL = {"Microempresa": 360_000.0, "Empresa de Pequeno Porte": 4_800_000.0}


def acima_do_porte(con: sqlite3.Connection, min_razao: float = 1.0) -> list[dict]:
    """Contratos do espelho do TCE-RJ cujo valor supera o teto do porte do contratado."""
    porte = {str(b).zfill(8): (p, cap) for b, p, cap in
             con.execute("SELECT cnpj_basico, porte_txt, capital_social FROM empresas_cadastro")}

    por_empresa: dict = collections.defaultdict(
        lambda: {"contratos": [], "soma": 0.0, "nome": "", "porte": "", "capital": 0.0})
    for processo, data, unidade, valor, cnpj, fornecedor, status in con.execute(
            "SELECT processo, data_contratacao, unidade, valor_contrato, cnpj, fornecedor, status "
            "FROM contratos_tcerj"):
        dig = re.sub(r"\D", "", str(cnpj or ""))
        if len(dig) < 8 or not valor:
            continue
        info = porte.get(dig[:8])
        if not info or info[0] not in TETO_ANUAL:
            continue
        teto = TETO_ANUAL[info[0]]
        if valor <= teto * min_razao:
            continue
        e = por_empresa[dig[:8]]
        e["nome"] = str(fornecedor or "").strip()
        e["porte"], e["capital"] = info[0], info[1] or 0.0
        e["soma"] += valor
        e["contratos"].append({
            "processo": processo, "data": str(data)[:10], "unidade": str(unidade or "").strip(),
            "valor": valor, "status": status, "razao_teto": valor / teto})

    saida = []
    for basico, e in por_empresa.items():
        e["contratos"].sort(key=lambda x: -x["valor"])
        saida.append({"cnpj_basico": basico, "nome": e["nome"], "porte": e["porte"],
                      "capital_social": e["capital"], "n_contratos": len(e["contratos"]),
                      "soma_contratada": e["soma"], "maior": e["contratos"][0]["valor"],
                      "razao_teto": e["contratos"][0]["razao_teto"],
                      "contratos": e["contratos"][:5]})
    saida.sort(key=lambda x: -x["razao_teto"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-razao", type=float, default=1.0, help="múltiplo do teto do porte")
    ap.add_argument("--limite", type=int, default=15)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    linhas = acima_do_porte(con, min_razao=a.min_razao)
    print("contrato acima do teto do porte — fonte: espelho de contratos do TCE-RJ")
    print(f"  {len(linhas)} empresas · {sum(x['n_contratos'] for x in linhas)} contratos · "
          f"R$ {moeda(sum(x['soma_contratada'] for x in linhas))}")
    print("\n  O critério legal é sobre CONTRATO CELEBRADO, não sobre o pago. Valor contratado "
          "NÃO é\n  valor executado — esta lente não mede dano, mede incompatibilidade no dia da "
          "assinatura.\n")
    print(f"{'maior contrato':>18} {'x teto':>7} {'n':>3}  porte · empresa")
    for x in linhas[:a.limite]:
        c0 = x["contratos"][0]
        print(f"R$ {moeda(x['maior']):>15} {x['razao_teto']:6.0f}x {x['n_contratos']:>3}  "
              f"{x['porte'][:12]:13s} {x['nome'][:34]}")
        print(f"{'':>27} {c0['data']}  {c0['unidade'][:40]}  [{c0['status']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
