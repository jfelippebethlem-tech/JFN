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


def _dossie_txt(d: dict) -> str:
    c = d.get("clausula", {})
    irmaos = d.get("irmaos_sem_clausula") or []
    return (
        f"OBJETO: {d.get('objeto', '')}\n"
        f"CLÁUSULA EM ANÁLISE (subtipo {c.get('subtipo')}): {c.get('texto', '')}\n"
        f"RARIDADE NO GRUPO: {c.get('raridade')} (fração dos editais de MESMO objeto que NÃO a exigem)\n"
        f"SÚMULA/DISPOSITIVO: {c.get('sumula') or 'n/d'}\n"
        f"EDITAIS IRMÃOS que NÃO exigem isso (amostra): {' | '.join(irmaos[:3]) or 'n/d'}\n"
        f"VENCEDOR: {d.get('vencedor_doc') or 'n/d'} | SINAIS: {', '.join(d.get('sinais_beneficiario') or []) or 'nenhum'}")


def _lente(pergunta: str):
    def fn(dossie: dict, gerar=None) -> dict:
        g = gerar or gerar_sync
        prompt = f"{_dossie_txt(dossie)}\n\nAVALIE: {pergunta}"
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


lente_proporcionalidade = _lente(
    "A exigência é PERTINENTE e PROPORCIONAL ao objeto (teste finalístico, art. 37/67)? "
    "Se for praxe defensável do setor, voto baixo; se restringe sem necessidade técnica, voto alto.")

lente_jurisprudencia = _lente(
    "A exigência casa com o padrão vedado pela súmula/dispositivo citado? "
    "Voto alto se a cláusula reproduz a restrição que a jurisprudência condena.")

lente_competicao = _lente(
    "Quantos fornecedores essa exigência tende a EXCLUIR para este objeto? "
    "Considere que os editais irmãos do mesmo objeto NÃO a fazem. Mais exclusão → voto mais alto.")

lente_refutador = _lente(
    "TENTE DERRUBAR a hipótese de direcionamento: existe justificativa técnica LEGÍTIMA "
    "para esta exigência neste objeto? Seja cético contra a acusação. "
    "Só vote ALTO se, mesmo tentando, você NÃO achar justificativa legítima.")

lente_beneficiario = _lente(
    "O vencedor e os SINAIS listados (favorecido de emenda, doador, fantasma, rede societária) "
    "reforçam que a cláusula rara beneficiou um alvo específico? Sem sinais, voto baixo.")
