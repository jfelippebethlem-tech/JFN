#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CONVERGÊNCIA DE SINAIS — a mesma empresa marcada por DIMENSÕES independentes.

Um sinal isolado é porta de entrada; vários sinais INDEPENDENTES sobre o mesmo CNPJ é o que
justifica gastar leitura humana. Esta lente cruza os detectores da casa e ordena por convergência.

**DIMENSÃO, NÃO DETECTOR — e essa distinção derrubou meu próprio número.** A primeira versão contava
cada função como um sinal e achou "15 empresas em 3 lentes". Mas `porte_incompativel.incompativeis`
e `estrutura_magra` medem A MESMA COISA (empresa pequena com muito dinheiro): somá-las é contar a
mesma evidência duas vezes. Agrupadas em dimensões de verdade:

    TAMANHO      porte acima do teto legal  OU  estrutura societária mínima
    SANCAO       pagamento durante sanção   OU  sócio-administrador vindo de sancionada
    DEPENDENCIA  concentração recíproca pagador ↔ fornecedor

Medido em 2026-08-19 sobre 1.358 empresas marcadas por ao menos uma dimensão:
    · 2 dimensões ... 83 (6,1%)
    · 3 dimensões ...  0 (0,00%)

O "15 em três lentes" era artefato. Com dimensões independentes, ninguém acumula as três — e isso é
informação: os eixos capturam populações diferentes, não a mesma sob nomes distintos.

RESSALVAS:
  · convergência ORDENA a fila, não conclui nada — cada dimensão já traz as suas próprias ressalvas
    (porte desatualizado, alcance da sanção, repasse, etc.);
  · agrega por CNPJ BÁSICO: matriz e filiais somam, como manda o porte e o QSA;
  · só OB `status='Contabilizado'`.

Uso:
    .venv/bin/python tools/convergencia.py
    .venv/bin/python tools/convergencia.py --min-dim 2 --limite 40
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
from tools.dependencia_mutua import dependencia
from tools.pago_a_sancionado import pagos_durante_sancao, sucessao_societaria
from tools.porte_declarado_certame import declaracoes_incompativeis
from tools.porte_incompativel import estrutura_magra, incompativeis
from tools.troca_de_controle import trocas

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"


def convergir(con: sqlite3.Connection, min_pago_estrutura: float = 5_000_000.0) -> list[dict]:
    """CNPJ básico -> dimensões que o marcam, com o total recebido."""
    dim: dict = collections.defaultdict(set)
    nome: dict = {}
    detalhe: dict = collections.defaultdict(list)

    def marcar(basico, dimensao, razao=None, origem=""):
        b = str(basico).zfill(8)[:8]
        dim[b].add(dimensao)
        if origem:
            detalhe[b].append(origem)
        if razao and b not in nome:
            nome[b] = razao

    for x in incompativeis(con, min_razao=1.0):
        marcar(x["cnpj_basico"], "TAMANHO", x["razao_social"], "porte acima do teto")
    # `estrutura_magra` FORA da convergência (2026-08-23). Medido: ela marca **707 de 1.278**
    # empresas do universo (QSA conhecido, >= R$ 5 mi) — **55,3%**, e mesmo o corte de UM só sócio
    # atinge 29,2%. Sinal que marca metade do acervo não ordena fila; ele só empurra empresas para
    # a dimensão TAMANHO sem dizer nada. Das 1.114 marcadas por TAMANHO, **541 vinham SÓ dela**.
    # A própria casa já havia descartado "um só sócio" por prevalência (54,9%, registrado no
    # docstring de `sucessao_societaria`) — e o sinal descartado seguia alimentando a convergência
    # por outra porta. Encontrado ao abrir o 1º colocado (LAND Serviços), cuja única marca de
    # TAMANHO era esta: 2 sócios para R$ 128,26 mi, o que não é anomalia nenhuma.
    # A função continua existindo e útil no CLI de `porte_incompativel`, como leitura de contexto.
    for x in pagos_durante_sancao(con):
        marcar(x["cnpj"][:8], "SANCAO", x["nome"], f"pago sob {x['categoria'][:18]}")
    for x in sucessao_societaria(con):
        marcar(x["cnpj_basico"], "SANCAO", x["razao_social"], "sócio de sancionada")
    for x in dependencia(con):
        marcar(x["cnpj"][:8], "DEPENDENCIA", x["nome"],
               f"{100*x['concentracao']:.0f}% de 1 UG / {100*x['fatia_ug']:.0f}% dela")

    # `porte_declarado_certame` entra em TAMANHO, NÃO como dimensão própria. Ele mede o mesmo
    # fenômeno que `porte_incompativel` — empresa maior do que o porte que ostenta —, mudando só
    # a FONTE (declaração no certame × cadastro da Receita). Contá-lo separado inflaria a
    # convergência exatamente como já aconteceu quando `porte` e `estrutura magra` contavam duas
    # vezes: "15 empresas em 3 lentes" virou 0 quando a duplicidade saiu.
    # O que ele acrescenta é AGRAVANTE, não dimensão: declarar-se ME ao licitar é ATO datado da
    # própria empresa, enquanto cadastro desatualizado é estado de terceiro. O `porque` diz isso.
    for x in declaracoes_incompativeis(con, estrito=True):
        marcar(x["cnpj_basico"], "TAMANHO", x["nome"],
               f"declarou-se {'/'.join(x['portes'])} em {x['n_certames']} certame(s)")

    # CONTROLE é dimensão PRÓPRIA: nada tem a ver com tamanho, sanção ou dependência. Mede outra
    # coisa — quem recebe hoje não é quem contratou.
    for x in trocas(con, forte=True):
        s0 = (x["saidas"] or [{}])[0]
        marcar(x["cnpj_basico"], "CONTROLE", x["nome"],
               f"troca total de sócios em {s0.get('quando', '?')}")

    pago: dict = collections.defaultdict(float)
    for credor, valor in con.execute(
            "SELECT credor, valor FROM ob_orcamentaria_siafe WHERE status='Contabilizado'"):
        d = re.sub(r"\D", "", str(credor))
        if len(d) >= 8 and d[:8] in dim:
            pago[d[:8]] += (valor or 0)

    saida = [{"cnpj_basico": b, "razao_social": nome.get(b, "?"), "dimensoes": sorted(v),
              "n_dim": len(v), "pago": pago.get(b, 0.0), "porques": detalhe[b][:4]}
             for b, v in dim.items()]
    saida.sort(key=lambda x: (-x["n_dim"], -x["pago"]))
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-dim", type=int, default=2)
    ap.add_argument("--limite", type=int, default=25)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    todos = convergir(con)
    linhas = [x for x in todos if x["n_dim"] >= a.min_dim]
    dist = collections.Counter(x["n_dim"] for x in todos)
    print(f"empresas marcadas por ao menos uma dimensão: {len(todos):,}")
    for k in sorted(dist, reverse=True):
        print(f"   {k} dimensão(ões): {dist[k]:5d}  ({100*dist[k]/len(todos):.1f}%)")
    print(f"\ncom >= {a.min_dim} dimensões: {len(linhas)} · R$ {moeda(sum(x['pago'] for x in linhas))}")
    print("\nDIMENSÃO ≠ DETECTOR: `porte` e `estrutura` medem a mesma coisa e contam UMA vez.\n"
          "Convergência ORDENA a fila — cada dimensão carrega as próprias ressalvas.\n")
    print(f"{'pago':>18} {'dim':>3}  dimensões                    empresa")
    for x in linhas[:a.limite]:
        print(f"R$ {moeda(x['pago']):>15} {x['n_dim']:3d}  {'+'.join(x['dimensoes']):28} "
              f"{x['razao_social'][:30]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
