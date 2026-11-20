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
  · **é PISO.** Só somo o que o Estado do RJ pagou (OB `status='Contabilizado'`, sem a devolvida pelo banco — 'Erro no Pagamento'); o critério legal
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

from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.limites_porte import TETO_EPP

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
            f"WHERE {_ob_paga(con)}"):
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


# Escopo da casa: certame do Estado do RJ ou da Prefeitura do Rio (vocabulário de `pncp_resultados`).
ESFERAS_DA_CASA = ("estado", "prefeitura")


def _esfera_do_certame(reg: dict, oficial: dict) -> str:
    """Esfera do COMPRADOR do certame pela régua única (`pncp_resultados.classificar_esfera`). Base antiga sem as
    colunas do órgão: vale o CNPJ que abre o número de controle do PNCP."""
    from compliance_agent.collectors.pncp_resultados import classificar_esfera
    if not reg.get("orgao_cnpj"):
        reg = {**reg, "orgao_cnpj": re.sub(r"\D", "", str(reg.get("certame") or "").split("-")[0])[:14]}
    return classificar_esfera(reg, oficial)


def declaracoes_incompativeis(con: sqlite3.Connection, estrito: bool = True,
                              esferas: tuple | None = ESFERAS_DA_CASA) -> list[dict]:
    """Certames em que a empresa se declarou ME/EPP/MEI já tendo estourado o teto no ano.

    `esferas`: de que comprador o certame pode ser — padrão, o escopo da casa (Estado do RJ e Prefeitura do Rio);
    None = todos (pesquisa). Até 20/11/2026 a lente da aba ESTADUAL listava certame de qualquer ente: dos 38
    certames exibidos, 16 eram de órgão federal, 13 de outros municípios, 8 da Prefeitura e 1 do Estado. Cada
    certame sai com a `esfera`; a empresa, com `por_esfera` e `certames_fora_do_escopo` (contado, não escondido)."""
    from compliance_agent.collectors.pncp_resultados import esferas_por_ente
    ev = _pagamentos(con)
    oficial = esferas_por_ente(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    extras = [c for c in ("orgao_cnpj", "orgao_nome", "unidade_nome", "municipio", "uf") if c in cols]
    achados: dict = collections.defaultdict(
        lambda: {"nome": "", "portes": set(), "certames": [], "homologado": 0.0, "pico": 0.0, "fora": 0})
    for cnpj, nome, porte, data_pub, certame, valor, *org in con.execute(
            "SELECT fornecedor_cnpj, fornecedor_nome, porte_fornecedor, data_pub, certame, "
            f"valor_homologado{''.join(', ' + c for c in extras)} FROM pncp_resultado WHERE porte_fornecedor IN (1,2,6)"):
        dig = re.sub(r"\D", "", str(cnpj or ""))
        if len(dig) < 8 or not data_pub:
            continue
        basico, pub = dig[:8], str(data_pub)
        recebido = (_acumulado_no_ano(ev, basico, pub) if estrito
                    else _total_no_ano(ev, basico, pub[:4]))
        if recebido <= TETO_EPP:
            continue
        esf = _esfera_do_certame({"certame": certame, **dict(zip(extras, org))}, oficial)
        if esferas is not None and esf not in esferas:
            achados[basico]["fora"] += 1          # certame de outro ente: fora do escopo, mas contado
            continue
        a = achados[basico]
        a["nome"] = a["nome"] or (nome or "")
        a["portes"].add(PORTE_PNCP.get(porte, str(porte)))
        a["homologado"] += valor or 0.0
        a["pico"] = max(a["pico"], recebido)
        a["certames"].append({"certame": certame, "esfera": esf, "data_pub": pub, "recebido_ate": recebido,
                              "homologado": valor or 0.0, "porte": PORTE_PNCP.get(porte, porte)})
    saida = []
    for basico, a in achados.items():
        if not a["certames"]:
            continue                               # só declarou em certame de outro ente: fora da lente da casa
        a["certames"].sort(key=lambda x: -x["recebido_ate"])
        por_esfera = collections.Counter()
        for c in {(c["certame"], c["esfera"]) for c in a["certames"]}:
            por_esfera[c[1]] += 1
        saida.append({"cnpj_basico": basico, "nome": a["nome"], "portes": sorted(a["portes"]),
                      "n_certames": len({c["certame"] for c in a["certames"]}),
                      "por_esfera": dict(por_esfera), "certames_fora_do_escopo": a["fora"],
                      "homologado": a["homologado"], "recebido_pico": a["pico"],
                      "certames": a["certames"]})
    saida.sort(key=lambda x: -x["recebido_pico"])
    return saida


def fora_do_escopo(con: sqlite3.Connection, estrito: bool = True) -> dict:
    """O que a lente da casa deixou de fora, para ninguém ler a lista curta como "é só isso": empresas cuja
    declaração só aparece em certame de outro ente, e certames distintos por esfera (municípios do interior,
    órgão federal). Não é achado da casa — é o que existe na base fora do escopo, e quem pesquisa pede `esferas=None`."""
    por_esfera: collections.Counter = collections.Counter()
    so_fora = []
    for x in declaracoes_incompativeis(con, estrito=estrito, esferas=None):
        cs = {(c["certame"], c["esfera"]) for c in x["certames"]}
        fora = [e for _, e in cs if e not in ESFERAS_DA_CASA]
        por_esfera.update(fora)
        if fora and len(fora) == len(cs):
            so_fora.append(x["nome"])
    return {"empresas_so_fora_do_escopo": len(so_fora), "nomes": sorted(so_fora)[:40],
            "certames_por_esfera": dict(por_esfera),
            "nota": "certames de outros entes (municípios do interior, órgãos federais) — fora do escopo da casa "
                    "(Estado do RJ e Prefeitura do Rio); listados aqui só como contagem"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--amplo", action="store_true",
                    help="mesmo ano-calendário (teto da medida) em vez do corte na data do certame")
    ap.add_argument("--limite", type=int, default=20)
    ap.add_argument("--todas", action="store_true",
                    help="inclui certame de outros entes (pesquisa); o padrão é Estado do RJ + Prefeitura do Rio")
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    linhas = declaracoes_incompativeis(con, estrito=not a.amplo, esferas=None if a.todas else ESFERAS_DA_CASA)
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
