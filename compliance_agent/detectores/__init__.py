# -*- coding: utf-8 -*-
"""Framework de DETECTORES de corrupção em licitações (spec V2 do dono).

Fundamento em `base.py` (schema padrão · score com âncoras fixas · rubrica fechada · verificador adversarial
LLM-opcional que degrada honesto · pipeline + convergência multiplicativa §7.2). Cards de detector plugam aqui
e REUSAM o que o JFN já tem (ver o MAPA DOS 30 DETECTORES no docstring de `base.py`).

    from compliance_agent.detectores import Detector, ResultadoDetector, pipeline, REGISTRO
    res = pipeline(list(REGISTRO.values()), contexto)
"""
from __future__ import annotations

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
from compliance_agent.detectores.p4_fracionamento import P4Fracionamento

# REGISTRO de detectores disponíveis (id → instância). Os próximos cards se registram aqui.
REGISTRO: dict[str, Detector] = {
    d.id: d for d in (
        P4Fracionamento(),
    )
}

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
    "REGISTRO",
    "P4Fracionamento",
]
