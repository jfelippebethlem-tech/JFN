# -*- coding: utf-8 -*-
"""Estados de saída e saúde operacional (plano mestre v2, §3.10, invariantes 2 e 5).

INDISPONÍVEL ≠ AUSENTE ≠ 0: "não consegui olhar" nunca é "olhei e não tem", e nenhum dos dois é zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EstadoSaida(str, Enum):
    """O que toda saída (indicador, detector, laudo, resposta) declara sobre si.

    AUSENTE             consultado na fonte; não consta. É resultado (a fonte respondeu).
    INDISPONIVEL        não deu para consultar (fonte fora, sem acesso, sem coleta). Não é ausência nem zero.
    INCERTO             consultado, mas o OCR ou a identidade (CPF/CNPJ/processo) não se resolveu.
    INDICIO             regra objetiva disparou, com as hipóteses inocentes declaradas. Não é acusação.
    CONCLUSAO_REVISADA  uma pessoa examinou a prova e concluiu.
    ABSTEVE             a IA se absteve — sempre com motivo; nunca aparece como "limpo".
    """
    AUSENTE = "AUSENTE"
    INDISPONIVEL = "INDISPONIVEL"
    INCERTO = "INCERTO"
    INDICIO = "INDICIO"
    CONCLUSAO_REVISADA = "CONCLUSAO_REVISADA"
    ABSTEVE = "ABSTEVE"


@dataclass(frozen=True)
class Saida:
    """Estado + motivo. `ABSTEVE(motivo)`: abstenção sem motivo é recusada."""
    estado: EstadoSaida
    motivo: str = ""

    def __post_init__(self):
        object.__setattr__(self, "estado", EstadoSaida(self.estado))
        if self.estado is EstadoSaida.ABSTEVE and not str(self.motivo).strip():
            raise ValueError("ABSTEVE exige motivo")

    def __str__(self) -> str:
        return f"{self.estado.value}({self.motivo})" if self.estado is EstadoSaida.ABSTEVE else self.estado.value


def absteve(motivo: str) -> Saida:
    return Saida(EstadoSaida.ABSTEVE, motivo)


class SaudeOperacional(str, Enum):
    """Saúde de um estágio/visão/fonte (invariante 5: estado honesto).

    SAUDAVEL      rodou dentro do SLO e o efeito foi conferido.
    DEGRADADO     rodou, mas parcial (cobertura abaixo do alvo, fallback ativo, erro em parte dos itens).
    ATRASADO      a última execução com efeito conferido está além do SLO.
    BLOQUEADO     não pode rodar: dependência a montante falhou ou trava/decisão pendente.
    INDISPONIVEL  não deu para medir o estado (sensor fora) — nunca lido como saudável.
    """
    SAUDAVEL = "SAUDAVEL"
    DEGRADADO = "DEGRADADO"
    ATRASADO = "ATRASADO"
    BLOQUEADO = "BLOQUEADO"
    INDISPONIVEL = "INDISPONIVEL"
