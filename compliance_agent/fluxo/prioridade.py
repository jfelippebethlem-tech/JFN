# -*- coding: utf-8 -*-
"""Prioridade única do planejador (plano mestre v2 §3.7 + §16.3) — porte da ORDEM DA FILA SEI de tools/sei_sweep.py
(`_fila`, a chave de `rows.sort` e o `foco.intercalar`), que é a regra mais madura da casa e passa a valer para todo
job que tem processo/contratação por trás.

Ordem (lexicográfica, igual à do sei_sweep; cada degrau é um componente GRAVADO, para a prioridade ser explicável):
  0. faixa 0 — urgente do dono: fura a fila (fora da cota Couto);
  1. grupo útil: unidade legível OU enfileirado à mão OU contratação direta grande vêm antes do resto
     (sei_sweep: "unidade que rende documentos primeiro" — e o alvo à mão/direta de unidade nunca lida também);
  2. enfileirado à mão (hipótese do vault);
  3. contratação direta (inexigibilidade/dispensa/emergencial) com OB PAGA ≥ R$ 1.000.000,00 (PISO_DIRETA);
  4. lacuna provada pelo parecer;
  5. sinal OSINT no credor;
  6. folha/previdência por último DENTRO do estrato (rebaixada, nunca excluída);
  7. valor de OB paga do SIAFE (régua `cruzamentos_intel._ob_paga`), maior antes.
  Desempate (não existia no sei_sweep — só decide entre valores iguais): risco dos achados maior, depois mais antigo.
A cota Couto de 50% é RESERVA DE SLOTS, não peso: `ordenar` intercala com `foco.intercalar` (⌈n·fração⌉ itens do
período em todo prefixo). Nunca se ordena pela posição na árvore (lição "quais 40").

`inteiro()` codifica a chave num número para `fluxo.jobs.prioridade` (menor = antes) preservando a ordem dos
degraus 0–7; a intercalação Couto não cabe num inteiro por item e fica com quem monta o lote (`ordenar`).
O estrato do vínculo OB↔contrato (teto de 50% do lote, `_intercalar_estrato`) não entra aqui: é cota de LOTE do E2,
portada com o estágio (O3).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Sequence, TypeVar

PISO_DIRETA = 1_000_000.00          # = tools/sei_sweep.PISO_DIRETA (SEI_PISO_CONTRATACAO_DIRETA)
_ESCALA_VALOR = 5000                # log10(1+R$) × 5000: R$ 1 tri ≈ 60.000 — cabe nos 5 dígitos do degrau 7
_TETO_VALOR = 99_999
T = TypeVar("T")


@dataclass(frozen=True)
class Sinais:
    """O que se sabe do item. Ausente = False/0 (INDISPONÍVEL não sobe ninguém — só muda ordem, nunca veredito)."""
    urgente_dono: bool = False
    legivel: bool = False            # unidade que o leitor já leu com sucesso (rende documentos)
    manual: bool = False             # enfileirado à mão (hipótese do vault)
    contratacao_direta: bool = False  # inexigibilidade/dispensa/emergencial citada em NE
    ob_paga: float = 0.0             # R$ de OB paga (SIAFE, _ob_paga) — nunca empenho
    lacuna_provada: bool = False
    osint: bool = False
    folha: bool = False
    risco: float = 0.0               # maior risco dos achados do item (0..1)
    idade_dias: float = 0.0
    couto: bool = False              # período Couto (foco.eh_couto)
    lente: str | None = None


def direta_grande(s: Sinais) -> bool:
    return s.contratacao_direta and (s.ob_paga or 0) >= PISO_DIRETA


def chave(s: Sinais) -> tuple:
    """A chave de ordenação (menor = antes). Degraus 1–7 = a lambda de `tools/sei_sweep._fila`."""
    dg = direta_grande(s)
    return (0 if s.urgente_dono else 1,
            0 if (s.legivel or s.manual or dg) else 1,
            0 if s.manual else 1,
            0 if dg else 1,
            0 if s.lacuna_provada else 1,
            0 if s.osint else 1,
            1 if s.folha else 0,
            -(s.ob_paga or 0),
            -(s.risco or 0),
            -(s.idade_dias or 0))


def _balde_valor(v: float) -> int:
    """Maior valor ⇒ número menor. Monótono (não estrito: valores muito próximos podem empatar no balde)."""
    return _TETO_VALOR - min(_TETO_VALOR, int(math.log10(1.0 + max(0.0, v or 0.0)) * _ESCALA_VALOR))


def inteiro(s: Sinais) -> int:
    """`fluxo.jobs.prioridade`: os 7 degraus binários em ordem + o balde de valor. Todo urgente do dono fica abaixo de
    6.400.000 e todo não urgente, de 6.400.000 para cima (máximo < 12.800.000: cabe no integer do PG)."""
    k = chave(s)
    bits = 0
    for b in k[:7]:
        bits = bits * 2 + b
    return bits * 100_000 + _balde_valor(s.ob_paga)


def explicar(s: Sinais) -> dict:
    """Componentes gravados com o job (`payload.prioridade`): o porquê de cada posição."""
    return {"inteiro": inteiro(s), "faixa": 0 if s.urgente_dono else 1, "direta_grande": direta_grande(s),
            "sinais": asdict(s)}


def ordenar(itens: Iterable[T], sinais: Callable[[T], Sinais], fracao_couto: float | None = None) -> list[T]:
    """O lote na ordem única: urgente do dono primeiro (fora da cota), depois a chave, com a reserva Couto
    intercalada (`foco.intercalar`; `fracao_couto=None` lê config/foco.yaml, 0 desliga)."""
    from compliance_agent.foco import intercalar
    lista: Sequence[T] = sorted(itens, key=lambda x: chave(sinais(x)))
    urgentes = [x for x in lista if sinais(x).urgente_dono]
    resto = [x for x in lista if not sinais(x).urgente_dono]
    return urgentes + intercalar(resto, lambda x: sinais(x).couto, fracao=fracao_couto)
