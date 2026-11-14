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
           "manchete_sem_fp_medida", "refutado_em_manchete")
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
    for did, e in carregar(arq).items():
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
        }
        for k, v in marcas.items():
            if v:
                out[k][did] = 1
    return out


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
    }
