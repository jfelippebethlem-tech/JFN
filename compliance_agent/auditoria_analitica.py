# -*- coding: utf-8 -*-
"""Audit analytics / forensic accounting para o JFN — técnicas estatísticas de triagem de INDÍCIO
(nunca acusação): Lei de Benford (MAD/bandas Nigrini), Relative Size Factor (RSF), round-number,
outlier robusto (modified z-score), e Same-Same-Different (duplicata refinada).

Honestidade: estatística = INDÍCIO/triagem, jamais CONFIRMADO isolado; desvio ≠ irregularidade.
Pré-condições respeitadas (Benford exige base ampla, não-sequencial, N≥~300). Sem dep nova (numpy/stdlib).
Pesquisa-fonte: data/sei_cache/pesquisa_audit_analytics.md. Ver [[codigo/lex-auditoria-contrato]].
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

# bandas de conformidade MAD (Nigrini) — 1º dígito
_MAD_BANDAS_1D = [(0.006, "conforme"), (0.012, "aceitável"), (0.015, "marginal"), (float("inf"), "NÃO-CONFORME")]


def _vals(xs):
    return [abs(float(x)) for x in xs if x is not None and abs(float(x)) > 0]


def benford_1d(valores: list) -> dict:
    """Lei de Benford no 1º dígito. Retorna {n, mad, faixa, esperado, observado, picos}. INDÍCIO se MAD alto."""
    v = [x for x in _vals(valores) if x >= 1]
    n = len(v)
    if n < 300:
        return {"ok": False, "motivo": f"N={n} < 300 (Benford exige base ampla)", "n": n}
    obs = Counter(int(str(x).lstrip("0.")[0]) for x in v if str(x).lstrip("0.")[:1].isdigit())
    esp = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
    ap = {d: obs.get(d, 0) / n for d in range(1, 10)}
    mad = sum(abs(ap[d] - esp[d]) for d in range(1, 10)) / 9
    faixa = next(nome for lim, nome in _MAD_BANDAS_1D if mad <= lim)
    # dígitos com maior excesso (z aproximado)
    picos = sorted(((d, ap[d] - esp[d]) for d in range(1, 10)), key=lambda t: -abs(t[1]))[:3]
    return {"ok": True, "n": n, "mad": round(mad, 5), "faixa": faixa,
            "esperado": {d: round(esp[d], 3) for d in range(1, 10)},
            "observado": {d: round(ap[d], 3) for d in range(1, 10)},
            "picos": [(d, round(delta, 3)) for d, delta in picos]}


def rsf(obs: list, chave="favorecido", valor="valor") -> list:
    """Relative Size Factor: maior/2º-maior valor por subset. RSF alto = lançamento fora de escala (erro de
    casa decimal, pagamento de outro grupo). Retorna subsets com RSF >= 10 (suspeitos)."""
    grupos = defaultdict(list)
    for o in obs:
        grupos[o.get(chave)].append(abs(float(o.get(valor) or 0)))
    out = []
    for k, vs in grupos.items():
        vs = sorted((x for x in vs if x > 0), reverse=True)
        if len(vs) >= 2 and vs[1] > 0:
            r = vs[0] / vs[1]
            if r >= 10:
                out.append({"subset": k, "rsf": round(r, 1), "maior": vs[0], "segundo": vs[1]})
    return sorted(out, key=lambda x: -x["rsf"])


def round_number(valores: list) -> dict:
    """Frequência de valores 'redondos' (múltiplos de 1.000 / 100) vs esperado. Excesso = indício."""
    v = _vals(valores)
    n = len(v)
    if not n:
        return {"n": 0}
    mil = sum(1 for x in v if abs(x - round(x / 1000) * 1000) < 0.01)
    cem = sum(1 for x in v if abs(x - round(x / 100) * 100) < 0.01)
    return {"n": n, "mult_1000": mil, "pct_1000": round(mil / n, 3), "mult_100": cem, "pct_100": round(cem / n, 3)}


def outliers_mod_z(obs: list, valor="valor", corte=3.5) -> list:
    """Outliers por modified z-score (robusto): Mi = 0.6745*(x-med)/MAD; |Mi|>corte = outlier."""
    xs = [(o, abs(float(o.get(valor) or 0))) for o in obs if o.get(valor)]
    v = sorted(x for _, x in xs)
    if len(v) < 5:
        return []
    med = v[len(v) // 2]
    mad = sorted(abs(x - med) for x in v)[len(v) // 2] or 1e-9
    out = []
    for o, x in xs:
        mi = 0.6745 * (x - med) / mad
        if abs(mi) > corte:
            out.append({"ob": o.get("numero_ob"), "valor": x, "mod_z": round(mi, 1)})
    return sorted(out, key=lambda x: -abs(x["mod_z"]))


def ssd(obs: list, cnpj="favorecido_cpf", valor="valor", doc="numero_ob", data="data_emissao") -> list:
    """Same-Same-Different: mesmo (cnpj,valor) com documentos distintos (candidato a duplicidade)."""
    g = defaultdict(list)
    for o in obs:
        g[(o.get(cnpj), round(abs(float(o.get(valor) or 0)), 2))].append(o)
    out = []
    for (c, val), grp in g.items():
        docs = {o.get(doc) for o in grp}
        if len(grp) >= 2 and len(docs) >= 2 and val > 0:
            out.append({"cnpj": c, "valor": val, "n_obs": len(grp), "docs": sorted(str(d) for d in docs)})
    return sorted(out, key=lambda x: -x["valor"])
