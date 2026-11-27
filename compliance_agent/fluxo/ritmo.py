# -*- coding: utf-8 -*-
"""Ritmo da assinatura no PostgreSQL (O2.3; relatório da sombra §8.7): a medição de `llm/ritmo_assinatura` mora num
arquivo da VM-1 — o supervisor de outra máquina, sem ele, leria "sem medição ⇒ sem restrição" e furaria o ritmo.

Aqui a MESMA medição (só números: % da semana, % da sessão, viradas) é publicada em `fluxo.metricas`
(nome `assinatura_ritmo`) pela máquina que mede (VM-1, rotina `ritmo_assinatura` do config/fluxo.yaml, quando
religar) e lida por TODOS os supervisores. A classificação é a do próprio `ritmo_assinatura.classificar` (uma regra
só). Diferença deliberada: para o MOTOR, medição ausente, velha (> `ritmo_assinatura.VALIDADE_S`) ou ilegível no PG =
PORTA FECHADA — nunca "normal por falta de leitura" (o teto da assinatura é da conta inteira, inclusive do dono).

    python -m compliance_agent.fluxo ritmo medir     # mede (grava o arquivo, como antes) e publica no PG
    python -m compliance_agent.fluxo ritmo status    # o que um supervisor leria agora
"""
from __future__ import annotations

import json
from typing import Mapping

import psycopg

from compliance_agent.llm import contingencia, ritmo_assinatura

NOME = "assinatura_ritmo"
CAMPOS = ("em", "medido_ts", "sessao_pct", "sessao_volta", "semana_pct", "semana_volta")


def publicar(con, medida: Mapping, no: str = "vm1") -> int:
    """Grava a medição (só os campos numéricos/datas de `ritmo_assinatura.extrair`) em `metricas`."""
    if medida.get("semana_pct") is None or not medida.get("semana_volta"):
        raise ValueError("medição sem semana_pct/semana_volta não é publicada")
    rot = {k: medida.get(k) for k in CAMPOS}
    lib = medida.get("liberacao") or ritmo_assinatura.liberacao_local()
    if lib:
        rot["liberacao"] = {k: lib.get(k) for k in ("teto_pct", "ate", "por")}   # vale em todos os nós, até `ate`
    return con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (%s, %s, %s, %s) RETURNING id",
                       (no, NOME, float(medida["semana_pct"]), json.dumps(rot))).fetchone()[0]


def ler(con) -> tuple[dict | None, float | None]:
    """(medição mais recente, idade em segundos pelo relógio do PG) ou (None, None)."""
    r = con.execute("SELECT rotulos, extract(epoch FROM now() - quando) FROM metricas WHERE nome = %s "
                    "ORDER BY quando DESC LIMIT 1", (NOME,)).fetchone()
    return (dict(r[0]), float(r[1])) if r else (None, None)


def motivo(con, tarefa: str) -> str | None:
    """Por que o job desta tarefa NÃO reserva agora (None = pode). Mesmas regras de `contingencia.motivo_bloqueio`
    para o ritmo semanal: contido segura tudo menos o canário; economia segura o que não é RESERVA_OPUS."""
    try:
        m, idade = ler(con)
    except psycopg.Error as exc:
        return f"porta fechada: medição da assinatura ilegível no PG ({type(exc).__name__})"
    if m is None:
        return "porta fechada: sem medição da assinatura no PG (fluxo.metricas assinatura_ritmo)"
    if idade > ritmo_assinatura.VALIDADE_S:
        return f"porta fechada: medição da assinatura velha ({idade / 3600:.1f} h > {ritmo_assinatura.VALIDADE_S / 3600:.0f} h)"
    agora = float(m.get("medido_ts") or 0) + idade          # idade pelo relógio do PG: relógio do nó não entra
    c = ritmo_assinatura.classificar(m, agora)
    if not c["medido"]:
        return f"porta fechada: {c['motivo']}"
    trava = None
    if c["nivel"] == "contido" and tarefa != "canario":
        trava = f"ritmo semanal da assinatura — {c['motivo']}"
    elif c["nivel"] == "economia" and tarefa not in contingencia.RESERVA_OPUS:
        trava = f"ritmo semanal da assinatura — {c['motivo']}"
    if trava and liberado_pelo_dono(c.get("semana_pct")):
        return None                                        # só a trava de ritmo, só no escopo do ensaio O8.5
    return trava


def motivo_local(tarefa: str) -> str | None:
    """O guarda LOCAL da assinatura (contingência: ritmo semanal, limite da conta, teto próprio, forçada) com a MESMA
    exceção do `claude_motor.motivo_desligado`: SÓ a trava de ritmo semanal cede, SÓ no escopo do ensaio O8.5 com a
    autorização do dono e a semana abaixo do teto. Os handlers de LLM (E8/E11) e o supervisor perguntam aqui — antes,
    o handler barrava pela contingência crua e a autorização do dono nunca chegava ao E8/E11 (passada r3, 25/11)."""
    from compliance_agent.llm import claude_motor
    m = contingencia.motivo_bloqueio(tarefa)
    if m and contingencia.estado().get("origem") == "ritmo_semanal" and claude_motor.ritmo_liberado_pelo_dono():
        return None
    return m


def liberado_pelo_dono(semana_pct) -> bool:
    """A MESMA regra de `claude_motor.ritmo_liberado_pelo_dono`, com a semana medida no PG: a trava de ritmo do MOTOR
    cede à autorização do dono (`data/.assinatura_liberada_dono.json`, escopo O8.5 pela ASSINATURA) SÓ quando o
    supervisor declara `JFN_ASSINATURA_ESCOPO=ensaio_o85` e a semana está ABAIXO do `teto_semana_pct`. Fora desse
    escopo (a produção) nada muda; sem medição, a porta segue fechada (motivo acima, antes desta regra)."""
    import os

    from compliance_agent.llm import arquivo_estado as arq
    from compliance_agent.llm import claude_motor as CM
    if os.environ.get(CM.ENV_ESCOPO) != CM.ESCOPO_ENSAIO or semana_pct is None:
        return False
    try:
        d = json.loads((arq.dados() / CM.LIBERACAO_DONO).read_text(encoding="utf-8"))
        teto = float(d["teto_semana_pct"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    esc = str(d.get("escopo") or "")
    return "O8.5" in esc and "ASSINATURA" in esc and float(semana_pct) < teto


def medir_e_publicar(con, no: str = "vm1", medir=None) -> dict:
    """O que a rotina `ritmo_assinatura` roda no fluxo: a medição de sempre (arquivo + histórico) e, se ela
    MEDIU agora (sem erro), a publicação no PG. Falha de medição não publica — a última fica e envelhece."""
    c = (medir or ritmo_assinatura.medir)()
    if c.get("erro"):
        return {"publicado": False, **c}
    m = ritmo_assinatura.ler()
    if not m:
        return {"publicado": False, **c, "motivo_publicacao": "arquivo de medição ausente depois de medir"}
    return {"publicado": True, "metrica_id": publicar(con, m, no), **c}
