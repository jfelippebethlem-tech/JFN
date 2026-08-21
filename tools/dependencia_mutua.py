#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEPENDÊNCIA MÚTUA pagador ↔ fornecedor — quem existe para um órgão, e pesa nele.

Dois lados, e é a combinação que vale:
  1. **concentração do fornecedor** — quanto do que ele recebe do Estado vem de UMA unidade;
  2. **fatia da unidade** — quanto do que aquela unidade paga vai para ELE.

**Um lado sozinho não discrimina.** Medido sobre os 3.020 fornecedores com mais de R$ 1 mi
recebidos: **67,6% concentram 95%+ numa única UG** — é a norma, não a exceção; fornecedor
especializado atende um órgão e pronto. Exigindo também **≥5% do orçamento daquela unidade**, caem
para **89 (2,9%)** — aí o vínculo é recíproco: ele depende dela, e ela depende dele.

**REPASSE NÃO É CONTRATAÇÃO, e domina o topo se não for separado.** Fundo Municipal de Saúde,
Banco do Brasil (folha/tarifa), Ipalerj e institutos gestores aparecem com 100% de concentração
porque recebem TRANSFERÊNCIA, não porque venceram licitação. A regra da casa é separar repasse
antes de somar — `--com-repasse` mostra tudo, para conferência.

RESSALVAS:
  · a lente ORDENA, não acusa: dependência mútua alta é esperada em serviço público essencial
    prestado por operador único (hemocentro, transporte metropolitano);
  · só OB `status='Contabilizado'`; agrega por CNPJ de 14 dígitos.

Uso:
    .venv/bin/python tools/dependencia_mutua.py
    .venv/bin/python tools/dependencia_mutua.py --min-fatia 10 --limite 30
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

# Quem recebe por TRANSFERÊNCIA, não por contrato. Sem isto o topo é só repasse.
REPASSE = re.compile(
    r"fundo\s+municipal|fundo\s+estadual|fundo\s+nacional|prefeitura|munic[íi]pio\s+de|"
    r"banco\s+do\s+brasil|caixa\s+econ[oô]mica|secretaria\s+de\s+estado|ipalerj|rioprevid|"
    r"instituto\s+de\s+previd|c[âa]mara\s+municipal|tribunal\s+de|minist[ée]rio\s+p[úu]blico|"
    r"defensoria|universidade\s+do\s+estado|uerj|fundo\s+[úu]nico", re.I)


# Naturezas que NÃO contratam por licitação: OSS e associações operam por CONTRATO DE GESTÃO, em
# que concentrar 100% numa unidade é o DESENHO do instituto, não captura do fornecedor. Achado no
# caso IDEAS (2026-08-21): a lente o trouxe como 1º colocado com R$ 4,12 bi e 100% da UG 296100 —
# número correto, leitura errada. `estrutura_magra` já filtrava 3999; a dependência não.
NAO_EMPRESARIAL = {"3999", "2143", "3069", "3255", "3131"}


def dependencia(con: sqlite3.Connection, min_pago: float = 1_000_000.0,
                min_conc: float = 0.95, min_fatia: float = 0.05,
                com_repasse: bool = False) -> list[dict]:
    """Fornecedores presos a uma unidade que também depende deles."""
    natureza = {str(b).zfill(8): str(n) for b, n in
                con.execute("SELECT cnpj_basico, natureza_cod FROM empresas_cadastro")}
    forn: dict = collections.defaultdict(collections.Counter)
    ug_total: dict = collections.Counter()
    nomes: dict = {}
    for credor, ug, valor, nome in con.execute(
            "SELECT credor, ug_emitente, valor, nome_credor FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado'"):
        d = re.sub(r"\D", "", str(credor))
        if len(d) != 14:
            continue
        v = valor or 0
        forn[d][str(ug)] += v
        ug_total[str(ug)] += v
        if nome and d not in nomes:
            nomes[d] = nome

    saida = []
    for d, ugs in forn.items():
        total = sum(ugs.values())
        if total < min_pago:
            continue
        nome = nomes.get(d, "?")
        if not com_repasse and (REPASSE.search(nome)
                                or natureza.get(d[:8]) in NAO_EMPRESARIAL):
            continue
        ug, v = ugs.most_common(1)[0]
        conc = v / total
        fatia = v / ug_total[ug] if ug_total[ug] else 0.0
        if conc < min_conc or fatia < min_fatia:
            continue
        saida.append({"cnpj": d, "nome": nome, "ug": ug, "pago_ug": v, "pago_total": total,
                      "concentracao": conc, "fatia_ug": fatia, "n_ugs": len(ugs)})
    saida.sort(key=lambda x: -x["fatia_ug"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-conc", type=float, default=95.0, help="%% do fornecedor vindo de 1 UG")
    ap.add_argument("--min-fatia", type=float, default=5.0, help="%% da UG que vai para ele")
    ap.add_argument("--min-pago", type=float, default=1_000_000.0)
    ap.add_argument("--com-repasse", action="store_true", help="inclui fundos e repasse (conferência)")
    ap.add_argument("--limite", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    linhas = dependencia(con, min_pago=a.min_pago, min_conc=a.min_conc / 100,
                         min_fatia=a.min_fatia / 100, com_repasse=a.com_repasse)
    print(f"dependência mútua — fornecedor com >= {a.min_conc:.0f}% numa UG "
          f"E >= {a.min_fatia:.0f}% do orçamento dela")
    print(f"  {len(linhas)} fornecedores · R$ {moeda(sum(x['pago_ug'] for x in linhas))}")
    if not a.com_repasse:
        print("  (repasse fundo-a-fundo, folha e órgãos públicos EXCLUÍDOS — não é contratação)")
    print("\nUM LADO SÓ NÃO DISCRIMINA: 67,6% dos fornecedores acima de R$ 1 mi já concentram 95%+ "
          "numa UG.\nÉ a reciprocidade que restringe a 2,9%.\n")
    print(f"{'conc':>5} {'fatia UG':>9} {'pago pela UG':>18} {'UG':>7}  fornecedor")
    for x in linhas[:a.limite]:
        print(f"{100*x['concentracao']:4.0f}% {100*x['fatia_ug']:8.1f}% "
              f"R$ {moeda(x['pago_ug']):>15} {x['ug']:>7}  {x['nome'][:32]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
