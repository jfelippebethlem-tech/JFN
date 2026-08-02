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
    # Hash da FONTE do prompt, não só a versão declarada: versão é o que alguém lembrou de subir.
    from compliance_agent.nucleo.prompt_versao import impressao, REGISTRO
    m["prompt_hash"] = impressao(REGISTRO["hermeneutica"]["alvo"])
    m["condicionados"] = sum(1 for d in detalhes if d.get("condicionada")) / n
    m["detalhes"] = detalhes
    return m


# ── catraca de qualidade ──────────────────────────────────────────────────────────────────────
# Uma medição que não vira trava não impede regressão: o número aparece no relatório, ninguém
# compara com o anterior, e a qualidade cai sem que nada acuse. A catraca é um ARQUIVO com o
# resultado aceito e uma comparação explícita contra ele.
#
# Por que isto NÃO é teste unitário: a medição exige chamar o modelo, e teste desta casa não toca
# a rede. A trava roda como job (off-hours) e o teste unitário cobre a lógica de comparação — que
# é onde mora o erro silencioso (tolerância frouxa demais, métrica errada, direção invertida).
BASELINE_PADRAO = "data/hermeneutica_baseline.json"
# O card de acurácia do painel (`reporting/painel_acuracia`) lê a ÚLTIMA medição daqui — e até
# 2026-08-02 ninguém escrevia este arquivo. O card dizia "ainda não medido neste ambiente — rode
# eval_hermeneutica --holdout --aceitar" e o `--aceitar` só gravava o baseline: o comando sugerido
# jamais apagaria a própria mensagem. Baseline é o PISO da catraca; última é O QUE SE MEDIU AGORA.
ULTIMA_PADRAO = "data/hermeneutica_ultima.json"

# Tolerância: variação de amostragem do modelo é real, e travar no valor exato produziria alarme
# a cada rodada. 3 pontos de F1 macro é folga suficiente para ruído e apertada o bastante para
# pegar regressão de prompt.
TOLERANCIA_F1 = 0.03
# Alucinação de citação NÃO tem tolerância para cima: é o invariante mais duro da casa.
TOLERANCIA_ALUCINACAO = 0.0


def comparar_com_baseline(atual: dict, baseline: dict | None,
                          *, tolerancia_f1: float = TOLERANCIA_F1) -> dict[str, Any]:
    """Compara uma medição com o resultado aceito. `{ok, regressoes, melhorias, motivo}`.

    Três regras, e a ordem delas importa:
      1. sem baseline, NÃO reprova — a primeira medição é a que cria a linha de base;
      2. F1 macro abaixo do aceito além da tolerância é REGRESSÃO;
      3. alucinação de citação acima do aceito é regressão SEM tolerância — um motor que passa a
         inventar citação piorou, ainda que o F1 tenha subido.
    """
    if not baseline:
        return {"ok": True, "primeira_medicao": True, "regressoes": [], "melhorias": [],
                "motivo": "sem baseline — esta medição passa a ser a linha de base"}

    regressoes: list[str] = []
    melhorias: list[str] = []

    f1_a, f1_b = float(atual.get("f1_macro") or 0), float(baseline.get("f1_macro") or 0)
    if f1_a < f1_b - tolerancia_f1:
        regressoes.append(f"F1 macro caiu de {f1_b:.3f} para {f1_a:.3f} "
                          f"(tolerância {tolerancia_f1:.2f})")
    elif f1_a > f1_b + tolerancia_f1:
        melhorias.append(f"F1 macro subiu de {f1_b:.3f} para {f1_a:.3f}")

    al_a = float(atual.get("alucinacao_citacao") or 0)
    al_b = float(baseline.get("alucinacao_citacao") or 0)
    if al_a > al_b + TOLERANCIA_ALUCINACAO:
        regressoes.append(f"alucinação de citação subiu de {al_b:.1%} para {al_a:.1%} — "
                          f"invariante sem tolerância")
    elif al_a < al_b:
        melhorias.append(f"alucinação de citação caiu de {al_b:.1%} para {al_a:.1%}")

    if not atual.get("bate_o_baseline", True):
        regressoes.append("o motor deixou de bater o baseline da classe majoritária — um "
                          "papagaio que responde sempre a classe mais comum teria F1 macro igual "
                          "ou melhor")

    for classe, f1 in (atual.get("f1_por_classe") or {}).items():
        anterior = (baseline.get("f1_por_classe") or {}).get(classe)
        if anterior is not None and float(f1) < float(anterior) - tolerancia_f1:
            regressoes.append(f"F1 da classe '{classe}' caiu de {anterior:.3f} para {f1:.3f}")

    return {
        "ok": not regressoes, "primeira_medicao": False,
        "regressoes": regressoes, "melhorias": melhorias,
        "prompt_versao_atual": atual.get("prompt_versao"),
        "prompt_versao_baseline": baseline.get("prompt_versao"),
        "motivo": ("sem regressão" if not regressoes else
                   f"{len(regressoes)} regressão(ões) frente ao baseline aceito"),
    }


def resumo_para_baseline(resultado: dict) -> dict[str, Any]:
    """O que se guarda como linha de base — nunca os `detalhes`, que carregam o holdout."""
    return {k: resultado.get(k) for k in
            ("n", "acuracia", "f1_macro", "f1_por_classe", "abstencao", "alucinacao_citacao",
             "indisponivel", "invalido", "bate_o_baseline", "prompt_versao", "prompt_hash")}


def gravar_ultima(resumo: dict, caminho: str = ULTIMA_PADRAO) -> str:
    """Publica a medição recém-feita para o card do painel, com carimbo de QUANDO.

    Sem a data, um número de três meses atrás apareceria como se fosse de hoje — que é o defeito
    que o próprio `painel_acuracia` diz ser pior que o card vazio.
    """
    import datetime
    import os
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    # A chave é `medido_em` porque é a que o card lê (`painel_acuracia.montar`). Gravar com outro
    # nome deixaria o número aparecer sem data — o card explicitamente chama isso de pior que vazio.
    payload = {**resumo, "medido_em": datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="seconds")}
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    return caminho


def carregar_baseline(caminho: str = BASELINE_PADRAO) -> dict | None:
    import os
    if not os.path.exists(caminho):
        return None
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


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
    ap.add_argument("--catraca", action="store_true",
                    help="compara com data/hermeneutica_baseline.json e falha (exit 1) em regressão")
    ap.add_argument("--aceitar", action="store_true",
                    help="grava a medição atual como novo baseline aceito")
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
    # Toda medição publica — não só a que vira baseline. Métrica que fica no log não disciplina
    # ninguém, e era exatamente o que acontecia: o card nunca saía de "sem medição".
    print(f"\núltima medição → {gravar_ultima(resumo)}")
    if a.por_vicio:
        pv = {v: {"n": m["n"], "f1_macro": round(m["f1_macro"], 3)}
              for v, m in por_vicio(r).items()}
        print("\npor vício:", json.dumps(pv, ensure_ascii=False, indent=2))
    if a.saida:
        with open(a.saida, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\ndetalhes → {a.saida}")

    if a.aceitar:
        import os
        os.makedirs(os.path.dirname(BASELINE_PADRAO) or ".", exist_ok=True)
        with open(BASELINE_PADRAO, "w", encoding="utf-8") as fh:
            json.dump(resumo_para_baseline(r), fh, ensure_ascii=False, indent=2)
        print(f"\nbaseline aceito gravado → {BASELINE_PADRAO}")

    if a.catraca:
        cmp = comparar_com_baseline(r, carregar_baseline())
        print("\ncatraca:", json.dumps(cmp, ensure_ascii=False, indent=2))
        if not cmp["ok"]:
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
