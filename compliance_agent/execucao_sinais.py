# -*- coding: utf-8 -*-
"""Camada de INTELIGÊNCIA DETERMINÍSTICA de EXECUÇÃO SEM COMPROVAÇÃO — 100% offline (regex/keyword, SEM LLM).

Por quê (#4, dono 2026-07-24): o `lex_execucao` avalia a execução (medição/NF/atesto) mas SÓ via LLM. Quando
a IA cai, o produto fica cego. Este módulo espelha a doutrina do `direcionamento_sinais` e a aplica à
EXECUÇÃO: detecta que há PAGAMENTO (OB/empenho/liquidação) no processo mas FALTAM as provas de entrega
(boletim de medição, nota fiscal, atesto/recebimento) — o sinal clássico de despesa paga sem execução
comprovada nos autos.

Calibração SENSÍVEL (pedido do dono: "rodar sensível e ir filtrando"): dispara na AUSÊNCIA. Mas HONESTO
(cláusula JFN): INDISPONÍVEL ≠ irregular — a ausência de um documento é uma FRAGILIDADE a verificar (pode ser
captura incompleta do processo), NUNCA prova de fraude. Cada achado carrega o TRECHO literal que o sustenta.
Veredito RESOLVIDO (nunca 'indeterminado'/'indisponível').
"""
from __future__ import annotations

import re
import unicodedata


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return _sem_acento((s or "").lower())


# Contexto de PAGAMENTO/DESPESA (é onde a comprovação de execução é exigível).
_PAGAMENTO = (
    "ordem bancaria", "nota de empenho", "empenho", "liquidacao", "ordem de pagamento",
    "pagamento", "valor pago", "nota de liquidacao", "processo de pagamento", "efetuar o pagamento",
    "programacao de desembolso", " ob ", "2024ne", "2025ne", "2026ne",
)

# Provas de ENTREGA/EXECUÇÃO. As 3 ESSENCIAIS gatilham o grau; 'relatorio_fotografico' LASTREIA o atesto
# (dono: o atesto não basta existir — precisa de foto por trás e fazer sentido).
_PROVAS: dict[str, tuple[str, ...]] = {
    "medicao": ("boletim de medicao", "boletim de medi", "medicao", "medido", "planilha de medicao"),
    "nota_fiscal": ("nota fiscal", "nf-e", "nfe", "danfe", "nota fiscal eletronica"),
    "atesto": ("atesto", "atestado de recebimento", "termo de recebimento", "recebimento definitivo",
               "recebimento provisorio", "aceite definitivo", "recebido pelo fiscal", "atestada a"),
    "relatorio_fotografico": ("relatorio fotografico", "registro fotografico", "fotos da execucao",
                              "reportagem fotografica", "documentacao fotografica", "fotografico"),
}
_ESSENCIAIS = ("medicao", "nota_fiscal", "atesto")

_NOME = {"medicao": "boletim de medição", "nota_fiscal": "nota fiscal",
         "atesto": "atesto/termo de recebimento", "relatorio_fotografico": "relatório fotográfico"}

# NF suspeita LEGÍVEL NO TEXTO (a verificação LIVE na SEFAZ pela chave de acesso é a fazer — ver plano).
_NF_CANCELADA = ("nota fiscal cancelada", "nf cancelada", "nf-e cancelada", "cancelamento da nota",
                 "cancelamento de nf", "cancelamento da nf", "nota fiscal foi cancelada", "cancelada a nota")
_NF_CONTINGENCIA = ("contingencia", "emitida em contingencia", "emissao em contingencia", "epec",
                    "scan ", "formulario de seguranca", "dpec")
_ORDEM_SEV = {"verde": 0, "amarelo": 1, "vermelho": 2}


def _primeiro_trecho(texto: str, low: str, marcadores: tuple[str, ...], janela: int = 90, limite: int = 200) -> str:
    """Recorta o trecho VERBATIM ao redor do 1º marcador encontrado (índices da string normalizada, que tem o
    MESMO comprimento da original)."""
    for m in marcadores:
        i = low.find(m)
        if i >= 0:
            a, b = max(0, i - janela), min(len(texto), i + len(m) + janela)
            seg = re.sub(r"\s+", " ", texto[a:b].strip())
            return seg[:limite]
    return ""


def sinais_execucao(texto: str) -> dict:
    """Presença de PAGAMENTO e das PROVAS de entrega no texto. Determinístico.
    Retorna {tem_pagamento, provas_presentes:[...], faltantes:[...], faltam_essenciais:[...], trecho_pagamento}."""
    low = _norm(texto or "")
    tem_pag = any(k in low for k in _PAGAMENTO)
    presentes = [k for k, kws in _PROVAS.items() if any(w in low for w in kws)]
    faltantes = [k for k in _PROVAS if k not in presentes]
    faltam_ess = [k for k in _ESSENCIAIS if k not in presentes]
    return {
        "tem_pagamento": tem_pag,
        "provas_presentes": presentes,
        "faltantes": faltantes,
        "faltam_essenciais": faltam_ess,
        "trecho_pagamento": _primeiro_trecho(texto or "", low, _PAGAMENTO) if tem_pag else "",
    }


def analisar_execucao_det(texto: str) -> dict:
    """Veredito DETERMINÍSTICO e RESOLVIDO de execução sem comprovação.

    Grau (SENSÍVEL): nao_aplicavel (sem contexto de pagamento) · verde (todas as 3 provas essenciais) ·
    amarelo (falta 1-2 essenciais) · vermelho (falta as 3 — pagamento sem NENHUMA prova de entrega).
    HONESTO: cada achado cita o trecho do pagamento; ausência = FRAGILIDADE a verificar (captura incompleta
    ou execução não comprovada), não acusação.
    """
    sig = sinais_execucao(texto)
    if not sig["tem_pagamento"]:
        return {"grau": "nao_aplicavel", "faltantes": [], "sinais": [], "faltam_essenciais": [],
                "resumo": "Não é um processo de pagamento/execução (sem OB/empenho/liquidação) — "
                          "a comprovação de execução não se avalia sobre esta peça.",
                "ressalva": "veredito resolvido: fora do escopo de execução; presunção de legitimidade",
                "a_verificar": [], "fonte": "execucao_sinais (determinístico/offline)"}
    low = _norm(texto or "")
    faltam_ess = sig["faltam_essenciais"]
    presentes = sig["provas_presentes"]
    trecho = sig["trecho_pagamento"]
    sinais: list[dict] = []
    grau = "verde"

    def _bump(novo: str):
        nonlocal grau
        if _ORDEM_SEV[novo] > _ORDEM_SEV[grau]:
            grau = novo

    # 1) provas essenciais ausentes (sensível: dispara na ausência; honesto: fragilidade, não prova)
    for k in faltam_ess:
        sinais.append({"tipo": f"falta_{k}", "trecho": trecho,
                       "observacao": f"Há pagamento, mas não consta {_NOME[k]} no processo lido — fragilidade a verificar."})
    if len(faltam_ess) == 3:
        _bump("vermelho")
    elif faltam_ess:
        _bump("amarelo")

    # 2) atesto SECO — existe atesto mas sem relatório fotográfico por trás (dono: não basta existir)
    atesto_seco = ("atesto" in presentes) and ("relatorio_fotografico" not in presentes)
    if atesto_seco:
        _bump("amarelo")
        sinais.append({"tipo": "atesto_sem_relatorio_fotografico",
                       "trecho": _primeiro_trecho(texto or "", low, _PROVAS["atesto"]) or trecho,
                       "observacao": "Há atesto/recebimento, mas SEM relatório fotográfico lastreando — verificar "
                                     "se não é atesto meramente formal e se FAZ SENTIDO (bate com a medição e o objeto)."})

    # 3) NF cancelada / em contingência LEGÍVEL no texto (a verificação live na SEFAZ é a fazer — ver plano)
    if any(w in low for w in _NF_CANCELADA):
        _bump("vermelho")
        sinais.append({"tipo": "nota_fiscal_cancelada", "trecho": _primeiro_trecho(texto or "", low, _NF_CANCELADA),
                       "observacao": "Menção a NOTA FISCAL CANCELADA lastreando o pagamento — indício grave a verificar."})
    if any(w in low for w in _NF_CONTINGENCIA):
        _bump("amarelo")
        sinais.append({"tipo": "nota_fiscal_contingencia", "trecho": _primeiro_trecho(texto or "", low, _NF_CONTINGENCIA),
                       "observacao": "NF emitida em CONTINGÊNCIA — verificar autorização definitiva na SEFAZ (chave de acesso)."})

    if grau == "verde":
        resumo = ("Pagamento com as provas essenciais de entrega presentes (medição, nota fiscal e atesto com "
                  "relatório fotográfico). Coerência (atesto × medição × objeto) e validade da NF na SEFAZ = "
                  "camada interpretativa/verificação (a fazer).")
    else:
        pend = [_NOME[k] for k in faltam_ess] + (["relatório fotográfico do atesto"] if atesto_seco else [])
        resumo = ("Fragilidade a verificar em pagamento: " + ("; ".join(s["observacao"] for s in sinais[:3]))
                  + " INDISPONÍVEL ≠ irregular (pode ser captura incompleta).")
        if pend:
            resumo += " Pendências: " + ", ".join(pend) + "."
    return {"grau": grau, "faltantes": sig["faltantes"], "faltam_essenciais": faltam_ess,
            "provas_presentes": presentes, "atesto_sem_foto": atesto_seco, "sinais": sinais, "resumo": resumo,
            # o que a camada interpretativa (LLM) e a verificação live precisam checar — dono 2026-07-24
            "a_verificar": ["atesto FAZ SENTIDO? (coerência com medição/objeto)",
                            "NF autorizada/cancelada/contingência na SEFAZ (chave de acesso)",
                            "relatório fotográfico corresponde ao objeto/medição"],
            "ressalva": "INDISPONÍVEL ≠ irregular; ausência de documento é fragilidade a verificar, não prova; "
                        "presunção de legitimidade",
            "fonte": "execucao_sinais (determinístico/offline)"}
