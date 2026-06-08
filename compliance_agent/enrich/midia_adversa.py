# -*- coding: utf-8 -*-
"""Mídia adversa (due diligence §9) — 100% KEYLESS, via GDELT DOC 2.0 (grátis, sem chave).

Ideia do dono (2026-06-08): enquanto as APIs key-gated (Aleph/OpenCorporates) não liberam a chave grátis,
usar serviços/sites públicos da internet para fazer o MESMO trabalho de due diligence. GDELT é grátis, sem
chave, multilíngue e indexa imprensa BR (G1, locais, etc.).

Estratégia: busca a cobertura recente sobre o alvo e classifica como ADVERSA quando o título traz termos de
risco (fraude, operação, improbidade, TCE/MP, superfaturamento, cartel, propina, lavagem…). Honesto:
rate-limit/sem resultado → reporta INDISPONÍVEL e nunca fabrica notícia. Cobertura jornalística é INDÍCIO a
confirmar na fonte (presunção de legitimidade) e pode conter homônimos.
"""
from __future__ import annotations

import re
import time

import httpx

_GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"

# termos de risco (substring, minúsculo, sem acento-sensível além do óbvio) — foco em recurso/agente público
_RISCO = [
    "fraude", "fraudes", "investiga", "operação", "operacao", "improbidade", "superfatur",
    "sobrepreç", "sobreprec", "cartel", "conluio", "propina", "lavagem", "preso", "presa",
    "condena", "desvio", "irregularidade", "irregular", "quadrilha", "apura", "apuração",
    "denúncia", "denuncia", "tce", "ministério público", "ministerio publico", "mpf", "mprj",
    "polícia federal", "policia federal", "cpi", "esquema", "propin", "corrup", "suspeit",
]


# fronteira de palavra ANTES do radical (evita falso-positivo como "presa" dentro de "emPRESA");
# o radical casa as flexões (investiga→investigação, condena→condenado, superfatur→superfaturamento)
_RISCO_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _RISCO) + r")", re.IGNORECASE)


def _classificar(titulo: str, tom) -> tuple[bool, list[str]]:
    """ADVERSO se o título casa termo de risco (com fronteira) OU o tom GDELT é fortemente negativo (< -3)."""
    hits = sorted({m.group(0).lower() for m in _RISCO_RE.finditer(titulo or "")})
    adverso = bool(hits) or (isinstance(tom, (int, float)) and tom < -3)
    return adverso, hits


def varrer(nome: str, cnpj: str = "", janela_meses: int = 24, max_artigos: int = 25) -> dict:
    """Varre mídia adversa sobre `nome`. {ok, alvo, n_total, adversos:[{titulo,fonte,url,data,termos}],
    n_adversos} | INDISPONÍVEL (rate-limit/erro). Nunca fabrica."""
    alvo = (nome or "").strip()
    if not alvo or len(alvo) < 3:
        return {"ok": False, "erro": "informe o nome (≥3 chars) da empresa/pessoa"}
    params = {"query": f'"{alvo}"', "mode": "ArtList", "format": "json",
              "maxrecords": max_artigos, "timespan": f"{janela_meses}m", "sort": "DateDesc"}
    headers = {"User-Agent": "JFN/2.0 (fiscalizacao publica)"}
    arts = None
    erro = ""
    for tentativa in range(3):  # GDELT free dá 429 sob carga; backoff curto resolve a maioria
        try:
            r = httpx.get(_GDELT, params=params, headers=headers, timeout=25)
            if r.status_code == 200:
                arts = (r.json() or {}).get("articles", []) or []
                break
            erro = f"HTTP {r.status_code}"
            if r.status_code == 429 and tentativa < 2:
                time.sleep(2.5 * (tentativa + 1))  # 2.5s, 5s
                continue
            break
        except Exception as e:  # noqa: BLE001
            erro = str(e)[:70]
            break
    if arts is None:
        return {"ok": True, "alvo": alvo, "n_total": 0, "n_adversos": 0, "adversos": [],
                "_fonte": "GDELT DOC 2.0 (grátis, sem chave)",
                "_nota": f"INDISPONÍVEL: GDELT {erro} (sem chave; reitere mais tarde). Nada fabricado."}

    adversos = []
    for a in arts:
        titulo = a.get("title")
        tom = a.get("tone")
        adv, hits = _classificar(titulo, tom)
        if adv:
            adversos.append({"titulo": titulo, "fonte": a.get("domain"), "url": a.get("url"),
                             "data": a.get("seendate"), "termos": hits, "tom": tom})
    return {"ok": True, "alvo": alvo, "n_total": len(arts), "n_adversos": len(adversos),
            "adversos": adversos[:15], "_fonte": "GDELT DOC 2.0 (grátis, sem chave)",
            "_nota": "Mídia adversa = INDÍCIO a confirmar na fonte (presunção de legitimidade). Cobertura "
                     "jornalística não é prova e pode conter homônimos."}
