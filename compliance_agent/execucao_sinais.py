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

# ESTÁGIO da despesa (§2 REGRA ABSOLUTA: Empenho ≠ Liquidação ≠ OB — só a Ordem Bancária é "pago").
# Empenho = compromisso (pode ser cancelado); liquidação = dívida reconhecida; OB = dinheiro que SAIU.
_OB = ("ordem bancaria", " ob ", "(ob)", "ordem bancária")
_EMPENHO = ("nota de empenho", "empenho", "empenhado", "empenhada")
_LIQUIDACAO = ("nota de liquidacao", "liquidacao", "liquidado", "liquidada")
# códigos do SIAFE: 2025OB800123 / 2024NE000123 / 2025NL000777
_RE_OB = re.compile(r"\b20\d{2}ob\d+")
_RE_NE = re.compile(r"\b20\d{2}ne\d+")
_RE_NL = re.compile(r"\b20\d{2}nl\d+")

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

# ABREVIAÇÕES que só aparecem em TÍTULO de documento da árvore ("Anexo NF 16787 - VENDA", "BM 07",
# "TRD - Termo de Recebimento"). No corpo do texto seriam ambíguas demais; no título, são o nome da peça.
_PROVAS_TITULO: dict[str, str] = {
    "nota_fiscal": r"\bnf-?e?\b|\bnfs-?e\b|\bdanfe\b|\bnota\s*fisc",
    "medicao": r"\bbm\s*\d|\bb\.?m\.?\s*n|\bmedi[çc]",
    "atesto": r"\btrd\b|\btrp\b|\batest|\brecebimento\s+(?:definitivo|provis)",
}

_NOME = {"medicao": "boletim de medição", "nota_fiscal": "nota fiscal",
         "atesto": "atesto/termo de recebimento", "relatorio_fotografico": "relatório fotográfico"}

# NF suspeita LEGÍVEL NO TEXTO (a verificação LIVE na SEFAZ pela chave de acesso é a fazer — ver plano).
# ATENÇÃO ao que se cancela: NOTA FISCAL é documento do FORNECEDOR (vício grave se lastreia pagamento);
# NOTA DE LIQUIDAÇÃO e NOTA DE EMPENHO são documentos ORÇAMENTÁRIOS do próprio Estado, e cancelá-los é
# rotina do SIAFE (reemissão, correção de classificação). Falso positivo medido no acervo real
# (080001/006770/2024): "após cancelamento da Nota de Liquidação" era acusado como nota fiscal cancelada.
# regex (não substring): no texto real vem "nota fiscal nº 555 foi cancelada" — número no meio. A janela
# de até 40 chars liga os dois termos sem atravessar a frase inteira.
_RE_NF_CANCELADA = re.compile(
    r"(nota\s+fiscal|nf-?e|danfe)[^.;]{0,40}\bcancelad|cancelamento\s+d[ae]\s+(nota\s+fiscal|nf-?e|danfe)",
    re.I)
_NF_CONTINGENCIA = ("contingencia", "emitida em contingencia", "emissao em contingencia", "epec",
                    "scan ", "formulario de seguranca", "dpec")
_ORDEM_SEV = {"verde": 0, "amarelo": 1, "vermelho": 2}

# ── TRANSFERÊNCIA ≠ CONTRATAÇÃO (erro conceitual corrigido em 2026-07-24, achado no acervo) ──
# Repasse fundo a fundo (Fundo Estadual de Saúde → Fundo Municipal), convênio, termo de cooperação e
# transferência a organismo internacional NÃO têm nota fiscal, boletim de medição nem atesto de
# recebimento: a comprovação é a PRESTAÇÃO DE CONTAS (RDQA/RAG — art. 16 do Decreto estadual 48.300/2022;
# Lei 8.080/1990 para o SUS). Cobrar NF de repasse do SUS é erro de direito financeiro, e transformaria
# transferência regular em "pagamento sem comprovação". Dos 30 achados brutos, boa parte era isto.
_TRANSFERENCIA = (
    # abreviações reais do favorecido no SIAFE: "Fundo Munic.de Saude", "FMS de ...", "Fdo Mun Saude"
    "fundo a fundo", "fundo municipal", "fundo munic", "fundo mun ", "fdo mun", "fms de ", "fes de ",
    "fundo estadual de saude", "fundo nacional de saude", "repasse ao municipio", "prefeitura municipal",
    "transferencia voluntaria", "transferencia obrigatoria", "termo de cooperacao", "convenio",
    "deliberacao cib", "organizacao pan-americana", "organismo internacional", "consorcio publico",
    "auxilio financeiro", "subvencao", "termo de fomento", "termo de colaboracao",
    # ÓRGÃO PÚBLICO como favorecido = tributo, encargo ou repasse entre entes — não há o que "entregar"
    "ministerio", "secretaria de estado", "secretaria municipal", "receita federal", "tesouro",
    "instituto nacional de seguro social", "inss", "procuradoria", "tribunal de", "camara municipal",
    "universidade estadual", "universidade federal", "autarquia", "banco do brasil", "caixa economica",
)


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


def estagio_despesa(texto: str) -> dict:
    """Em que ESTÁGIO a despesa está no texto (§2). Retorna {tem_ob, tem_liquidacao, tem_empenho, estagio}.
    `estagio`: 'ob' (pagou de verdade) > 'liquidacao' > 'empenho' > 'generico' (fala em pagamento sem
    identificar o estágio) > 'nenhum'. HONESTO: é o que o TEXTO mostra — a fonte de verdade do pagamento
    continua sendo a OB do SIAFE, não o texto do processo."""
    low = _norm(texto or "")
    tem_ob = any(k in low for k in _OB) or bool(_RE_OB.search(low))
    tem_nl = any(k in low for k in _LIQUIDACAO) or bool(_RE_NL.search(low))
    tem_ne = any(k in low for k in _EMPENHO) or bool(_RE_NE.search(low))
    if tem_ob:
        est = "ob"
    elif tem_nl:
        est = "liquidacao"
    elif tem_ne:
        est = "empenho"
    elif any(k in low for k in _PAGAMENTO):
        est = "generico"
    else:
        est = "nenhum"
    return {"tem_ob": tem_ob, "tem_liquidacao": tem_nl, "tem_empenho": tem_ne, "estagio": est}


def sinais_execucao(texto: str, titulos_documentos=()) -> dict:
    """Presença de PAGAMENTO e das PROVAS de entrega no texto. Determinístico.
    Retorna {tem_pagamento, estagio/tem_ob/…, provas_presentes:[...], faltantes:[...], faltam_essenciais:[...],
    trecho_pagamento}."""
    low = _norm(texto or "")
    # O TÍTULO do documento na árvore é prova tanto quanto o texto: "Anexo NF 16787 - VENDA" diz que a
    # nota fiscal ESTÁ nos autos, mesmo quando a extração não trouxe o conteúdo (caso real
    # 260007/017749/2024: 8 documentos, 625 caracteres de texto). Ignorar o título é acusar o órgão pela
    # falha da NOSSA captura.
    low_titulos = _norm(" \n ".join(str(t) for t in (titulos_documentos or [])))
    low_busca = low + " \n " + low_titulos
    tem_pag = any(k in low_busca for k in _PAGAMENTO)
    est = estagio_despesa(texto + " " + low_titulos)
    presentes = [k for k, kws in _PROVAS.items() if any(w in low_busca for w in kws)]
    for chave, pat in _PROVAS_TITULO.items():          # abreviações valem no TÍTULO da peça
        if chave not in presentes and low_titulos and re.search(pat, low_titulos, re.I):
            presentes.append(chave)
    faltantes = [k for k in _PROVAS if k not in presentes]
    faltam_ess = [k for k in _ESSENCIAIS if k not in presentes]
    return {
        "tem_pagamento": tem_pag or est["estagio"] != "nenhum",
        **{k: est[k] for k in ("tem_ob", "tem_liquidacao", "tem_empenho")},
        "estagio_despesa": est["estagio"],
        "pagamento_efetivo": est["tem_ob"],   # §2: só a Ordem Bancária é "pago"
        "provas_presentes": presentes,
        "faltantes": faltantes,
        "faltam_essenciais": faltam_ess,
        "trecho_pagamento": _trecho_pagamento(texto or "", low, tem_pag, est["estagio"]),
    }


def _trecho_pagamento(texto: str, low: str, tem_pag: bool, estagio: str) -> str:
    """Trecho literal que sustenta o contexto de despesa — pelas palavras OU pelo código do SIAFE (2025OB…)."""
    trecho = _primeiro_trecho(texto, low, _PAGAMENTO) if tem_pag else ""
    if not trecho and estagio != "nenhum":
        m = _RE_OB.search(low) or _RE_NL.search(low) or _RE_NE.search(low)
        if m:
            trecho = _primeiro_trecho(texto, low, (m.group(0),))
    return trecho


def analisar_execucao_det(texto: str, favorecido: str = "", titulos_documentos=()) -> dict:
    """Veredito DETERMINÍSTICO e RESOLVIDO de execução sem comprovação.

    Grau (SENSÍVEL): nao_aplicavel (sem contexto de pagamento) · verde (todas as 3 provas essenciais) ·
    amarelo (falta 1-2 essenciais) · vermelho (falta as 3 — pagamento sem NENHUMA prova de entrega).
    HONESTO: cada achado cita o trecho do pagamento; ausência = FRAGILIDADE a verificar (captura incompleta
    ou execução não comprovada), não acusação.

    §2 (OB ≠ empenho): o vermelho da AUSÊNCIA de prova pressupõe que o dinheiro SAIU — i.e., Ordem Bancária.
    Sem OB no texto (empenho/liquidação apenas, ou menção genérica a pagamento) o grau dessa família tem TETO
    amarelo: empenho é compromisso e pode ser cancelado; não se acusa "pagou sem comprovar" o que não foi pago.
    O teto NÃO se aplica a vício do próprio documento (NF cancelada), que independe do estágio da despesa.
    """
    # o DESTINATÁRIO define a natureza tanto quanto o texto — e o nome dele mora na Ordem Bancária
    # (banco), não no processo. Quem tiver o dado passa em `favorecido`.
    low_all = _norm((texto or "") + " " + (favorecido or ""))
    natureza = "transferencia" if any(k in low_all for k in _TRANSFERENCIA) else "contratacao"
    sig = sinais_execucao(texto, titulos_documentos)
    if natureza == "transferencia":
        return {"grau": "nao_aplicavel", "natureza": natureza, "faltantes": [], "sinais": [],
                "faltam_essenciais": [], "tem_ob": sig["tem_ob"], "tem_liquidacao": sig["tem_liquidacao"],
                "tem_empenho": sig["tem_empenho"], "estagio_despesa": sig["estagio_despesa"],
                "pagamento_efetivo": sig["pagamento_efetivo"], "provas_presentes": sig["provas_presentes"],
                "resumo": ("Despesa de TRANSFERÊNCIA (repasse fundo a fundo, convênio, termo de cooperação "
                           "ou organismo internacional), não de contratação: nota fiscal, boletim de "
                           "medição e atesto de recebimento NÃO são exigíveis aqui. A comprovação própria "
                           "é a PRESTAÇÃO DE CONTAS do destinatário (no SUS: RDQA e RAG — art. 16 do "
                           "Decreto estadual 48.300/2022), que se verifica em outro rito."),
                "a_verificar": ["prestação de contas do destinatário (RDQA/RAG) no prazo",
                                "pactuação/deliberação que autoriza o repasse",
                                "aplicação dos recursos na finalidade pactuada"],
                "ressalva": "transferência regular não se confunde com contratação; INDISPONÍVEL ≠ irregular",
                "fonte": "execucao_sinais (determinístico/offline)"}
    if not sig["tem_pagamento"]:
        return {"grau": "nao_aplicavel", "natureza": natureza, "faltantes": [], "sinais": [],
                "faltam_essenciais": [],
                "tem_ob": False, "tem_liquidacao": False, "tem_empenho": False,
                "estagio_despesa": "nenhum", "pagamento_efetivo": False,
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
    efetivo = sig["pagamento_efetivo"]          # §2: só a OB é "pago"
    est = sig["estagio_despesa"]
    _DESP = {"ob": "Ordem Bancária (pagamento efetivo)", "liquidacao": "liquidação (despesa reconhecida, "
             "ainda NÃO paga)", "empenho": "empenho (compromisso, ainda NÃO pago e cancelável)",
             "generico": "menção a pagamento sem identificar o estágio (empenho/liquidação/OB)"}
    for k in faltam_ess:
        sinais.append({"tipo": f"falta_{k}", "trecho": trecho,
                       "observacao": f"Há {_DESP.get(est, 'despesa')}, mas não consta {_NOME[k]} no processo "
                                     "lido — fragilidade a verificar."})
    if len(faltam_ess) == 3:
        _bump("vermelho" if efetivo else "amarelo")   # §2: sem OB não houve pagamento — teto amarelo
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
    m_nfc = _RE_NF_CANCELADA.search(low)
    if m_nfc:
        _bump("vermelho")
        sinais.append({"tipo": "nota_fiscal_cancelada",
                       "trecho": _primeiro_trecho(texto or "", low, (m_nfc.group(0)[:40],)),
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
        resumo = ("Fragilidade a verificar em despesa no estágio "
                  f"'{est}' — {_DESP.get(est, 'estágio não identificado')}: "
                  + ("; ".join(s["observacao"] for s in sinais[:3]))
                  + " INDISPONÍVEL ≠ irregular (pode ser captura incompleta).")
        if not efetivo and len(faltam_ess) == 3:
            resumo += (" §2: sem Ordem Bancária no texto, o dinheiro ainda NÃO saiu (empenho ≠ pagamento) — "
                       "grau limitado a amarelo; confirmar a OB no SIAFE antes de tratar como despesa paga.")
        if pend:
            resumo += " Pendências: " + ", ".join(pend) + "."
    return {"grau": grau, "natureza": natureza, "faltantes": sig["faltantes"],
            "faltam_essenciais": faltam_ess,
            "provas_presentes": presentes, "atesto_sem_foto": atesto_seco, "sinais": sinais, "resumo": resumo,
            "tem_ob": sig["tem_ob"], "tem_liquidacao": sig["tem_liquidacao"], "tem_empenho": sig["tem_empenho"],
            "estagio_despesa": est, "pagamento_efetivo": efetivo,
            # o que a camada interpretativa (LLM) e a verificação live precisam checar — dono 2026-07-24
            "a_verificar": ["atesto FAZ SENTIDO? (coerência com medição/objeto)",
                            "NF autorizada/cancelada/contingência na SEFAZ (chave de acesso)",
                            "relatório fotográfico corresponde ao objeto/medição"],
            "ressalva": "INDISPONÍVEL ≠ irregular; ausência de documento é fragilidade a verificar, não prova; "
                        "presunção de legitimidade",
            "fonte": "execucao_sinais (determinístico/offline)"}
