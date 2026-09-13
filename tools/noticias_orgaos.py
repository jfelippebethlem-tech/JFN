#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""noticias_orgaos — imprensa sobre os ÓRGÃOS do Estado (Google News RSS, sem chave), classificada por termo de risco.

Pedido do dono (12/09/2026): usar ferramentas online sem API para melhorar as apurações. O RSS do Google News
enxerga a imprensa local (o GDELT não). Aqui a pergunta é por órgão, não por fornecedor: o que a imprensa diz
da Fundação Saúde, da SEEDUC, da CEDAE… Materializa `noticias_orgaos` (dedupe por url) e o painel mostra as
adversas dos últimos dias. Cobertura jornalística é INDÍCIO a confirmar na fonte — nunca prova.

Uso: PYTHONPATH=. .venv/bin/python -m tools.noticias_orgaos   (cron diário)
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"

# consulta → rótulo curto. Aspas = frase exata no Google News.
ORGAOS = [
    ('"Fundação Saúde" Rio de Janeiro', "FSERJ"),
    ('"Secretaria de Estado de Saúde" RJ', "SES-RJ"),
    ('"Secretaria de Estado de Educação" RJ', "SEEDUC"),
    ('"CEDAE"', "CEDAE"),
    ('"DETRAN-RJ" OR "Detran RJ"', "DETRAN-RJ"),
    ('"Polícia Militar" RJ licitação OR contrato OR fraude', "PMERJ"),
    ('"Corpo de Bombeiros" RJ licitação OR contrato OR fraude', "CBMERJ"),
    ('"Governo do Estado do Rio" contrato OR licitação OR TCE', "Governo RJ"),
    ('"TCE-RJ"', "TCE-RJ"),
    ('"ITERJ"', "ITERJ"),
    ('"Fundação Leão XIII" OR "FUNDAÇÃO LEÃO XIII"', "Leão XIII"),
    ('"UERJ" contrato OR licitação', "UERJ"),
    ('"Prefeitura do Rio" contrato OR licitação OR TCM', "PCRJ"),
    ('"RioSaúde"', "RioSaúde"),
]


def _iso(pubdate: str) -> str:
    try:
        return parsedate_to_datetime(pubdate).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def coletar(orgaos=ORGAOS, pausa: float = 1.0) -> list[dict]:
    from compliance_agent.enrich.midia_adversa import _classificar, _gnews
    out = []
    for consulta, rotulo in orgaos:
        arts, err = _gnews(consulta, max_r=30)
        if arts is None:
            print(f"[imprensa] {rotulo}: {err}", flush=True)
            continue
        # o nome do órgão não pode ser o "risco": a consulta "TCE-RJ" casava "tce" em 23 de 26 títulos (12/09)
        proprios = {t for t in re.findall(r"[a-záéíóúç]{3,}", consulta.lower())}
        for a in arts:
            adv, termos = _classificar(a.get("title") or "", None)
            termos = [t for t in termos if t not in proprios and not any(t in p for p in proprios)]
            adv = bool(termos)
            out.append({"orgao": rotulo, "consulta": consulta, "titulo": a.get("title") or "", "url": a.get("url") or "",
                        "fonte": a.get("domain") or "", "data": _iso(a.get("seendate") or ""), "adversa": int(adv),
                        "termos": ",".join(termos)})
        time.sleep(pausa)
    return out


def materializar(itens: list[dict] | None = None) -> dict:
    itens = itens if itens is not None else coletar()
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    novos = 0
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS noticias_orgaos (url TEXT PRIMARY KEY, orgao TEXT, consulta TEXT, titulo TEXT, fonte TEXT, "
                    "data TEXT, adversa INTEGER, termos TEXT, visto_em TEXT)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_not_org ON noticias_orgaos(orgao, data)")
        for i in itens:
            if not i["url"]:
                continue
            cur = con.execute("INSERT OR IGNORE INTO noticias_orgaos VALUES (?,?,?,?,?,?,?,?,?)",
                              (i["url"], i["orgao"], i["consulta"], i["titulo"], i["fonte"], i["data"], i["adversa"], i["termos"], agora))
            novos += cur.rowcount
            if not cur.rowcount:   # já existia: a classificação pode ter mudado (regra dos termos próprios)
                con.execute("UPDATE noticias_orgaos SET adversa=?, termos=? WHERE url=?", (i["adversa"], i["termos"], i["url"]))
    tot = con.execute("SELECT count(*), sum(adversa) FROM noticias_orgaos").fetchone()
    con.close()
    return {"coletadas": len(itens), "novas": novos, "total": tot[0], "adversas": tot[1] or 0}


def main() -> int:
    r = materializar()
    print(f"[imprensa] {r['coletadas']} notícias lidas · {r['novas']} novas · acervo {r['total']} ({r['adversas']} com termo de risco)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
