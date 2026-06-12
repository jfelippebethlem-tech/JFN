# -*- coding: utf-8 -*-
"""Framework de DETECTORES de corrupção em licitações (spec V2 do dono).

Fundamento em `base.py` (schema padrão · score com âncoras fixas · rubrica fechada · verificador adversarial
LLM-opcional que degrada honesto · pipeline + convergência multiplicativa §7.2). Cards de detector plugam aqui
e REUSAM o que o JFN já tem (ver o MAPA DOS 30 DETECTORES no docstring de `base.py`).

    from compliance_agent.detectores import Detector, ResultadoDetector, pipeline, REGISTRO
    res = pipeline(list(REGISTRO.values()), contexto)

ORQUESTRADOR (entrada do mundo real → lista de ResultadoDetector, schema fixo §1.4):
    from compliance_agent.detectores import rodar_orgao, rodar_fornecedor
    rodar_orgao("036100")            # J1 (conluio/cartel por UG)
    rodar_fornecedor("12.345.678/0001-90")  # P3 (sobrepreço) + C (C1/C2/C3-5/C4 fachada)
"""
from __future__ import annotations

from typing import Any

from compliance_agent.detectores.base import (
    ANCORAS,
    PESOS_FAMILIA,
    Detector,
    ResultadoDetector,
    ancora,
    aplicar_exculpatoria,
    avaliar_rubrica,
    evidencia,
    pipeline,
    score_processo,
    verificar_adversarial,
)
from compliance_agent.detectores.c_fachada import CFachada
from compliance_agent.detectores.j1_cartel import J1Cartel
from compliance_agent.detectores.p3_sobrepreco import P3Sobrepreco
from compliance_agent.detectores.p4_fracionamento import P4Fracionamento

# REGISTRO de detectores disponíveis (id → instância). Os próximos cards se registram aqui.
REGISTRO: dict[str, Detector] = {
    d.id: d for d in (
        P4Fracionamento(),
        J1Cartel(),
        P3Sobrepreco(),
        CFachada(),
    )
}

# pesos por detector p/ a convergência multiplicativa (§7.2): herdam o peso da família do detector.
PESOS_DETECTOR: dict[str, float] = {
    "P4": PESOS_FAMILIA["violacao_legal"],
    "J1": PESOS_FAMILIA["conluio"],
    "P3": PESOS_FAMILIA["preco"],
    "C1": PESOS_FAMILIA["perfil"], "C2": PESOS_FAMILIA["perfil"],
    "C3/C5": PESOS_FAMILIA["perfil"], "C4": PESOS_FAMILIA["perfil"],
}


def rodar_orgao(ug: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores de ÓRGÃO (entrada = UG). Hoje: J1 (conluio/cartel por concentração de grupo +
    rodízio temporal). Reusa `pipeline` (isola detector que quebra → nao_avaliavel honesto, não derruba os outros).

    `contexto` extra (opcional) é mesclado — em teste, injete `concentracao`/`rodizio` aqui p/ não tocar DuckDB."""
    ctx: dict[str, Any] = {"processo": str(ug), "ug": str(ug)}
    if contexto:
        ctx.update(contexto)
    dets = [d for d in REGISTRO.values() if d.familia == "conluio"]
    return pipeline(dets, ctx, exculpatoria=exculpatoria, gerar=gerar)


def rodar_fornecedor(cnpj: str, *, contexto: dict | None = None, exculpatoria: bool = False, gerar=None) -> list[ResultadoDetector]:
    """Orquestra os detectores de FORNECEDOR (entrada = CNPJ). Hoje: P3 (sobrepreço interno) + C (C1/C2/C3-5/C4
    perfil de fachada/laranja). C produz VÁRIOS resultados por investigação (`avaliar_todos`), então é tratado à
    parte; P3 (e qualquer outro detector de fornecedor de 1 resultado) passa pelo `pipeline` padrão.

    `contexto` extra (opcional) é mesclado — em teste, injete `investigacao`/`achados`/`registros` p/ não tocar
    rede/DuckDB. `exculpatoria=True` roda o verificador adversarial nos achados confirmados (LLM-opcional)."""
    ctx: dict[str, Any] = {"processo": str(cnpj), "cnpj": str(cnpj)}
    if contexto:
        ctx.update(contexto)

    resultados: list[ResultadoDetector] = []
    # P3 e outros detectores de fornecedor de 1-resultado via pipeline padrão
    simples = [d for d in REGISTRO.values() if d.familia == "preco"]
    resultados.extend(pipeline(simples, ctx, exculpatoria=exculpatoria, gerar=gerar))

    # C (fachada) — multi-resultado por investigação
    cdet = REGISTRO.get("C")
    if isinstance(cdet, CFachada):
        cres = cdet.avaliar_todos(ctx)
        if exculpatoria:
            for r in cres:
                if r.status == "confirmado":
                    achado = f"{r.detector} score={r.score}: {r.explicacao_inocente or 'indício de fachada'}"
                    aplicar_exculpatoria(r, achado, gerar=gerar)
        resultados.extend(cres)
    return resultados


__all__ = [
    "Detector",
    "ResultadoDetector",
    "pipeline",
    "score_processo",
    "ancora",
    "avaliar_rubrica",
    "verificar_adversarial",
    "aplicar_exculpatoria",
    "evidencia",
    "ANCORAS",
    "PESOS_FAMILIA",
    "PESOS_DETECTOR",
    "REGISTRO",
    "P4Fracionamento",
    "J1Cartel",
    "P3Sobrepreco",
    "CFachada",
    "rodar_orgao",
    "rodar_fornecedor",
]
