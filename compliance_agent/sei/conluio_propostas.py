# -*- coding: utf-8 -*-
"""Detector de CONLUIO entre propostas de uma mesma licitação (bid-rigging) — Onda 5/extra.

Pedido do dono: avaliar propostas que indicam concorrência fraudulenta (combinada):
  (1) MARKUP UNIFORME — proposta B = proposta A com o MESMO percentual em TODA a lista (ex.: B = A−5% item a
      item). Diferença percentual constante entre listas inteiras é forte indício de proposta-cobertura.
  (2) PREÇOS QUASE IDÊNTICOS entre concorrentes.
  (3) TEXTO MUITO SIMILAR entre propostas de empresas diferentes (mesmo redator / cópia).

Tudo INDÍCIO a verificar, nunca prova (presunção de legitimidade). Fundamento: Art. 90 Lei 8.666/Art. 337-F CP
(frustrar/fraudar licitação), Art. 36 Lei 12.529/2011 (CADE — conluio), red flags ACFE/TCU (propostas-cobertura).
Opera sobre os itens extraídos (extrator_precos) + texto das propostas — sem rede.
"""
from __future__ import annotations

import re
import statistics
import unicodedata


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s)


def _chave_item(desc: str) -> str:
    """Chave para casar o MESMO item entre propostas (descrição normalizada, 1as palavras significativas)."""
    toks = [w for w in _n(desc).split() if len(w) > 3]
    return " ".join(toks[:6])


def _ratios(itens_a: list[dict], itens_b: list[dict]) -> list[float]:
    """Razões vu_B/vu_A dos itens casados por descrição (preço unitário > 0 nos dois)."""
    mapa_a = {}
    for it in itens_a:
        k = _chave_item(it.get("descricao", ""))
        v = it.get("valor_unitario")
        if k and isinstance(v, (int, float)) and v > 0:
            mapa_a.setdefault(k, v)
    out = []
    for it in itens_b:
        k = _chave_item(it.get("descricao", ""))
        v = it.get("valor_unitario")
        if k in mapa_a and isinstance(v, (int, float)) and v > 0:
            out.append(v / mapa_a[k])
    return out


def markup_uniforme(itens_a: list[dict], itens_b: list[dict], min_itens: int = 3, cv_max: float = 0.02) -> dict | None:
    """Detecta diferença percentual ~constante entre as duas listas inteiras. Retorna {pct, n, cv} ou None."""
    r = _ratios(itens_a, itens_b)
    if len(r) < min_itens:
        return None
    media = statistics.mean(r)
    cv = (statistics.pstdev(r) / media) if media else 1.0
    # razão quase constante (cv baixo) e diferente de 1 (não é o mesmo preço por acaso)
    if cv <= cv_max and abs(media - 1.0) > 0.005:
        return {"pct": round((media - 1.0) * 100, 2), "n_itens": len(r), "cv": round(cv, 4)}
    return None


def precos_identicos(itens_a: list[dict], itens_b: list[dict], min_itens: int = 3, tol: float = 0.001) -> dict | None:
    """Itens com preço praticamente IGUAL entre as duas propostas (suspeito entre concorrentes)."""
    r = _ratios(itens_a, itens_b)
    if len(r) < min_itens:
        return None
    iguais = sum(1 for x in r if abs(x - 1.0) <= tol)
    if iguais >= max(min_itens, int(0.8 * len(r))):
        return {"iguais": iguais, "n_itens": len(r), "frac": round(iguais / len(r), 2)}
    return None


def texto_similar(texto_a: str, texto_b: str, limiar: float = 0.85) -> dict | None:
    """Similaridade de Jaccard (tokens) entre dois textos de proposta. Alta = mesmo redator/cópia."""
    ta = set(w for w in _n(texto_a).split() if len(w) > 3)
    tb = set(w for w in _n(texto_b).split() if len(w) > 3)
    if len(ta) < 20 or len(tb) < 20:
        return None
    j = len(ta & tb) / len(ta | tb)
    if j >= limiar:
        return {"jaccard": round(j, 3)}
    return None


def detectar(propostas: list[dict]) -> dict:
    """propostas = [{fornecedor, cnpj, itens:[{descricao,valor_unitario}], texto?}]. Compara par a par.
    Retorna {ok, n_propostas, indicios:[{tipo, a, b, ...}], _nota}. Indício, nunca acusação."""
    props = [p for p in (propostas or []) if p.get("itens") or p.get("texto")]
    indicios = []
    for i in range(len(props)):
        for j in range(i + 1, len(props)):
            a, b = props[i], props[j]
            na = a.get("fornecedor") or a.get("cnpj") or f"#{i}"
            nb = b.get("fornecedor") or b.get("cnpj") or f"#{j}"
            mu = markup_uniforme(a.get("itens", []), b.get("itens", []))
            if mu:
                indicios.append({"tipo": "markup_uniforme", "a": na, "b": nb, **mu,
                                 "obs": f"{nb} = {na} {mu['pct']:+.1f}% em {mu['n_itens']} itens (cv={mu['cv']}) — "
                                        "diferença percentual ~constante em toda a lista: indício de proposta-cobertura "
                                        "(Art. 90 Lei 8.666/Art. 337-F CP; Art. 36 Lei 12.529/CADE)."})
            pid = precos_identicos(a.get("itens", []), b.get("itens", []))
            if pid:
                indicios.append({"tipo": "precos_identicos", "a": na, "b": nb, **pid,
                                 "obs": f"{pid['iguais']}/{pid['n_itens']} itens com preço idêntico entre concorrentes."})
            ts = texto_similar(a.get("texto", ""), b.get("texto", ""))
            if ts:
                indicios.append({"tipo": "texto_similar", "a": na, "b": nb, **ts,
                                 "obs": f"propostas com texto {ts['jaccard']*100:.0f}% similar — mesmo redator/cópia (verificar)."})
    return {"ok": True, "n_propostas": len(props), "indicios": indicios,
            "_nota": "Indício de conluio a verificar (presunção de legitimidade) — nunca prova. "
                     "Fundamento: Art. 90 Lei 8.666/Art. 337-F CP, Art. 36 Lei 12.529/2011 (CADE), ACFE/TCU."}
