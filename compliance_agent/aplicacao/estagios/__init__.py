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
(catraca em tests/test_fluxo_supervisor.py). E0 "eco" (teste) e, desde a O2.1, `legado:<rotina>` (estagios/legado.py:
roda o comando que rodava antes da parada), E18 `observar` (O8.1: estagios/observar.py, sensores → fluxo.metricas), E2 `arvore` e E3 `capturar` (O3.3), E4 `texto`, E5 `ocr`, E6 `confirmar_ocr` e E7
`arquivar` (O3.4), E12 `conferir` e E17 `manter` (O8.5); os outros
estágios reais chegam na O3+.
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


MARCA_FORA_DE_ALCANCE = "[fora_de_alcance]"


class ForaDeAlcance(ErroPermanente):
    """Resultado DECLARADO do domínio, não falha do estágio (26/11/2026): processo RESTRITO à unidade ou em sigilo
    integral — rota própria do dono (SIP/SeiWS, P5). Vai à quarentena (lista do dono) com a marca no texto, que a
    conferência da religação não conta como erro do estágio."""

    def __init__(self, msg: str):
        super().__init__(f"{MARCA_FORA_DE_ALCANCE} {msg}")


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


def estagio_de(tipo: str) -> Estagio | None:
    """O estágio que roda um tipo de job: nome exato no REGISTRO, ou a família antes do `:` — `legado:<rotina>`
    (O2.1) é um tipo por rotina do config/fluxo.yaml, todos rodados pelo mesmo handler `legado`."""
    if tipo in REGISTRO:
        return REGISTRO[tipo]
    familia = tipo.split(":", 1)[0]
    if familia == "fatos":                                          # E8 (O6.3): import tardio, como o legado
        from compliance_agent.aplicacao.estagios import fatos
        return fatos.ESTAGIO
    if familia == "legado":
        from compliance_agent.aplicacao.estagios import legado     # import tardio: só o filho que roda legado paga
        return legado.ESTAGIO
    if familia == "elegibilidade":                                  # E9 (O4.7, sombra ⚖️): import tardio, como o legado
        from compliance_agent.aplicacao.estagios import elegibilidade
        return elegibilidade.ESTAGIO
    if familia == "detectar":                                       # E10 (O5.3, sombra ⚖️): import tardio, como a E9
        from compliance_agent.aplicacao.estagios import detectar
        return detectar.ESTAGIO
    if familia == "periciar":                                       # E11 (O6.4): perícia única, laudo v2 versionado
        from compliance_agent.aplicacao.estagios import periciar
        return periciar.ESTAGIO
    if familia == "arvore":                                       # E2 (O3.3): import tardio (playwright só no filho)
        from compliance_agent.aplicacao.estagios import arvore
        return arvore.ESTAGIO
    if familia == "capturar":                                       # E3 (O3.3)
        from compliance_agent.aplicacao.estagios import capturar
        return capturar.ESTAGIO
    if familia in ("texto", "ocr", "confirmar_ocr", "arquivar"):    # E4–E7 (O3.4): import tardio (fitz/OCR no filho)
        import importlib
        return importlib.import_module(f"compliance_agent.aplicacao.estagios.{familia}").ESTAGIO
    if familia == "observar":                                       # E18 (O8.1): sensores → fluxo.metricas
        from compliance_agent.aplicacao.estagios import observar
        return observar.ESTAGIO
    if familia == "materializar":                                   # E15 (O7.1): visões do painel
        from compliance_agent.aplicacao.estagios import materializar
        return materializar.ESTAGIO
    if familia == "calibrar":                                       # E13 (O5.4): o motor não o alcançava (O8.5)
        from compliance_agent.aplicacao.estagios import calibrar
        return calibrar.ESTAGIO
    if familia == "caso":                                           # E14 (O7.4): caso + contestação + RBAC
        from compliance_agent.aplicacao.estagios import caso
        return caso.ESTAGIO
    if familia == "entregar":                                       # E16 (O7.5): dossiê com manifesto e validador
        from compliance_agent.aplicacao.estagios import entregar
        return entregar.ESTAGIO
    if familia == "conferir":                                       # E12 (O8.5): por risco; sem LLM ⇒ ABSTEVE
        from compliance_agent.aplicacao.estagios import conferir
        return conferir.ESTAGIO
    if familia == "manter":                                         # E17 (O8.5): backup/WAL/VACUUM/zelador
        from compliance_agent.aplicacao.estagios import manter
        return manter.ESTAGIO
    return REGISTRO.get(familia)

