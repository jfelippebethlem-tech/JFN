#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PAGO SEM CONTRATO — o que a leitura da IA aponta e nenhuma outra lente vê.

**A fonte é nova.** As sete lentes anteriores leem tabelas (OB, cadastro, QSA, PNCP, espelho do
TCE). Esta lê a **interpretação qualitativa** que o confronto IA×régua já gravou em
`sei_leitura_dupla.ia`, campo `interpretacao.chama_atencao` — 3.256 processos lidos, dos quais
2.968 têm apontamentos com **trecho citado dos autos**. Era dado pago e nunca minerado.

**O SINAL.** A IA aponta, em 13,4% dos processos lidos, ausência de contrato ou instrumento — a
citação típica vem da própria nota de empenho: *"Contrato 00000000 - SEM CONTRATO"*.

**PAGAR SEM CONTRATO É LÍCITO NA MAIORIA DOS CASOS**, e é isso que separa ruído de achado. A Lei
14.133 (art. 95) dispensa o termo de contrato em compra com entrega imediata e integral, e há toda
uma classe de despesa que nunca teve contrato por natureza: folha, tributo, tarifa de concessionária,
repasse fundo-a-fundo, precatório, diária. O filtro `_LEGITIMO` tira essas antes de qualquer conta.

**O que sobra é o núcleo exigível:** despesa de **compra, serviço, obra, locação ou manutenção** —
onde o instrumento é a regra — paga sem que os autos apresentem contrato.

RESSALVAS que viajam com o número:
  · **é a leitura da IA, não veredito jurídico.** Cada apontamento traz o trecho; a conferência é
    do humano. A lente ORDENA a fila, não acusa;
  · **só vê o que foi LIDO** — 3.256 de 221.130 processos com OB paga (1,5%). Ausência aqui não diz
    nada sobre o resto (INDISPONÍVEL != 0);
  · indenização e reconhecimento de dívida entram no núcleo DE PROPÓSITO: são exatamente os casos
    em que o serviço foi prestado sem cobertura contratual — o achado clássico do FSERJ;
  · o valor é o pago no PROCESSO (OB `Contabilizado`), não o do contrato inexistente.

Uso:
    .venv/bin/python tools/pago_sem_contrato.py
    .venv/bin/python tools/pago_sem_contrato.py --com-legitimos --limite 30
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.reporting.intel_base import moeda

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# A citação que a IA extrai dos autos — quase sempre da nota de empenho ou de liquidação.
_SEM_CONTRATO = re.compile(
    r"SEM CONTRATO|Contrato 0{6,}|aus[êe]ncia de (contrato|instrumento)|"
    r"sem instrumento contratual|n[ãa]o (h[áa]|consta) (contrato|instrumento)", re.I)

# Despesa que NUNCA teve contrato por natureza — sai antes de qualquer conta.
# "apoio financeiro a município" entra aqui: é repasse, e foi o que apareceu no topo da 1ª medição
# (R$ 123,5 mi ao Fundo Municipal de Saúde de Magé) fazendo o número parecer maior do que é.
_LEGITIMO = re.compile(
    r"folha|sal[áa]ri|pessoal|servidor|di[áa]ria|repasse|conv[êe]nio|transfer[êe]nc|subven|"
    r"contribui[çc][ãa]o|apoio financeiro|energia|[áa]gua|telefon|tarifa|concession|tributo|"
    r"imposto|INSS|FGTS|PASEP|encargo|judicial|precat|senten[çc]|honor[áa]ri|bolsa|aux[íi]lio", re.I)

# Onde o instrumento É a regra (Lei 14.133, art. 95 e seus limites).
_ESPERA_CONTRATO = re.compile(r"aquisi|contrata|servi[çc]o|fornecim|obra|manuten|loca[çc]", re.I)


def sem_contrato(con: sqlite3.Connection, com_legitimos: bool = False) -> list[dict]:
    """Processos em que a IA aponta ausência de contrato onde o instrumento era esperado."""
    alvo: dict = {}
    for numero, ia in con.execute(
            "SELECT numero_sei, ia FROM sei_leitura_dupla WHERE ia IS NOT NULL"):
        try:
            d = json.loads(ia)
        except (ValueError, TypeError):
            continue
        interp = d.get("interpretacao") or {}
        ca = interp.get("chama_atencao")
        if not ca:
            continue
        itens = ca if isinstance(ca, list) else [ca]
        texto = " ".join(str(x.get("ponto") if isinstance(x, dict) else x) for x in itens)
        if not _SEM_CONTRATO.search(texto):
            continue
        o_que_e = str(interp.get("o_que_e") or "")
        if not com_legitimos:
            if _LEGITIMO.search(o_que_e) or not _ESPERA_CONTRATO.search(o_que_e):
                continue
        # o trecho que sustenta — é ele que o humano confere
        trecho = ""
        for x in itens:
            if isinstance(x, dict):
                t = str(x.get("ponto") or "")
                if _SEM_CONTRATO.search(t):
                    trecho = t[:300]
                    break
        alvo[numero] = {"numero_sei": numero, "o_que_e": o_que_e[:200],
                        "trecho": trecho or texto[:300]}

    pago: dict = collections.defaultdict(float)
    obs: dict = collections.Counter()
    credor: dict = {}
    for processo, valor, nome in con.execute(
            "SELECT processo, valor, nome_credor FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado' AND processo LIKE 'SEI-%'"):
        k = str(processo).replace("SEI-", "")
        if k in alvo:
            pago[k] += valor or 0.0
            obs[k] += 1
            credor.setdefault(k, nome)

    saida = []
    for k, v in alvo.items():
        saida.append({**v, "pago": pago.get(k, 0.0), "n_obs": obs.get(k, 0),
                      "credor": credor.get(k, "")})
    saida.sort(key=lambda x: -x["pago"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--com-legitimos", action="store_true",
                    help="inclui folha/tarifa/repasse (conferência — NÃO é fila)")
    ap.add_argument("--limite", type=int, default=15)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    linhas = sem_contrato(con, com_legitimos=a.com_legitimos)
    print("pago sem contrato — fonte: interpretação da IA na leitura dupla")
    print(f"  {len(linhas)} processos · R$ {moeda(sum(x['pago'] for x in linhas))} pagos")
    if not a.com_legitimos:
        print("  (folha, tarifa, tributo, repasse e precatório EXCLUÍDOS — nunca tiveram contrato)")
    print("\n  Pagar sem contrato é LÍCITO em compra de entrega imediata (Lei 14.133, art. 95).")
    print("  A lente ordena fila: o trecho citado é o que o humano confere.\n")
    for x in linhas[:a.limite]:
        print(f"  R$ {moeda(x['pago']):>15} {x['n_obs']:4d} OB  {x['numero_sei']}  "
              f"{x['credor'][:26]}")
        print(f"       {x['o_que_e'][:104]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
