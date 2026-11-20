"""preco_de_fonte_unica_interessada — estimativa de preço apoiada numa fonte só, ou na tabela do próprio vendedor.

Origem: CDEL (SEI-420001/003312/2024): TR — "a SEGOV localizou apenas a coleção 'Cidadania Hoje – Direitos das
Mulheres'" e "preços de capa das coleções avaliadas, no site das respectivas editoras" (preço = capa fixada pela
editora); STEM (SEI-420001/006323/2025): "levantamento do preço estimado … com base no valor unitário do kit …
conforme disponibilizado no sítio eletrônico https://www.educarmelhor.com/…" (site da distribuidora cliente da gráfica).

Sinais (modo verbal de ATO — "foi realizado", "localizou" — não a cláusula que manda pesquisar):
  F1 fonte_unica      — o texto afirma uma fonte só: "localizou apenas", "único orçamento", "apenas uma cotação"…
  F2 base_do_vendedor — a estimativa foi feita "com base" em site/tabela/catálogo/preço de capa/proposta da própria
                        empresa (fonte interessada: art. 23 §1º e §4º da Lei 14.133 — na contratação direta, o preço
                        se justifica por notas fiscais emitidas a OUTROS contratantes).
Grau: F1 + F2 → forte; F2 só → médio; F1 só → FRACO. 1ª varredura (19/11/2026): os 16 F1 isolados eram, em regra,
UMA das fontes da cesta ("Foi encontrado apenas 01 resultado" no TCE-RJ, "identificou apenas um curso") — não a
estimativa inteira; sem F2 não sustenta médio.
Só em TR/ETP/pesquisa/despacho de estimativa (não em edital-modelo).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _carona_comum as cc

ID = "preco_de_fonte_unica_interessada"
VICIO = "sobrepreco_estimativa"  # knowledge/catalogo_vicios.py
# documentos onde a estimativa mora: TR/ETP/pesquisa e, entre os "outros", os de título de estimativa/justificativa
_RX_TIT_ESTIM = re.compile(r"estimativa|pre[cç]o|cota[cç]|mapa|justificativa|informa[cç][aã]o d[ae] contrata|"
                           r"or[cç]amento|planilha estimativa", re.I)

RX_F1 = re.compile(
    r"(?:localizou|localizad[oa]s?|identificou|encontrou|encontrad[oa]s?|obteve|obtid[oa]s?|recebe(?:u|mos)|"
    r"retorn\w+)\s+(?:se\s+)?(?:apenas|somente|unicamente|s[óo])\s+(?:a|o|um|uma|01|1)\b[^.;]{0,120}"
    r"|(?:apenas|somente)\s+(?:um|uma|01|1)\s*(?:\(\w+\)\s*)?(?:or[çc]amento|cota[çc][ãa]o|proposta\s+de\s+pre[çc]o|fonte)"
    r"[^.;]{0,80}?(?:foi|foram|obtid|recebid|apresentad|encaminhad|retorn)"
    r"|(?:[úu]nic[oa])\s+(?:or[çc]amento|cota[çc][ãa]o|fonte\s+de\s+pre[çc]o)\s+(?:obtid|recebid|apresentad|v[áa]lid|dispon[íi]vel)",
    re.I)
RX_F2 = re.compile(
    r"(?:pre[çc]o|valor)\s+(?:estimad[oa]|de\s+refer[êe]ncia|da\s+contrata[çc][ãa]o)[^.;]{0,120}?"
    r"(?:foi|foram)?\s*(?:realizad[oa]|feit[oa]|obtid[oa]|elaborad[oa]|definid[oa]|calculad[oa]|apurad[oa])?\s*"
    r"com\s+base\s+(?:no|na|nos|nas|em)\s+[^.;]{0,160}?"
    r"(?:s[íi]tio\s+eletr[ôo]nico|site\b|https?://|www\.|tabela\s+(?:de\s+pre[çc]os\s+)?d[ao]\s+(?:pr[óo]pri[ao]\s+)?"
    r"(?:editora|fornecedor|fabricante|empresa|distribuidor)|cat[áa]logo|pre[çc]o\s+de\s+capa|valor\s+de\s+capa|"
    r"proposta\s+(?:apresentada\s+)?(?:pela|da)\s+(?:pr[óo]pria\s+)?(?:empresa|contratad|fornecedor|editora))"
    r"|pre[çc]os?\s+de\s+capa\s+[^.;]{0,80}?(?:no\s+site|n[oa]\s+s[íi]tio|fixad[oa]|d[ao]s?\s+(?:respectiv[ao]s?\s+)?editoras?)",
    re.I)
# frase de REGRA (pesquisa a fazer) e não de ato: "deverá", "poderá", "será"
RX_NORMA = re.compile(r"(?:dever[áa]|poder[áa]|ser[áa]|dever[ãa]o|poder[ãa]o|vedad|n[ãa]o\s+(?:se\s+)?admit)\s*$", re.I)
_DOCS_OK = ("tr", "etp", "pesquisa", "outro")


def _norma_antes(texto: str, ini: int) -> bool:
    return bool(RX_NORMA.search(texto[max(0, ini - 50): ini].strip()))


def avaliar(ds: list[cc.Doc]) -> dict:
    f1 = f2 = None
    for d in ds:
        if cc.tipo_doc(d.titulo) not in _DOCS_OK:
            continue
        if not f1:
            for m in RX_F1.finditer(d.texto):
                if not _norma_antes(d.texto, m.start()):
                    f1 = f'{d.ref} ({d.titulo[:60]}) — "{cc.trecho(d.texto, m.start(), m.end(), 40)[:340]}"'
                    break
        if not f2:
            for m in RX_F2.finditer(d.texto):
                if not _norma_antes(d.texto, m.start()):
                    f2 = f'{d.ref} ({d.titulo[:60]}) — "{cc.trecho(d.texto, m.start(), m.end(), 40)[:380]}"'
                    break
    return {"fonte_unica": f1, "base_do_vendedor": f2}


def varrer(limite: int | None = None) -> dict:
    todos = cc.tags()[: limite or None]
    universo = sem_texto = sem_doc = 0
    brutos = []
    cc.refs_em_paralelo(todos)
    sel: dict[str, list] = {}
    for t in todos:
        rs = [r for r in cc.refs(t) if cc.tipo_doc(r.titulo) in ("tr", "etp", "pesquisa")
              or (cc.tipo_doc(r.titulo) == "outro" and _RX_TIT_ESTIM.search(cc.sem_acento(r.titulo)))]
        if rs:
            sel[t] = rs
        else:
            sem_doc += 1

    def _ler(t):
        return [d for d in (cc.ler(r) for r in sel[t]) if d]
    for t, ds in cc.em_paralelo(_ler, list(sel)):
        if not ds:
            sem_texto += 1
            continue
        universo += 1
        r = avaliar(ds)
        if r["fonte_unica"] or r["base_do_vendedor"]:
            brutos.append((t, r, ds))
    obs = cc.ob_pagas({cc.canon(t) for t, _, _ in brutos})
    achados = []
    for t, r, ds in brutos:
        ambos = bool(r["fonte_unica"] and r["base_do_vendedor"])
        ob = obs.get(cc.canon(t))
        provas = [f"{k}: {v}" for k, v in r.items() if v]
        achados.append({
            "processo": cc.canon(t), "grau": "forte" if ambos else ("medio" if r["base_do_vendedor"] else "fraco"),
            "sinal": "+".join(k for k, v in r.items() if v), "prova": " | ".join(provas),
            **cc.campos_ob(ds, ob),
            "porque": ("Inocente possível: produto autoral de editora única (preço de capa é o único preço público) ou "
                       "ata com desconto sobre tabela. Não afasta: art. 23 da Lei 14.133 pede cesta de preços e, na "
                       "contratação direta, notas fiscais do mesmo objeto vendidas a outros contratantes (§4º)."),
            "fonte": "SEI (TR/ETP/pesquisa) + SIAFE (_ob_paga, piso)"})
    cc.ligar(achados, VICIO)
    return cc.resultado(ID, universo, {"processos_no_acervo": len(todos), "sem_tr_etp_pesquisa_nos_autos": sem_doc,
                                       "sem_texto": sem_texto,
                                       "nota": "universo = processos com TR/ETP/pesquisa/estimativa juntados (por título); "
                                               "estimativa não juntada aos autos não é avaliável."}, achados)
