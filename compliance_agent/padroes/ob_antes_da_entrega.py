# -*- coding: utf-8 -*-
"""Liquidação sobre fatura PRÓ-FORMA / "importação em andamento" e OB paga antes de qualquer recebimento nos autos.

ORIGEM (perícia por agente, 18/11/2026):
  · CBMERJ × Angloco, SEI-270006/012128/2024: doc 126 — "Documento de cobrança: SEI n° (Proforma Invoice 111256454)
    Valor total a liquidar: R$ 22.000.000,00"; NL "Reconhecimento de importaçao em andamento"; nenhum termo de
    recebimento das 10 viaturas no processo.
  · PMERJ fuzis (CZ), SEI-350006/002721/2025: NL 2025NL02598 com documento comprobatório = proforma "12522397";
    "O serviço foi devidamente atestado, certificado e liquidado".
  · SEIOP × POMA, SEI-330001/001798/2025: contrato inteiro liquidado em 2024 antes de qualquer entrega.
FALSO POSITIVO CONHECIDO: carta de crédito de importação (SWIFT MT700) — o Estado deposita no banco garantidor e o
banco só paga ao exportador contra documentos de embarque; quando o recebimento vem depois nos autos (Jacinto
Marques, SEI-270006/021632/2025: ARM 753/26 e vistoria com chassis conferidos) o pagamento antes da entrega é o
DESENHO da operação, não vício. Separado por código (`classificar`).

SINAL: documento de LIQUIDAÇÃO (título: solicitação/formalização de liquidação, Nota de Liquidação) cujo texto diz
"pro forma"/"proforma" ou "importação em andamento" + OB PAGA no SIAFE. Grau:
  · forte  = nenhum documento de recebimento nos autos (termo de recebimento, atestado de recebimento de material,
             vistoria, termo de aceite) e sem carta de crédito;
  · medio  = sem recebimento mas COM carta de crédito (pagamento condicionado ao banco; entrega não comprovada), ou
             recebimento só DEPOIS da 1ª OB sem carta de crédito;
  · fora   = recebimento antes da 1ª OB (entregue antes de pagar) ou carta de crédito + recebimento posterior
             (Jacinto) — contados em `cobertura`.
Norma: Lei 4.320/1964 art. 62 e 63 §2º; Lei 14.133/2021 art. 145 (vedação de pagamento antecipado; §1º exceções).
Indício para requerer documentos, não acusação: a entrega pode estar provada em outro processo (pedir o termo).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _pagamento_comum as C

ID = "ob_antes_da_entrega"

TIT_LIQ = re.compile(r"liquida[cç][aã]o|\b\d{4}NL\d{5}\b|nota de liquida", re.I)
TIT_RECEB = re.compile(r"termo de recebimento|recebimento (provis[oó]rio|definitivo)|atestado de recebimento|"
                       r"\bARM\b|vistoria|termo de aceite|aceite definitivo", re.I)
TIT_CC = re.compile(r"carta de cr[eé]dito|letter of credit|FIN\s*700|MT\s?700|swift|documentary credit", re.I)
TIT_ALVO = re.compile("|".join(x.pattern for x in (TIT_LIQ, TIT_RECEB, TIT_CC)), re.I)
_RE_PROFORMA = re.compile(r"pr[oó][\s-]?forma|importa[cç][aã]o\s+em\s+andamento", re.I)
_RE_CC_TXT = re.compile(r"carta de cr[eé]dito|letter of credit|MT\s?700|documentary credit", re.I)
_RE_DATA_NL = re.compile(r"\b(\d{2}/\d{2}/\d{2,4})\b")


_RE_RECEB_TXT = re.compile(
    r"conformidade\s+d[oa]s?\s+(?:material|materiais|bens?|equipamentos?|viaturas?|ve[ií]culos?)\s+atestada|"
    r"atest\w*\s+(?:o|a)\s+(?:recebimento|conformidade)(?!\s+d[aoe]s?\s+(?:nota|empenho|NE\b|of[ií]cio|documento))|"
    r"(?:foram|foi)\s+recebid[oa]s?\s+(?:pela|por)\s+comiss|"
    r"recebimento\s+(?:provis[oó]rio|definitivo)\s+(?:foi\s+)?realizado", re.I)
# Documentos que DESCREVEM o recebimento como regra futura (cláusula), não como fato: não contam.
_TIT_NAO_ATO = re.compile(r"contrato|\bata\b|edital|termo de refer|proposta|minuta|parecer|decreto|justificativa|"
                          r"\bCTT\b|carta de cr|FIN\s*700|pedido de abertura|empenho|\bNE\b", re.I)


def _data_doc(texto: str):
    d = C.data_do_atesto(texto)
    if d:
        return d
    for x in _RE_DATA_NL.findall(texto[:1500]):
        x = x if len(x) == 10 else x[:6] + "20" + x[6:]
        if (dd := C.data_br(x)) and 2000 < dd.year < 2100:
            return dd
    return None


_RE_PROFORMA_NUM = re.compile(r"pr[oó][\s-]?forma\s+invoice\s*(?:n[oº°.]*|number|#)?\s*[:.]?\s*([A-Z0-9/.-]{4,20})", re.I)
_RE_NL = re.compile(r"\b(\d{4}NL\d{5})\b")
_RE_UG = re.compile(r"\b(\d{6})\s*-\s*[A-ZÀ-Ú]")


def _pasta(pasta, man, sel):
    liq, receb, cc = [], [], False
    # Pró-forma juntada como documento próprio: a NL a cita só pelo NÚMERO ("Documentos Comprobatórios … 12522397",
    # PMERJ × CZ) ou pelo id SEI — a palavra "proforma" não aparece na NL.
    marcas: set[str] = set()
    for d in C.docs(man):
        tit = str(d.get("titulo") or "")
        if re.search(r"pr[oó][\s-]?forma", tit, re.I):
            m = re.search(r"\((\d{7,10})\)\s*$", tit)
            if m:
                marcas.add(m[1])
            t = C.ler(pasta, man, d, teto=6000)
            marcas |= {x.strip(".-/") for x in _RE_PROFORMA_NUM.findall(t) if re.search(r"\d{4}", x)}
    nls, ugs = set(), set()
    for d in sel:
        tit = str(d.get("titulo") or "")
        if TIT_CC.search(tit):
            cc = True
        if TIT_RECEB.search(tit):
            t = C.ler(pasta, man, d, teto=20000)
            receb.append({"doc": C.numero_doc(d), "titulo": tit[:100], "data": _data_doc(t)})
        elif TIT_LIQ.search(tit):
            t = C.ler(pasta, man, d, teto=20000)
            m = _RE_PROFORMA.search(t)
            if not m:
                for mk in marcas:
                    if (i := t.find(mk)) >= 0:
                        m = re.compile(re.escape(mk)).search(t, i)
                        break
            if m:
                liq.append({"doc": C.numero_doc(d), "titulo": tit[:100], "data": _data_doc(t),
                            "trecho": C.trecho(t, m.start(), m.end(), 110)})
            nls |= set(_RE_NL.findall(t)) | set(_RE_NL.findall(tit))
            ugs |= set(_RE_UG.findall(t))
            if not cc and _RE_CC_TXT.search(t):
                cc = True
    if not liq:
        return [], {}
    # Recebimento declarado no CORPO de manifestação/despacho (ITURRI × CBMERJ, SEI-270005/000992/2025, doc 15: "a
    # conformidade do material atestada pela Comissão de Fiscalização (SEI nº 129726203)") — o título não diz.
    for d in C.docs(man):
        tit = str(d.get("titulo") or "")
        if TIT_RECEB.search(tit) or _TIT_NAO_ATO.search(tit):
            continue
        t = C.ler(pasta, man, d, teto=30000)
        m = _RE_RECEB_TXT.search(t)
        if m:
            receb.append({"doc": C.numero_doc(d), "titulo": tit[:100], "data": _data_doc(t),
                          "trecho": C.trecho(t, m.start(), m.end(), 80)})
    return [{"tag": pasta.name, "liq": liq, "receb": receb, "cc": cc, "nls": sorted(nls), "ugs": sorted(ugs)}], \
        {"liquidacao_proforma": 1}


def classificar(primeira_ob, receb: list[dict], cc: bool) -> str | None:
    datas = [r["data"] for r in receb if r.get("data")]
    if receb and not datas:
        return None                     # há recebimento sem data legível: não se afirma ordem — fica fora
    if datas and primeira_ob and min(datas) <= primeira_ob:
        return None                     # entregue antes de pagar
    if not receb:
        return "medio" if cc else "forte"
    return None if cc else "medio"      # recebimento posterior: com carta de crédito é o desenho (Jacinto)


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    brutos, cob, n = C.varrer_acervo(TIT_ALVO, _pasta, so=so, limite=limite)
    con = C.con_ro()
    obs = C.obs_pagas(con, [C.processo(b["tag"]) for b in brutos])
    con.close()
    achados = []
    for b in brutos:
        proc = C.processo(b["tag"])
        ob_p, via = obs.get(proc, []), "campo processo da OB"
        if not ob_p and b["nls"]:
            con = C.con_ro()
            ob_p, via = C.obs_por_nl(con, set(b["nls"]), set(b["ugs"])), "NL citada nos autos × UG dos autos"
            con.close()
        if not ob_p:
            cob["sem_ob_paga"] = cob.get("sem_ob_paga", 0) + 1
            continue
        datas_ob = sorted(((C.data_br(o["data_emissao"]), o) for o in ob_p if C.data_br(o["data_emissao"])), key=lambda x: x[0])
        primeira = datas_ob[0][0] if datas_ob else None
        g = classificar(primeira, b["receb"], b["cc"])
        if not g:
            chave = "fora_carta_credito_com_recebimento" if b["cc"] and b["receb"] else "fora_recebido_antes_ou_sem_data"
            cob[chave] = cob.get(chave, 0) + 1
            continue
        l0 = b["liq"][0]
        rec = "; ".join(f"{r['doc']} {r['data']:%d/%m/%Y}" if r.get("data") else r["doc"] for r in b["receb"][:4])
        achados.append({
            "processo": proc, "grau": g, "carta_de_credito": b["cc"],
            "credor": C.credor_nome(ob_p),
            "prova": (f"{l0['doc']} ({l0['titulo']}) — \"{l0['trecho']}\"; 1ª OB paga "
                      f"{datas_ob[0][1]['numero_ob'] if datas_ob else '?'} de {primeira:%d/%m/%Y}" if primeira else "")
                     + ("; recebimento nos autos: " + rec if rec else "; nenhum termo de recebimento nos autos"),
            "valor_pago_ob": C.pago(ob_p), "ob_via": via,
            "porque": ("liquidação apoiada em pró-forma/importação em andamento e OB paga sem recebimento anterior nos "
                       "autos; inocentes não excluídas: entrega provada em outro processo; antecipação do art. 145 §1º "
                       "com garantia" + ("; carta de crédito — o banco só libera contra documentos" if b["cc"] else "")),
            "fonte": "data/sei_arquivo (liquidação, recebimento, carta de crédito pelo título) × ob_orcamentaria_siafe/_ob_paga (piso)"})
    return C.resultado(ID, n, cob, achados, "data/sei_arquivo × SIAFE")
