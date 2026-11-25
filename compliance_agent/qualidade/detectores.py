# -*- coding: utf-8 -*-
"""Registro de quem afirma algo sobre terceiros — `config/qualidade_detectores.yaml`.

Cobra as regras COR-03 (controle positivo e negativo), COR-04 (falso positivo medido antes de manchete), COR-05
(hipótese inocente excluída por código) e COR-10 (domínio declarado). As dívidas viram catracas em
`tests/test_regra_controles_detector.py` (bases `detector_*` em `tests/golden/qualidade_base.json`).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ARQ = REPO / "config" / "qualidade_detectores.yaml"

CAMPOS = ("modulo", "simbolo", "afirma", "fonte", "grava", "consome", "manchete", "controle_positivo",
          "controle_negativo", "hipoteses_inocentes", "dominio", "fp_medida")
CAMPOS_FP = ("data", "amostra", "taxa", "fonte_primaria", "onde")
VEREDITOS = ("CONFIRMADA", "PARCIAL", "REFUTADA")
VALIDADE_FP = timedelta(days=180)
DIVIDAS = ("sem_controle_positivo", "sem_controle_negativo", "sem_hipotese_inocente", "sem_dominio",
           "manchete_sem_fp_medida", "refutado_em_manchete", "manchete_sem_tier1")
# O5.1 (plano mestre v2 §5): estado de vida da entrada e tier de confiabilidade.
#   ativo          há caminho de código que roda e grava/serve o achado (mesmo com a PARADA DE OBRAS)
#   sem_varredura  o código existe mas nada o roda em lote (só sob demanda) — não há achado acumulado
#   a_portar       regra única que vive num sweep/arquivo a aposentar; entra aqui para não sumir (mapa O1.2 §6)
#   fundido        mesma hipótese de outra entrada (`fundido_em`): a canônica é a outra
ESTADOS = ("ativo", "sem_varredura", "a_portar", "fundido")
# Tier 1 (manchete, alerta, dossiê) — TODOS: medida válida (≤ 180 d), n ≥ 30 decididos com amostra estratificada,
# ponto de FP ≤ 15%, limite superior do IC95 de Wilson ≤ 25%, elegibilidade (domínio declarado, COR-10/E9) e
# cobertura ≥ 50%. Tier 2 (sinal complementar): há medida com n ≥ 1 e falta alguma condição. Tier 3 (oculto): sem
# medida utilizável — ausente, incompleta, vencida ou sem contagem de decididos.
TIER1_N_MIN, TIER1_PONTO_MAX, TIER1_IC_MAX, TIER1_COBERTURA_MIN = 30, 0.15, 0.25, 0.50
CAMPOS_CALCULADOS = ("tier", "tier_motivo", "fp_ic95", "manchete_efetiva")   # gravados por tools/registro_tiers.py
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@lru_cache(maxsize=8)
def _ler(caminho: str, _mtime: float) -> dict:
    return yaml.load(Path(caminho).read_text(encoding="utf-8"), Loader=_Loader)["detectores"]


def carregar(arq: Path = ARQ) -> dict:
    """id → entrada do registro (cache por mtime; não altere o dict devolvido)."""
    return _ler(str(arq), Path(arq).stat().st_mtime)


def _tem_simbolo(texto: str, simbolo: str) -> bool:
    nome = re.escape(simbolo.split(".")[-1].split(" ")[0])
    return bool(re.search(rf"^\s*(?:async\s+def|def|class)\s+{nome}\b|^{nome}\s*[:=]", texto, re.M))


def _ref_quebrada(ref: str, repo: Path, sep: str) -> str | None:
    """Motivo se `arquivo<sep>símbolo` não existe; None se existe."""
    arq, _, simb = ref.partition(sep)
    p = repo / arq
    if not p.is_file():
        return f"arquivo inexistente ({arq})"
    if simb and not _tem_simbolo(p.read_text(encoding="utf-8", errors="replace"), simb):
        return f"símbolo inexistente ({ref})"
    return None


def problemas(arq: Path = ARQ, repo: Path = REPO) -> list[str]:
    """Defeitos do registro: campo faltando, controle/teste/exclusão apontando para o que não existe."""
    out = []
    reg = carregar(arq)
    for did, e in reg.items():
        if not isinstance(e, dict):
            out.append(f"{did}: entrada não é mapa")
            continue
        falta = [c for c in CAMPOS if c not in e]
        if falta:
            out.append(f"{did}: campo(s) faltando: {', '.join(falta)}")
            continue
        for c in ("modulo", "simbolo", "afirma"):
            if not str(e[c] or "").strip():
                out.append(f"{did}: `{c}` vazio")
        if e["modulo"] and not (repo / e["modulo"]).is_file():
            out.append(f"{did}: módulo inexistente ({e['modulo']})")
        if not isinstance(e["manchete"], bool):
            out.append(f"{did}: `manchete` tem de ser true/false")
        refs = [(c, e[c]) for c in ("controle_positivo", "controle_negativo")]
        # controle escrito que FALHA contra o código (xfail strict = achado): não conta como controle, mas existe
        refs += [("controle_xfail", r) for r in e.get("controle_xfail") or []]
        for c, ref in refs:
            if ref is None:
                continue
            if "::" not in str(ref):
                out.append(f"{did}: {c} sem '::teste' ({ref})")
                continue
            motivo = _ref_quebrada(str(ref), repo, "::")
            if motivo:
                out.append(f"{did}: {c} aponta para {motivo}")
        for h in e["hipoteses_inocentes"] or []:
            if not isinstance(h, dict) or not h.get("hipotese") or "excluida_por" not in h:
                out.append(f"{did}: hipótese inocente mal formada ({h})")
            elif h["excluida_por"]:
                motivo = _ref_quebrada(str(h["excluida_por"]), repo, ":")
                if motivo:
                    out.append(f"{did}: hipótese '{h['hipotese']}' excluída por {motivo}")
        fp = e["fp_medida"]
        if fp is not None and (not isinstance(fp, dict) or any(not fp.get(c) and fp.get(c) != 0 for c in CAMPOS_FP)):
            out.append(f"{did}: fp_medida incompleta (exige {', '.join(CAMPOS_FP)})")
        rev = e.get("revisao_2026_11_13")
        if rev is not None and (rev.get("veredito") not in VEREDITOS or not rev.get("afirmado")
                                or not rev.get("sustentado")):
            out.append(f"{did}: revisao_2026_11_13 mal formada")
        out += _problemas_o51(did, e, reg)
    return out


def _problemas_o51(did: str, e: dict, reg: dict) -> list[str]:
    """Campos da O5.1: estado, fusão e a contagem da medida (n, falsos) coerentes."""
    out = []
    if "estado" in e and e["estado"] not in ESTADOS:
        out.append(f"{did}: estado '{e['estado']}' fora de {ESTADOS}")
    alvo = e.get("fundido_em")
    if (e.get("estado") == "fundido") != bool(alvo):
        out.append(f"{did}: estado 'fundido' exige `fundido_em` (e vice-versa)")
    if alvo and (alvo not in reg or alvo == did or reg[alvo].get("fundido_em")):
        out.append(f"{did}: fundido_em aponta para entrada inexistente, a si mesma ou já fundida ({alvo})")
    fp = e.get("fp_medida")
    if isinstance(fp, dict) and fp.get("n") is not None:
        n, k = fp.get("n"), fp.get("falsos")
        if not (isinstance(n, int) and isinstance(k, int) and 0 <= k <= n):
            out.append(f"{did}: fp_medida.n/falsos inválidos (n={n!r}, falsos={k!r})")
    return out


def _data_fp(fp) -> date | None:
    if not isinstance(fp, dict):
        return None
    d = fp.get("data")
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def _calibrado(e: dict, hoje: date | None = None) -> bool:
    """fp_medida completa e com no máximo 180 dias (COR-04)."""
    fp = e.get("fp_medida")
    d = _data_fp(fp)
    if d is None or any(fp.get(c) in (None, "") for c in CAMPOS_FP):
        return False
    return (hoje or date.today()) - d <= VALIDADE_FP


def _dividas(reg: dict, hoje: date | None = None) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {k: {} for k in DIVIDAS}
    for did, e in reg.items():
        marcas = {
            "sem_controle_positivo": not e.get("controle_positivo"),
            "sem_controle_negativo": not e.get("controle_negativo"),
            "sem_hipotese_inocente": not e.get("hipoteses_inocentes"),
            "sem_dominio": not e.get("dominio"),
            "manchete_sem_fp_medida": bool(e.get("manchete")) and not _calibrado(e, hoje),
            "refutado_em_manchete": bool(e.get("manchete"))
            and (e.get("revisao_2026_11_13") or {}).get("veredito") == "REFUTADA",
            "manchete_sem_tier1": bool(e.get("manchete")) and avaliar_tier(e, hoje)["tier"] != 1,
        }
        for k, v in marcas.items():
            if v:
                out[k][did] = 1
    return out


def wilson_ic95(falsos: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    """Intervalo de confiança de 95% de Wilson para a proporção falsos/n (None sem n)."""
    if not n:
        return None
    p = falsos / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (round(max(0.0, centro - meia), 4), round(min(1.0, centro + meia), 4))


def avaliar_tier(e: dict, hoje: date | None = None) -> dict:
    """Tier, motivo e IC95 de uma entrada pela régua da O5.1 (ver TIER1_* no topo). Função pura."""
    fp = e.get("fp_medida")
    n = fp.get("n") if isinstance(fp, dict) else None
    k = fp.get("falsos") if isinstance(fp, dict) else None
    ic = wilson_ic95(k, n) if isinstance(n, int) and isinstance(k, int) and n > 0 else None
    if not isinstance(fp, dict):
        return {"tier": 3, "tier_motivo": "sem_medida", "fp_ic95": None}
    if not _calibrado(e, hoje):
        return {"tier": 3, "tier_motivo": "medida_incompleta_ou_vencida", "fp_ic95": ic}
    if ic is None:
        return {"tier": 3, "tier_motivo": "medida_sem_contagem_de_decididos", "fp_ic95": None}
    falta = []
    if n < TIER1_N_MIN:
        falta.append(f"n={n}<{TIER1_N_MIN}")
    if not fp.get("estratificada"):
        falta.append("amostra_nao_estratificada")
    if k / n > TIER1_PONTO_MAX:
        falta.append(f"ponto={k / n:.1%}>{TIER1_PONTO_MAX:.0%}")
    if ic[1] > TIER1_IC_MAX:
        falta.append(f"ic95_sup={ic[1]:.1%}>{TIER1_IC_MAX:.0%}")
    if not e.get("dominio"):
        falta.append("sem_elegibilidade")
    cob = fp.get("cobertura")
    if not isinstance(cob, (int, float)) or cob < TIER1_COBERTURA_MIN:
        falta.append("cobertura_desconhecida" if cob is None else f"cobertura={cob:.0%}<{TIER1_COBERTURA_MIN:.0%}")
    if (e.get("calibracao") or {}).get("erro_grave_aberto"):   # O5.4/E13: rebaixa no 1º erro grave conferido
        falta.append("erro_grave_conferido")
    if falta:
        return {"tier": 2, "tier_motivo": "; ".join(falta), "fp_ic95": list(ic)}
    return {"tier": 1, "tier_motivo": "cumpre_tier1", "fp_ic95": list(ic)}


def campos_calculados(e: dict, hoje: date | None = None) -> dict:
    """O que `tools/registro_tiers.py` grava em cada entrada: tier, motivo, IC95 e a manchete EFETIVA
    (manchete declarada E tier 1 — é o que o painel lê na O7.3; a declarada fica como pedido)."""
    t = avaliar_tier(e, hoje)
    return {**t, "manchete_efetiva": bool(e.get("manchete")) and t["tier"] == 1}


def tiers_desatualizados(arq: Path = ARQ, hoje: date | None = None) -> list[str]:
    """Entradas cujo tier/IC95/manchete_efetiva gravado difere do calculado hoje (ou falta)."""
    out = []
    for did, e in carregar(arq).items():
        calc = campos_calculados(e, hoje)
        dif = [c for c in CAMPOS_CALCULADOS if e.get(c, "<ausente>") != calc[c]]
        if dif:
            out.append(f"{did}: {', '.join(dif)}")
    return out


def manchete_efetiva(id: str) -> bool:  # noqa: A002 — mesma assinatura de `calibrado`
    """Pode ser manchete? Só com `manchete: true` e tier 1 (calculado agora, não o gravado)."""
    e = carregar().get(id)
    return bool(e) and campos_calculados(e)["manchete_efetiva"]


def dividas(arq: Path = ARQ, hoje: date | None = None) -> dict[str, dict[str, int]]:
    """Por dívida, {id: 1} — formato das catracas (cada id conta como um 'arquivo')."""
    return _dividas(carregar(arq), hoje)


def calibrado(id: str, hoje=None) -> bool:  # noqa: A002 — assinatura combinada com o sensor
    """O detector tem taxa de falso positivo medida em fonte primária há no máximo 180 dias?"""
    e = carregar().get(id)
    return bool(e) and _calibrado(e, hoje)


def nao_calibrados_em_manchete() -> list[str]:
    """Ids com `manchete: true` sem medição válida — o que o sensor `calibragem_manchetes` lista."""
    return sorted(_dividas(carregar())["manchete_sem_fp_medida"])


def resumo(arq: Path = ARQ, hoje: date | None = None) -> dict:
    """Contagens para o painel de conformidade."""
    reg = carregar(arq)
    dv = _dividas(reg, hoje)
    return {
        "total": len(reg),
        "manchetes": sum(bool(e.get("manchete")) for e in reg.values()),
        "com_dois_controles": sum(bool(e.get("controle_positivo") and e.get("controle_negativo"))
                                  for e in reg.values()),
        "calibrados": sum(_calibrado(e, hoje) for e in reg.values()),
        "por_divida": {k: len(v) for k, v in dv.items()},
        "refutados_em_manchete": sorted(dv["refutado_em_manchete"]),
        "nao_calibrados_em_manchete": sorted(dv["manchete_sem_fp_medida"]),
        "por_tier": {t: sum(avaliar_tier(e, hoje)["tier"] == t for e in reg.values()) for t in (1, 2, 3)},
        "manchetes_efetivas": sorted(k for k, e in reg.items() if campos_calculados(e, hoje)["manchete_efetiva"]),
    }
