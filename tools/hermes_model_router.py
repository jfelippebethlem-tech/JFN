# -*- coding: utf-8 -*-
"""
hermes_model_router — roteamento ADAPTATIVO de modelo do Hermes/Yoda (JFN 2.0, Onda 1).
Decisão do dono (2026-06-08): **heurística simples**, default 100%-free = **gemini-2.5-flash**;
casos difíceis escalam p/ modelo mais forte. Tudo gratuito (gemini free-tier / mistral free-tier).

Como integrar no gateway (overlay idempotente — `hermes update` sobrescreve o core):
    from tools.hermes_model_router import escolher_modelo   # (ajustar sys.path p/ ~/JFN)
    prov, modelo = escolher_modelo(texto_da_mensagem, tem_anexo_pdf_ou_imagem=bool(media))
    # aplicar antes da chamada ao modelo (ponto: gateway/run.py:13078 onde _tools/model são montados;
    # setar agent.model/provider = modelo/prov para ESTE request, default caso contrário).
Mantém o fallback failure-based do config.yaml intacto (gemini→mistral→nous).

Filosofia: NÃO gastar modelo caro em chat trivial; escalar só quando o caso pede raciocínio jurídico/
analítico pesado ou leitura de documento. Conservador: na dúvida, fica no free default.
"""
from __future__ import annotations

import re

# default 100% free (free-tier do Google; decisão do dono)
DEFAULT = ("gemini", "gemini-2.5-flash")
# raciocínio pesado (jurídico/auditoria/análise longa) — ainda gratuito (free-tier)
PESADO = ("gemini", "gemini-2.5-pro")
# reforço se o pesado falhar (failure-fallback já cobre, mas explicitamos a intenção)
PESADO_FALLBACK = ("mistral", "mistral-large-latest")
# BULK: tarefas LLM PESADAS NO VOLUME mas SIMPLES/REPETITIVAS (extração SEI em massa, classificação de
# notícias em lote, normalização) → nous 100% FREE, sem cota (decisão do dono 2026-06-08). Qualidade
# suficiente p/ trabalho repetitivo; não queima a cota free-tier do gemini.
# NOTA: NÃO se aplica ao sweep SIAFE/coletores (código determinístico, SEM LLM) nem a OCR/visão (easyocr/gemini).
BULK = ("nous", "stepfun/step-3.7-flash:free")

# gatilhos de "caso difícil" → escalar p/ PESADO
_GATILHOS = re.compile(
    r"\b(parecer|jur[ií]dic[oa]|edital|licita[çc][aã]o|contrat[oa]|representa[çc][aã]o|requerimento|"
    r"d[oó]ssi[eê]|fraude|sobrepre[çc]o|c[aá]rtel|conluio|conflito|direcionamento|superfaturamento|"
    r"investig|audit|an[aá]lise jur|tomada de contas|improbidade|14\.?133|8\.?666|acord[aã]o|tce|tcu)\b",
    re.IGNORECASE,
)
# pedidos longos/complexos também sobem
_LIMIAR_LONGO = 600  # chars


def escolher_modelo(texto: str, tem_anexo_pdf_ou_imagem: bool = False,
                    forcar_pesado: bool = False, tarefa: str = "") -> tuple[str, str]:
    """Retorna (provider, model).
    - tarefa in {bulk, repetitivo, lote}: nous (100% free) — trabalho LLM de volume alto e simples.
    - default free (gemini-2.5-flash); escala p/ PESADO (gemini-2.5-pro) em caso difícil.
    Anexo PDF/imagem fica no default (gemini-2.5-flash é multimodal — spec: visao_ocr=flash)."""
    if (tarefa or "").lower() in {"bulk", "repetitivo", "lote", "massa"}:
        return BULK
    t = texto or ""
    if forcar_pesado or _GATILHOS.search(t) or len(t) >= _LIMIAR_LONGO:
        return PESADO
    return DEFAULT


def explicar(texto: str, tem_anexo_pdf_ou_imagem: bool = False) -> dict:
    """Versão verbosa p/ debug/observabilidade: retorna o modelo + o motivo da escolha."""
    t = texto or ""
    m = _GATILHOS.search(t)
    if m:
        motivo = f"gatilho:'{m.group(0)}'"
        prov, mod = PESADO
    elif len(t) >= _LIMIAR_LONGO:
        motivo = f"mensagem longa ({len(t)}>={_LIMIAR_LONGO})"
        prov, mod = PESADO
    else:
        motivo = "default (chat trivial)"
        prov, mod = DEFAULT
    return {"provider": prov, "model": mod, "motivo": motivo}


if __name__ == "__main__":
    import sys
    txt = " ".join(sys.argv[1:]) or "oi, tudo bem?"
    import json
    print(json.dumps(explicar(txt), ensure_ascii=False))
