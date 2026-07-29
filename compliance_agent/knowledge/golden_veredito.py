# -*- coding: utf-8 -*-
"""O conjunto-ouro pronto para medir: split selado, estratificação e o baseline burro.

`corpus_veredito` extrai e rotula. Este módulo prepara a MEDIÇÃO, e existe separado porque as
armadilhas aqui não são de extração, são de estatística — e são as que fazem um número errado
parecer rigoroso:

**Desequilíbrio de classe.** O acervo dá 776 `vicio_por_omissao`, 551 `vicio` e 203 `licito`. Um
motor que responde "é vício" para tudo acerta ~87%. Em controle externo isso é o pior resultado
possível, porque o custo do falso positivo é acusar quem está regular — a lição que a casa já
pagou sete vezes com manchete inflada. Por isso `baseline_classe_majoritaria` fica calculado e
exposto: qualquer acurácia comemorada tem de bater o burro, e o F1 tem de ser POR CLASSE.

**Split determinístico, não aleatório.** Semente aleatória exige guardar a semente; se ela se
perder, o holdout de ontem vira treino de hoje e a medição fica sem sentido sem ninguém notar. O
corte aqui é `sha256(id)`, reprodutível em qualquer máquina, sem estado.

**Cobertura declarada.** 1.530 casos parecem censo; são recorte de 8.718 (55% sem polaridade
reconhecível, 27% com tema fora do mapa). `estratificacao()` carrega esse número junto, para que
o relatório não possa citar o corpus sem citar o que ficou de fora.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from compliance_agent.knowledge.corpus_veredito import cobertura, iterar_casos

ROTULOS_VALIDOS = ("vicio", "licito", "vicio_por_omissao")
FRACAO_HOLDOUT = 0.30


def carregar(db: str | Path | None = None) -> list[dict]:
    """Todos os casos rotuláveis. Lista vazia se o acervo não estiver indexado (nunca inventa)."""
    return list(iterar_casos(db))


def _balde(identificador: str) -> int:
    """0-99 estável por caso. `hash()` do Python é randomizado por processo — não serve."""
    return int(hashlib.sha256(str(identificador).encode()).hexdigest()[:8], 16) % 100


def split(casos: list[dict], fracao_holdout: float = FRACAO_HOLDOUT) -> dict[str, list[dict]]:
    """`{treino, holdout}` — determinístico, reprodutível e sem semente guardada.

    O holdout é SELADO: só entra em medição final. Ele jamais deve aparecer em prompt, exemplo
    ou fixture de produção — `tests/test_golden_veredito` varre o código atrás de vazamento.
    """
    corte = int(round(fracao_holdout * 100))
    treino, holdout = [], []
    for c in casos:
        (holdout if _balde(c["id"]) < corte else treino).append(c)
    return {"treino": treino, "holdout": holdout}


def estratificacao(casos: list[dict], db: str | Path | None = None) -> dict[str, Any]:
    """Composição do conjunto + o que ficou de fora do acervo."""
    por_rotulo: dict[str, int] = {}
    por_vicio: dict[str, int] = {}
    condicionados = 0
    for c in casos:
        por_rotulo[c["rotulo"]] = por_rotulo.get(c["rotulo"], 0) + 1
        por_vicio[c["vicio"]] = por_vicio.get(c["vicio"], 0) + 1
        condicionados += bool(c.get("condicionada"))
    maior = max(por_rotulo, key=por_rotulo.get) if por_rotulo else ""
    total = len(casos) or 1
    return {
        "n": len(casos),
        "por_rotulo": por_rotulo,
        "por_vicio": dict(sorted(por_vicio.items(), key=lambda kv: -kv[1])),
        "classe_majoritaria": maior,
        "frac_majoritaria": por_rotulo.get(maior, 0) / total,
        "condicionados": condicionados,
        "frac_condicionados": condicionados / total,
        "cobertura_acervo": cobertura(db),
    }


def matriz_confusao(pares: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """`[(esperado, previsto)]` → matriz. Previsto fora da escala vira 'indeterminado'."""
    m: dict[str, dict[str, int]] = {}
    for esperado, previsto in pares:
        p = previsto if previsto in ROTULOS_VALIDOS else "indeterminado"
        m.setdefault(esperado, {}).setdefault(p, 0)
        m[esperado][p] += 1
    return m


def metricas(pares: list[tuple[str, str]]) -> dict[str, Any]:
    """Precisão, recall e F1 POR CLASSE, mais acurácia e abstenção.

    Acurácia sozinha é enganosa aqui (ver o baseline). A abstenção entra como métrica de primeira
    classe: um motor honesto que diz "não sei" em 30% dos casos é melhor, em controle externo, que
    um que chuta — e a acurácia bruta puniria o primeiro.
    """
    total = len(pares) or 1
    acertos = sum(1 for e, p in pares if e == p)
    abstencoes = sum(1 for _, p in pares if p not in ROTULOS_VALIDOS)
    por_classe: dict[str, dict[str, float]] = {}
    for classe in ROTULOS_VALIDOS:
        vp = sum(1 for e, p in pares if e == classe and p == classe)
        fp = sum(1 for e, p in pares if e != classe and p == classe)
        fn = sum(1 for e, p in pares if e == classe and p != classe)
        prec = vp / (vp + fp) if (vp + fp) else 0.0
        rec = vp / (vp + fn) if (vp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        por_classe[classe] = {"precisao": prec, "recall": rec, "f1": f1,
                              "n": sum(1 for e, _ in pares if e == classe)}
    macro = sum(v["f1"] for v in por_classe.values()) / len(ROTULOS_VALIDOS)
    return {"n": len(pares), "acuracia": acertos / total, "abstencao": abstencoes / total,
            "f1_macro": macro, "por_classe": por_classe,
            "f1_por_classe": {k: v["f1"] for k, v in por_classe.items()},
            "matriz": matriz_confusao(pares)}


def baseline_classe_majoritaria(casos: list[dict]) -> dict[str, Any]:
    """O burro que responde sempre a classe mais comum. Todo resultado tem de bater ISTO.

    Serve como piso publicado: sem ele, uma acurácia de 85% num corpus 87% desbalanceado passa
    por bom resultado.
    """
    if not casos:
        return {"acuracia": 0.0, "f1_por_classe": {}, "classe": ""}
    e = estratificacao(casos)
    classe = e["classe_majoritaria"]
    r = metricas([(c["rotulo"], classe) for c in casos])
    return {"classe": classe, "acuracia": r["acuracia"], "f1_macro": r["f1_macro"],
            "f1_por_classe": r["f1_por_classe"]}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Conjunto-ouro de vereditos — composição e split")
    ap.add_argument("--split", action="store_true")
    a = ap.parse_args(argv)

    casos = carregar()
    e = estratificacao(casos)
    saida: dict[str, Any] = {"estratificacao": e,
                             "baseline_burro": baseline_classe_majoritaria(casos)}
    if a.split:
        s = split(casos)
        saida["split"] = {"treino": len(s["treino"]), "holdout": len(s["holdout"])}
    print(json.dumps(saida, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
