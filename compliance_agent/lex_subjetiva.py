# -*- coding: utf-8 -*-
"""Lex — CAMADA SUBJETIVA do parecer: o juízo raciocinado, separado da camada determinística.

Regra do dono (20/11/2026): o parecer tem duas camadas que não se misturam. A DETERMINÍSTICA é o que o código
prova contra a fonte primária (com proveniência e estado). A SUBJETIVA é a opinião do Claude Opus pela
ASSINATURA (`claude_motor.pensar(..., backend="cli")`) — nunca a cascata barata, nunca a API paga. Ela:
  · recebe SÓ o quadro de fatos e os indícios já provados (não consulta nada e não cria número);
  · sai marcada como OPINIÃO, com a explicação inocente e o grau de confiança;
  · nunca altera fato da camada determinística nem o grau — no máximo recomenda diligência.
Motor indisponível (sem cota, teto, sob pytest, desligado) → a camada sai declarada INDISPONÍVEL com o motivo,
sem texto inventado. `JFN_LEX_SUBJETIVA=0` desliga (o snapshot desliga); `JFN_VEREDITO_LLM_DISABLED=1` também, salvo
`JFN_LEX_SUBJETIVA=1` explícito (liga só o Opus da assinatura, mantendo desligada a cascata barata).
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

TAREFA = "parecer_juridico"   # teto diário próprio em llm/orcamento.TETOS_TAREFA
_CONFIANCAS = ("baixa", "média", "alta")

_SISTEMA = (
    "Você é um auditor sênior de controle externo (TCE-RJ), com formação em Direito Administrativo, contabilidade "
    "pública e compliance. Recebe um quadro de FATOS já verificados por código contra o SIAFE e outras fontes "
    "primárias, e a lista de INDÍCIOS já disparados. Sua tarefa é dar uma OPINIÃO profissional fundamentada, "
    "em português do Brasil, sem inventar fato, número, processo, norma ou jurisprudência que não esteja no "
    "material. Indício não é acusação; vigora a presunção de legitimidade; a dúvida sobre a economicidade "
    "favorece o gestor. Você NÃO altera fatos nem o grau: pode, no máximo, recomendar diligências.")

_SCHEMA = {
    "juizo": "2 a 4 parágrafos: leitura de conjunto dos fatos e indícios — o que pesa, o que não pesa e por quê",
    "explicacao_inocente": "a explicação inocente mais plausível para o conjunto",
    "confianca": "baixa | média | alta — confiança na leitura, dada a cobertura dos dados",
    "diligencias": ["até 5 diligências concretas (documento + processo/órgão) que confirmariam ou afastariam"],
}


def desligada() -> str:
    """Motivo pelo qual a camada não roda nesta execução ('' = pode rodar)."""
    flag = os.environ.get("JFN_LEX_SUBJETIVA", "")
    if flag == "0":
        return "camada subjetiva desligada nesta execução (JFN_LEX_SUBJETIVA=0)"
    if flag != "1" and os.environ.get("JFN_VEREDITO_LLM_DISABLED") == "1":   # =1 explícito liga só o Opus
        return "motores de IA desligados nesta execução (JFN_VEREDITO_LLM_DISABLED=1)"
    return ""


def _prompt(alvo: str, fatos: list[dict], achados: list[dict], lacunas: list[str]) -> str:
    L = [f"ALVO: {alvo}", "", "QUADRO DE FATOS (camada determinística — não contestar o número, só interpretar):"]
    for f in fatos:
        L.append(f"- {f['fato']}: {f['valor']} [fonte: {f['fonte']}; estado: {f['estado']}]")
    L += ["", "INDÍCIOS DISPARADOS (código + gravidade 1-5 + observação):"]
    if achados:
        for a in achados:
            obs = re.sub(r"\*\*", "", str(a.get("obs") or ""))[:1500]
            L.append(f"- {a.get('rf')} (grav. {a.get('grav')}): {obs}")
    else:
        L.append("- nenhum indício disparou")
    L += ["", "LACUNAS DECLARADAS (o que NÃO foi verificado):"]
    L += [f"- {x}" for x in lacunas] or ["- nenhuma"]
    return "\n".join(L)


def avaliar(alvo: str, fatos: list[dict], achados: list[dict], lacunas: list[str], *, pensar=None) -> dict:
    """{estado, motivo, juizo, explicacao_inocente, confianca, diligencias, modelo}. `pensar` injetável (teste)."""
    m = desligada()
    if m and pensar is None:
        return {"estado": "INDISPONÍVEL", "motivo": m}
    try:
        from compliance_agent.llm import claude_motor
        from compliance_agent.llm.json_resposta import parse_json_llm
        _p = pensar or claude_motor.pensar
        r = _p(TAREFA, _prompt(alvo, fatos, achados, lacunas), schema=_SCHEMA, modelo=claude_motor.MODELO_JUIZO,
               sistema=_SISTEMA, backend="cli", timeout=240.0)
    except Exception as exc:  # noqa: BLE001 — a camada degrada declarada; a determinística segue intacta
        logger.warning("camada subjetiva do Lex falhou: %s", exc)
        return {"estado": "INDISPONÍVEL", "motivo": f"motor falhou ({str(exc)[:100]})"}
    if r is None:
        motivo = ""
        try:
            from compliance_agent.llm import claude_motor
            motivo = claude_motor.ultimo_motivo or ""
        except Exception:  # noqa: BLE001
            pass
        return {"estado": "INDISPONÍVEL", "motivo": f"Opus pela assinatura indisponível ({motivo or 'sem resposta'})"}
    modelo = str(getattr(r, "modelo", "") or "")
    if "@api" in modelo or "opus" not in modelo.lower():
        # salvaguarda: só o Opus da assinatura assina a camada subjetiva (nunca API paga, nunca modelo barato)
        return {"estado": "INDISPONÍVEL", "motivo": f"resposta veio de motor fora da régua ({modelo or 'desconhecido'})"}
    d = getattr(r, "dados", None) or parse_json_llm(getattr(r, "texto", "")) or {}
    if not isinstance(d, dict) or not str(d.get("juizo") or "").strip():
        return {"estado": "INDISPONÍVEL", "motivo": "resposta do Opus sem o JSON pedido"}
    conf = str(d.get("confianca") or "").strip().lower().replace("media", "média")
    dil = d.get("diligencias") or []
    return {"estado": "OPINIÃO", "motivo": "", "modelo": modelo,
            "juizo": str(d.get("juizo")).strip(), "explicacao_inocente": str(d.get("explicacao_inocente") or "").strip(),
            "confianca": conf if conf in _CONFIANCAS else "não declarada",
            "diligencias": [str(x).strip() for x in dil if str(x).strip()][:5] if isinstance(dil, list) else []}
