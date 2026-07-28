#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materializa a fila de candidatos a fracionamento (ótica do pagamento, SIAFE).

POR QUE ESTE ARQUIVO EXISTE. `compliance_agent/fracionamento_siafe.py` foi construído em
2026-07-24, é sólido, e estava **órfão**: nenhum módulo o chamava e nada persistia o resultado.
A fila existia só na memória de quem rodasse à mão. Aqui ela vira tabela consultável.

HONESTIDADE HERDADA DO MÓDULO: isto é **triagem, não achado**. O SIAFE não traz objeto nem
modalidade, e seu número de processo não casa com o do SEI. O grau é sempre `a_verificar`, e
cada linha carrega os processos para o auditor puxar os autos.

IDEMPOTENTE: `INSERT OR REPLACE` por (exercicio, ug, credor), mais uma retirada ESCOPADA das
gerações anteriores do MESMO exercício (ver `persistir`) — sem ela, melhorar a régua não limpa
a fila. Nunca um `DELETE` global — a lição de
`anomalias.regras()`, que truncou a `ob_redflag` de 69.807 para 12.215 ao ser testada com amostra.

    .venv/bin/python tools/fracionamento_siafe_sweep.py --exercicio 2026 [--gravar] [--top 15]
    .venv/bin/python tools/fracionamento_siafe_sweep.py --todos --gravar
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.fracionamento_siafe import triagem  # noqa: E402
from compliance_agent.reporting.intel_base import moeda  # noqa: E402  formatador da casa (BR)

DB = os.environ.get("JFN_DB", "data/compliance.db")


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS siafe_fracionamento (
            exercicio INTEGER, ug_emitente TEXT, credor TEXT, nome_credor TEXT,
            n_obs INTEGER, n_processos INTEGER, soma REAL, limite_dispensa REAL,
            razao_soma_limite REAL, intervalo_mediano_dias REAL, n_rente_ao_teto INTEGER,
            primeira_ob TEXT, ultima_ob TEXT, prioridade REAL, grau TEXT,
            processos TEXT, obs TEXT, resumo TEXT, acao TEXT, ressalva TEXT,
            fundamento TEXT, gerado_em TEXT,
            PRIMARY KEY (exercicio, ug_emitente, credor)
        );
        CREATE INDEX IF NOT EXISTS ix_frac_prio ON siafe_fracionamento(prioridade DESC);
        CREATE INDEX IF NOT EXISTS ix_frac_credor ON siafe_fracionamento(credor);
    """)
    con.commit()


def persistir(con: sqlite3.Connection, candidatos: list[dict], *,
              exercicio: int | None = None) -> int:
    """Grava a fila do exercício e RETIRA o que a régua atual já não considera candidato.

    `INSERT OR REPLACE` sozinho só acrescenta e atualiza — nunca tira. Consequência medida em
    2026-07-28: melhorei o filtro de entidade pública (49 dos 617 credores da fila eram Fundo
    Municipal de Saúde, Prefeitura, Associação de Apoio à Escola — abreviados, que o padrão
    antigo não pegava), reprocessei, e a fila continuou com 1.175 grupos. As linhas velhas
    ficaram, e o analista seguiria abrindo processo de repasse achando que era compra.

    A retirada é ESCOPADA e auditável: só o exercício reprocessado, e só linhas de gerações
    ANTERIORES a esta execução. Não é o `DELETE` global de `anomalias.regras()`, que truncou
    `ob_redflag` de 69.807 para 12.215 quando rodado com amostra — aqui, se a execução trouxer
    zero candidatos, nada é apagado, porque não há geração nova para suceder a antiga.
    """
    init_schema(con)
    agora = datetime.now().isoformat(timespec="seconds")
    con.executemany(
        "INSERT OR REPLACE INTO siafe_fracionamento VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(c["exercicio"], c["ug_emitente"], c["credor"], c["nome_credor"],
          c["n_obs"], c["n_processos"], c["soma"], c["limite_dispensa"],
          c["razao_soma_limite"], c["intervalo_mediano_dias"], c["n_rente_ao_teto"],
          c["primeira_ob"], c["ultima_ob"], c["prioridade"], c["grau"],
          " ".join(str(p) for p in c["processos"]), " ".join(str(o) for o in c["obs"]),
          c["resumo"], c["acao"], c["ressalva"], c["fundamento"], agora)
         for c in candidatos])
    if exercicio is not None and candidatos:
        removidas = con.execute(
            "DELETE FROM siafe_fracionamento WHERE exercicio = ? AND gerado_em < ?",
            (int(exercicio), agora)).rowcount
        if removidas:
            print(f"    retiradas {removidas} linha(s) de gerações anteriores do exercício "
                  f"{exercicio} (a régua atual já não as considera candidatas)")
    con.commit()
    return len(candidatos)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int)
    ap.add_argument("--todos", action="store_true", help="2021 até o ano corrente")
    ap.add_argument("--ug", help="limita a uma unidade gestora")
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

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
