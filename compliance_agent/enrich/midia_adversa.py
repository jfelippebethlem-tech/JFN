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
    "punid", "advertid", "multad", "sanção", "sancao", "inidône", "inidone", "impedid", "suspens",
]


# fronteira de palavra ANTES do radical (evita falso-positivo como "presa" dentro de "emPRESA");
# o radical casa as flexões (investiga→investigação, condena→condenado, superfatur→superfaturamento)
_RISCO_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _RISCO) + r")", re.IGNORECASE)


def _classificar(titulo: str, tom) -> tuple[bool, list[str]]:
    """ADVERSO se o título casa termo de risco (com fronteira) OU o tom GDELT é fortemente negativo (< -3)."""
    hits = sorted({m.group(0).lower() for m in _RISCO_RE.finditer(titulo or "")})
    adverso = bool(hits) or (isinstance(tom, (int, float)) and tom < -3)
    return adverso, hits


def _ddg_fallback(alvo: str, max_r: int = 12) -> tuple[list | None, str]:
    """Fallback KEYLESS quando o GDELT falha: DuckDuckGo HTML com query de termos de risco.
    Retorna (adversos, erro). Classifica por título+trecho. Nunca fabrica."""
    try:
        from bs4 import BeautifulSoup
    except Exception:  # noqa: BLE001
        return None, "BeautifulSoup ausente"
    q = (f'"{alvo}" (fraude OR operação OR investigação OR improbidade OR TCE OR '
         '"Ministério Público" OR superfaturamento OR cartel OR propina)')
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": q},
                       headers={"User-Agent": "Mozilla/5.0 (JFN/2.0 fiscalizacao)"},
                       timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return None, f"DDG HTTP {r.status_code}"
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:  # noqa: BLE001
        return None, f"DDG {str(e)[:50]}"
    adversos = []
    for res in soup.select(".result")[:max_r]:
        a = res.select_one(".result__a")
        if not a:
            continue
        titulo = a.get_text(strip=True)
        snip = res.select_one(".result__snippet")
        trecho = snip.get_text(strip=True) if snip else ""
        adv, hits = _classificar(f"{titulo} {trecho}", None)
        if adv:
            adversos.append({"titulo": titulo, "fonte": "DuckDuckGo (web)", "url": a.get("href", ""),
                             "data": None, "termos": hits, "trecho": trecho[:160]})
    return adversos, ""


_GNEWS = "https://news.google.com/rss/search"


def _gnews(alvo: str, max_r: int = 20) -> tuple[list | None, str]:
    """Google News RSS (sem chave, sem API): é o que enxerga a imprensa BRASILEIRA local — o GDELT devolveu
    0 artigos para "RESTAURANTE NOVA RODOVIA 2007" enquanto o RSS trouxe a Metrópoles (empresa punida por servir
    salsicha, 26/02/2026) e um procedimento do MP; e o DuckDuckGo HTML passou a responder 'anomaly' (bot).
    Medido em 12/09/2026. Retorna (artigos brutos, erro)."""
    import html as _html
    q = {"q": f'"{alvo}"', "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}
    try:
        r = httpx.get(_GNEWS, params=q, headers={"User-Agent": "Mozilla/5.0 (JFN/2.0 fiscalizacao)"},
                      timeout=20, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        return None, f"gnews {str(e)[:50]}"
    if r.status_code != 200:
        return None, f"gnews HTTP {r.status_code}"
    itens = re.findall(r"<item>(.*?)</item>", r.text, re.S)
    out = []
    for it in itens[:max_r]:
        def _tag(t):
            m = re.search(rf"<{t}>(.*?)</{t}>", it, re.S)
            return _html.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", m.group(1).strip())) if m else ""
        out.append({"title": _tag("title"), "url": _tag("link"), "seendate": _tag("pubDate"),
                    "domain": _tag("source") or "google-news"})
    return out, ""


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
        # GDELT falhou (tipicamente 429) → fallback KEYLESS no DuckDuckGo
        ddg, ddg_err = _ddg_fallback(alvo)
        if ddg is not None:
            return {"ok": True, "alvo": alvo, "n_total": len(ddg), "n_adversos": len(ddg),
                    "adversos": ddg[:15], "_fonte": "DuckDuckGo web (fallback do GDELT)",
                    "_nota": f"GDELT indisponível ({erro}); usei DuckDuckGo. Mídia adversa = indício a confirmar "
                             "na fonte (cobertura não é prova; pode haver homônimos)."}
        return {"ok": True, "alvo": alvo, "n_total": 0, "n_adversos": 0, "adversos": [],
                "_fonte": "GDELT DOC 2.0 + DuckDuckGo (ambos indisponíveis)",
                "_nota": f"INDISPONÍVEL: GDELT {erro}; DDG {ddg_err}. Nada fabricado."}

    # Google News RSS SEMPRE (não só como fallback): cobre a imprensa local que o GDELT não indexa
    gn, gn_err = _gnews(alvo)
    fontes = "GDELT DOC 2.0 + Google News RSS (grátis, sem chave)" if gn is not None else f"GDELT DOC 2.0 (Google News {gn_err})"
    adversos, vistos = [], set()
    for a in list(arts) + list(gn or []):
        titulo = a.get("title")
        tom = a.get("tone")
        adv, hits = _classificar(titulo, tom)
        chave = (titulo or "").strip().lower()[:80]
        if adv and chave not in vistos:
            vistos.add(chave)
            adversos.append({"titulo": titulo, "fonte": a.get("domain"), "url": a.get("url"),
                             "data": a.get("seendate"), "termos": hits, "tom": tom})
    return {"ok": True, "alvo": alvo, "n_total": len(arts) + len(gn or []), "n_adversos": len(adversos),
            "adversos": adversos[:15], "_fonte": fontes,
            "_nota": "Mídia adversa = INDÍCIO a confirmar na fonte (presunção de legitimidade). Cobertura "
                     "jornalística não é prova e pode conter homônimos."}
