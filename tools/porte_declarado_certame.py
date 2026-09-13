#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PORTE DECLARADO NO CERTAME × recebido no ano — fruição indevida do benefício de ME/EPP.

**A diferença para `porte_incompativel.py`.** Aquele lê o porte do CADASTRO da Receita, e a
objeção óbvia é que cadastro fica velho por inércia. Este lê o porte que a empresa **declarou ao
licitar** (`pncp_resultado.porte_fornecedor`, domínio oficial do PNCP: 1=ME, 2=EPP, 3=Demais,
4=Não se aplica, 5=Não informado, 6=MEI). Declaração é ato próprio, datado, no processo — não é
inércia de terceiro.

**O critério é o LEGAL, não um proxy.** A Lei 14.133/2021 exige do licitante ME/EPP declaração de
que, no ano-calendário da licitação, não celebrou contratos com a Administração cujos valores
somados extrapolem a receita bruta máxima de EPP (R$ 4.800.000,00 — LC 123/2006, art. 3º). O TCU
firmou que a **declaração falsa de enquadramento já caracteriza fraude à licitação**, ainda que a
empresa não obtenha vantagem concreta no certame (Ac. 2695/2025-Plenário).

**Dois cortes, e o estrito é o que se publica:**
  · `--amplo`   — declarou ME/EPP em certame no MESMO ano em que estourou o teto. Inclui o caso
                  em que o certame é de janeiro e o estouro veio em dezembro: a empresa podia
                  ainda não saber. Serve de teto da medida, não de acusação.
  · (padrão)    — **estrito**: o certame foi publicado DEPOIS de a empresa já ter recebido, naquele
                  mesmo ano, acima do teto. Aqui ela sabia — o dado estava no próprio caixa dela.

RESSALVAS que viajam com o número:
  · **é PISO.** Só somo o que o Estado do RJ pagou (OB `status='Contabilizado'`); o critério legal
    soma contratos com TODA a Administração — União, outros estados, municípios;
  · **pago ≠ contrato celebrado.** A vedação fala em valor de contratos do ano-calendário; eu meço
    OB paga. Para o desenquadramento por RECEITA BRUTA (LC 123, art. 3º) a medida vale direto —
    quem recebeu R$ 27 mi teve receita ≥ R$ 27 mi;
  · **a captura do PNCP cobre 2024-2026 e só o RJ.** Ausência de certame aqui é lacuna de captura,
    NUNCA prova de que não houve licitação;
  · agrega por CNPJ **básico** (8 dígitos): o teto da LC 123 é da pessoa jurídica, não do
    estabelecimento — matriz e filial somam;
  · indício para apuração. Só o edital e a ata dizem se algum benefício (empate ficto, cota
    reservada, exclusividade) foi de fato aplicado.

Uso:
    .venv/bin/python tools/porte_declarado_certame.py
    .venv/bin/python tools/porte_declarado_certame.py --amplo --limite 30
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

# LC 123/2006, art. 3º, II — receita bruta máxima de EPP. É o limite citado pela Lei 14.133 na
# declaração exigida do licitante; ME (R$ 360 mil) é mais baixo, então EPP é o corte CONSERVADOR.
TETO_EPP = 4_800_000.0

# Domínio oficial do PNCP (GET /api/pncp/v1/portes-empresa, conferido em 2026-08-22).
PORTE_PNCP = {1: "ME", 2: "EPP", 3: "Demais", 4: "Não se aplica", 5: "Não informado", 6: "MEI"}
PEQUENO = {1, 2, 6}


def _iso(data_emissao: str) -> str:
    """`data_emissao` do SIAFE é TEXTO DD/MM/AAAA — comparar como string exige virar ISO."""
    p = str(data_emissao or "").split("/")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 and len(p[2]) == 4 else ""


def _pagamentos(con: sqlite3.Connection) -> dict[str, list[tuple[str, float]]]:
    """OB paga por CNPJ básico, ordenada por data ISO. Só `Contabilizado` — OB é pagamento."""
    ev: dict = collections.defaultdict(list)
    for credor, valor, data in con.execute(
            "SELECT credor, valor, data_emissao FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado'"):
        dig = re.sub(r"\D", "", str(credor))
        iso = _iso(data)
        if len(dig) == 14 and iso:
            ev[dig[:8]].append((iso, valor or 0.0))
    for k in ev:
        ev[k].sort()
    return ev


def _acumulado_no_ano(ev: dict, basico: str, ate_iso: str) -> float:
    """Quanto a empresa já recebeu no ano-calendário de `ate_iso`, até essa data inclusive."""
    ano = ate_iso[:4]
    return sum(v for dt, v in ev.get(basico, ()) if dt[:4] == ano and dt <= ate_iso)


def _total_no_ano(ev: dict, basico: str, ano: str) -> float:
    return sum(v for dt, v in ev.get(basico, ()) if dt[:4] == ano)


def declaracoes_incompativeis(con: sqlite3.Connection, estrito: bool = True) -> list[dict]:
    """Certames em que a empresa se declarou ME/EPP/MEI já tendo estourado o teto no ano."""
    ev = _pagamentos(con)
    achados: dict = collections.defaultdict(
        lambda: {"nome": "", "portes": set(), "certames": [], "homologado": 0.0, "pico": 0.0})
    for cnpj, nome, porte, data_pub, certame, valor in con.execute(
            "SELECT fornecedor_cnpj, fornecedor_nome, porte_fornecedor, data_pub, certame, "
            "valor_homologado FROM pncp_resultado WHERE porte_fornecedor IN (1,2,6)"):
        dig = re.sub(r"\D", "", str(cnpj or ""))
        if len(dig) < 8 or not data_pub:
            continue
        basico, pub = dig[:8], str(data_pub)
        recebido = (_acumulado_no_ano(ev, basico, pub) if estrito
                    else _total_no_ano(ev, basico, pub[:4]))
        if recebido <= TETO_EPP:
            continue
        a = achados[basico]
        a["nome"] = a["nome"] or (nome or "")
        a["portes"].add(PORTE_PNCP.get(porte, str(porte)))
        a["homologado"] += valor or 0.0
        a["pico"] = max(a["pico"], recebido)
        a["certames"].append({"certame": certame, "data_pub": pub, "recebido_ate": recebido,
                              "homologado": valor or 0.0, "porte": PORTE_PNCP.get(porte, porte)})
    saida = []
    for basico, a in achados.items():
        a["certames"].sort(key=lambda x: -x["recebido_ate"])
        saida.append({"cnpj_basico": basico, "nome": a["nome"], "portes": sorted(a["portes"]),
                      "n_certames": len({c["certame"] for c in a["certames"]}),
                      "homologado": a["homologado"], "recebido_pico": a["pico"],
                      "certames": a["certames"]})
    saida.sort(key=lambda x: -x["recebido_pico"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--amplo", action="store_true",
                    help="mesmo ano-calendário (teto da medida) em vez do corte na data do certame")
    ap.add_argument("--limite", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    linhas = declaracoes_incompativeis(con, estrito=not a.amplo)
    print("declaração de ME/EPP em certame × já recebido do Estado no ano-calendário")
    print(f"  critério: {'MESMO ANO (amplo — inclui certame anterior ao estouro)' if a.amplo else 'ESTRITO — certame publicado DEPOIS de a empresa já ter estourado o teto'}")
    print(f"  teto de EPP: R$ {moeda(TETO_EPP)} (LC 123/2006, art. 3º, II)\n")
    print(f"  {len(linhas)} empresas · {sum(x['n_certames'] for x in linhas)} certames · "
          f"R$ {moeda(sum(x['homologado'] for x in linhas))} homologado")
    print("\n  O número é PISO: só entra o pago pelo Estado do RJ, e a captura do PNCP cobre "
          "2024-2026/RJ.\n  Ausência de certame aqui é lacuna de captura, nunca prova de que não houve.\n")
    print(f"{'já recebido no ano':>20} {'data do certame':>16} {'homologado':>16}  porte  empresa")
    for x in linhas[:a.limite]:
        c0 = x["certames"][0]
        print(f"R$ {moeda(c0['recebido_ate']):>17} {c0['data_pub']:>16} "
              f"R$ {moeda(x['homologado']):>13}  {'/'.join(x['portes']):5s}  {x['nome'][:34]}")
        print(f"{'':>20} {'certame':>16} {c0['certame']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
