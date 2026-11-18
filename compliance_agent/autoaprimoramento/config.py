# -*- coding: utf-8 -*-
"""Caminhos, chaves e tetos do autoaprimoramento. Tudo desligado por padrão: o ciclo real exige
`JFN_AUTOAPRIMORAMENTO=1`; o kill switch (arquivo `KILL` ou `JFN_AUTOAPRIMORAMENTO_KILL=1`) vence qualquer chave."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALTO = 7                    # nota de risco a partir da qual o laudo é "risco alto" (mesmo corte do resto da casa)
NIVEL_FRACO, NIVEL_RESUMO, NIVEL_FONTE = 0, 1, 2     # hierarquia de prova: modelo de volume < Opus sobre resumo < fonte primária

# Tetos por ciclo. Nada aqui chama API paga: LLM só pela assinatura (`claude_motor`, backend="cli") ou pela cascata
# grátis já guardada pelos tetos da casa, e só quando o ciclo é real (não --dry-run).
ORCAMENTO = {"max_candidatos_ciclo": 3, "max_chamadas_llm_ciclo": 0, "max_casos_reexecucao": 40,
             "max_consultas_teste_trimestre": 4, "max_licoes_ativas": 8}
# Portão determinístico (portao.py). Mudar estes números é decisão do dono, registrada no documento.
PORTAO = {"min_casos": 30, "min_altos_verdadeiros": 3, "melhora_minima": 0.05, "regressao_maxima": 0.0,
          "p_mcnemar": 0.05, "min_metades_estaveis": 2}
SOMBRA_MIN_LAUDOS = 50      # laudos em sombra antes de o desafiante poder virar campeão
ALFA_FP = 0.10              # taxa de falso alto tolerada numa faixa "certificada" (limite superior de Jeffreys a 95%)


def dados() -> Path:
    d = Path(os.environ.get("JFN_AUTOAPRIMORAMENTO_DIR") or REPO / "data" / "autoaprimoramento")
    d.mkdir(parents=True, exist_ok=True)
    return d


def banco() -> Path:
    return dados() / "auto.db"


def candidatos() -> Path:
    d = dados() / "candidatos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ligado() -> bool:
    return os.environ.get("JFN_AUTOAPRIMORAMENTO") == "1" and not morto()


def morto() -> bool:
    return os.environ.get("JFN_AUTOAPRIMORAMENTO_KILL") == "1" or (dados() / "KILL").exists()
