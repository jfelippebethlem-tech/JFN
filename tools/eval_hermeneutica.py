# -*- coding: utf-8 -*-
"""Mede a hermenêutica jurídica da camada não-determinística contra o conjunto-ouro.

O QUE ESTE HARNESS RESPONDE, e ninguém respondia: **quando a IA diz que uma conduta é vício, ela
acerta?** A casa media honestidade do modelo (`tools/bench_modelos.py`), o motor determinístico
contra punições reais (`eval_groundtruth.py`) e formato de relatório (`tests/golden/`). O juízo
jurídico em si — o que decide o grau que vai para a fila do fiscal — nunca teve precisão nem
recall medidos.

COMO MEDE. Cada caso do conjunto-ouro traz a tese decidida pelo TCU, VERBATIM, e o rótulo
derivado da polaridade dela (`knowledge/corpus_veredito`). O harness apresenta ao modelo a
CONDUTA descrita — sem a conclusão do tribunal — e compara o veredito com o rótulo.

TRÊS CUIDADOS QUE MUDAM O RESULTADO:

  1. **A conclusão é removida do enunciado.** "É irregular a exigência de X" vira "exigência de
     X". Deixar o "é irregular" seria pedir ao modelo que copiasse a resposta, e o número
     mediria leitura, não hermenêutica.
  2. **Abstenção é medida, não punida como erro.** Um motor que diz "não sei" em 30% dos casos
     difíceis é melhor, em controle externo, do que um que chuta — a acurácia bruta puniria o
     primeiro. Sai como métrica própria.
  3. **Alucinação de citação é contada.** Toda resposta deve trazer o trecho que a sustenta; se
     o trecho não existe no texto apresentado, conta como alucinação, e não como acerto — mesmo
     quando o rótulo bateu por sorte.

Uso:
    python -m tools.eval_hermeneutica --holdout --limite 200
    python -m tools.eval_hermeneutica --treino --por-vicio
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from compliance_agent.knowledge.golden_veredito import (
    ROTULOS_VALIDOS,
    baseline_classe_majoritaria,
    carregar,
    metricas,
    split,
)
from compliance_agent.knowledge.moldura_juridica import moldura

# ── o prompt sob medição ──────────────────────────────────────────────────────────────────────
# Fechado, com escala nomeada e citação obrigatória — o mesmo contrato de `detectores/base`.
# Versionado: sem `PROMPT_VERSAO` não há como investigar uma regressão de qualidade depois.
PROMPT_VERSAO = "v1"

_SISTEMA = (
    "Você é AUDITOR DE CONTROLE EXTERNO qualificando juridicamente uma CONDUTA em contratação "
    "pública, à luz da Lei 14.133/2021 e da jurisprudência do TCU/TCE-RJ.\n"
    "Classifique a conduta descrita em UMA destas classes:\n"
    "  'vicio'             — a conduta descrita é irregular/ilegal/vedada;\n"
    "  'licito'            — a conduta é lícita, admissível ou não configura irregularidade;\n"
    "  'vicio_por_omissao' — o texto descreve um DEVER da Administração, cuja omissão é irregular;\n"
    "  'nao_sei'           — o texto não permite concluir.\n"
    "REGRAS ABSOLUTAS: (1) presunção de legitimidade — na dúvida entre 'vicio' e 'licito', "
    "responda 'nao_sei'; (2) a resposta DEVE citar o TRECHO LITERAL do texto que a sustenta — "
    "sem trecho, será descartada; (3) nunca invente fato, norma ou número fora do texto.\n"
    'Responda SOMENTE um objeto JSON: {"classe":"...","citacao":"trecho LITERAL",'
    '"fundamento":"1 frase"}'
)

# Fórmulas que ENTREGAM a resposta. Sem removê-las, mede-se cópia, não juízo.
_RE_CONCLUSAO = re.compile(
    # Os radicais terminam em `\w*` de propósito: exigir `\b` logo após o radical fazia
    # "Não é obrigatório" escapar da máscara — `obrigat[óo]ri` casa, mas o `o` seguinte é
    # caractere de palavra e a fronteira falha. O veredito ficava no texto e o harness passava
    # a medir transcrição.
    r"^\s*(?:[ée]\s+(?:irregular|ileg[ai]l\w*|indevid\w*|vedad\w*|inadmiss[íi]v\w*|l[íi]cit\w*|"
    r"leg[íi]tim\w*|regular|admiss[íi]v\w*|poss[íi]v\w*|obrigat[óo]ri\w*|desqualificad\w*)|"
    r"n[ãa]o\s+(?:[ée]|s[ãa]o)\s+(?:obrigat[óo]ri\w*|admit\w*|permit\w*|l[íi]cit\w*|"
    r"irregular|ileg[ai]l\w*|vedad\w*|exig[íi]v\w*)|"
    r"n[ãa]o\s+(?:configura|caracteriza)\w*)\b[,:]?\s*", re.I)
_RE_DEVER_INICIAL = re.compile(r"\b(?:deve[m]?|dever[áa](?:o)?)\s+", re.I)


def mascarar_conclusao(enunciado: str) -> str:
    """Tira o veredito da frase e devolve só a CONDUTA.

    "É irregular a exigência de X" → "a exigência de X". Sem isso, o modelo lê a resposta no
    enunciado e o harness mede transcrição.
    """
    texto = re.sub(r"\s+", " ", enunciado or "").strip()
    mascarado = _RE_CONCLUSAO.sub("", texto, count=1)
    if mascarado == texto:
        # o dever costuma vir no meio ("A demonstração ... deve ser realizada mediante ...")
        mascarado = _RE_DEVER_INICIAL.sub("", texto, count=1)
    return mascarado.strip() or texto


def _ancorada(citacao: str, fonte: str) -> bool:
    """A citação existe mesmo no texto apresentado? (grounding conferido, não declarado)."""
    c = re.sub(r"\s+", " ", (citacao or "")).strip().lower()
    if len(c) < 12:
        return False
    return c[:60] in re.sub(r"\s+", " ", fonte or "").lower()


def avaliar_caso(caso: dict, gerar: Callable) -> dict:
    """Um caso → `{esperado, previsto, ancorada, bruto}`. Nunca levanta."""
    from compliance_agent.llm.json_resposta import parse_json_llm

    conduta = mascarar_conclusao(caso["trecho_ancora"])
    prompt = (f"{moldura()}\n\nCONDUTA A QUALIFICAR:\n{conduta}\n\nResponda só o JSON.")
    try:
        bruto = gerar(prompt, _SISTEMA)
    except Exception as exc:  # noqa: BLE001 — provedor fora do ar não é erro de hermenêutica
        return {"esperado": caso["rotulo"], "previsto": "indisponivel", "ancorada": False,
                "erro": str(exc)[:120], "conduta": conduta}
    j = parse_json_llm(bruto) or {}
    classe = str(j.get("classe") or "").strip().lower()
    citacao = str(j.get("citacao") or "")
    ancorada = _ancorada(citacao, conduta)
    if classe not in ROTULOS_VALIDOS:
        previsto = "nao_sei" if classe in {"nao_sei", "nao sei", ""} else "invalido"
    elif not ancorada:
        # Rótulo certo com citação inventada não é acerto: é sorte com aparência de prova.
        previsto = "citacao_nao_ancorada"
    else:
        previsto = classe
    return {"esperado": caso["rotulo"], "previsto": previsto, "ancorada": ancorada,
            "classe_bruta": classe, "citacao": citacao[:200], "conduta": conduta,
            "vicio": caso["vicio"], "id": caso["id"], "condicionada": caso.get("condicionada")}


def avaliar(casos: list[dict], gerar: Callable, *, limite: int | None = None) -> dict[str, Any]:
    """Roda o conjunto e devolve as métricas completas, incluindo o baseline burro."""
    alvo = casos[:limite] if limite else casos
    detalhes = [avaliar_caso(c, gerar) for c in alvo]
    pares = [(d["esperado"], d["previsto"]) for d in detalhes]
    m = metricas(pares)
    n = len(detalhes) or 1
    m["alucinacao_citacao"] = sum(1 for d in detalhes
                                  if d["previsto"] == "citacao_nao_ancorada") / n
    m["indisponivel"] = sum(1 for d in detalhes if d["previsto"] == "indisponivel") / n
    m["invalido"] = sum(1 for d in detalhes if d["previsto"] == "invalido") / n
    m["baseline_burro"] = baseline_classe_majoritaria(alvo)
    m["bate_o_baseline"] = m["f1_macro"] > m["baseline_burro"].get("f1_macro", 0.0)
    m["prompt_versao"] = PROMPT_VERSAO
    m["condicionados"] = sum(1 for d in detalhes if d.get("condicionada")) / n
    m["detalhes"] = detalhes
    return m


def por_vicio(resultado: dict) -> dict[str, dict]:
    """F1 por vício do catálogo — média geral esconde a família que o motor não entende."""
    grupos: dict[str, list] = {}
    for d in resultado["detalhes"]:
        grupos.setdefault(d.get("vicio") or "?", []).append((d["esperado"], d["previsto"]))
    return {v: metricas(p) for v, p in sorted(grupos.items(), key=lambda kv: -len(kv[1]))}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Avaliação da hermenêutica contra o conjunto-ouro")
    grupo = ap.add_mutually_exclusive_group()
    grupo.add_argument("--holdout", action="store_true", help="parte SELADA (medição final)")
    grupo.add_argument("--treino", action="store_true", help="parte de calibração")
    ap.add_argument("--limite", type=int, default=100)
    ap.add_argument("--por-vicio", action="store_true")
    ap.add_argument("--saida", help="grava o JSON completo aqui")
    a = ap.parse_args(argv)

    casos = carregar()
    if not casos:
        print("acervo TCU não indexado — rode `python -m compliance_agent.knowledge."
              "tcu_juris_index indexar`")
        return 1
    s = split(casos)
    alvo = s["holdout"] if a.holdout else s["treino"]

    from compliance_agent.direcionamento_cerebro import gerar_sync

    r = avaliar(alvo, gerar_sync, limite=a.limite)
    resumo = {k: v for k, v in r.items() if k != "detalhes"}
    print(json.dumps(resumo, ensure_ascii=False, indent=2, default=str))
    if a.por_vicio:
        pv = {v: {"n": m["n"], "f1_macro": round(m["f1_macro"], 3)}
              for v, m in por_vicio(r).items()}
        print("\npor vício:", json.dumps(pv, ensure_ascii=False, indent=2))
    if a.saida:
        with open(a.saida, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\ndetalhes → {a.saida}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
