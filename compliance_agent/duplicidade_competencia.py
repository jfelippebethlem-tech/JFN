# -*- coding: utf-8 -*-
"""Detector DETERMINÍSTICO de duplicidade de pagamento em contrato contínuo (cobertura de competência).

Nasceu do caso ITERJ→MGS (contrato 005/2021): um detector naive de "mês pago 2×" gera FALSO-POSITIVO por
(a) lag de pagamento, (b) dezembro lag-0 (fechamento de exercício), (c) reajuste-complemento (parcela
pequena), (d) split de desembolso (MESMO empenho/RE), (e) retroativo de repactuação. A regra robusta
reconcilia pela VIDA do contrato e só sinaliza o EXCEDENTE LÍQUIDO / mês dobrado SEM vizinho ausente.
Smoking gun real = mesma Nota Fiscal em 2 OBs (fora do alcance do grid; vira "verificar NF").

Ver [[casos/iterj-mgs-clean-pagamentos]] e [[aprendizados/duplicidade-ob-competencia-vs-valor]].
"""
from __future__ import annotations

from collections import defaultdict


def _money(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _comp_mm_aaaa(c: str) -> str:
    """Normaliza competência p/ 'MM/AAAA' (SIAFE 1 vem 'DD/MM/AAAA', SIAFE 2 vem 'MM/AAAA')."""
    c = (c or "").strip()
    if len(c) == 10 and c[2] == "/":
        return c[3:10]
    return c


def _mes_idx(comp: str) -> int | None:
    try:
        mm, aaaa = comp.split("/")
        return int(aaaa) * 12 + int(mm)
    except Exception:
        return None


def detectar(obs: list[dict], favorecido: str = "", orgao: str = "") -> list[dict]:
    """`obs`: dicts com competencia, valor, re, pd (nl/numero_ob opcionais).
    Retorna red flags {favorecido,orgao,competencia,tipo_indicio,severidade,evidencia}. Indício ≠ acusação.
    """
    norm = []
    for o in obs:
        norm.append({
            "comp": _comp_mm_aaaa(o.get("competencia")), "val": _money(o.get("valor")),
            "re": o.get("re") or "", "pd": o.get("pd") or "", "nl": o.get("nl") or "",
            "ob": o.get("numero_ob") or "",
        })
    if not norm:
        return []
    by_comp: dict[str, list] = defaultdict(list)
    for x in norm:
        by_comp[x["comp"]].append(x)
    # tarifa mensal modal (mês com 1 OB) — base p/ "pequeno" e "patamar"
    base = [c[0]["val"] for c in (v for v in by_comp.values()) if len(c) == 1]
    modal = sorted(base)[len(base) // 2] if base else 0.0
    meses = sorted(m for m in (_mes_idx(c) for c in by_comp) if m is not None)
    presentes = set(meses)

    flags = []
    n_logicos = 0
    for comp, lst in by_comp.items():
        grandes = [x for x in lst if x["val"] >= max(20000.0, 0.25 * modal)]
        pequenos = [x for x in lst if x not in grandes]
        n_log = len(set(x["re"] for x in grandes)) or len(grandes)
        n_logicos += n_log
        if len(lst) == 1:
            continue
        # (d) split: mesmo RE → 1 evento, benigno
        if len(set(x["re"] for x in lst)) == 1:
            continue
        # (c) reajuste-complemento: a 2ª parcela é pequena
        if pequenos and len(grandes) <= 1:
            continue
        # mês dobrado com REs distintos: olha o vizinho ausente (timing/má-atribuição)
        mi = _mes_idx(comp)
        vizinho_vazio = mi is not None and ((mi - 1) not in presentes or (mi + 1) not in presentes)
        sev = "baixa" if vizinho_vazio else "media"
        ev = (f"{len(grandes)} OBs de R$ {grandes[0]['val']:,.2f}~ na competência {comp} com REs/PDs distintos "
              f"({', '.join(x['re'] for x in grandes)}). "
              + ("Mês vizinho AUSENTE → provável recuperação de mês atrasado (timing); " if vizinho_vazio
                 else "SEM vizinho ausente → "))
        ev += "confirmar pela Nota Fiscal o mês-base de serviço de cada OB (mesma NF = duplicidade)."
        flags.append({
            "favorecido": favorecido, "orgao": orgao, "competencia": comp,
            "tipo_indicio": "competencia_dobrada", "severidade": sev, "evidencia": ev,
        })
    # excedente líquido sobre a vida do contrato (nº meses lógicos vs nº meses-calendário do span)
    span = (max(meses) - min(meses) + 1) if meses else 0
    excedente = n_logicos - span
    if excedente >= 1 and span:
        flags.insert(0, {
            "favorecido": favorecido, "orgao": orgao, "competencia": "—",
            "tipo_indicio": "excedente_liquido", "severidade": "media" if excedente >= 2 else "baixa",
            "evidencia": (f"{n_logicos} pagamentos mensais lógicos para {span} meses de vigência (Δ +{excedente}). "
                          f"Verificar se o excedente é retroativo de repactuação/aditivo (benigno) ou pagamento extra. "
                          f"Indício ≠ acusação."),
        })
    return flags
