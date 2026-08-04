# -*- coding: utf-8 -*-
"""
Fases da contratação pública — taxonomia DETERMINÍSTICA (sem LLM).

O "entendimento perfeito" de cada fase vive AQUI, em código testado
(tests/test_sei_fases.py), não na memória de nenhum modelo. Qualquer título de
documento SEI é classificado em (fase, tipo_documento) por regras; a linha do
tempo e as lacunas por modalidade saem de funções puras.

Fases (espinha dorsal Lei 14.133/2021; serve aos legados 8.666/93 e 10.520/02):

  planejamento  DFD, ETP, TR/projeto, pesquisa de preços, mapa de riscos
  selecao       edital→julgamento→homologação; ou dispensa/inexigibilidade
  contratacao   contrato/ata de RP, garantia, publicação, ordem de início
  execucao      medição, relatório fotográfico, fiscalização, aceite, aditivo
  despesa       empenho (NE) → liquidação (NL/NF) → pagamento (PD/OB)
  controle      pareceres jurídicos, auditoria, TCE/CGE, diligências
  tramitacao    despachos, ofícios, memorandos (movimentação genérica)
  indefinida    sem sinal suficiente (ex.: "Anexo" solto) — honestidade

Regra de ouro do uso pericial: OB/NF presentes SEM medição/atesto em serviço
ou obra = pagamento sem evidência de execução (lacuna CRÍTICA).
"""
from __future__ import annotations

import re
import unicodedata

# ordem processual canônica (dict preserva ordem)
FASES: dict[str, str] = {
    "planejamento": "Planejamento da contratação",
    "selecao": "Seleção do fornecedor (licitação ou contratação direta)",
    "contratacao": "Formalização do contrato",
    "execucao": "Execução física do objeto",
    "despesa": "Execução da despesa (empenho→liquidação→pagamento)",
    "controle": "Controle e assessoramento jurídico",
    "tramitacao": "Tramitação administrativa",
    "indefinida": "Sem sinal suficiente no título",
}

# (tipo, fase, padrões) — avaliados NA ORDEM; primeiro que casar vence.
# Padrões casam sobre o título NORMALIZADO (minúsculo, sem acento, e com os
# buracos de encoding dos nomes de arquivo — 'Cota__o' → 'cota o' — tolerados
# por usar radicais curtos).
_REGRAS: list[tuple[str, str, list[str]]] = [
    # ── despesa (antes de 'anexo' genérico: "Anexo NE - …" é empenho) ──────
    ("nota_empenho", "despesa", [r"\bne\b.*\d{4}ne", r"\d{4}ne\d", r"nota de empenho", r"anexo ne\b"]),
    ("ordem_bancaria", "despesa", [r"ordem bancaria", r"\d{4}ob\d", r"\bob\b.*\d{4}ob"]),
    ("nota_liquidacao", "despesa", [r"nota de liquida", r"liquidacao de despesa",
                                    r"\bnl\b.*\d{4}nl", r"\d{4}nl\d"]),
    ("programacao_desembolso", "despesa", [r"programacao de desembolso", r"\bpd\b.*\d{4}pd", r"\d{4}pd\d"]),
    ("nota_fiscal", "despesa", [r"nota fiscal", r"\bdanfe\b", r"\bnfs?-?e\b", r"\bfatura\b"]),
    ("autorizacao_despesa", "despesa", [r"autorizacao de despesa", r"\bnad\b"]),
    # ── execução física ────────────────────────────────────────────────────
    ("relatorio_fotografico", "execucao", [r"relatorio fotogra", r"registro fotogra"]),
    ("medicao", "execucao", [r"medicao", r"boletim de medi", r"\bmedi(cao|coes)\b"]),
    ("fiscalizacao", "execucao", [r"relatorio de fiscaliza", r"fiscalizacao", r"diario de obra"]),
    # O ATO DE ATESTAR, nas formas que o SEI-RJ realmente usa. Medido em 2026-08-04: dos processos
    # acusados de "sem evidência de execução APESAR DE HAVER PAGAMENTO" — acusação de gravidade
    # CRÍTICA, 353 nos EXTREMO+ALTO —, ~10% tinham o atesto nos autos e não eram vistos:
    #     "Nota Fiscal - NF - Invoice - ATESTADA"      → caía em despesa/nota_fiscal
    #     "Despacho ATESTAÇÃO"                          → caía em tramitacao/despacho
    #     "ATESTADO DE RECEBIMENTO de Materiais"        → caía em indefinida/outro
    #     "Anexo NOTA FISCAL, ATESTO e RELAÇÃO…"        → caía em despesa/nota_fiscal
    # `atestad[oa]` sozinho NÃO entra: "atestado de capacidade/idoneidade/regularidade" é
    # CERTIDÃO de habilitação, não prova de entrega — e confundir os dois inverteria o erro.
    ("aceite", "execucao", [r"atestado de realiza", r"atestado de execu", r"termo de recebimento",
                            r"recebimento (provisorio|definitivo)", r"\batesto\b",
                            r"atesta(cao|da|do)\b(?!\s+(?:de\s+)?(capacidade|idoneidade|"
                            r"regularidade|locacao|permiss|comparecimento|retorno|saude|medic|"
                            r"tecnic|obito|antecedent))",
                            r"atestado de recebimento", r"nota fiscal[^|]{0,40}atestad"]),
    ("aditivo", "execucao", [r"termo aditivo", r"aditivo", r"apostilamento", r"repactuacao",
                             r"reajuste", r"prorrogacao"]),
    ("penalidade", "execucao", [r"glosa", r"penalidade", r"notificacao ao contratado", r"multa contratual"]),
    # ── planejamento ───────────────────────────────────────────────────────
    ("etp", "planejamento", [r"estudo tecnico preliminar", r"\betp\b"]),
    ("termo_referencia", "planejamento", [r"termo de referencia", r"\btr\b.*refer"]),
    ("projeto", "planejamento", [r"projeto basico", r"projeto executivo"]),
    ("dfd", "planejamento", [r"\bdfd\b", r"formalizacao da demanda"]),
    ("pesquisa_precos", "planejamento", [r"pesquisa de preco", r"\bcota\w*\b(?!.*(social|parte))",
                                          r"mapa comparativo de preco", r"planilha orcament", r"orcamento estimad"]),
    ("mapa_riscos", "planejamento", [r"mapa de risco", r"matriz de risco", r"gerenciamento de risco"]),
    # ── seleção do fornecedor ──────────────────────────────────────────────
    ("edital", "selecao", [r"\bedital\b", r"aviso de licitacao", r"aviso de pregao"]),
    ("julgamento", "selecao", [r"ata de (realizacao|sessao|julgamento|abertura)", r"ata do pregao",
                               r"mapa de lances", r"julgamento das propostas"]),
    ("proposta", "selecao", [r"\bproposta\b"]),
    ("habilitacao", "selecao", [r"habilitacao", r"documentos de habilita"]),
    ("homologacao", "selecao", [r"homologa"]),
    ("adjudicacao", "selecao", [r"adjudica"]),
    ("recurso", "selecao", [r"\brecurso\b", r"contrarrazo", r"impugna", r"esclarecimento ao edital"]),
    ("contratacao_direta", "selecao", [r"dispensa de licita", r"inexigibilidade", r"ratifica",
                                       r"justificativa de (dispensa|contrata)"]),
    # ── formalização do contrato ───────────────────────────────────────────
    # contrato SOCIAL é documento societário de habilitação, não o instrumento contratual
    # (virava marco de contrato e fabricava inversão do art. 53 — calibração 2026-08-01)
    ("habilitacao", "selecao", [r"contrato social"]),
    ("ata_rp", "contratacao", [r"ata de registro de preco"]),
    ("contrato", "contratacao", [r"termo de contrato", r"\bcontrato\b", r"extrato de contrato",
                                 r"publicacao .*contrato"]),
    ("garantia", "contratacao", [r"garantia contratual", r"seguro garantia", r"apolice"]),
    ("ordem_inicio", "contratacao", [r"ordem de (inicio|servico|fornecimento|compra|execucao)",
                                     r"\bos\b.*servico", r"autorizacao de fornecimento"]),
    ("fiscal_designacao", "contratacao", [r"designacao de fiscal", r"portaria de fiscal", r"gestor do contrato"]),
    # ── controle ───────────────────────────────────────────────────────────
    # certidão ANTES de parecer: "CERTIDÃO DA PROCURADORIA DA DÍVIDA ATIVA - PGE" é documento
    # de habilitação/regularidade, não parecer jurídico — já fabricou inversão do art. 53
    # (FP real no 030001/087722/2024, calibração 2026-08-01).
    # 2026-08-03: faltava o PLURAL — "Certidões Negativa de Débitos" e "Documentos fiscais -
    # Certidões" caíam em 'outro', a regra acima não desmentia o tipo armazenado, e 42 processos
    # do acervo seguiam com a CND tipada `parecer`. O singular passava; o plural, que é como o
    # SEI-RJ costuma nomear, não. Esta é a camada que cura o acervo JÁ CAPTURADO, sem recaptura.
    ("certidao", "tramitacao", [r"certid(ao|oes)", r"certificado de regularidade"]),
    ("parecer", "controle", [r"\bparecer\b", r"\bpge\b", r"assessoria juridica", r"assjur",
                             r"manifestacao juridica", r"nota tecnica"]),
    ("orgao_controle", "controle", [r"\btce\b", r"\bcge\b", r"\btcu\b", r"auditoria", r"diligencia",
                                    r"controle interno", r"tomada de contas"]),
    # ── tramitação genérica ────────────────────────────────────────────────
    ("despacho", "tramitacao", [r"\bdespacho\b"]),
    ("oficio", "tramitacao", [r"\boficio\b", r"\bmemorando\b", r"\bcomunicacao\b", r"\be-?mail\b",
                              r"termo de (encaminhamento|abertura|encerramento|cancelamento)",
                              r"\bcapa\b", r"folha de informacao"]),
    # anexo genérico por último (Anexo NE etc. já casaram acima)
    ("anexo", "indefinida", [r"^anexo\b"]),
]

_COMPILADAS = [(tipo, fase, [re.compile(p) for p in pads])
               for tipo, fase, pads in _REGRAS]


def _norm(titulo: str) -> str:
    t = unicodedata.normalize("NFKD", str(titulo or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    t = re.sub(r"[_\W]+", " ", t)          # '_' e pontuação → espaço
    return re.sub(r"\s+", " ", t).strip()


def classificar(titulo: str) -> tuple[str, str]:
    """Título de documento SEI → (fase, tipo_documento). Determinístico."""
    t = _norm(titulo)
    if not t:
        return ("indefinida", "vazio")
    for tipo, fase, pads in _COMPILADAS:
        if any(p.search(t) for p in pads):
            return (fase, tipo)
    return ("indefinida", "outro")


# tipo canônico → fase, derivado das MESMAS regras que classificam por título (uma fonte só).
_FASE_POR_TIPO = {tipo: fase for tipo, fase, _ in _REGRAS}


def fase_do_tipo(tipo: str) -> str:
    """Fase que corresponde a um tipo canônico de documento. Desconhecido → 'indefinida'."""
    return _FASE_POR_TIPO.get((tipo or "").strip().lower(), "indefinida")


def classificar_com_tipo(titulo: str, tipo: str = "") -> tuple[str, str]:
    """(fase, tipo) usando o título e, se ele nada disser, o TIPO já resolvido pelo manifesto.

    Achado em 2026-08-03 (SEI-080007/001365/2024): um Termo de Referência de 20.000 caracteres
    com 11 anexos ficou em fase `indefinida` porque o título era "Formulário de solicitação de
    material ou serviço" — e o sistema acusou "falta Planejamento" num processo que o tem. O
    classificador de documentos já havia acertado (`tipo: termo_referencia`); a fase é que não
    aproveitava o que a casa já sabia.

    A ordem não muda a doutrina: o TÍTULO manda quando diz algo (é ele que desmente o
    classificador por conteúdo, que já rotulou certidão como parecer e nota fiscal como
    contrato). O tipo só entra quando o título é mudo.
    """
    fase, tipo_titulo = classificar(titulo)
    if fase != "indefinida":
        return (fase, tipo_titulo)
    do_tipo = fase_do_tipo(tipo)
    if do_tipo != "indefinida":
        return (do_tipo, (tipo or "").strip().lower())
    return (fase, tipo_titulo)


def linha_do_tempo(titulos: list[str]) -> dict[str, list[str]]:
    """Agrupa os títulos (na ordem dos autos) por fase — o esqueleto do processo."""
    tl: dict[str, list[str]] = {f: [] for f in FASES}
    for t in titulos:
        fase, _ = classificar(t)
        tl[fase].append(t)
    return tl


# checklist mínimo por modalidade (o que um processo SÃO deve conter)
_CHECKLIST = {
    "licitacao": [("planejamento", "Planejamento (ETP/TR/pesquisa de preços)", "media"),
                  ("selecao", "Seleção (edital, julgamento, homologação)", "alta"),
                  ("contratacao", "Contrato/ata formalizados", "media")],
    "dispensa": [("planejamento", "Planejamento (TR/justificativa/cotações)", "media"),
                 ("selecao", "Ato de dispensa/inexigibilidade e ratificação", "alta"),
                 ("contratacao", "Contrato ou instrumento equivalente", "media")],
}
_MODALIDADES_DIRETAS = ("dispensa", "inexigibilidade", "adesao", "credenciamento")


# Fases que NÃO se cobram de um processo de aditivo/prorrogação: elas ocorreram no processo que
# originou o contrato. Achado ao ler o SEI-270131/000548/2023 na íntegra (2026-08-03): o sistema
# lançava "Seleção (edital, julgamento, homologação)" com gravidade ALTA num processo de
# prorrogação — o mesmo erro que a casa já tinha corrigido para processo de PAGAMENTO. Sem isto,
# todo aditivo nasce com um achado alto estrutural e a fila do fiscal enche de ruído.
_FASES_DO_PROCESSO_DE_ORIGEM = ("selecao",)
# Processo FINANCEIRO não carrega nenhuma das fases de contratação: planejamento, seleção e
# formalização vivem no processo-pai — que os próprios autos costumam nomear. Medido em
# 2026-08-03 (SEI-080001/018592/2026): três lacunas cobradas, uma delas ALTA, num processo cuja
# CI diz "encontra respaldo no processo administrativo SEI-080001/004018/2023". A evidência de
# execução CONTINUA sendo cobrada: pagar sem prova de entrega é o achado que mais importa.
_FASES_DO_PROCESSO_PAI = ("planejamento", "selecao", "contratacao")
# Compra CANCELADA: seleção e formalização não ocorreram porque a contratação foi desfeita. O
# planejamento continua sendo cobrado (ele antecede o cancelamento e é onde mora a motivação), e a
# evidência de execução também — cancelar e ainda assim pagar é o oposto de inocente.
_FASES_QUE_O_CANCELAMENTO_DISPENSA = ("selecao", "contratacao")


def lacunas(fases_presentes: set[str], modalidade: str = "",
            com_pagamento: bool = False, natureza: str = "") -> list[dict]:
    """
    O que FALTA nos autos dado o que já se vê neles. Cada lacuna:
    {"falta": ..., "gravidade": baixa|media|alta|critica}.

    A crítica clássica: há pagamento (despesa) mas não há NENHUMA evidência de
    execução física — serviço pago sem prova de entrega.

    `natureza="aditivo"` isenta apenas a SELEÇÃO (que vive no processo de origem); tudo o mais —
    planejamento, formalização, evidência de execução — continua sendo cobrado.
    """
    m = _norm(modalidade)
    chave = "dispensa" if any(k in m for k in _MODALIDADES_DIRETAS) else "licitacao"
    saida = []
    for fase, rotulo, grav in _CHECKLIST[chave]:
        if natureza == "aditivo" and fase in _FASES_DO_PROCESSO_DE_ORIGEM:
            continue
        if natureza == "pagamento" and fase in _FASES_DO_PROCESSO_PAI:
            continue
        if natureza == "cancelado" and fase in _FASES_QUE_O_CANCELAMENTO_DISPENSA:
            continue
        if fase not in fases_presentes:
            saida.append({"falta": rotulo, "gravidade": grav})
    if com_pagamento and "execucao" not in fases_presentes:
        saida.append({"falta": "Evidência de execução (medição/atesto/relatório "
                               "fotográfico) apesar de haver pagamento",
                      "gravidade": "critica"})
    return saida
