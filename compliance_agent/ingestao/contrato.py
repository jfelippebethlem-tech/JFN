# -*- coding: utf-8 -*-
"""Contrato de ingestão — `config/fontes_cobertura.yaml` validado (O4.11; doc 2 §40.1).

Cada fonte declara: dono, frequência, SLO de frescor (horas), chave natural, campos com domínio
(tipo/regex/faixa/lista), teto de páginas, tabela de destino, coluna de frescor e se é EFÊMERA (some da
origem se não for coletada — notícia, página que a fonte reescreve) ou RE-OBTÍVEL (a origem guarda o
histórico; perder uma coleta atrasa, não apaga).

POR QUE (24/11/2026). Coletas pararam caladas por meses (TCE-RJ compras diretas desde 09/08, licitantes
desde 29/07, TFE desde 30/10) e nada as acusava, porque nenhuma fonte tinha contrato: não havia SLO a
violar nem chave a duplicar. O contrato é a régua que os sensores (`sensores.py`) medem.

Fonte `interna` (regra no git, memória, vault, laudo derivado) não é ingestão de dado externo: entra no
contrato para o mapa ficar completo frente a `config/propagacao.yaml`, mas não exige chave nem domínio.

Validação é só estrutural e de coerência — nunca toca a rede nem o banco.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = RAIZ / "config" / "fontes_cobertura.yaml"
PROPAGACAO = RAIZ / "config" / "propagacao.yaml"

# identificador SQL seguro: o yaml vira SQL em sensores.py — nada de aspas, espaço ou ponto-e-vírgula
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

TipoCampo = Literal["texto", "inteiro", "real", "data_iso", "data_br", "datahora_iso", "cnpj", "cpf_cnpj",
                    "processo_sei", "ug", "ano"]
EstadoFonte = Literal["ATIVA", "PARCIAL", "PARADA", "CONGELADA_NA_ORIGEM", "INDISPONIVEL"]

_RX_TIPO = {
    "inteiro": re.compile(r"^-?\d+$"),
    "data_iso": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "data_br": re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    "datahora_iso": re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?$"),
    "cnpj": re.compile(r"^\d{14}$"),
    "cpf_cnpj": re.compile(r"^(\d{11}|\d{14})$"),
    "ug": re.compile(r"^\d{6}$"),
    "ano": re.compile(r"^(19|20)\d{2}$"),
}


def _ident(v: str | None, nome: str) -> str | None:
    if v is not None and not _IDENT.match(v):
        raise ValueError(f"{nome} {v!r} não é identificador SQL simples (a-z, 0-9, _)")
    return v


class Campo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoCampo = "texto"
    obrigatorio: bool = False
    critico: bool = False                 # entra na completude
    regex: str | None = None
    minimo: float | None = None
    maximo: float | None = None
    dominio: list[str] | None = None

    @field_validator("regex")
    @classmethod
    def _regex_compila(cls, v):
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:          # re.error não é ValueError: o Pydantic não o converteria
                raise ValueError(f"regex inválida {v!r}: {exc}") from exc
        return v

    @model_validator(mode="after")
    def _faixa(self):
        if self.minimo is not None and self.maximo is not None and self.minimo > self.maximo:
            raise ValueError(f"faixa invertida: minimo {self.minimo} > maximo {self.maximo}")
        if (self.minimo is not None or self.maximo is not None) and self.tipo not in ("inteiro", "real", "ano"):
            raise ValueError(f"faixa numérica em campo {self.tipo}")
        return self


class RegraConsistencia(BaseModel):
    """Regra entre campos da mesma linha. `ordem`: campos[0] <= campos[1] (datas/números; vazio não julga).
    `data_no_exercicio`: o ano da data campos[0] é o exercício campos[1] (SIAFE: data DD/MM/AAAA × exercicio)."""
    model_config = ConfigDict(extra="forbid")
    tipo: Literal["ordem", "data_no_exercicio"]
    campos: list[str] = Field(min_length=2, max_length=2)

    @field_validator("campos")
    @classmethod
    def _ids(cls, v):
        for c in v:
            _ident(c, "campo da regra")
        return v


class Fonte(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str
    natureza: Literal["externa", "interna"]
    dono: str
    coletor: str                           # módulo/script que escreve (ou "manual")
    frequencia: str                        # diaria | semanal | mensal | sob_demanda | evento
    estado: EstadoFonte = "ATIVA"
    motivo_estado: str | None = None
    banco: str = "compliance"              # compliance | pcrj | dadosabertos_rj | arquivo
    tabela: str | None = None
    coluna_frescor: str | None = None
    formato_frescor: Literal["datahora_iso", "data_iso", "data_br"] = "datahora_iso"
    slo_frescor_h: float | None = Field(default=None, gt=0)
    chave_natural: list[str] = []
    campos: dict[str, Campo] = {}
    consistencia: list[RegraConsistencia] = []
    teto_paginas: int | None = Field(default=None, gt=0)
    efemera: bool = False
    propagacao: list[str] = []             # ids em config/propagacao.yaml que esta fonte alimenta
    reconciliacao: str | None = None       # o que a origem declara para comparar (ex.: recordsFiltered)
    recuperacao: str | None = None         # comando de recuperação da lacuna (O9.0) — nunca rodado daqui
    observacao: str | None = None

    @field_validator("tabela", "coluna_frescor")
    @classmethod
    def _sql(cls, v, info):
        return _ident(v, info.field_name)

    @field_validator("chave_natural")
    @classmethod
    def _chave(cls, v):
        for c in v:
            _ident(c, "chave_natural")
        return v

    @field_validator("campos")
    @classmethod
    def _campos(cls, v):
        for c in v:
            _ident(c, "campo")
        return v

    @model_validator(mode="after")
    def _coerencia(self):
        if self.estado != "ATIVA" and not self.motivo_estado:
            raise ValueError(f"estado {self.estado} sem motivo_estado (INDISPONÍVEL ≠ 0: diga por quê)")
        if self.natureza == "interna":
            return self
        faltam = [k for k in ("tabela", "coluna_frescor", "slo_frescor_h") if getattr(self, k) is None]
        if not self.chave_natural:
            faltam.append("chave_natural")
        if faltam:
            raise ValueError(f"fonte externa sem {faltam}")
        fora = [c for c in self.chave_natural if c not in self.campos]
        if fora:
            raise ValueError(f"chave_natural {fora} sem declaração em campos")
        for r in self.consistencia:
            fora = [c for c in r.campos if c not in self.campos]
            if fora:
                raise ValueError(f"regra {r.tipo} cita campos não declarados {fora}")
        return self


class Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versao: int = Field(ge=1)
    revisado_em: date
    fontes: dict[str, Fonte]

    @field_validator("fontes")
    @classmethod
    def _ids(cls, v):
        for k in v:
            _ident(k, "id da fonte")
        return v


def carregar(caminho: str | Path | None = None) -> Contrato:
    with open(caminho or ARQUIVO, encoding="utf-8") as f:
        return Contrato.model_validate(yaml.safe_load(f))


def fontes_da_propagacao(caminho: str | Path | None = None) -> set[str]:
    with open(caminho or PROPAGACAO, encoding="utf-8") as f:
        return set((yaml.safe_load(f) or {}).get("fontes") or {})


def conferir_propagacao(contrato: Contrato, ids_propagacao: set[str]) -> dict:
    """Toda fonte da propagação tem de estar coberta por ALGUMA fonte do contrato (campo `propagacao`), e
    nenhuma fonte do contrato pode citar id inexistente. Devolve {faltam, inexistentes}."""
    citados = {p for f in contrato.fontes.values() for p in f.propagacao}
    return {"faltam": sorted(ids_propagacao - citados), "inexistentes": sorted(citados - ids_propagacao)}


# ── validação de UM registro contra o contrato (pura) ─────────────────────────────────────────────

def _vazio(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _data_valida(v: str, tipo: str) -> bool:
    try:
        if tipo == "data_iso":
            date.fromisoformat(v)
        elif tipo == "data_br":
            datetime.strptime(v, "%d/%m/%Y")
        else:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validar_campo(nome: str, campo: Campo, valor) -> str | None:
    """Motivo da rejeição, ou None se o valor respeita o contrato. Vazio só reprova se `obrigatorio`."""
    if _vazio(valor):
        return f"{nome}: obrigatório ausente" if campo.obrigatorio else None
    s = str(valor).strip()
    if campo.tipo in ("inteiro", "real", "ano"):
        n = _num(s)
        if n is None or (campo.tipo in ("inteiro", "ano") and n != int(n)):
            return f"{nome}: {s[:40]!r} não é {campo.tipo}"
        if campo.minimo is not None and n < campo.minimo:
            return f"{nome}: {n} abaixo do mínimo {campo.minimo}"
        if campo.maximo is not None and n > campo.maximo:
            return f"{nome}: {n} acima do máximo {campo.maximo}"
    rx = _RX_TIPO.get(campo.tipo)
    if rx is not None and campo.tipo != "inteiro" and not rx.match(s):
        return f"{nome}: {s[:40]!r} fora do formato {campo.tipo}"
    if campo.tipo in ("data_iso", "data_br", "datahora_iso") and not _data_valida(s, campo.tipo):
        return f"{nome}: {s[:40]!r} não é data real"
    if campo.regex and not re.fullmatch(campo.regex, s):
        return f"{nome}: {s[:40]!r} não casa {campo.regex}"
    if campo.dominio is not None and s not in campo.dominio:
        return f"{nome}: {s[:40]!r} fora do domínio"
    return None


def validar_registro(fonte: Fonte, registro: dict) -> list[str]:
    """Todos os motivos de rejeição do registro (lista vazia = válido). Campo extra não reprova — vira
    `extensoes` desconhecidas no relatório do lote (schema drift), não perda de dado."""
    motivos = []
    for nome, campo in fonte.campos.items():
        m = validar_campo(nome, campo, registro.get(nome))
        if m:
            motivos.append(m)
    return motivos


def extensoes(fonte: Fonte, registro: dict) -> set[str]:
    """Campos que vieram e o contrato não conhece (alerta de schema drift, doc 2 §40.2)."""
    return set(registro) - set(fonte.campos) if fonte.campos else set()
