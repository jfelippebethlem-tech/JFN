# -*- coding: utf-8 -*-
"""Curva ABC (D.3.3) — onde a análise de planilha deve gastar atenção.

A METODOLOGIA, e por que ela não é um detalhe de conveniência. Numa planilha de obra com 800
itens, uns poucos respondem por quase todo o valor: é a concentração de Pareto, e o TCU e o
IBRAOP fixaram nela o método de análise de sobrepreço. Auditar os 800 com o mesmo cuidado gasta a
atenção onde ela não muda nada; auditar a faixa A resolve a maior parte do risco com uma fração
do esforço.

O QUE ISTO MUDA EM CADA DETECTOR DE PREÇO. O X5 (jogo de planilha) e o comparador correlacionam
sobre TODOS os itens; um desvio de 300% num item de R$ 40 pesa igual a 3% num item de R$ 4
milhões. A curva devolve o peso — e com ele o **dano potencial por item**, que é o número que
ordena a fila de verdade.

DUAS ARMADILHAS QUE O MÉTODO TEM, e ambas viram estado declarado:

  · **Planilha achatada.** Se nenhum item concentra (mil itens de valor parecido), a curva ABC
    não informa: a faixa A teria 800 itens. O resultado diz `concentracao: baixa` e o chamador
    sabe que não pode usar "olhei a faixa A" como cobertura.
  · **Item sem quantidade ou sem preço** não entra no cálculo, mas NÃO some: sai como
    `sem_valor`, com a fração que representa. Somar zero no lugar dele encolheria o denominador
    e inflaria o peso relativo de todos os outros.

CORTE PADRÃO 80/95, que é o consagrado — A até 80% do valor acumulado, B até 95%, C o resto. Os
percentuais ficam no CÓDIGO, parametrizáveis, nunca em prompt.
"""
from __future__ import annotations

from typing import Any

CORTE_A = 0.80
CORTE_B = 0.95
# Abaixo disto a planilha é achatada e a curva não ajuda a priorizar: a faixa A viraria a
# planilha inteira, e "auditei a faixa A" deixaria de significar cobertura.
FRACAO_A_MAXIMA_UTIL = 0.40


def _valor(item: dict) -> float | None:
    """Valor total do item. `None` quando falta preço ou quantidade — e isso não vira zero."""
    v = item.get("valor_total")
    if v not in (None, ""):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    p, q = item.get("preco_unitario"), item.get("quantidade")
    if p in (None, "") or q in (None, ""):
        return None
    try:
        return float(p) * float(q)
    except (TypeError, ValueError):
        return None


def montar(itens: list[dict], *, corte_a: float = CORTE_A,
           corte_b: float = CORTE_B) -> dict[str, Any]:
    """Classifica os itens em A/B/C por valor acumulado e devolve a concentração medida."""
    com_valor, sem_valor = [], []
    for i, it in enumerate(itens or []):
        v = _valor(it)
        (com_valor if v is not None and v > 0 else sem_valor).append(
            {**it, "_i": i, "valor": v})

    if not com_valor:
        return {"estado": "sem_valor_calculavel", "itens": [], "sem_valor": len(sem_valor),
                "n": len(itens or []), "concentracao": None,
                "motivo": "nenhum item com preço e quantidade — curva não calculável",
                "ressalva": _RESSALVA}

    total = sum(x["valor"] for x in com_valor)
    ordenados = sorted(com_valor, key=lambda x: -x["valor"])
    acumulado = 0.0
    saida = []
    for pos, x in enumerate(ordenados, 1):
        acumulado += x["valor"]
        frac_ac = acumulado / total
        faixa = "A" if frac_ac <= corte_a else ("B" if frac_ac <= corte_b else "C")
        saida.append({**{k: v for k, v in x.items() if k != "_i"},
                      "posicao": pos, "fracao": round(x["valor"] / total, 6),
                      "fracao_acumulada": round(frac_ac, 6), "faixa": faixa})
    # O primeiro item que cruza o corte pertence à faixa que ele fecha — sem isso, uma planilha
    # com um único item de 90% teria faixa A vazia, que é o oposto do que a curva quer dizer.
    if saida and saida[0]["faixa"] != "A":
        saida[0]["faixa"] = "A"

    n_a = sum(1 for x in saida if x["faixa"] == "A")
    frac_itens_a = n_a / len(saida)
    concentracao = ("alta" if frac_itens_a <= 0.20 else
                    "media" if frac_itens_a <= FRACAO_A_MAXIMA_UTIL else "baixa")

    return {
        "estado": "calculada",
        "n": len(itens or []), "n_com_valor": len(com_valor), "sem_valor": len(sem_valor),
        "total": round(total, 2),
        "itens": saida,
        "faixa_a": [x for x in saida if x["faixa"] == "A"],
        "n_faixa_a": n_a,
        "fracao_itens_na_faixa_a": round(frac_itens_a, 4),
        "concentracao": concentracao,
        "curva_util_para_priorizar": concentracao != "baixa",
        "cortes": {"a": corte_a, "b": corte_b},
        "nota_sem_valor": (
            f"{len(sem_valor)} item(ns) sem preço ou quantidade ficaram FORA do cálculo e não "
            "foram somados como zero — zerá-los encolheria o denominador e inflaria o peso "
            "relativo de todos os outros" if sem_valor else ""),
        "ressalva": _RESSALVA,
    }


def dano_potencial(curva: dict[str, Any], desvios: dict[Any, float], *,
                   chave: str = "item") -> dict[str, Any]:
    """Ordena por DANO POTENCIAL (valor × desvio), não por desvio.

    `desvios` mapeia o identificador do item para o desvio relativo (0.30 = 30% acima da
    referência). Um desvio de 300% num item de R$ 40 é R$ 120; 3% num item de R$ 4 milhões é
    R$ 120 mil — e é a segunda linha que precisa ir ao relatório primeiro.
    """
    linhas = []
    for x in curva.get("itens") or []:
        ident = x.get(chave)
        d = desvios.get(ident)
        if d is None:
            continue
        linhas.append({"item": ident, "faixa": x["faixa"], "valor": x["valor"],
                       "desvio": d, "dano_potencial": round(x["valor"] * d, 2)})
    linhas.sort(key=lambda r: -r["dano_potencial"])
    total = round(sum(r["dano_potencial"] for r in linhas), 2)
    em_a = round(sum(r["dano_potencial"] for r in linhas if r["faixa"] == "A"), 2)
    return {
        "linhas": linhas, "dano_potencial_total": total,
        "dano_na_faixa_a": em_a,
        "fracao_do_dano_na_faixa_a": round(em_a / total, 4) if total else 0.0,
        "itens_sem_desvio": len(curva.get("itens") or []) - len(linhas),
        "ressalva": (
            "DANO POTENCIAL, não dano: pressupõe a referência de preço correta e a quantidade "
            "efetivamente executada. Dano exige medição e Ordem Bancária — empenho não é "
            "pagamento."),
    }


_RESSALVA = (
    "A curva ordena a ATENÇÃO, não julga preço. Concentração baixa significa que a faixa A não "
    "resume a planilha, e nesse caso 'auditei a faixa A' NÃO é cobertura. Item sem preço ou "
    "quantidade fica fora do cálculo e é contado à parte — nunca somado como zero."
)
