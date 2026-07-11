# -*- coding: utf-8 -*-
"""Agentes-lente do enxame — cada um vota 0-10 numa cláusula-candidata, por um
ângulo distinto. Todos free-tier (direcionamento_cerebro.gerar_sync).

O dossiê que cada lente recebe:
  {clausula:{subtipo,texto,raridade,sumula}, objeto, irmaos_sem_clausula:[trechos],
   vencedor_doc, sinais_beneficiario:[str]}

Saída de cada lente: {"voto": 0-10|None, "justificativa": str, "citacao": str}.
Parse honesto: JSON malformado → voto=None (não conta na síntese; INDISPONÍVEL ≠ 0).
"""
from __future__ import annotations

import json
import re

from compliance_agent.direcionamento_cerebro import gerar_sync

_SISTEMA = ("Você é perito em licitações (Lei 14.133/2021) do controle externo do RJ. "
           "Responda SOMENTE um JSON {\"voto\": inteiro 0-10, \"justificativa\": \"...\", "
           "\"citacao\": \"...\"}. voto alto = forte indício de direcionamento; "
           "indício ≠ acusação; presunção de legitimidade.")


def _parse(resp: str) -> dict:
    m = re.search(r"\{.*\}", resp or "", re.DOTALL)
    if not m:
        return {"voto": None, "justificativa": "sem JSON na resposta", "citacao": ""}
    try:
        j = json.loads(m.group(0))
        v = j.get("voto")
        v = int(v) if v is not None and str(v).strip() != "" else None
        if v is not None:
            v = max(0, min(10, v))
        return {"voto": v, "justificativa": str(j.get("justificativa", ""))[:500],
                "citacao": str(j.get("citacao", ""))[:200]}
    except Exception:
        return {"voto": None, "justificativa": "JSON malformado", "citacao": ""}


def _dossie_txt(d: dict, *, com_sumula: bool = False, com_beneficiario: bool = False) -> str:
    """Dossiê NEUTRO por padrão — não entrega o veredito de raridade pronto (evita
    o LLM ancorar na moldura e votar alto em tudo). Cada lente recebe só o que a
    sua pergunta precisa; a súmula vai só para a lente de jurisprudência, os
    sinais do vencedor só para a lente de beneficiário."""
    c = d.get("clausula", {})
    irmaos = d.get("irmaos_sem_clausula") or []
    n = len(irmaos)
    linhas = [
        f"OBJETO DA LICITAÇÃO: {d.get('objeto', '')}",
        f"EXIGÊNCIA DO EDITAL EM ANÁLISE: {c.get('texto', '')}",
        (f"OBSERVAÇÃO FACTUAL: entre os editais que compram este MESMO objeto, "
         f"{n} deles NÃO fazem esta exigência." if n else
         "OBSERVAÇÃO: não há editais-irmãos comparáveis."),
    ]
    if com_sumula and c.get("sumula"):
        linhas.append(f"JURISPRUDÊNCIA POTENCIALMENTE APLICÁVEL: {c['sumula']} "
                      f"(verifique se a exigência de fato reproduz a restrição vedada).")
    if com_beneficiario:
        linhas.append(f"VENCEDOR: {d.get('vencedor_doc') or 'n/d'} | "
                      f"SINAIS CRUZADOS: {', '.join(d.get('sinais_beneficiario') or []) or 'nenhum'}")
    return "\n".join(linhas)


def _lente(pergunta: str, *, com_sumula: bool = False, com_beneficiario: bool = False):
    def fn(dossie: dict, gerar=None) -> dict:
        g = gerar or gerar_sync
        prompt = (f"{_dossie_txt(dossie, com_sumula=com_sumula, com_beneficiario=com_beneficiario)}"
                  f"\n\nTAREFA: {pergunta}")
        # 2 tentativas: o provedor free-tier às vezes devolve vazio/timeout;
        # só declara indisponível se ambas falharem (INDISPONÍVEL ≠ 0).
        ultimo = ""
        for _ in range(2):
            try:
                r = _parse(g(prompt, _SISTEMA))
                if r.get("voto") is not None:
                    return r
                ultimo = r.get("justificativa", "")
            except Exception as e:
                ultimo = str(e)
        return {"voto": None, "justificativa": f"lente indisponível: {ultimo}", "citacao": ""}
    return fn


# TETOS LEGAIS que uma exigência PODE atingir sem ser irregular (dados às lentes
# que julgam mérito, p/ não marcarem como direcionamento o que a lei permite):
_TETOS_LEGAIS = (
    "REFERÊNCIAS DE LEGALIDADE (uma exigência DENTRO destes limites é LÍCITA, não "
    "direcionamento): capital social ou patrimônio líquido até 10% do valor estimado "
    "(Súmula TCU 275); atestado de capacidade técnica com quantitativo até ~50% do "
    "licitado (praxe aceita); índices contábeis são admitidos SE justificados no processo "
    "(Súmula TCU 289); marca é admitida se seguida de 'ou equivalente/similar' (Súmula 270).")

lente_proporcionalidade = _lente(
    "A exigência é pertinente e proporcional ao objeto? Vote BAIXO (0-3) se é praxe "
    "defensável ou está dentro do limite legal; ALTO (7-10) só se restringe sem "
    "necessidade técnica real para ESTE objeto. " + _TETOS_LEGAIS)

lente_jurisprudencia = _lente(
    "A exigência REPRODUZ a restrição que a jurisprudência veda, ou está dentro do que "
    "ela permite? Vote ALTO só se ultrapassa o limite da súmula; se está no limite ou "
    "abaixo, vote BAIXO. " + _TETOS_LEGAIS, com_sumula=True)

lente_competicao = _lente(
    "Quantos fornecedores esta exigência tende a EXCLUIR para este objeto? Vote pela "
    "magnitude da exclusão INJUSTIFICADA (exigência comum do setor exclui pouco → voto baixo). "
    + _TETOS_LEGAIS)

lente_refutador = _lente(
    "Seu papel é DEFENDER a legalidade da exigência (advogado do edital). Encontre a "
    "justificativa técnica ou legal que a torna legítima para ESTE objeto. Vote BAIXO "
    "(0-3) se você CONSEGUE defendê-la (então NÃO é direcionamento); vote ALTO (8-10) "
    "só se, mesmo se esforçando, não há defesa possível. " + _TETOS_LEGAIS)

lente_beneficiario = _lente(
    "Os SINAIS cruzados do vencedor reforçam que a exigência beneficiou um alvo específico? "
    "Sem sinais concretos, vote BAIXO (0-2) — ausência de sinal não é indício.",
    com_beneficiario=True)
