# -*- coding: utf-8 -*-
"""COLETOR da ATA DE JULGAMENTO → ctx da fase de julgamento (a ponte que faltava para J4/J7 e o `resultado` do E1).

Espelha `coletor_edital.py`, mas para a FASE DE JULGAMENTO: acha os documentos de ata/habilitação no processo
(via `sei.fases.classificar` — o classificador determinístico já testado), extrai por REGEX as DECISÕES por
licitante (habilitado/inabilitado/diligência + fundamento), as PROPOSTAS quando literais, e agrega o RESULTADO
{licitantes, inabilitados, motivos, vencedor}. O que sobra vai ao LLM-OPCIONAL (schema fixo, citação obrigatória).

ARQUITETURA (honestidade JFN, cláusula absoluta):
  • `classe_falha` REUSA `j7.classificar_classe_falha` — a taxonomia de falha vive num só lugar (não se duplica).
  • Cada decisão/proposta carrega PROVENIÊNCIA (doc/trecho). Campo que o regex não pega e o LLM não confirma fica
    FORA do ctx → J4/J7 marcam aquele eixo `nao_avaliavel` (campo ausente ≠ 0). NUNCA inventamos decisão/CNPJ.
  • Sem doc de julgamento legível e sem LLM → devolve ctx vazio: os detectores de julgamento degradam honesto.

Uso:
    from compliance_agent.detectores.coletor_ata import montar_ctx_julgamento
    ctx_julg = montar_ctx_julgamento(leitura)   # leitura = dict de tools.sei_reader.ler
"""
from __future__ import annotations

import re
from typing import Any, Callable

from compliance_agent.detectores.coletor_edital import (
    _prov,
    _texto_unificado,
    _valor_reais,
)
from compliance_agent.detectores.j7_inabilitacao_seletiva import classificar_classe_falha
from compliance_agent.sei.fases import classificar

# ───────────────────────────── regex determinístico (decisões da ata) ─────────────────────────────
# CNPJ formatado sempre; cru de 14 dígitos SÓ com DV válido (mesma régua do rodizio_grafo — evita
# nº de processo). Tolerante a espaços de OCR em torno de ./-/ .
_RX_CNPJ = re.compile(r"\d{2}\s?\.\s?\d{3}\s?\.\s?\d{3}\s?/\s?\d{4}\s?-\s?\d{2}|\d{14}")
_RX_INABILITADO = re.compile(r"inabilitad[oa]|desclassificad[oa]|desabilitad[oa]", re.IGNORECASE)
_RX_HABILITADO = re.compile(
    r"\bhabilitad[oa]\b|\bclassificad[oa]\b|melhor\s+classificad|declarad[oa]\s+vencedor|"
    r"sagrou-?se\s+vencedor|arrematante|adjudic|homologad|homologo\b|1[ºo°]?\s*lugar|"
    r"primeir[oa]\s+colocad", re.IGNORECASE)
_RX_DILIGENCIA = re.compile(
    r"dilig[êe]ncia|saneamento|prazo\s+para\s+(?:sanar|regulariz|apresentar|complementar)|convertid[oa]\s+em\s+dilig",
    re.IGNORECASE)
_RX_VENCEDOR = re.compile(r"vencedor|arrematante|adjudicat[óo]ri|primeira\s+colocad", re.IGNORECASE)
_RX_MOTIVO = re.compile(
    r"(?:por(?:que)?|em\s+raz[ãa]o\s+d[eo]|motivos?[:\s]|deixou\s+de|n[ãa]o\s+apresentou|"
    r"aus[êe]ncia\s+de|face\s+[àa]|tendo\s+em\s+vista)\s+(.+)$",
    re.IGNORECASE)
# marcadores FORTES de que uma fonte é uma ata/sessão de julgamento (fallback quando o título não classifica).
# NÃO usa 'habilitad'/'inabilitad' isolado — essas palavras aparecem no próprio edital e gerariam falso positivo.
_RX_ATA_MARCADOR = re.compile(
    r"ata\s+d[ae]\s+(?:sess|julgamento)|sess[ãa]o\s+p[úu]blica\s+(?:de|do|para)|"
    r"julgamento\s+das?\s+propostas?|mapa\s+de\s+lances|resultado\s+d[ao]\s+julgamento",
    re.IGNORECASE)


def _docs_de_julgamento(leitura: dict) -> list[dict]:
    """Fontes {fonte, texto} dos documentos de JULGAMENTO/HABILITAÇÃO/RECURSO do processo, achadas por
    `sei.fases.classificar` (determinístico). Sem título que classifique → fallback por marcador de ata no
    conteúdo (títulos SEI são ruidosos), mas nunca inventa: só entra o que tem marcador real."""
    fontes: list[dict] = []
    for cd in leitura.get("conteudo_documentos") or []:
        doc = str(cd.get("doc") or "").strip()
        conteudo = (cd.get("conteudo") or "").strip()
        if not conteudo:
            continue
        fase, tipo = classificar(doc)
        if fase == "selecao" and tipo in ("julgamento", "habilitacao", "recurso"):
            fontes.append({"fonte": f"documento '{doc}' (seleção/{tipo})", "texto": conteudo})
    if fontes:
        return fontes
    # fallback honesto: nenhum título casou — varre as fontes cujo CONTEÚDO tem marcador de ata
    for f in _texto_unificado(leitura):
        if _RX_ATA_MARCADOR.search(f["texto"]):
            fontes.append(f)
    return fontes


def _blocos_com_contexto(fontes: list[dict]) -> list[tuple[str, str]]:
    """Achata as fontes em BLOCOS (parágrafos, separados por linha em branco), cada um (bloco, fonte). A ata
    descreve cada licitante num parágrafo que quebra em várias linhas — o bloco preserva CNPJ + decisão juntos
    (a extração por linha isolada perderia a decisão que cai na linha seguinte ao CNPJ)."""
    out: list[tuple[str, str]] = []
    for f in fontes:
        for bloco in re.split(r"\n\s*\n", f["texto"]):
            b = re.sub(r"\s+", " ", bloco).strip()
            if b:
                out.append((b, f["fonte"]))
    return out


def _segmentos_por_cnpj(fontes: list[dict]) -> list[tuple[str, str, str]]:
    """Segmenta cada bloco por CNPJ → (cnpj, segmento, fonte). O segmento inclui uma JANELA RETROATIVA
    (a decisão pode vir ANTES do CNPJ: 'foi declarada vencedora a empresa X, CNPJ Y') limitada pelo CNPJ
    anterior, e vai até o próximo CNPJ. CNPJ cru de 14 dígitos só entra com DV válido (nº de processo
    fora); CNPJ em contexto de PREÂMBULO (autoridade contratante) não é licitante."""
    from compliance_agent.rodizio_grafo import _PREAMBULO, _cnpj_dv_ok
    out: list[tuple[str, str, str]] = []
    for bloco, fonte in _blocos_com_contexto(fontes):
        matches = list(_RX_CNPJ.finditer(bloco))
        for i, m in enumerate(matches):
            cnpj = re.sub(r"\s", "", m.group(0))
            if "." not in cnpj and not _cnpj_dv_ok(cnpj):
                continue
            ini = max(matches[i - 1].end() if i > 0 else 0, m.start() - 80)
            fim = matches[i + 1].start() if i + 1 < len(matches) else len(bloco)
            seg = bloco[ini:fim]
            if _PREAMBULO.search(seg):
                continue
            out.append((cnpj, seg, fonte))
    return out


_RX_NEGACAO_INAB = re.compile(
    r"nenhum(?:a)?\s+(?:participante|licitante|empresa|proposta)[^.]{0,60}?"
    r"(?:inabilitad|desclassificad)|n[ãa]o\s+(?:houve|foram?|foi)\s+"
    r"(?:\w+\s+){0,3}?(?:inabilitad|desclassificad)|sem\s+(?:inabilitad|desclassificad)",
    re.IGNORECASE)


def _classificar_decisao(linha: str) -> str | None:
    """Mapeia a linha numa decisão canônica que o J7 entende: 'diligencia'|'inabilitado'|'habilitado'|None.
    Ordem importa: diligência/saneamento é TOLERÂNCIA mesmo que a palavra 'inabilitada' apareça na frase.
    Guard de NEGAÇÃO (corpus PNCP 2026-07-22): boilerplate de ata eletrônica — "PARTICIPANTE(S)
    INABILITADO(S): Nenhum" — casava o regex e inventava inabilitação para o CNPJ vizinho."""
    if _RX_DILIGENCIA.search(linha):
        return "diligencia"
    if _RX_NEGACAO_INAB.search(linha):
        # "nenhum inabilitado/não houve desclassificação": segue avaliando habilitação abaixo
        if _RX_HABILITADO.search(linha) or _RX_VENCEDOR.search(linha):
            return "habilitado"
        return None
    if _RX_INABILITADO.search(linha):
        return "inabilitado"
    if _RX_HABILITADO.search(linha) or _RX_VENCEDOR.search(linha):
        return "habilitado"
    return None


def _fundamento(linha: str) -> str:
    """Texto da fundamentação/falha (o que vem após 'por'/'em razão de'/'motivo'…). '' se não houver rótulo."""
    m = _RX_MOTIVO.search(linha)
    return (m.group(1).strip()[:160]) if m else ""


def _extrair_decisoes(fontes: list[dict]) -> list[dict]:
    """Ata → list[{cnpj, decisao, falha, classe_falha, fundamento, vencedor, prov}] (schema que o J7 consome).
    Determinístico: cada CNPJ recebe a decisão do seu SEGMENTO (do CNPJ até o próximo). `classe_falha` via reuso
    do J7. `falha` = o fundamento rotulado quando houver, senão o próprio segmento (texto literal — nunca inventado)."""
    decisoes: list[dict] = []
    for cnpj, seg, fonte in _segmentos_por_cnpj(fontes):
        decisao = _classificar_decisao(seg)
        if decisao is None:
            continue
        fund = _fundamento(seg)
        # J7 precisa de falha não-vazia p/ parear INABILITADOS; para HABILITADO sem fundamento
        # rotulado, o segmento é boilerplate ("apresentou toda a documentação") — não é falha:
        # emitir classe 'outra' evita parear tolerância espúria (o J7 ignora 'outra').
        if decisao == "habilitado" and not fund:
            falha, classe = "", "outra"
        else:
            falha = fund or seg[:160]
            classe = classificar_classe_falha(fund or seg)
        vencedor = bool(_RX_VENCEDOR.search(seg))
        decisoes.append({
            "cnpj": cnpj,
            "decisao": decisao,
            "falha": falha,
            "classe_falha": classe,
            "fundamento": fund,
            "vencedor": bool(vencedor),
            "prov": _prov(fonte, seg),
        })
    return decisoes


def _extrair_propostas(fontes: list[dict]) -> list[dict]:
    """Mapa de lances/ata → list[{licitante_cnpj, valor, classificacao, prov}] p/ J2/J4. Só o que estiver
    LITERAL (segmento com CNPJ + valor R$). Sem valor → não entra (não inventa)."""
    propostas: list[dict] = []
    for cnpj, seg, fonte in _segmentos_por_cnpj(fontes):
        valor = _valor_reais(seg)
        if valor is None:
            continue
        classificacao = "classificada" if _RX_HABILITADO.search(seg) else (
            "desclassificada" if _RX_INABILITADO.search(seg) else None)
        p: dict[str, Any] = {"licitante_cnpj": cnpj, "valor": valor, "prov": _prov(fonte, seg)}
        if classificacao:
            p["classificacao"] = classificacao
        propostas.append(p)
    return propostas


def _extrair_resultado(decisoes: list[dict], propostas: list[dict]) -> dict:
    """Agrega o RESULTADO do certame que o cruzamento do E1 consome: {licitantes, inabilitados, motivos,
    vencedor_cnpj}. `licitantes` = CNPJs distintos vistos em decisões + propostas."""
    cnpjs = {d["cnpj"] for d in decisoes} | {p["licitante_cnpj"] for p in propostas}
    # dedup por CNPJ: o mesmo licitante inabilitado em docs/itens diferentes conta UMA vez
    # (senão inab > licitantes e a taxa de inabilitação em massa infla — visto em ata real)
    vistos: set[str] = set()
    inabilitados = [d for d in decisoes if d["decisao"] == "inabilitado"
                    and not (d["cnpj"] in vistos or vistos.add(d["cnpj"]))]
    vencedores = [d["cnpj"] for d in decisoes if d["vencedor"]]
    # diligência é ATRIBUÍDA por licitante (art. 64 §1º): saneamento concedido a OUTRO CNPJ não
    # exculpa a inabilitação trivial deste — é justamente o padrão dois-pesos que o J7 caça.
    dil_cnpjs = {d["cnpj"] for d in decisoes if d["decisao"] == "diligencia"}
    resultado: dict[str, Any] = {
        "licitantes": len(cnpjs),
        "inabilitados": len(inabilitados),
        "motivos": [d["fundamento"] for d in inabilitados if d["fundamento"]],
        "motivos_det": [{"cnpj": d["cnpj"], "motivo": d["fundamento"],
                         "diligencia": d["cnpj"] in dil_cnpjs}
                        for d in inabilitados if d["fundamento"]],
    }
    if vencedores:
        resultado["vencedor_cnpj"] = vencedores[0]
    return resultado


# ───────────────────────────── LLM-opcional (extração estruturada de decisões) ─────────────────────────────
_SYS_DECISOES = (
    "Você é EXTRATOR de decisões de habilitação de uma ATA DE JULGAMENTO de licitação (controle externo, JFN). "
    "Extraia, para CADA licitante citado, a decisão da comissão SOMENTE se estiver LITERAL no texto, citando o "
    "trecho. NUNCA invente CNPJ, decisão ou motivo. Responda SOMENTE com um objeto JSON: "
    '{"decisoes":[{"cnpj":"..","decisao":"habilitado|inabilitado|diligencia","fundamento":"..","vencedor":true|false,'
    '"trecho":"<citação literal>"}]}. Item sem trecho é descartado.'
)


def _llm_extrair_decisoes(fontes: list[dict], gerar: Callable[[str, str], str] | None) -> list[dict]:
    """Extração LLM-OPCIONAL das decisões (schema JSON fixo, citação obrigatória por item). Sem motor/《LLM caiu》
    → [] (degrada honesto). Reusa o parser tolerante de `base._parse_json`."""
    if gerar is None:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync as gerar  # type: ignore
        except ImportError:
            return []
    contexto = "\n\n".join(f"[{f['fonte']}]\n{f['texto'][:1500]}" for f in fontes[:4])[:6000]
    prompt = (f"ATA/DECISÕES:\n{contexto}\n\n"
              "Extraia as decisões de habilitação por licitante. Responda só com o JSON.")
    try:
        raw = gerar(prompt, _SYS_DECISOES)
    except Exception:
        return []
    from compliance_agent.detectores.base import _parse_json
    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        return []
    out: list[dict] = []
    for item in dados.get("decisoes") or []:
        if not isinstance(item, dict):
            continue
        cnpj = str(item.get("cnpj") or "").strip()
        decisao = str(item.get("decisao") or "").strip().lower()
        trecho = str(item.get("trecho") or "").strip()
        if not cnpj or decisao not in ("habilitado", "inabilitado", "diligencia") or not trecho:
            continue  # citação obrigatória + sem invenção
        fund = str(item.get("fundamento") or "").strip()[:160]
        out.append({
            "cnpj": cnpj, "decisao": decisao, "falha": fund, "classe_falha": classificar_classe_falha(fund or trecho),
            "fundamento": fund, "vencedor": bool(item.get("vencedor")),
            "prov": _prov("LLM (extração estruturada — ata)", trecho),
        })
    return out


# ───────────────────────────── montagem do ctx de julgamento ─────────────────────────────
def montar_ctx_julgamento(leitura: dict, *, usar_llm: bool = False,
                          gerar: Callable[[str, str], str] | None = None) -> dict:
    """Da íntegra do processo (``sei_reader.ler``) monta o ctx da FASE DE JULGAMENTO: {decisoes, propostas,
    resultado, _proveniencia}. REGEX pega o comum; ``usar_llm=True`` aciona a extração estruturada das decisões
    para o que o regex não pegou. Degrada honesto: sem ata legível e sem LLM → campos ficam FORA do ctx."""
    fontes = _docs_de_julgamento(leitura)
    prov: dict[str, Any] = {}
    ctx: dict[str, Any] = {}
    if not fontes:
        ctx["_proveniencia"] = prov
        return ctx

    decisoes = _extrair_decisoes(fontes)
    if usar_llm and not decisoes:
        decisoes = _llm_extrair_decisoes(fontes, gerar)
    propostas = _extrair_propostas(fontes)

    if decisoes:
        ctx["decisoes"] = decisoes
        prov["decisoes"] = [d["prov"] for d in decisoes]
    if propostas:
        ctx["propostas"] = propostas
        prov["propostas"] = [p["prov"] for p in propostas]
    if decisoes or propostas:
        resultado = _extrair_resultado(decisoes, propostas)
        ctx["resultado"] = resultado
        prov["resultado"] = {"doc": "agregado das decisões/propostas da ata", "trecho": str(resultado)[:160]}

    ctx["_proveniencia"] = prov
    return ctx


_RX_CERTAME_PNCP = re.compile(r"\b(\d{14}-\d-\d{6}/\d{4})\b")


def certame_de_leitura(leitura: dict) -> str | None:
    """Nº de controle PNCP mais citado nos textos do processo (None se nenhum — nunca inventa)."""
    from collections import Counter
    hits: Counter = Counter()
    for d in leitura.get("conteudo_documentos") or []:
        for m in _RX_CERTAME_PNCP.findall(d.get("conteudo") or ""):
            hits[m] += 1
    return hits.most_common(1)[0][0] if hits else None


def persistir_julgamento(leitura: dict, certame: str, con=None, *, processo_sei: str | None = None) -> dict | None:
    """Monta o ctx da ata e PERSISTE o `resultado` em certame_julgamento (editais/db.salvar_julgamento) —
    antes o resultado era efêmero e a família certame_ata do índice ficava eternamente INDISPONÍVEL.
    `houve_diligencia` é inferido das próprias decisões (alguma decisao=='diligencia' na sessão).
    Sem resultado extraível → None (não grava vazio). `con` ausente → abre o compliance.db da casa."""
    from compliance_agent.editais.db import conectar, salvar_julgamento

    ctx = montar_ctx_julgamento(leitura)
    resultado = ctx.get("resultado")
    if not resultado:
        return None
    houve_dil = any(d.get("decisao") == "diligencia" for d in ctx.get("decisoes") or [])
    fechar = con is None
    con = con or conectar()
    try:
        return salvar_julgamento(con, certame, resultado, houve_diligencia=houve_dil,
                                 processo_sei=processo_sei)
    finally:
        if fechar:
            con.close()
