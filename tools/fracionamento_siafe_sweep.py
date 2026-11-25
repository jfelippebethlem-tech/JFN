#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lista a fila de candidatos ao P4 (`candidato_p4`, ótica do pagamento, SIAFE) — gravação CONGELADA (O4.8).

POR QUE ESTE ARQUIVO EXISTE. `compliance_agent/fracionamento_siafe.py` foi construído em
2026-07-24, é sólido, e estava **órfão**: nenhum módulo o chamava e nada persistia o resultado.
A fila existia só na memória de quem rodasse à mão. Aqui ela vira tabela consultável.

HONESTIDADE HERDADA DO MÓDULO: isto é **triagem, não achado**. O SIAFE não traz objeto nem
modalidade, e seu número de processo não casa com o do SEI. O grau é sempre `a_verificar`, e
cada linha carrega os processos para o auditor puxar os autos.

CONGELADA (O4.8, plano mestre v2 §4.5): `siafe_fracionamento` não recebe escrita nova — a série é `candidato_p4`
e vive no E10 `e10.candidato_p4_siafe`. O sweep só LISTA; `--gravar` sai com código 2 e `persistir` levanta.

    .venv/bin/python tools/fracionamento_siafe_sweep.py --exercicio 2026 [--gravar] [--top 15]
    .venv/bin/python tools/fracionamento_siafe_sweep.py --todos --gravar
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.fracionamento_siafe import triagem  # noqa: E402
from compliance_agent.reporting.intel_base import moeda  # noqa: E402  formatador da casa (BR)

from compliance_agent.collectors.arquivos import caminho_db  # noqa: E402

DB = str(caminho_db())


class TabelaCongelada(RuntimeError):
    """`siafe_fracionamento` está congelada (O4.8): nenhuma escrita nova."""


CONGELADA = ("siafe_fracionamento CONGELADA na O4.8 (plano mestre v2 §4.5): a série de OB por credor × UG é "
             "`candidato_p4`, não fracionamento, e vive no E10 `e10.candidato_p4_siafe` (PG, esquema sombra). "
             "A tabela fica só-leitura como histórico; o sweep só lista (sem --gravar).")


def persistir(con: sqlite3.Connection, candidatos: list[dict], *,
              exercicio: int | None = None) -> int:
    """CONGELADA (O4.8): levanta `TabelaCongelada` sem tocar o banco. Até 24/11/2026 gravava a fila por
    (exercicio, ug, credor) com retirada escopada das gerações anteriores; o histórico fica na tabela, só-leitura."""
    raise TabelaCongelada(CONGELADA)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int)
    ap.add_argument("--todos", action="store_true", help="2021 até o ano corrente")
    ap.add_argument("--ug", help="limita a uma unidade gestora")
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    if a.gravar:
        print(CONGELADA, file=sys.stderr)
        return 2

    anos = (list(range(2021, datetime.now().year + 1)) if a.todos
            else [a.exercicio or datetime.now().year])

    con = sqlite3.connect(DB, timeout=60)
    total = 0
    for ano in anos:
        r = triagem(con, exercicio=ano, limite_ug=a.ug)
        cands = r["candidatos"]
        total += len(cands)
        print(f"\n=== {ano} — teto R$ {moeda(r['limite_dispensa'])} ({r['ato']}) ===")
        print(f"  OBs lidas {r['obs_lidas']:>7} · descartadas: status {r['obs_descartadas_status']:>5}, "
              f"credor não-licitável {r['obs_descartadas_credor']:>6}, "
              f"processo único {r['grupos_descartados_processo_unico']:>4}")
        # DISCRIMINANTE: o fornecedor teve contratação direta registrada neste exercício?
        # Sem isto a fila mistura execução de contrato licitado (normal) com direta repetida
        # (o que o art. 75, § 1º veda), e obriga o analista a abrir cada um dos 1.175.
        from compliance_agent.fracionamento_siafe import fornecedor_teve_direta
        for c in cands:
            c["fornecedor_teve_direta"] = fornecedor_teve_direta(con, c)
        com_direta = [c for c in cands if c.get("fornecedor_teve_direta")]
        print(f"  CANDIDATOS (a_verificar): {len(cands)}")
        if cands:
            soma = sum(c.get("soma") or 0 for c in com_direta)
            print(f"    dos quais com fornecedor que teve DIRETA no exercício: "
                  f"{len(com_direta)} (R$ {moeda(soma)}) — prioridade de diligência")
        for c in cands[:a.top]:
            print(f"    prio={c['prioridade']:.3f}  {(c['nome_credor'] or '')[:36]:38} "
                  f"UG {c['ug_emitente']:8} OBs={c['n_obs']:>3} proc={c['n_processos']:>3} "
                  f"rente={c['n_rente_ao_teto']:>2} R$ {c['soma']:>13,.2f} ({c['razao_soma_limite']}× o teto)")
        if a.gravar:
            print(f"  gravados: {persistir(con, cands, exercicio=ano)}")
    con.close()
    print(f"\nTOTAL de candidatos: {total}")
    print("Lembrete: TRIAGEM, não achado — falta objeto e modalidade; puxar os autos antes de concluir.")
    print("`fornecedor_teve_direta` diz que o FORNECEDOR teve contratação direta no exercício, "
          "não que ESTA despesa foi direta — a unidade não entra na chave (as bases a guardam "
          "de formas incompatíveis).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
