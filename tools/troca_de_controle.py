#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TROCA DE CONTROLE durante a execução — quem recebe hoje não é quem contratou.

**A pergunta.** A habilitação de uma licitante é da PESSOA JURÍDICA, mas quem responde por ela é
o quadro societário. Se a empresa foi vendida no meio da execução, a Administração passou a pagar
a um controlador que não participou do certame — e isso pode ser rotina de mercado ou pode ser o
veículo de uma sucessão que a habilitação não examinou.

**Por que não é `osint/grupo_economico` nem `pago_a_sancionado.sucessao_societaria`.** Aquele mede
grupo de fato num instante (fecho transitivo por sócio comum); este mede MUDANÇA no tempo. E a
`sucessao_societaria` pergunta outra coisa: sócio que vem de empresa SANCIONADA. Aqui não há
sanção envolvida — há troca de dono durante o contrato.

**A fonte certa é `socio_historico`, não `socios_receita`.** O primeiro protótipo inferia troca
pela `data_entrada` do snapshot único de `socios_receita` (2026-05) e produziu lixo: Light, Ampla,
Vibra, Correios e Pluxee no topo, porque a Receita registra DIRETOR eleito como sócio e mandato
rotativo virava "troca de controle". `socio_historico` tem 41 meses de snapshots e registra a
SAÍDA com janela (`saiu_entre`, `janela_confiavel`) — é observação, não inferência.

**PREVALÊNCIA MANDA NO CORTE** (medido em 2026-08-23 sobre 1.892 LTDA acima de R$ 1 mi com
histórico societário confiável):
  · alguma saída de sócio durante a janela de pagamentos .... 408 (**21,6%**) — NÃO discrimina;
  · **nenhum** sócio atual estava lá no 1º pagamento ........ 135 (**7,1%**) — este é o padrão.
Um sinal que marca um quinto do universo não ordena fila nenhuma. O corte forte é o default, e
`--fraco` existe só para conferência.

RESSALVAS que viajam com o número:
  · **trocar de dono é LÍCITO.** Venda de empresa, entrada de investidor e sucessão familiar são
    rotina — o achado é a PERGUNTA (a Administração examinou?), não a resposta;
  · só sociedades LIMITADAS e empresário individual (naturezas 2062/2240/2305). S.A. e empresa
    pública ficam fora porque nelas a rotação de administrador não é troca de controle;
  · só qualificação de **sócio** (o filtro `'cio' in qualificacao`), nunca Diretor/Presidente;
  · a janela do histórico começa em **2023-03**: troca anterior a isso é invisível — ausência aqui
    é limite de fonte, NUNCA prova de que não houve;
  · OB `status='Contabilizado'` apenas — OB é pagamento; empenho e liquidação não entram.

Uso:
    .venv/bin/python tools/troca_de_controle.py
    .venv/bin/python tools/troca_de_controle.py --fraco --limite 30
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

# Limitada, unipessoal e empresário individual. Fora: S.A., OSS, fundação, órgão público — onde
# administrador rotativo NÃO é troca de controle.
NATUREZAS = {"2062", "2240", "2305"}

# QUEM É "COMANDO" — sócio E administrador, não só sócio.
# A primeira versão exigia `'cio' in qualificacao` e deixava de fora o "Administrador" puro. Isso
# produziu falso positivo medido em 2026-08-23 ao abrir o 1º colocado, como manda a casa: a LAND
# SERVIÇOS (R$ 128,26 mi) trocou de sócio (ASPEN ENGENHARIA E PARTICIPAÇÕES -> ASPEN PARTICIPAÇÕES,
# nomes quase idênticos) enquanto ALESSANDRO CARVALHO DE MIRANDA seguia ADMINISTRADOR desde 2017.
# Chamar isso de "troca total de controle" é falso: o comando não mudou. Eram 11 casos assim
# (8,1%, R$ 543 mi), incluindo a Comercial Milano, que eu já havia publicado.
# Diretor/Presidente continuam FORA — em S.A. e empresa pública são mandato, não controle; e a
# natureza já restringe a LTDA, onde "Administrador" designa quem responde pela sociedade.
_COMANDO = re.compile(r"s[oó]cio|administrador", re.I)


def _ym(data_emissao: str) -> str:
    """`data_emissao` do SIAFE é TEXTO DD/MM/AAAA — vira AAAA-MM para comparar com o histórico."""
    p = str(data_emissao or "").split("/")
    return f"{p[2]}-{p[1]}" if len(p) == 3 and len(p[2]) == 4 else ""


def _pagamentos(con: sqlite3.Connection) -> tuple[dict, dict, dict, dict]:
    pri: dict = {}
    ult: dict = {}
    tot: dict = collections.defaultdict(float)
    nome: dict = {}
    for credor, valor, data, nm in con.execute(
            "SELECT credor, valor, data_emissao, nome_credor FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado'"):
        dig = re.sub(r"\D", "", str(credor))
        ym = _ym(data)
        if len(dig) != 14 or not ym:
            continue
        b = dig[:8]
        if b not in pri or ym < pri[b]:
            pri[b] = ym
        if b not in ult or ym > ult[b]:
            ult[b] = ym
        tot[b] += valor or 0.0
        nome.setdefault(b, nm)
    return pri, ult, tot, nome


def trocas(con: sqlite3.Connection, min_pago: float = 1_000_000.0,
           forte: bool = True) -> list[dict]:
    """Empresas que trocaram de sócio durante a janela de pagamentos."""
    natureza = {str(b).zfill(8): str(n) for b, n in
                con.execute("SELECT cnpj_basico, natureza_cod FROM empresas_cadastro")}
    pri, ult, tot, nome = _pagamentos(con)

    saiu: dict = collections.defaultdict(list)
    ativo: dict = collections.defaultdict(list)
    for b, nn, qual, saiu_entre, status, entrada in con.execute(
            "SELECT cnpj_basico, nome_norm, qualificacao, saiu_entre, status, data_entrada "
            "FROM socio_historico WHERE janela_confiavel=1"):
        b = str(b).zfill(8)
        if b == "00000000" or not _COMANDO.search(str(qual)):
            continue
        if status == "saiu":
            saiu[b].append({"quando": str(saiu_entre)[:7], "nome": nn, "qualificacao": qual})
        elif len(str(entrada)) == 8:
            e = str(entrada)
            ativo[b].append({"desde": f"{e[:4]}-{e[4:6]}", "nome": nn, "qualificacao": qual})

    saida = []
    for b, pago in tot.items():
        if pago < min_pago or natureza.get(b) not in NATUREZAS:
            continue
        na_janela = [s for s in saiu.get(b, []) if pri[b] <= s["quando"] <= ult[b]]
        if not na_janela:
            continue
        atuais = ativo.get(b) or []
        # CORTE FORTE: nenhum sócio de hoje estava lá quando o primeiro pagamento saiu.
        if forte and not (atuais and min(a["desde"] for a in atuais) > pri[b]):
            continue
        saida.append({
            "cnpj_basico": b, "nome": nome.get(b, "?"), "pago": pago,
            "primeiro_pagamento": pri[b], "ultimo_pagamento": ult[b],
            "saidas": sorted(na_janela, key=lambda s: s["quando"]),
            "socios_atuais": sorted(atuais, key=lambda a: a["desde"]),
            "troca_total": bool(atuais and min(a["desde"] for a in atuais) > pri[b]),
        })
    saida.sort(key=lambda x: -x["pago"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fraco", action="store_true",
                    help="qualquer saída na janela (21,6% do universo — conferência, não fila)")
    ap.add_argument("--min-pago", type=float, default=1_000_000.0)
    ap.add_argument("--limite", type=int, default=15)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    linhas = trocas(con, min_pago=a.min_pago, forte=not a.fraco)
    print("troca de controle durante a execução do contrato")
    print(f"  corte: {'QUALQUER saída na janela (fraco, 21,6% — conferência)' if a.fraco else 'TROCA TOTAL — nenhum sócio atual estava no 1º pagamento (7,1%)'}")
    print(f"  {len(linhas)} empresas · R$ {moeda(sum(x['pago'] for x in linhas))}")
    print("\n  Trocar de dono é LÍCITO. O achado é a pergunta — a Administração examinou a "
          "habilitação\n  do novo controlador? —, não a resposta. Histórico começa em 2023-03: "
          "troca anterior é invisível.\n")
    for x in linhas[:a.limite]:
        print(f"R$ {moeda(x['pago']):>17}  {x['nome'][:42]}  ({x['primeiro_pagamento']} → "
              f"{x['ultimo_pagamento']})")
        for s in x["saidas"][:2]:
            print(f"{'':>19}  SAIU   {s['quando']}  {s['nome'][:36]} ({s['qualificacao']})")
        for s in x["socios_atuais"][:2]:
            print(f"{'':>19}  entrou {s['desde']}  {s['nome'][:36]} ({s['qualificacao']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
