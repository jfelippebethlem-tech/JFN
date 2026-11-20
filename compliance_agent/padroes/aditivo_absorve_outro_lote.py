# -*- coding: utf-8 -*-
"""Termo aditivo de "acréscimo quantitativo" que ABSORVE o objeto de OUTRO contrato/lote.

ORIGEM (perícia integral 18/11/2026, conferida na fonte): SEAP × Seleta, SEI-210108/000153/2023, doc 873 — 5º TA
"decorre da absorção parcial do Contrato nº 14/2020, referente ao lote 12", 243.764 refeições/mês trazidas para um
contrato de 289.012, declarado como acréscimo de 14,59%. Mesma redação nos contratos da Cassarotti (000169 e
000163/2023), Qualybem (000158/2023) e Locasem (000165/2023).

POR QUE É VÍCIO. O art. 65, I, "b" e §1º da Lei 8.666/93 (art. 125 da Lei 14.133/21) admitem acrescer o objeto
LICITADO até 25%. Trazer para o contrato as unidades de outro lote — que foram licitadas separadamente e tinham outro
contratado — é contratar objeto novo sem licitação; o percentual declarado mede o valor do termo, não o objeto.

SINAL (determinístico): no CORPO de um documento que É termo aditivo (título; nunca minuta, parecer ou extrato):
  • "absorção (parcial|total) do(s) Contrato(s) nº X" / "do lote N", com X ≠ o próprio contrato; ou
  • "assumir a prestação dos serviços nas unidades" (redação SEAP).
GRAU: forte = absorção de contrato/lote IDENTIFICADO + termo declarado como acréscimo/alteração quantitativa;
medio = só a redação "assumir a prestação" ou absorção sem identificar o contrato; fraco = nunca emitido.
EXPLICAÇÕES INOCENTES avaliadas e anotadas no achado: (1) continuidade de serviço essencial (justifica emergencial
ou nova licitação, não aditivo); (2) lote absorvido do MESMO contrato (excluído: X = o próprio contrato); (3) texto
de extrato do DOERJ de outro ato (excluído: trecho precisa estar no corpo do termo, antes da página do Diário).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _aditivos_comum as C

ID = "aditivo_absorve_outro_lote"

_RE_ABSORCAO = re.compile(
    r"absor[çc][ãa]o\s+(?:parcial\s+|total\s+|integral\s+)?(?:do\s+objeto\s+)?d[oa]s?\s+"
    r"(?P<alvo>contratos?|lotes?)\s*(?:n[º°o.]*\s*)?(?P<lista>(?:\d{1,4}\s*/\s*\d{2,4}|\d{1,3})"
    r"(?:\s*(?:,|e)\s*(?:n[º°o.]*\s*)?(?:\d{1,4}\s*/\s*\d{2,4}|\d{1,3}))*)", re.I)
_RE_ASSUMIR = re.compile(r"assumir\s+a\s+presta[çc][ãa]o\s+dos\s+servi[çc]os\s+n[ao]s?\s+unidades", re.I)
_RE_REF_LOTE = re.compile(r"referente[s]?\s+a[o]?s?\s+lotes?\s*(?:n[º°o.]*\s*)?(\d{1,3}(?:\s*(?:,|e)\s*\d{1,3})*)", re.I)
_RE_QUANTITATIVO = re.compile(r"altera[çc][ãa]o\s+quantitativa|acr[ée]scimo\s+(?:do\s+objeto|quantitativo)|"
                              r"art\.?\s*65,?\s*(?:inciso\s+)?I\b[^.;]{0,30}?\bb\b|art\.?\s*125|art\.?\s*124,?\s*(?:inciso\s+)?I\b",
                              re.I)
_RE_PCT = re.compile(r"percentual\s+de\s+(\d{1,2}(?:,\d{1,4})?)\s*%")
_RE_PROPRIO = re.compile(r"(?:aditivo\s+ao|altera[çc][ãa]o\s+quantitativa\s+do|ao)\s+contrato\s*(?:n[º°o.]*\s*)?"
                         r"(\d{1,4}\s*/\s*\d{2,4})", re.I)
_RE_PROPRIO_TIT = re.compile(r"contrato\s*(?:n[º°o.]*\s*)?(\d{1,4}\s*/\s*\d{2,4})", re.I)
_RE_NUM_CONTRATO = re.compile(r"\d{1,4}\s*/\s*\d{2,4}")


def analisar_texto(texto: str, titulo: str = "") -> list[dict]:
    """Ocorrências de absorção no corpo de um termo aditivo. Função pura (testável)."""
    proprios = {C.norm_contrato(m.group(1)) for m in _RE_PROPRIO.finditer(texto[:20000])}
    proprios |= {C.norm_contrato(m.group(1)) for m in _RE_PROPRIO_TIT.finditer(titulo or "")}
    out, vistos = [], set()
    for m in _RE_ABSORCAO.finditer(texto):
        if not C.no_corpo(texto, m.start()):
            continue
        alvo = m.group("alvo").lower()
        # peça que compila vários termos: o "próprio" é também o contrato nomeado logo antes da cláusula
        perto = {C.norm_contrato(x.group(1)) for x in _RE_PROPRIO.finditer(texto[max(0, m.start() - 2000):m.start()])}
        if alvo.startswith("contrato"):
            nums = {C.norm_contrato(x) for x in _RE_NUM_CONTRATO.findall(m.group("lista"))}
            outros = nums - proprios - perto
            if not outros:
                continue      # absorção de parte do PRÓPRIO contrato não é o vício
            lotes = []
            ml = _RE_REF_LOTE.search(texto, m.end(), m.end() + 200)
            if ml:
                lotes = re.findall(r"\d{1,3}", ml.group(1))
        else:
            outros = set()
            lotes = re.findall(r"\d{1,3}", m.group("lista"))
        janela = texto[max(0, m.start() - 3000): m.end() + 4000]
        pcts = [C.pct_br(p) for p in _RE_PCT.findall(texto[m.end(): m.end() + 4000])]
        chave = (tuple(sorted(outros)), tuple(lotes))
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append({"tipo": "absorcao", "contratos_absorvidos": sorted(outros), "lotes": lotes,
                    "proprio": sorted(proprios | perto), "quantitativo": bool(_RE_QUANTITATIVO.search(janela)),
                    "pct_declarado": pcts[0] if pcts else None,
                    "trecho": C.trecho(texto, m.start(), m.end(), 160)})
    if not out:
        for m in _RE_ASSUMIR.finditer(texto):
            if C.no_corpo(texto, m.start()):
                janela = texto[max(0, m.start() - 3000): m.end() + 3000]
                pcts = [C.pct_br(p) for p in _RE_PCT.findall(texto[m.end(): m.end() + 4000])]
                out.append({"tipo": "assumir", "contratos_absorvidos": [], "lotes": [], "proprio": sorted(proprios),
                            "quantitativo": bool(_RE_QUANTITATIVO.search(janela)),
                            "pct_declarado": pcts[0] if pcts else None,
                            "trecho": C.trecho(texto, m.start(), m.end(), 200)})
                break
    return out


def grau(oc: dict) -> str:
    if oc["tipo"] == "absorcao" and (oc["contratos_absorvidos"] or oc["lotes"]) and oc["quantitativo"]:
        return "forte"
    return "medio"


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_termo_aditivo": 0, "termos_lidos": 0, "termos_sem_texto": 0,
             "termos_alheios": 0, "com_ocorrencia": 0}
    achados = []
    for tag, p in idx.items():
        if not any(C.eh_termo_aditivo(d) for d in p["docs"]):
            continue
        funil["com_termo_aditivo"] += 1
        termos, fora = C.termos_do_processo(p)
        funil["termos_alheios"] += fora["alheios"]
        funil["termos_sem_texto"] += fora["sem_texto"]
        funil["termos_lidos"] += len(termos)
        melhores = [(d, oc) for d, t in termos for oc in analisar_texto(t, d.get("titulo") or "")]
        if not melhores:
            continue
        funil["com_ocorrencia"] += 1
        melhores.sort(key=lambda x: (grau(x[1]) != "forte", -(len(x[1]["contratos_absorvidos"]) + len(x[1]["lotes"]))))
        d, oc = melhores[0]
        chave = C.chave_de_tag(tag)
        alvo = ", ".join(f"Contrato {c}" for c in oc["contratos_absorvidos"]) or \
            (", ".join(f"lote {l}" for l in oc["lotes"]) or "unidades de outro contrato")
        achados.append(C.achado(
            chave, grau(oc),
            prova=f"doc {d['i']} ({d['titulo'][:90]}) — \"{oc['trecho']}\"",
            porque=(f"Termo aditivo traz para o contrato o objeto de {alvo}"
                    + (f", declarado como acréscimo de {oc['pct_declarado']:.2f}%" if oc["pct_declarado"] is not None else "")
                    + ". Hipóteses inocentes: continuidade de serviço essencial (cabe emergencial/nova licitação, não "
                      "aditivo); absorção do próprio contrato (excluída pelo número). O percentual declarado mede o valor "
                      "do termo, não o objeto: conferir quantitativo e faturamento antes × depois "
                      "(padrão acrescimo_medido_pelo_objeto)."),
            fonte=f"{d['fonte']}:{tag}#{d['i']}",
            contratos_absorvidos=oc["contratos_absorvidos"], lotes_absorvidos=oc["lotes"],
            contrato_proprio=oc["proprio"], pct_declarado=oc["pct_declarado"],
            n_termos_com_ocorrencia=len(melhores)))
    cobertura = {"termos_sem_texto": funil["termos_sem_texto"], "termos_alheios_descartados": funil["termos_alheios"],
                 "nota": "processo sem termo aditivo no acervo não foi avaliado (não é 'sem achado')"}
    return C.resultado(ID, funil["com_termo_aditivo"], cobertura, achados, funil)
