# -*- coding: utf-8 -*-
"""Ponte SpiderFoot — footprint digital (OSINT) de alvo de ALTO risco.

Uma empresa real deixa rastro digital (site, MX, redes sociais, subdomínios); uma
fachada de papel quase não existe on-line. O SpiderFoot (``~/spiderfoot``, venv
próprio) coleta esse footprint via OSINT passivo; aqui só o PARSEAMOS e derivamos um
score onde **footprint vazio = 1.0 = mais suspeito**.

Custo/tempo: um scan leva minutos e faz dezenas de requisições externas — NUNCA rodar
em sweep de massa. Use ``elegivel(radar_score)`` como guarda: só alvo com
``radar_risco >= 50`` justifica o scan.

INDISPONÍVEL ≠ 0: sem o binário/venv do SpiderFoot, ``footprint`` retorna ``None`` (não
sabemos), nunca um dict de "zero achados" (que significaria "existe e nada foi achado").
"""
from __future__ import annotations

import json
import logging
import math
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Invocação descoberta em ~/spiderfoot/sf.py --help (v4.0.0):
#   sf.py -s ALVO -o json -q -u footprint
#   -s ALVO         alvo do scan (domínio/e-mail/IP)
#   -o json         saída JSON: array [ {generated,type,data,module,source}, ... ]
#   -q              silencia logging (não polui o stdout JSON)
#   -u footprint    seleção automática de módulos pelo caso de uso "footprint"
# O venv do SpiderFoot é ``.venv`` (não ``venv``): ~/spiderfoot/.venv/bin/python.
_SF_DIR = Path.home() / "spiderfoot"
_SF_PY = _SF_DIR / ".venv" / "bin" / "python"
_SF_SCRIPT = _SF_DIR / "sf.py"

# Classificação por palavra-chave no campo ``type`` (tolera tanto o nome-máquina
# INTERNET_NAME/PROVIDER_MAIL/SOCIAL_MEDIA quanto o rótulo humano que o -o json emite).
_KW_SITE = ("internet_name", "domain_name", "web", "url", "website", "co-hosted",
            "co_hosted", "linked_url", "http_")
_KW_MX = ("provider_mail", "mail_provider", " mx", "mx ", "mailserver")
_KW_REDES = ("social_media", "social media", "account_external", "account external")

# Escala do score (exponencial): score = e^(-n/_K). n=0 → 1.0 (vazio = máximo suspeito);
# n=8 → ~0.37; n=30 → ~0.02 (footprint rico → próximo de 0). Suave e monotônico.
_K_DECAIMENTO = 8.0

# Limiar de elegibilidade: só alvo de alto risco (radar) justifica o custo do scan.
_LIMIAR_RADAR = 50.0


def _disponivel() -> bool:
    return _SF_PY.exists() and _SF_SCRIPT.exists()


def _classificar(tipos: dict[str, int]) -> tuple[bool, bool, bool]:
    """(tem_site, tem_mx, tem_redes) por palavra-chave nos tipos de evento presentes."""
    chaves = " ".join(tipos).lower()
    tem_site = any(k in chaves for k in _KW_SITE)
    tem_mx = any(k in chaves for k in _KW_MX)
    tem_redes = any(k in chaves for k in _KW_REDES)
    return tem_site, tem_mx, tem_redes


def _parse_saida(saida: str) -> dict | None:
    """Parseia o array JSON do SpiderFoot num resumo. Malformado → None (não assumível)."""
    try:
        eventos = json.loads(saida or "[]")
    except (ValueError, TypeError):
        logger.warning("SpiderFoot: saída JSON malformada (%d bytes) — INDISPONÍVEL", len(saida or ""))
        return None
    if not isinstance(eventos, list):
        return None
    tipos: dict[str, int] = {}
    for ev in eventos:
        if isinstance(ev, dict):
            t = str(ev.get("type") or "DESCONHECIDO")
            tipos[t] = tipos.get(t, 0) + 1
    n = sum(tipos.values())
    tem_site, tem_mx, tem_redes = _classificar(tipos)
    resumo = (f"{n} achados em {len(tipos)} tipos; "
              f"site={tem_site} mx={tem_mx} redes={tem_redes}") if n else \
             "footprint vazio (nenhum achado on-line)"
    return {"n_achados": n, "tipos": tipos, "tem_site": tem_site,
            "tem_mx": tem_mx, "tem_redes": tem_redes, "resumo": resumo}


def footprint(alvo: str, timeout_s: int = 300) -> dict | None:
    """Roda o SpiderFoot sobre ``alvo`` (domínio/e-mail/IP) e devolve o resumo do footprint.

    Retorna ``{n_achados, tipos, tem_site, tem_mx, tem_redes, resumo}`` ou ``None`` quando o
    binário/venv está ausente (INDISPONÍVEL), o scan estoura ``timeout_s`` ou a saída é
    malformada. Nunca chamar em sweep — ver ``elegivel``.
    """
    if not _disponivel():
        logger.warning("SpiderFoot INDISPONÍVEL: %s ou %s ausente", _SF_PY, _SF_SCRIPT)
        return None
    cmd = [str(_SF_PY), str(_SF_SCRIPT), "-s", alvo, "-o", "json", "-q", "-u", "footprint"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, cwd=str(_SF_DIR))
    except subprocess.TimeoutExpired:
        logger.warning("SpiderFoot: timeout (%ss) para %s", timeout_s, alvo)
        return None
    except OSError as exc:
        logger.warning("SpiderFoot: falha ao executar (%s)", exc)
        return None
    return _parse_saida(proc.stdout)


def score_footprint(f: dict | None) -> float | None:
    """Score 0..1 do footprint: 1.0 = vazio (máximo suspeito), ~0 = footprint rico.

    Escala exponencial ``e^(-n/_K_DECAIMENTO)`` sobre o nº de achados: 0→1.0, 8→~0.37,
    30→~0.02. ``None`` (INDISPONÍVEL) propaga ``None`` — não vira 0 nem 1.
    """
    if f is None:
        return None
    n = int(f.get("n_achados", 0) or 0)
    if n <= 0:
        return 1.0
    return round(max(0.0, min(1.0, math.exp(-n / _K_DECAIMENTO))), 4)


def elegivel(radar_score: float | None) -> bool:
    """Guarda de custo: só alvo com ``radar_risco >= 50`` justifica um scan (tempo/rede).

    NUNCA usar footprint em sweep de massa — cada scan faz dezenas de requisições externas.
    """
    return radar_score is not None and radar_score >= _LIMIAR_RADAR
