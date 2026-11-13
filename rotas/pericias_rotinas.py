# -*- coding: utf-8 -*-
"""Rotas das ROTINAS AUTOMÁTICAS que alimentam o painel (13/11/2026):

  /api/pericia_contabil   — resumo diário da perícia contábil de todos os contratos (Estado › Perícia contábil)
  /api/cge_confronto      — confronto semanal CGE × JFN (Estado › CGE × JFN)
  /api/detectores_achados — achados dos detectores em `achados.db` (`achado_detector`), por detector

Só leitura. Os dois primeiros leem o JSON que a rotina grava (relido a cada chamada — a rotina pode regravá-lo a
qualquer hora); arquivo ausente = "rotina ainda não rodou" (≠ zero). CPF mascarado em tudo que sai.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_RAIZ = Path(__file__).resolve().parents[1]
# detectores com cron próprio e o horário (para dizer "ainda não rodou" em vez de "zero achados")
DETECTORES_AGENDADOS = {
    "P7": "domingo 06:20 — p7_direta_de_risco (contratação direta de risco, painel de NE da CGE)",
    "EST-VALOR-EXCEDIDO": "domingo 06:50 — est_valor_contratual (OB acima do valor contratado)",
    "EST-ADITIVO-TETO": "domingo 06:50 — est_valor_contratual (aditivo acima do teto legal)",
}


def _data() -> Path:
    from compliance_agent.rotina_base import DATA
    return DATA


def _mascarar(x):
    from compliance_agent.governo_couto import _mascarar_tudo
    return _mascarar_tudo(x)


def _ler_rotina(nome: str, rotina: str, horario: str) -> JSONResponse:
    p = _data() / nome
    if not p.exists():
        return JSONResponse({"ok": True, "estado": "sem_execucao", "rotina": rotina, "horario": horario,
                             "mensagem": f"A rotina ainda não gravou {nome} — não é zero, é ausência de execução."})
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return JSONResponse({"ok": False, "estado": "erro", "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)
    d = _mascarar(d)
    d.update(ok=True, rotina=rotina, horario=horario,
             arquivo_mtime=time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)))
    d.setdefault("estado", "ok")
    return JSONResponse(d)


@router.get("/api/pericia_contabil")
def api_pericia_contabil():
    """Placar por esfera, maiores "a maior", duplicidades (mesma NL, mesmo valor) e motivos dos indeterminados."""
    return _ler_rotina("pericia_contabil_resumo.json", "python -m compliance_agent.pericia_contabil_rotina",
                       "diária, madrugada")


@router.get("/api/cge_confronto")
def api_cge_confronto():
    """Recall do JFN contra as contratações auditadas pela CGE (por processo) + histórico semanal."""
    return _ler_rotina("cge_confronto.json", "python -m compliance_agent.cge_confronto", "semanal")


def _achados_db() -> Path:
    return Path(os.environ.get("JFN_DB_ACHADOS") or _RAIZ / "data" / "achados.db")


def resumir_achados(linhas: list[tuple], *, top: int = 40) -> dict:
    """Agrupa as linhas de `achado_detector` por detector. Função pura (testada com dados sintéticos).
    linha = (ug, detector, processo, escopo, score, status, motivo, explicacao_inocente, valores, evidencia, gerado_em)"""
    por: dict[str, dict] = {}
    itens: dict[str, list] = defaultdict(list)
    for ug, det, proc, esc, score, st, mot, ino, val, evid, ger in linhas:
        a = por.setdefault(det, {"detector": det, "status": Counter(), "ultimo": None, "ugs": set()})
        a["status"][st or "?"] += 1
        a["ultimo"] = max(a["ultimo"] or "", ger or "") or None
        if st == "confirmado":
            a["ugs"].add(ug)
            try:
                v = json.loads(val) if val else {}
            except ValueError:
                v = {}
            itens[det].append({"ug": ug, "processo": proc, "escopo": esc, "score": score, "motivo": (mot or "")[:400],
                               "explicacao_inocente": (ino or "")[:300], "gerado_em": ger,
                               "valores": {k: v[k] for k in list(v)[:12]} if isinstance(v, dict) else {},
                               "evidencia": (evid or "")[:300]})
    out = []
    for det, a in por.items():
        conf = sorted(itens[det], key=lambda x: -(x["score"] or 0))
        out.append({"detector": det, "n_confirmado": a["status"].get("confirmado", 0),
                    "n_total": sum(a["status"].values()), "por_status": dict(a["status"]), "ultimo": a["ultimo"],
                    "n_ugs": len(a["ugs"]), "agenda": DETECTORES_AGENDADOS.get(det), "itens": conf[:top]})
    for det, ag in DETECTORES_AGENDADOS.items():
        if det not in por:
            out.append({"detector": det, "n_confirmado": None, "n_total": 0, "por_status": {}, "ultimo": None, "n_ugs": 0,
                        "agenda": ag, "itens": [], "sem_execucao": True})
    out.sort(key=lambda x: (x["detector"] not in DETECTORES_AGENDADOS, -(x["n_confirmado"] or 0), x["detector"]))
    return _mascarar({"detectores": out, "n_confirmados": sum(x["n_confirmado"] or 0 for x in out)})


@router.get("/api/detectores_achados")
def api_detectores_achados():
    """Achados de TODOS os detectores gravados em `achados.db`; os semanais (P7, EST-*) aparecem mesmo sem linha
    ("ainda não rodou" — não é zero)."""
    p = _achados_db()
    if not p.exists():
        return JSONResponse({"ok": False, "estado": "indisponivel", "erro": f"{p.name} ausente — INDISPONÍVEL, não zero"})
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=20)
        try:
            linhas = con.execute("SELECT ug, detector, processo, escopo, score, status, motivo, explicacao_inocente, "
                                 "valores, evidencia, gerado_em FROM achado_detector").fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return JSONResponse({"ok": False, "estado": "indisponivel", "erro": f"{type(exc).__name__}: {exc}"},
                            status_code=500)
    r = resumir_achados(linhas)
    r.update(ok=True, estado="ok", fonte=f"achados.db · achado_detector ({len(linhas)} linhas)",
             ressalva="Achado confirmado de detector é indício para leitura humana, não acusação.")
    return JSONResponse(r)
