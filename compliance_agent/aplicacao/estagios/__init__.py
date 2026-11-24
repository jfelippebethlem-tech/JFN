# -*- coding: utf-8 -*-
"""Registro de estágios da Esteira Única (plano mestre v2 §3.2 — contrato de estágio).

Cada estágio é um tipo de job com contrato fixo:
  · `handler(payload, ctx) -> Resultado` — idempotente pela `chave` do job;
  · `efeito(payload, ctx, resultado) -> bool` — conferência INDEPENDENTE do que o handler declarou (lê o mundo, não
    confia na palavra do handler). Sem efeito conferido o job vira `falhou_efeito`, nunca "feito";
  · `recursos`, `prioridade` e `volta` declarados aqui (na O2.1 passam ao config/fluxo.yaml, que o planejador lê
    sem importar handler nenhum);
  · os eventos que sujam os estágios seguintes vão em `Resultado.eventos`.

Quem roda handler e efeito é SEMPRE o processo-filho `compliance_agent.fluxo.executar`, nunca o supervisor
(catraca em tests/test_fluxo_supervisor.py). Por ora só o E0 "eco", de teste; os estágios reais chegam na O2/O3.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

from compliance_agent.fluxo import fila
from compliance_agent.fluxo.fila import Resultado


class ErroPermanente(Exception):
    """O handler sabe que tentar de novo não adianta (entrada inválida, documento inexistente): vai direto à
    quarentena, sem gastar as tentativas."""


@dataclass
class Contexto:
    no: str
    tipo: str
    chave: str
    ficha: int
    tentativa: int
    correlation_id: str | None = None


@dataclass
class Estagio:
    handler: Callable[[dict, Contexto], Resultado]
    efeito: Callable[[dict, Contexto, Resultado], bool]
    recursos: list[str] = field(default_factory=lambda: ["cpu_leve"])
    prioridade: int = 100
    volta: dict | None = None


# ── E0 "eco": prova ponta a ponta do motor ────────────────────────────────────────────────────────────
def _eco(payload: dict, ctx: Contexto) -> Resultado:
    """Grava UMA linha em `metricas` com a ficha e o PID do processo que rodou (o teste usa o PID para provar que
    não foi o supervisor). `payload.falhar_efeito` simula um handler que declara efeito que não houve."""
    con = fila.conectar()
    try:
        rotulos = {"chave": ctx.chave, "ficha": ctx.ficha, "pid": os.getpid()}
        mid = con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (%s, 'eco', 1, %s) RETURNING id",
                          (ctx.no, json.dumps(rotulos))).fetchone()[0]
    finally:
        con.close()
    declarado = -1 if payload.get("falhar_efeito") else mid
    return Resultado(efeito={"metrica_id": declarado},
                     eventos=[{"fonte": "eco", "tipo": "concluido", "chave": ctx.chave}])


def _eco_efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = fila.conectar()
    try:
        r = con.execute("SELECT rotulos->>'ficha' FROM metricas WHERE id = %s AND nome = 'eco'",
                        (resultado.efeito.get("metrica_id"),)).fetchone()
    finally:
        con.close()
    return r is not None and r[0] == str(ctx.ficha)


REGISTRO: dict[str, Estagio] = {
    "eco": Estagio(handler=_eco, efeito=_eco_efeito, recursos=["cpu_leve"], prioridade=100),
}

