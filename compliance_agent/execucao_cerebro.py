# -*- coding: utf-8 -*-
"""Cérebro de EXECUÇÃO — o atesto FAZ SENTIDO? (plano #4, itens 1.1 e 1.5 · dono 2026-07-24)

O `execucao_sinais` (determinístico) responde se o atesto EXISTE. Não basta: o dono foi explícito — "o
atesto não basta existir, precisa fazer sentido". Um atesto pode ser carimbo: genérico ("de acordo"),
DATADO ANTES do período medido, com quantidade divergente da medição, ou descolado do objeto contratado.
Isso é juízo interpretativo — camada SUBJETIVA (LLM), fundida com a objetiva por `fundir_graus`.

Ciclo fechado (1.5): `avaliar_execucao` = determinístico + LLM → fusão (nenhum alarme silenciado) →
`_versao_hash` da captura → `guardar_snapshot_execucao` (snapshot imutável e versionado em
`analise_remotes`, igual ao direcionamento: mesma captura não re-sobe; processo mudou, nova versão).

HONESTIDADE: sem atesto → 'nao_aplicavel' (não se afirma coerência do que não existe); com atesto e SEM
medição → 'pendente_captura' dizendo o que buscar (a medição é a régua da coerência); LLM fora do ar ou
resposta inválida → 'pendente_reprocessar' (NUNCA 'verde' por omissão — a análise interpretativa não
rodou). Veredito sempre RESOLVIDO. `gerar=None` ⇒ só a camada determinística (offline, sem rede).
"""
from __future__ import annotations

import logging

from compliance_agent import execucao_sinais as ES
from compliance_agent.direcionamento_cerebro import _com_fusao, _parse_json

logger = logging.getLogger(__name__)

_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ) avaliando se o ATESTO/termo de recebimento de um processo "
    "de pagamento FAZ SENTIDO — isto é, se é COERENTE com o boletim de medição e com o objeto contratado. "
    "Regras ABSOLUTAS: (1) indício ≠ acusação (presunção de legitimidade). (2) CADA incoerência DEVE citar o "
    "TRECHO literal que a sustenta; sem trecho, não afirme. (3) Se os documentos não permitem concluir, diga "
    "dados_suficientes=false — NUNCA invente. Procure: atesto GENÉRICO (só 'de acordo'/'a contento', sem "
    "dizer o que foi recebido); DATA do atesto anterior ao período/data da medição (atestou antes de medir); "
    "QUANTIDADE/valor divergente entre atesto, medição e objeto; atesto que descreve objeto DIFERENTE do "
    "contratado; medição que não fecha com o percentual/valor pago. Coerente e específico ⇒ grau verde."
)
_SCHEMA = (
    '{"grau":"verde|amarelo|vermelho","coerente":true,'
    '"incoerencias":[{"tipo":"data|quantidade|generico|objeto|valor","trecho":"literal","por_que":""}],'
    '"resumo":"1-2 frases (indício, não acusação)","dados_suficientes":true}'
)
_JANELA = 350      # contexto ao redor de cada peça (atesto/medição) levado ao prompt
_MAX_PECA = 1200


def extrair_pecas(texto: str) -> dict:
    """Recorta do processo as 3 peças que a coerência exige: ATESTO, MEDIÇÃO e (quando presente) o objeto.
    Determinístico — reusa os marcadores do `execucao_sinais` (fonte única, sem duplicar vocabulário)."""
    txt = texto or ""
    low = ES._norm(txt)
    atesto = ES._primeiro_trecho(txt, low, ES._PROVAS["atesto"], janela=_JANELA, limite=_MAX_PECA)
    medicao = ES._primeiro_trecho(txt, low, ES._PROVAS["medicao"], janela=_JANELA, limite=_MAX_PECA)
    foto = ES._primeiro_trecho(txt, low, ES._PROVAS["relatorio_fotografico"], janela=200, limite=400)
    return {"atesto": atesto, "medicao": medicao, "relatorio_fotografico": foto,
            "tem_atesto": bool(atesto), "tem_medicao": bool(medicao)}


def _montar_user(pecas: dict, objeto: str) -> str:
    return "\n".join([
        f"OBJETO CONTRATADO: {objeto or '(não informado — avalie o que for possível sem ele)'}",
        f"\nBOLETIM DE MEDIÇÃO (trecho literal):\n{pecas['medicao']}",
        f"\nATESTO / TERMO DE RECEBIMENTO (trecho literal):\n{pecas['atesto']}",
        (f"\nRELATÓRIO FOTOGRÁFICO (trecho):\n{pecas['relatorio_fotografico']}"
         if pecas.get("relatorio_fotografico") else "\nRELATÓRIO FOTOGRÁFICO: não localizado no texto."),
        f"\nO atesto é coerente com a medição e com o objeto? Responda no schema: {_SCHEMA}",
    ])


def _resolvido(grau: str, resumo: str, acao: str, **extra) -> dict:
    base = {"grau": grau, "coerente": None, "incoerencias": [], "resumo": resumo, "acao": acao,
            "ressalva": "indício a apurar, não acusação; INDISPONÍVEL ≠ irregular; presunção de legitimidade",
            "fonte": "execucao_cerebro (coerência do atesto)"}
    base.update(extra)
    return base


async def avaliar_coerencia_atesto(texto: str = "", *, objeto: str = "", gerar=None,
                                   pecas: dict | None = None) -> dict:
    """O atesto FAZ SENTIDO? (camada subjetiva). `gerar`: callable async(messages)->str — injetável;
    None ⇒ não roda (offline). Veredito sempre resolvido; nunca fabrica coerência."""
    p = pecas or extrair_pecas(texto)
    if not p["tem_atesto"]:
        return _resolvido("nao_aplicavel",
                          "Não há atesto/termo de recebimento no texto lido — não se avalia a coerência de "
                          "um atesto inexistente (a AUSÊNCIA é tratada pela camada determinística).",
                          "", pecas=p)
    if not p["tem_medicao"]:
        return _resolvido("pendente_captura",
                          "Há atesto, mas não há boletim de medição no texto lido — a medição é a RÉGUA da "
                          "coerência (quantidades/período). Sem ela não se afirma nem se nega o sentido do "
                          "atesto: INDISPONÍVEL ≠ irregular.",
                          "buscar o boletim de medição do período no processo (árvore SEI) e reavaliar",
                          pecas=p)
    if gerar is None:
        return _resolvido("pendente_reprocessar",
                          "Camada interpretativa não executada (sem gerador de IA injetado) — a coerência "
                          "atesto × medição × objeto continua PENDENTE; não é 'verde'.",
                          "reprocessar com a IA para o veredito de coerência", pecas=p)
    messages = [{"role": "system", "content": _SYS},
                {"role": "user", "content": _montar_user(p, objeto)}]
    try:
        raw = await gerar(messages)
    except Exception as e:  # noqa: BLE001 — IA fora do ar: honesto, não fabrica veredito
        logger.debug("avaliar_coerencia_atesto: LLM indisponível: %s", e)
        return _resolvido("pendente_reprocessar",
                          f"A IA não pôde avaliar a coerência do atesto agora ({str(e)[:40]}). Ausência de "
                          "parecer interpretativo ≠ regularidade.",
                          "reprocessar com a IA para o veredito de coerência", pecas=p, _llm_erro=str(e)[:80])
    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        return _resolvido("pendente_reprocessar",
                          "A IA respondeu em formato inválido (não-parseável) — coerência do atesto PENDENTE.",
                          "reprocessar com a IA para o veredito de coerência", pecas=p,
                          _llm_erro="resposta não-parseável")
    dados.setdefault("ressalva", "indício a apurar, não acusação; presunção de legitimidade")
    dados.setdefault("acao", "")
    dados["pecas"] = p
    dados["fonte"] = "execucao_cerebro (coerência do atesto)"
    return dados


_ORDEM_NFE = {"verde": 0, "a_verificar": 0, "amarelo": 1, "vermelho": 2}


async def avaliar_execucao(texto: str = "", *, objeto: str = "", gerar=None, consultar_nfe=None,
                           contexto: dict | None = None) -> dict:
    """Veredito FUNDIDO da EXECUÇÃO: determinístico (`execucao_sinais`, inclui §2 OB≠empenho) × subjetivo
    (coerência do atesto) × NF-e (chave de acesso: contingência offline + situação na SEFAZ, quando a
    consulta é injetada). A fusão nunca silencia o alarme objetivo e sinaliza divergência entre camadas.
    Acrescenta `_versao_hash` (assinatura da captura) para o snapshot versionado."""
    from compliance_agent import nfe_verifica
    det = ES.analisar_execucao_det(texto)
    coer = await avaliar_coerencia_atesto(texto, objeto=objeto, gerar=gerar)
    nfe = await nfe_verifica.analisar_nfe(texto, consultar=consultar_nfe)
    # o vício da NOTA é objetivo (vem da chave/SEFAZ, não de juízo): entra pelo lado determinístico.
    # 'a_verificar' NÃO agrava — é falta de verificação, não achado (ausência de prova ≠ prova).
    if _ORDEM_NFE.get(nfe["grau"], 0) > _ORDEM_NFE.get(det.get("grau", "verde"), 0):
        det = {**det, "grau": nfe["grau"],
               "resumo": det.get("resumo", "") + " NF-e: " + nfe["resumo"]}
    from compliance_agent import analise_remotes
    base = {"deterministico": det, "coerencia_atesto": coer, "nfe": nfe, "contexto": contexto or {},
            "resumo": det.get("resumo", ""), "ressalva": det.get("ressalva", ""),
            "a_verificar": det.get("a_verificar", []),
            "_versao_hash": analise_remotes.hash_versao(texto or ""),
            "fonte": "execucao_cerebro (det × subjetivo, fundidos)"}
    if coer.get("resumo"):
        base["resumo"] = f"{base['resumo']} COERÊNCIA DO ATESTO: {coer['resumo']}"
    # só grau CONCLUSIVO do LLM entra na fusão: 'nao_aplicavel'/'pendente_captura'/'pendente_reprocessar'
    # dizem que a camada subjetiva NÃO julgou — não são veredito e não podem rebaixar (nem tingir) o
    # objetivo. O estado real fica preservado em `coerencia_atesto.grau`, para o auditor ver o porquê.
    grau_llm = coer.get("grau") if coer.get("grau") in ("verde", "amarelo", "vermelho") else None
    return _com_fusao(base, grau_llm, det.get("grau"))


def guardar_snapshot_execucao(numero_sei: str, veredito: dict, *, versoes_conhecidas=(),
                              guardar=None, agora: str | None = None) -> str | None:
    """Guarda o SNAPSHOT imutável do veredito de execução SE a captura mudou (delta por hash). Idempotente:
    versão já conhecida → None (não re-sobe). `guardar` injetável (default = analise_remotes). Espelha
    `sei_direcionamento_llm._snapshot_analise` — mesma política, sem duplicar a regra de storage."""
    vh = veredito.get("_versao_hash")
    if not vh:
        return None
    from compliance_agent import analise_remotes
    if not analise_remotes.mudou(vh, versoes_conhecidas):
        return None
    if agora is None:
        from datetime import datetime
        agora = datetime.now().isoformat()
    guardar = guardar or analise_remotes.guardar_analise
    return guardar(numero_sei, veredito, versao_hash=vh, criado_em=agora)
