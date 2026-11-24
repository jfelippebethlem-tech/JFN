# -*- coding: utf-8 -*-
"""Contrato único do achado — O5.2 do plano mestre v2 (§5 "Contrato único"; doc 2 §17.2 e §35.1).

Três entidades que NÃO se misturam numa tabela de alertas (doc 2 §17.2):

  ExecucaoRegra  resultado técnico reproduzível: que regra (id + versão), sobre que entradas (sha256 canônico),
                 produziu o quê. Rodar de novo a mesma versão sobre as mesmas entradas dá o mesmo hash.
  Achado         a hipótese de auditoria que a execução sustenta, nos quatro planos do doc 2 §35.1:
                   observacao   o que a fonte efetivamente contém (dado bruto, sem adjetivo);
                   inferencia   o que os dados podem indicar (indício, correlação, anomalia — não fato);
                   qualificacao que regra jurídica PODE incidir (enquadramento; None = não qualificado);
                   (decisão)    fica FORA — `DecisaoHumana`.
                 `estado` é o estado de saída de §3.10 (`dominio.estados.EstadoSaida`: AUSENTE, INDISPONIVEL,
                 INCERTO, INDICIO, CONCLUSAO_REVISADA e ABSTEVE com motivo). `evidencias` são `Fato`s com papel
                 (suporte | contradicao | contexto).
  DecisaoHumana  o que a instituição faz (confirma, refuta, arquiva, manda revisar), com autor e justificativa.

Regra de autoridade (doc 2 §35.1, "não permitir que score ou agente decida por autoridade"): uma regra só produz
achado em `triagem` ou `em_revisao`; `confirmado`, `refutado` e `arquivado` só nascem de `decidir()` com uma
`DecisaoHumana`. `CONCLUSAO_REVISADA` ⇔ status confirmado/refutado.

Puro: sem I/O (contrato `dominio-sem-io`). Os adaptadores das três gerações de detectores moram em
`compliance_agent/adaptadores/achados.py`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from compliance_agent.dominio.estados import EstadoSaida


class Papel(str, Enum):
    SUPORTE = "suporte"
    CONTRADICAO = "contradicao"
    CONTEXTO = "contexto"


class StatusAchado(str, Enum):
    TRIAGEM = "triagem"
    EM_REVISAO = "em_revisao"
    CONFIRMADO = "confirmado"
    REFUTADO = "refutado"
    ARQUIVADO = "arquivado"


STATUS_DE_REGRA = frozenset({StatusAchado.TRIAGEM, StatusAchado.EM_REVISAO})   # o que uma regra pode emitir
STATUS_CONCLUSIVO = frozenset({StatusAchado.CONFIRMADO, StatusAchado.REFUTADO})
ESTADOS_FATO = ("extraido", "confirmado", "refutado", "incerto", "indisponivel")   # doc 2 §17.1


def hash_entradas(entradas: Any) -> str:
    """sha256 do JSON canônico (chaves ordenadas, sem espaço, Decimal/data como texto). Mesmas entradas, mesmo hash."""
    txt = json.dumps(entradas, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class Fato(_Base):
    """Uma evidência e o seu papel no achado. Aponta para a fonte; não a substitui (o valor normalizado nunca
    substitui o trecho literal — doc 2 §17.1). Sem `trecho_literal`, é registro estruturado da fonte, não citação."""
    papel: Papel
    tipo: str = Field(min_length=1)                 # 'ob', 'contrato', 'folha', 'cadastro', 'documento', 'registro', …
    fonte: str = Field(min_length=1)                # tabela ou acervo de origem ('ob_orcamentaria_siafe', 'alertas', …)
    referencia: str | None = None                   # chave na fonte (nº da OB, processo, id da linha)
    descricao: str = ""
    valor: Decimal | None = None
    trecho_literal: str | None = None
    documento_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pagina: int | None = Field(default=None, ge=1)
    estado: str = "extraido"
    dados: dict[str, Any] = Field(default_factory=dict)   # o registro estruturado, como a fonte o deu

    @field_validator("estado")
    @classmethod
    def _estado_valido(cls, v: str) -> str:
        if v not in ESTADOS_FATO:
            raise ValueError(f"estado do fato fora de {ESTADOS_FATO}: {v!r}")
        return v


class ExecucaoRegra(_Base):
    regra_id: str = Field(min_length=1)             # id do registro (config/qualidade_detectores.yaml)
    versao: str = Field(min_length=1)               # versão do código que executou (ex.: sha do módulo)
    entradas_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resultado: dict[str, Any]
    processo: str | None = None
    origem: str = Field(min_length=1)               # de onde a execução foi lida ('alertas:123', 'achado_certame:…')
    executado_em: datetime | None = None


class Achado(_Base):
    execucao: ExecucaoRegra
    status: StatusAchado = StatusAchado.TRIAGEM
    estado: EstadoSaida
    motivo_estado: str = ""
    observacao: str = Field(min_length=1)
    inferencia: str = Field(min_length=1)
    qualificacao: str | None = None
    hipotese: str = Field(min_length=1)
    hipoteses_alternativas: list[str] = Field(default_factory=list)
    evidencias: list[Fato] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coerencia(self) -> "Achado":
        if self.estado is EstadoSaida.ABSTEVE and not self.motivo_estado.strip():
            raise ValueError("ABSTEVE exige motivo_estado")
        if (self.estado is EstadoSaida.CONCLUSAO_REVISADA) != (self.status in STATUS_CONCLUSIVO):
            raise ValueError("CONCLUSAO_REVISADA ⇔ status confirmado/refutado (só pessoa conclui)")
        if self.estado is EstadoSaida.INDICIO and not any(f.papel is Papel.SUPORTE for f in self.evidencias):
            raise ValueError("INDICIO exige ao menos um Fato de suporte")
        return self

    @classmethod
    def de_regra(cls, **campos) -> "Achado":
        """Construtor das regras/adaptadores: recusa status de decisão (a regra não decide)."""
        a = cls(**campos)
        if a.status not in STATUS_DE_REGRA:
            raise ValueError(f"regra não emite status '{a.status.value}' — só DecisaoHumana (decidir())")
        return a


class DecisaoHumana(_Base):
    autor: str = Field(min_length=1)
    status: StatusAchado
    justificativa: str = Field(min_length=1)
    decidido_em: datetime
    encaminhamento: str | None = None               # despacho, diligência, arquivamento, encaminhamento

    @field_validator("status")
    @classmethod
    def _nao_triagem(cls, v: StatusAchado) -> StatusAchado:
        if v is StatusAchado.TRIAGEM:
            raise ValueError("decisão não devolve a triagem — use em_revisao")
        return v

    @field_validator("autor", "justificativa")
    @classmethod
    def _nao_branco(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("autor e justificativa não podem ser brancos")
        return v


def decidir(achado: Achado, decisao: DecisaoHumana) -> Achado:
    """O achado depois da decisão: status da decisão; estado CONCLUSAO_REVISADA quando confirma ou refuta.
    O achado original não muda (imutável); quem persiste guarda os dois."""
    estado = EstadoSaida.CONCLUSAO_REVISADA if decisao.status in STATUS_CONCLUSIVO else (
        EstadoSaida.INDICIO if achado.estado is EstadoSaida.CONCLUSAO_REVISADA else achado.estado)
    return Achado.model_validate({**achado.model_dump(), "status": decisao.status, "estado": estado})
