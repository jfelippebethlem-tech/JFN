# -*- coding: utf-8 -*-
"""Vantajosidade da PRORROGAÇÃO — o teste que a lei exige e que ninguém computava.

O DEVER É DA ADMINISTRAÇÃO, E É EXPRESSO. Serviço contínuo só se prorroga se a contratação
permanecer vantajosa, e a vantagem tem de ser DEMONSTRADA nos autos — não presumida pela
continuidade. O X2 já pontua a perpetuidade e já tem a rubrica `real / pro_forma / ausente`, mas
ela era LLM-opcional e nada a alimentava: `varredura_execucao_ctx` devolve
`pesquisa_vantajosidade: None` porque a base não guarda o campo. Resultado: o eixo mais decisivo
da prorrogação ficava sempre `nao_avaliavel`.

Este módulo computa o que dá para computar. Quando existem preços de mercado, a pergunta "seguir
com este contrato é melhor que licitar de novo?" é aritmética, e a resposta não depende de
julgamento de modelo.

OS TRÊS TESTES, e cada um pega uma forma diferente de a vantagem se perder:

  1. **PREÇO ACIMA DO MERCADO** — o contrato prorrogado custa mais que a mediana corrente do
     objeto. É o teste central, e usa a mesma régua de `knowledge/economicidade`: portão de
     homogeneidade primeiro, mediana depois (IN SEGES 65/2021).
  2. **REAJUSTE ACIMA DO ÍNDICE SETORIAL** — o preço subiu mais que o custo do setor. Aqui a
     vantagem não se perdeu de uma vez: ela foi CORROÍDA a cada renovação, e é por isso que
     contratos velhos costumam ficar caros sem que nenhum ato isolado pareça irregular.
  3. **VANTAGEM DECRESCENTE** — a distância para o mercado piora renovação após renovação. Um
     ponto no tempo não mostra isso; a série mostra.

A HONESTIDADE QUE DEFINE O MÓDULO. Sem referência de mercado, o resultado é `nao_aferivel` — e
esse é o veredito CERTO, não um fracasso: a ausência da pesquisa é, ela própria, o vício que o
art. 107 quer evitar. O módulo diz isso com todas as letras em vez de devolver "sem achado", que
o leitor confundiria com regularidade.
"""
from __future__ import annotations

from typing import Any, Sequence

# `homogeneidade` NÃO é importada aqui de propósito: `avaliar` já a aplica internamente
# (economicidade.py:151), então a promessa do docstring — homogeneidade primeiro, mediana depois —
# é cumprida por `avaliar_preco`. Importá-la de novo era só um símbolo morto.
from compliance_agent.knowledge.economicidade import avaliar as avaliar_preco

# Acima disto, o contrato prorrogado é caro frente ao mercado corrente. Conservador: variação de
# 10% entre contratações do mesmo objeto é comum e não sustenta afirmação.
DESVANTAGEM_ATENCAO = 0.10
DESVANTAGEM_FORTE = 0.25
# Reajuste que supera o índice setorial em mais que isto corrói a vantagem de forma perceptível.
FOLGA_INDICE = 0.02


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def avaliar(*, valor_atual: Any, precos_mercado: Sequence[float] | None = None,
            fonte_mercado: str = "", data_mercado: str = "",
            reajuste_aplicado: Any = None, indice_setorial: Any = None,
            historico_desvantagem: Sequence[float] | None = None) -> dict[str, Any]:
    """A prorrogação permanece vantajosa? Devolve o veredito E o que falta para afirmá-lo.

    `valor_atual` é o preço do contrato na renovação (global ou unitário — o que estiver na mesma
    base dos `precos_mercado`). Comparar bases diferentes é o erro que inventa desvantagem.
    """
    atual = _f(valor_atual)
    precos = [p for p in (precos_mercado or []) if _f(p)]
    sinais: list[dict] = []
    lacunas: list[str] = []

    if atual is None:
        return {"veredito": "nao_aferivel", "nivel": None, "sinais": [],
                "motivo": "valor atual do contrato ausente — nada a comparar (ausente ≠ zero)",
                "lacunas": ["valor_atual"],
                "diligencia": "requisitar o valor vigente do contrato na data da prorrogação"}

    # ── 1 · preço acima do mercado ────────────────────────────────────────────────────────────
    comparacao = None
    if precos:
        comparacao = avaliar_preco(atual, precos, fonte_referencia=fonte_mercado,
                                   data_referencia=data_mercado)
        if comparacao.get("aferivel"):
            pct = comparacao["sobrepreco_pct"] or 0.0
            if pct >= DESVANTAGEM_FORTE:
                sinais.append({"regra": "preco_acima_do_mercado", "nivel": "forte", "pct": pct,
                               "texto": (f"o contrato prorrogado custa {pct:.1%} acima da mediana "
                                         f"corrente do objeto ({fonte_mercado or 'referência'})")})
            elif pct >= DESVANTAGEM_ATENCAO:
                sinais.append({"regra": "preco_acima_do_mercado", "nivel": "medio", "pct": pct,
                               "texto": (f"o contrato prorrogado custa {pct:.1%} acima da mediana "
                                         f"corrente — acima do usual, abaixo do grave")})
        else:
            lacunas.append(f"comparação de preço prejudicada: {comparacao.get('motivo')}")
    else:
        lacunas.append("sem referência de mercado")

    # ── 2 · reajuste acima do índice setorial ─────────────────────────────────────────────────
    r, i = _f(reajuste_aplicado), _f(indice_setorial)
    if r is not None and i is not None:
        if r > i + FOLGA_INDICE:
            sinais.append({
                "regra": "reajuste_acima_do_indice", "nivel": "medio",
                "pct": round(r - i, 4),
                "texto": (f"reajuste aplicado de {r:.1%} contra índice setorial de {i:.1%} — a "
                          f"diferença de {r - i:.1%} corrói a vantagem a cada renovação, sem que "
                          f"nenhum ato isolado pareça irregular")})
    elif reajuste_aplicado is not None or indice_setorial is not None:
        lacunas.append("reajuste ou índice setorial ausente — teste 2 não aferido")

    # ── 3 · vantagem decrescente ao longo das renovações ──────────────────────────────────────
    serie = [x for x in (historico_desvantagem or []) if x is not None]
    if len(serie) >= 3:
        if all(b > a for a, b in zip(serie, serie[1:])):
            sinais.append({
                "regra": "vantagem_decrescente", "nivel": "forte",
                "texto": (f"a distância para o mercado piorou em TODAS as {len(serie)} renovações "
                          f"({serie[0]:.1%} → {serie[-1]:.1%}) — um ponto no tempo não mostra "
                          f"isso; a série mostra")})
    elif serie:
        lacunas.append(f"histórico com {len(serie)} ponto(s) — série curta para tendência")

    if not precos:
        # A ausência da pesquisa É o vício que o art. 107 quer evitar. Dizer "sem achado" aqui
        # seria deixar o leitor concluir regularidade a partir da falta de dado.
        return {
            "veredito": "nao_aferivel", "nivel": None, "sinais": sinais, "lacunas": lacunas,
            "motivo": ("sem referência de mercado, a vantajosidade NÃO foi demonstrada — e a "
                       "demonstração é dever da Administração a cada prorrogação, não presunção "
                       "decorrente da continuidade"),
            "diligencia": ("requisitar a pesquisa de preços que instruiu a prorrogação; se não "
                           "houver, a própria ausência é o achado"),
            "comparacao": comparacao,
        }

    if not sinais:
        return {"veredito": "vantajosa", "nivel": None, "sinais": [], "lacunas": lacunas,
                "motivo": (f"preço do contrato compatível com a mediana corrente "
                           f"({fonte_mercado or 'referência'})"),
                "comparacao": comparacao}

    ordem = {"forte": 3, "medio": 2, "fraco": 1}
    sinais.sort(key=lambda s: -ordem.get(s["nivel"], 0))
    return {
        "veredito": "desvantajosa", "nivel": sinais[0]["nivel"], "sinais": sinais,
        "lacunas": lacunas, "comparacao": comparacao,
        "motivo": "; ".join(s["texto"] for s in sinais),
        "explicacao_inocente": (
            "Preço acima da mediana pode refletir escopo maior, nível de serviço superior ou "
            "custo de transição que a nova contratação teria. O que a lei exige é que essa "
            "comparação CONSTE dos autos — o achado é sobre a demonstração, não sobre o preço em "
            "si."),
        "diligencia": ("requisitar a pesquisa de preços da prorrogação e a memória de cálculo do "
                       "reajuste aplicado"),
    }


def classe_para_x2(resultado: dict) -> str | None:
    """Traduz o veredito para a rubrica do X2 (`real` / `pro_forma` / `ausente`).

    Só traduz o que é DETERMINÍSTICO: contrato caro frente ao mercado com pesquisa existente é
    `pro_forma` (a pesquisa foi feita e não sustentou a decisão); ausência de referência é
    `ausente`. Contrato compatível devolve `real`. Qualquer outro caso devolve `None` — a rubrica
    do LLM continua sendo o caminho, e sobrescrevê-la com chute pioraria o X2.
    """
    v = (resultado or {}).get("veredito")
    if v == "nao_aferivel" and "sem referência de mercado" in " ".join(resultado.get("lacunas") or []):
        return "ausente"
    if v == "desvantajosa":
        return "pro_forma"
    if v == "vantajosa":
        return "real"
    return None
