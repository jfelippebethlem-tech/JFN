# -*- coding: utf-8 -*-
"""monitor — deriva, integridade da prova e kill switch.

  fonte_perdida   processo com laudo conferido na FONTE no ledger cujo laudo vigente em `lex_execucao` tem nível de
                  prova menor (a prova primária foi regravada por juízo mais fraco)
  deriva          a fração de 'risco alto' dos motores de volume na última semana fugiu da faixa das 4 anteriores
`matar(motivo)` cria o arquivo KILL: a produção volta à rubrica de partida e o ciclo real para até um humano apagar."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import config, ledger


def matar(motivo: str) -> Path:
    p = config.dados() / "KILL"
    p.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {motivo}\n", encoding="utf-8")
    return p


def fonte_perdida(con, compliance_db: Path | None = None) -> list[str]:
    db = compliance_db or config.REPO / "data" / "compliance.db"
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    try:
        atual = dict(ro.execute("SELECT numero_sei, modelo FROM lex_execucao"))
    finally:
        ro.close()
    return sorted(ns for (ns,) in con.execute("SELECT DISTINCT numero_sei FROM laudo_versao WHERE nivel_prova=?",
                                              (config.NIVEL_FONTE,))
                  if ns in atual and 0 <= ledger.nivel_gravado(atual[ns]) < config.NIVEL_FONTE)


def deriva(con, agora: float | None = None, minimo: int = 30) -> list[dict]:
    """Fração de risco alto dos laudos de nível 0 por semana (pela data do laudo). Alerta se a última semana sai de
    média ± 3 desvios-padrão binomiais das 4 anteriores. Sem amostra mínima ⇒ 'aguardando amostra' (não alerta).
    LIMITE: semanas anteriores ao gancho de regravação (18/11/2026) só têm os laudos que sobreviveram ou que a fila
    do Opus guardou — a base dessas semanas é parcial, e por isso a deriva fica no relatório, fora do sensor."""
    agora = agora or time.time()

    def semana(i):
        a = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora - (i + 1) * 7 * 86400))
        b = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora - i * 7 * 86400))
        return con.execute("SELECT COUNT(*), COALESCE(SUM(nota>=?),0) FROM laudo_versao WHERE nivel_prova=0 AND "
                           "em_laudo>=? AND em_laudo<?", (config.ALTO, a, b)).fetchone()

    n0, k0 = semana(0)
    nb = kb = 0
    for i in range(1, 5):
        n, k = semana(i)
        nb, kb = nb + n, kb + k
    if n0 < minimo or nb < minimo:
        return [{"estado": "aguardando amostra", "ultima_semana": n0, "base": nb}]
    p = kb / nb
    dp = (p * (1 - p) / n0) ** 0.5
    atual = k0 / n0
    if dp and abs(atual - p) > 3 * dp:
        return [{"estado": "deriva", "detalhe": f"risco alto em {atual * 100:.1f}% dos {n0} laudos de volume da última "
                                               f"semana, contra {p * 100:.1f}% nas 4 anteriores ({nb} laudos)"}]
    return [{"estado": "ok", "ultima_semana": n0, "fracao_alto": round(atual, 4), "base": round(p, 4)}]
