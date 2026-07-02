#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EXPERIMENTO: como instruir uma IA fraca a periciar como o gabarito determinístico.

Pergunta do dono: "como as IAs fracas podem ser instruídas?" Resposta empírica:
mede-se a IA fraca (groq llama-3.1-8b, o modelo de volume) contra o GABARITO
determinístico (compliance_agent/sei/fases.classificar), num processo REAL já
arquivado, e compara-se um prompt INGÊNUO com um prompt INSTRUÍDO (com as
regras que o gabarito codifica). O ganho de concordância é a lição.

    .venv/bin/python tools/experimento_ia_fraca.py "330020/000762/2021"

Precisa das chaves em ~/.hermes/.env (GROQ_API_KEY). Barato: 2 chamadas de LLM
sobre os títulos dos documentos (não o texto inteiro). Gera relatório em
data/experimento_ia_fraca_<TAG>.md.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent.sei.fases import FASES, classificar


def _canon(fase: str) -> str:
    """Normaliza a fase da IA fraca: sem acento, minúsculo (ela devolve
    'tramitação', 'seleção' — acento é ruído, não desacordo semântico)."""
    t = unicodedata.normalize("NFKD", str(fase or "").strip().lower())
    return "".join(c for c in t if not unicodedata.combining(c))

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "data" / "sei_arquivo"
FASES_VALIDAS = [f for f in FASES if f not in ("indefinida",)]

PROMPT_INGENUO = (
    "Você classifica documentos de processos de contratação pública. "
    "Para cada título, diga a fase: " + ", ".join(FASES_VALIDAS) + ". "
    "Responda SÓ um array JSON [{\"i\":0,\"fase\":\"...\"}, ...]."
)

# o prompt INSTRUÍDO carrega as REGRAS que o gabarito determinístico embute —
# é essa transferência de conhecimento explícito que faz a IA fraca acertar
PROMPT_INSTRUIDO = (
    "Você é perito em contratação pública (Lei 14.133/2021). Classifique cada "
    "título na fase do PROCESSO, não no assunto genérico:\n"
    "- planejamento: ETP, Termo de Referência, Projeto Básico, pesquisa de "
    "preços, cotação, mapa de riscos, DFD (é o ESTUDO, ANTES de licitar).\n"
    "- selecao: edital, aviso, ata de pregão, proposta, habilitação, "
    "homologação, adjudicação, dispensa/inexigibilidade (escolha do fornecedor).\n"
    "- contratacao: termo de contrato, ata de registro de preços, garantia, "
    "ordem de início, designação de fiscal (formalização do contrato).\n"
    "- execucao: boletim de MEDIÇÃO, relatório fotográfico, fiscalização, "
    "diário de obra, atestado/termo de recebimento, termo ADITIVO, "
    "apostilamento, reajuste (o objeto sendo entregue).\n"
    "- despesa: nota de empenho (NE), nota de liquidação (NL), liquidação de "
    "despesa, nota fiscal/DANFE, programação de desembolso (PD), ordem "
    "bancária (OB), autorização de despesa/NAD (o dinheiro saindo).\n"
    "- controle: parecer jurídico, PGE, auditoria, TCE, diligência.\n"
    "- tramitacao: despacho, ofício, memorando, capa, encaminhamento (só "
    "movimenta o processo, sem decidir nada).\n"
    "REGRA DE OURO: 'Termo de Referência' é planejamento (não contratação); "
    "'Termo Aditivo' é execução (não contratação); qualquer 'Liquidação de "
    "Despesa' é despesa. Na dúvida entre assunto e fase processual, escolha a "
    "FASE. Responda SÓ um array JSON [{\"i\":0,\"fase\":\"...\"}, ...]."
)


def _titulos(tag: str) -> list[str]:
    man = ARQUIVO / tag / "manifest.json"
    if not man.exists():
        return []
    m = json.loads(man.read_text(encoding="utf-8"))
    return [d.get("titulo") or "" for d in m["docs"] if d.get("titulo")]


def _classificar_llm(titulos: list[str], system: str) -> dict[int, str]:
    from compliance_agent.llm import free_llm as F
    lista = "\n".join(f"{i}: {t}" for i, t in enumerate(titulos))
    resp = F.groq_chat("Títulos:\n" + lista, system=system, smart=False)
    m = re.search(r"\[.*\]", resp, re.S)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return {}
    out = {}
    for e in arr:
        try:
            out[int(e["i"])] = _canon(e["fase"])
        except Exception:
            continue
    return out


def _concordancia(titulos, gab, llm) -> tuple[float, list[dict]]:
    acertos, erros = 0, []
    for i, t in enumerate(titulos):
        g = gab[i]
        p = llm.get(i, "?")
        if g == "indefinida":          # gabarito não sabe → não conta
            continue
        if p == g:
            acertos += 1
        else:
            erros.append({"titulo": t, "gabarito": g, "ia": p})
    validos = sum(1 for i in range(len(titulos)) if gab[i] != "indefinida")
    return (acertos / validos if validos else 0.0), erros


def main() -> int:
    if len(sys.argv) < 2:
        print('uso: experimento_ia_fraca.py "330020/000762/2021"')
        return 1
    proc = sys.argv[1]
    tag = re.sub(r"[^0-9]", "_", proc)
    titulos = _titulos(tag)
    if not titulos:
        print(f"processo {proc} não arquivado (rode sei_arquivar antes)")
        return 1

    gab = {i: classificar(t)[0] for i, t in enumerate(titulos)}
    ingenuo = _classificar_llm(titulos, PROMPT_INGENUO)
    instruido = _classificar_llm(titulos, PROMPT_INSTRUIDO)
    c0, e0 = _concordancia(titulos, gab, ingenuo)
    c1, e1 = _concordancia(titulos, gab, instruido)

    # catálogo de erros do prompt ingênuo agrupado por confusão fase→fase
    confusao = {}
    for e in e0:
        k = f"{e['ia']} → deveria ser {e['gabarito']}"
        confusao[k] = confusao.get(k, 0) + 1

    linhas = [
        f"# Experimento — instruindo a IA fraca (processo {proc})", "",
        f"- Documentos com fase objetiva (gabarito): "
        f"{sum(1 for g in gab.values() if g != 'indefinida')} de {len(titulos)}",
        f"- **Concordância prompt INGÊNUO:** {c0:.0%}",
        f"- **Concordância prompt INSTRUÍDO:** {c1:.0%}",
        f"- **Ganho pela instrução explícita:** {c1 - c0:+.0%}", "",
        "## Confusões mais comuns do prompt ingênuo", "",
    ]
    for k, n in sorted(confusao.items(), key=lambda x: -x[1]):
        linhas.append(f"- {n}× {k}")
    linhas += ["", "## Lições — como instruir a IA fraca", "",
               "1. **Diga a fase PROCESSUAL, não o assunto.** A IA fraca lê "
               "'Termo de Referência' e pensa 'contrato'; precisa da regra "
               "explícita de que TR é planejamento.",
               "2. **Liste exemplos-âncora por fase** (o prompt instruído faz "
               "isso). Sem âncora, ela chuta pelo substantivo mais saliente.",
               "3. **Dê a regra de ouro dos casos-armadilha** (TR≠contrato, "
               "Aditivo=execução, Liquidação=despesa).",
               "4. **Force saída estruturada E normalize** (JSON; tire acento/"
               "caixa): a IA fraca devolve 'tramitação'/'seleção' — sem "
               "normalizar, vira falso desacordo em volume.",
               "5. **Quando o gabarito é determinístico, use-o direto** "
               "(compliance_agent/sei/fases.py); a IA fraca só entra onde não "
               "há regra objetiva. É mais barato e não regride."]

    saida = RAIZ / "data" / f"experimento_ia_fraca_{tag}.md"
    saida.write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))
    print(f"\n[relatório salvo em {saida}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
