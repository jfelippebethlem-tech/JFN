"""inexigibilidade_bem_comum — contratação por inexigibilidade/exclusividade cujo próprio TR/ETP diz o contrário.

Origem: MVT (SEI-030001/056588/2025): inexigibilidade art. 74 I com TR item 1.4 "caracterizado como bem comum, em
razão de seus padrões serem facilmente definidos e encontrados no mercado"; Estudo Play (SEI-030001/064253/2025):
exclusividade com TR admitindo "outras editoras, desde que tenham características similares".

Sinais (contradição INTERNA — o processo afirma as duas coisas; trecho literal de cada lado):
  C1 bem_comum      — TR/ETP afirma que o objeto é comum, de padrões "facilmente definidos e encontrados no mercado".
  C2 outros_fornec  — TR/ETP admite outras editoras/fornecedores/marcas "similares"/"equivalentes".
Grau: C1 + C2 → forte; um só → médio (o C1 sozinho pode ser cópia do modelo de TR da AGU/PGE — por isso não basta).
Pré-condição: o processo se declara inexigibilidade (NE "06 - Inexigibilidade" ou fundamento no art. 74 / art. 25).
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _carona_comum as cc

ID = "inexigibilidade_bem_comum"
VICIO = "contratacao_direta_indevida"  # knowledge/catalogo_vicios.py
_RX_TIT_INEX = re.compile(r"inexigib|exclusividade", re.I)

RX_INEX = re.compile(
    r"\b0?6\s*-\s*Inexigibilidade|inexigibilidade[^.;]{0,160}?(?:art(?:igo)?\.?\s*74|art(?:igo)?\.?\s*25)"
    r"|(?:art(?:igo)?\.?\s*74|inciso\s+I,?\s+do\s+art(?:igo)?\.?\s*74)[^.;]{0,120}?inexigib", re.I)
RX_INCISO = re.compile(r"art(?:igo)?\.?\s*74\s*,?\s*(?:inciso\s*)?(I{1,3}|IV|V)\b|inciso\s+(I{1,3}|IV|V),?\s+do\s+art(?:igo)?\.?\s*74"
                       r"|art(?:igo)?\.?\s*25\s*,?\s*(?:inciso\s*)?(I{1,3})\b", re.I)
RX_COMUM = re.compile(
    r"(?:caracterizad[oa]\s+como|consider\w+\s+como|trata-se\s+de|enquadra-se\s+como|é)\s+(?:bem|servi[çc]o|objeto)?\s*"
    r"comu(?:m|ns)\s*,?\s*(?:[^.;]{0,40}?)(?:em\s+raz[ãa]o|uma\s+vez|pois|por(?:que|quanto)?|nos\s+termos|haja\s+vista)"
    r"[^.;]{0,140}?(?:facilmente|usuais\s+(?:no|de)\s+mercado|encontrad[oa]s?\s+no\s+mercado|especifica[çc][õo]es\s+usuais)",
    re.I)
RX_OUTROS = re.compile(
    r"(?:outr[oa]s|demais|divers[oa]s)\s+(?:editoras?|fornecedor(?:es|as)?|fabricantes?|marcas?|empresas?)"
    r"[^.;]{0,140}?(?:similar|equivalent|semelhant|atendam|desde\s+que|poder[ãa]o|possível|aceit|admit)"
    r"|(?:possível|poder[áa]|admit\w+|aceit\w+)[^.;]{0,80}?(?:outr[oa]s|demais)\s+(?:editoras?|fornecedor(?:es)?|fabricantes?|marcas?)",
    re.I)
# negação perto do sinal: "não se caracteriza como comum", "não há outras editoras"
RX_NEG = re.compile(r"\bn[ãa]o\s+(?:se\s+|é\s+|h[áa]\s+|existe\w*\s+|foram?\s+)?(?:\w+\s+){0,3}$"
                    # "a inexistência de outros fornecedores" (SEI-240002/003084/2025, 270006/012496/2025): é a
                    # JUSTIFICATIVA da exclusividade, o contrário do sinal — falso positivo virou regra
                    r"|\b(?:inexist[êe]ncia|aus[êe]ncia|nenhum\w*|sem)\s+(?:de\s+|d[eo]s?\s+)?$", re.I)
# a frase de exclusividade CITADA (in verbis do art. 74) não é TR afirmando nada
_DOCS_TR = ("tr", "etp")


def _negado(texto: str, ini: int) -> bool:
    return bool(RX_NEG.search(texto[max(0, ini - 40): ini]))


def avaliar(ds: list[cc.Doc]) -> dict | None:
    inex = None
    for d in ds:
        m = RX_INEX.search(d.texto)
        if m:
            inex = (d, m)
            break
    if not inex:
        return None
    inciso = None
    for d in ds:
        mi = RX_INCISO.search(d.texto)
        if mi and re.search(r"inexigib", d.texto[max(0, mi.start() - 300): mi.end() + 300], re.I):
            inciso = next(g for g in mi.groups() if g)
            break
    c1 = c2 = None
    for d in ds:
        if cc.tipo_doc(d.titulo) not in _DOCS_TR:
            continue
        if not c1:
            for m in RX_COMUM.finditer(d.texto):
                if not _negado(d.texto, m.start()):
                    c1 = f'{d.ref} ({d.titulo[:60]}) — "{cc.trecho(d.texto, m.start(), m.end(), 20)[:320]}"'
                    break
        if not c2:
            for m in RX_OUTROS.finditer(d.texto):
                if not _negado(d.texto, m.start()):
                    c2 = f'{d.ref} ({d.titulo[:60]}) — "{cc.trecho(d.texto, m.start(), m.end(), 60)[:360]}"'
                    break
    d0, m0 = inex
    return {"inexigibilidade": f'{d0.ref} — "{cc.trecho(d0.texto, m0.start(), m0.end(), 40)[:220]}"',
            "inciso": inciso, "bem_comum": c1, "outros_fornecedores": c2,
            "tem_tr": any(cc.tipo_doc(d.titulo) in _DOCS_TR for d in ds)}


def varrer(limite: int | None = None) -> dict:
    cache = cc.carregar_cache_ne()
    todos = cc.tags()[: limite or None]
    universo = sem_texto = sem_tr = ne06 = por_titulo = 0
    brutos = []
    cc.prefetch_ne(todos, cache)
    cc.refs_em_paralelo([t for t in todos if cc.codigo_mod(cache[t]) is None])
    pedidos = []
    for t in todos:
        cod = cc.codigo_mod(cc.modalidade_ne(t, cache))
        if cod == "06":
            ne06 += 1
            pedidos.append((t, _DOCS_TR + ("empenho",)))
        elif cod is None and cc.titulos_casam(t, _RX_TIT_INEX):
            por_titulo += 1
            pedidos.append((t, _DOCS_TR + ("empenho", "outro")))
    for t, ds in cc.docs_em_paralelo(pedidos):
        if not ds:
            sem_texto += 1
            continue
        r = avaliar(ds)
        if not r:
            continue
        universo += 1
        if not r["tem_tr"]:
            sem_tr += 1
            continue
        if r["bem_comum"] or r["outros_fornecedores"]:
            brutos.append((t, r, ds))
    obs = cc.ob_pagas({cc.canon(t) for t, _, _ in brutos})
    achados = []
    for t, r, ds in brutos:
        ambos = bool(r["bem_comum"] and r["outros_fornecedores"])
        grau = "forte" if ambos and r["inciso"] in (None, "I") else "medio"
        ob = obs.get(cc.canon(t))
        provas = [f"inexigibilidade: {r['inexigibilidade']}"]
        if r["bem_comum"]:
            provas.append(f"bem comum: {r['bem_comum']}")
        if r["outros_fornecedores"]:
            provas.append(f"outros fornecedores: {r['outros_fornecedores']}")
        achados.append({
            "processo": cc.canon(t), "grau": grau, "inciso_art74": r["inciso"],
            "sinal": "bem_comum+outros_fornecedores" if ambos else ("bem_comum" if r["bem_comum"] else "outros_fornecedores"),
            "prova": " | ".join(provas), "orgao": cc.orgao(ds), "credor": cc.credor_principal(ob),
            "valor_pago_ob": ob["total"] if ob else None, "obs": (ob or {}).get("obs", [])[:20],
            "porque": ("Inocente possível: o item 'bem comum' é cópia do modelo de TR (AGU/PGE) e a exclusividade está "
                       "provada por atestado de exclusividade/direito autoral juntado; 'outras editoras' pode ser só "
                       "referência de ISBN. Não afasta: o próprio TR declara mercado com vários fornecedores — exige "
                       "prova de inviabilidade de competição (art. 74 I e §1º da Lei 14.133)."),
            "fonte": "SEI (TR/ETP e NE dos autos) + SIAFE (_ob_paga, piso)"})
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    achados.sort(key=lambda a: (ordem[a["grau"]], -(a["valor_pago_ob"] or 0)))
    cc.ligar(achados, VICIO)
    return cc.resultado(ID, universo, {"processos_no_acervo": len(todos), "ne_06_inexigibilidade": ne06,
                                       "sem_ne_titulo_de_inexigibilidade": por_titulo,
                                       "sem_texto": sem_texto, "inexigibilidade_sem_tr_etp_nos_autos": sem_tr,
                                       "nota": "sem TR/ETP juntado não há o que contradizer — fica fora, não é 'limpo'."},
                        achados)
