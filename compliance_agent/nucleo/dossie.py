"""
Dossiê — esquema normalizado de evidências da perícia.

É o formato ÚNICO que os indicadores consomem. Collectors (SIAFE/PNCP/CNPJ/SEI)
e a extração por IA fraca preenchem um Dossiê; os indicadores nunca leem banco
ou LLM diretamente. Isso dá três ganhos:

  1. Testabilidade  — indicadores são funções puras sobre um Dossiê sintético.
  2. Blindagem      — todo campo passa por validação determinística aqui
                      (dígito verificador de CNPJ, datas, valores), então lixo
                      vindo de uma IA fraca é rejeitado ANTES de virar "achado".
  3. Rastreabilidade— cada valor carrega sua ``fonte`` (siafe|pncp|cnpj|sei|llm),
                      exigência de qualquer perícia séria.

Sem dependência de IA. Puro Python/stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


# ── Validadores determinísticos ──────────────────────────────────────────────

def cnpj_valido(cnpj: str | None) -> bool:
    """Valida um CNPJ pelos dígitos verificadores (algoritmo oficial)."""
    if not cnpj:
        return False
    n = re.sub(r"\D", "", str(cnpj))
    if len(n) != 14 or len(set(n)) == 1:
        return False
    def dv(base: str, pesos: list[int]) -> str:
        s = sum(int(d) * p for d, p in zip(base, pesos))
        r = s % 11
        return "0" if r < 2 else str(11 - r)
    d1 = dv(n[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(n[:12] + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return n[12:] == d1 + d2


def cpf_valido(cpf: str | None) -> bool:
    """Valida um CPF pelos dígitos verificadores."""
    if not cpf:
        return False
    n = re.sub(r"\D", "", str(cpf))
    if len(n) != 11 or len(set(n)) == 1:
        return False
    def dv(base: str, fator: int) -> str:
        s = sum(int(d) * (fator - i) for i, d in enumerate(base))
        r = (s * 10) % 11
        return "0" if r == 10 else str(r)
    d1 = dv(n[:9], 10)
    d2 = dv(n[:10], 11)
    return n[9:] == d1 + d2


def para_data(v: Any) -> date | None:
    """Converte string/date/datetime em date, tolerante a formatos BR e ISO."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    # tentativa final: ISO parcial
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def para_reais(v: Any) -> float | None:
    """
    Converte um valor monetário heterogêneo em float.

    Aceita ``"R$ 1.234.567,89"``, ``"1234567.89"``, ``1234.5``. Rejeita texto
    sem número. Essencial para blindar a saída de IA fraca, que costuma devolver
    valores como string com pontuação BR.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not re.search(r"\d", s):
        return None
    # Heurística BR: se tem vírgula, ela é o decimal; pontos são milhar.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        # Só pontos: se houver mais de um, são milhares (remove todos menos separador).
        if s.count(".") > 1:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def idade_em_dias(inicio: date | None, referencia: date | None) -> int | None:
    """Dias entre ``inicio`` e ``referencia`` (idade da empresa no contrato, etc.)."""
    if inicio is None or referencia is None:
        return None
    return (referencia - inicio).days


# ── Estruturas de evidência ──────────────────────────────────────────────────

@dataclass
class Contratacao:
    """Uma contratação (contrato, empenho, OB ou dispensa) normalizada."""

    identificador: str = ""              # nº contrato / empenho / OB
    objeto: str = ""
    orgao: str = ""
    modalidade: str = ""                 # pregão|concorrência|dispensa|inexigível|...
    valor: float | None = None           # valor total
    valor_estimado: float | None = None
    data: date | None = None             # assinatura / emissão
    categoria: str = ""                  # saúde|obras|ti|cultura|... (do categorizar.py)
    propostas_validas: int | None = None
    prazo_edital_dias: int | None = None
    aditivos_valor: float = 0.0          # soma dos aditivos
    aditivos_qtd: int = 0
    fonte: str = ""                      # siafe|pncp|sei|tfe|llm

    def __post_init__(self) -> None:
        self.valor = para_reais(self.valor)
        self.valor_estimado = para_reais(self.valor_estimado)
        self.aditivos_valor = para_reais(self.aditivos_valor) or 0.0
        self.data = para_data(self.data)


@dataclass
class Fornecedor:
    """A empresa/pessoa contratada, com o que sabemos dela."""

    cnpj: str = ""
    nome: str = ""
    data_abertura: date | None = None
    capital_social: float | None = None
    situacao: str = ""                   # ATIVA|BAIXADA|SUSPENSA
    cnae_principal: str = ""
    qtd_funcionarios: int | None = None  # CAGED/e-Social, se conhecido
    endereco_tipo: str = ""              # comercial|residencial|coworking|desconhecido
    sancionado: bool = False             # consta em CEIS/CNEP
    doacoes_eleitorais: list[dict] = field(default_factory=list)  # [{valor, data, candidato}]
    fonte: str = ""

    def __post_init__(self) -> None:
        self.cnpj = re.sub(r"\D", "", str(self.cnpj or ""))
        self.capital_social = para_reais(self.capital_social)
        self.data_abertura = para_data(self.data_abertura)

    @property
    def cnpj_ok(self) -> bool:
        return cnpj_valido(self.cnpj)


@dataclass
class Dossie:
    """
    Pacote de evidências sobre um alvo (uma contratação + seu fornecedor +
    histórico do par órgão×fornecedor no período).

    ``historico_orgao_fornecedor`` são outras contratações do MESMO fornecedor
    com o MESMO órgão, usadas por indicadores de fracionamento e conluio.
    """

    contratacao: Contratacao = field(default_factory=Contratacao)
    fornecedor: Fornecedor = field(default_factory=Fornecedor)
    historico_orgao_fornecedor: list[Contratacao] = field(default_factory=list)
    # Estatística de mercado da categoria (mediana/desvio) para prova de preço.
    referencia_categoria: dict[str, float] = field(default_factory=dict)
    # Avisos de validação acumulados (campos rejeitados, inconsistências).
    avisos: list[str] = field(default_factory=list)

    def validar(self) -> list[str]:
        """
        Roda checagens determinísticas e acumula avisos. NÃO levanta exceção:
        a perícia continua com o que é confiável, mas registra o que não bate.
        """
        av: list[str] = []
        f = self.fornecedor
        if f.cnpj and not f.cnpj_ok:
            av.append(f"CNPJ inválido (dígito verificador): {f.cnpj!r} — desconsiderado.")
        c = self.contratacao
        if c.valor is not None and c.valor < 0:
            av.append("Valor de contrato negativo — desconsiderado.")
            c.valor = None
        if (c.valor is not None and c.valor_estimado is not None
                and c.valor_estimado > 0 and c.valor > c.valor_estimado * 100):
            av.append("Valor total 100x acima do estimado — provável erro de extração.")
        if f.data_abertura and c.data and f.data_abertura > c.data:
            av.append("Empresa aberta DEPOIS do contrato — data inconsistente.")
        self.avisos = av
        return av
