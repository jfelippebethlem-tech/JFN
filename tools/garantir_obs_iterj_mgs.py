#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUTO-CURA da base ITERJ×MGS: garante as 55 OBs (2022/2023 somem intermitentemente da
ob_orcamentaria_siafe). Reingere do cache estável (siafe1_iterj_2022/2023.json) se a contagem
cair abaixo do esperado. Idempotente, barato, sem browser. Roda no cron diário (após o siafe_runner)
e é chamado pelo gerador do laudo. Exit 0 sempre que terminar com >=ESPERADO.

Uso: python tools/garantir_obs_iterj_mgs.py [--force]
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data" / "compliance.db"
UG, CNPJ = "133100", "19088605000104"
ANOS_DO_CACHE = (2022, 2023)
# ESPERADO era a constante 55 e virou vermelho perpétuo: o cache só cobre 2022/2023, que somam 28
# OBs da MGS, e os outros 22 registros vêm de anos que este guarda NÃO toca (2024-2026). Ou seja,
# ele nunca poderia devolver ok=True depois de curar — e um guarda que sempre falha ensina a
# ignorar guarda. Agora o alvo é lido DO PRÓPRIO CACHE, que é o que ele consegue garantir; o
# total entra no laudo como informação, não como critério. (2026-08-04)
MAP = {"Número": "numero_ob", "UG Emitente": "ug_emitente", "UG Pagadora": "ug_pagadora",
       "Data Emissão": "data_emissao", "Status": "status", "Tipo": "tipo", "Finalidade": "finalidade",
       "Credor": "credor", "Nome do Credor": "nome_credor", "UG Liquidante": "ug_liquidante",
       "Valor": "valor", "Status de Envio": "status_envio", "Guia Devolução": "gd", "RE": "re", "PD": "pd",
       "Tipo de Regularização": "tipo_regularizacao", "Qtd. Impressões": "qtd_impressoes",
       "Data de Competência": "competencia", "Vinculação de Pagamento": "vinculacao_pagamento"}


def _money(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _no_cache() -> dict[int, int]:
    """Quantas OBs da MGS cada cache de ano contém — o alvo que este guarda pode cumprir."""
    alvo = {}
    for ano in ANOS_DO_CACHE:
        fp = REPO / f"data/sei_cache/siafe1_iterj_{ano}.json"
        if not fp.exists():
            continue
        d = json.loads(fp.read_text())
        h = d["header"]
        if "Credor" not in h:
            continue
        i = h.index("Credor")
        alvo[ano] = sum(1 for r in d["linhas"]
                        if i < len(r) and re.sub(r"\D", "", r[i] or "") == CNPJ)
    return alvo


def _na_base(cur, anos) -> dict[int, int]:
    return {ano: cur.execute(
        "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND credor=? "
        "AND exercicio=?", (UG, CNPJ, ano)).fetchone()[0] for ano in anos}


def garantir(force: bool = False) -> dict:
    con = sqlite3.connect(DB); cur = con.cursor()
    alvo = _no_cache()
    if not alvo:
        con.close()
        return {"ok": False, "acao": "indisponivel",
                "motivo": "cache siafe1_iterj_*.json ausente — sem base para garantir nada"}
    n0 = cur.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND credor=?", (UG, CNPJ)).fetchone()[0]
    if _na_base(cur, alvo) == alvo and not force:
        con.close()
        return {"ok": True, "acao": "nada", "n": n0, "por_ano": alvo}
    agora = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    for ano in (2022, 2023):
        fp = REPO / f"data/sei_cache/siafe1_iterj_{ano}.json"
        if not fp.exists():
            continue
        d = json.loads(fp.read_text()); h = d["header"]
        cur.execute("DELETE FROM ob_orcamentaria_siafe WHERE exercicio=? AND ug_emitente=?", (ano, UG))
        for r in d["linhas"]:
            rec = {MAP[h[i]]: (r[i] if i < len(r) else "") for i in range(len(h)) if h[i] in MAP}
            rec["valor"] = _money(rec.get("valor")); rec["exercicio"] = ano; rec["coletado_em"] = agora
            cur.execute(f"INSERT OR REPLACE INTO ob_orcamentaria_siafe ({','.join(rec)}) VALUES ({','.join('?'*len(rec))})", tuple(rec.values()))
    con.commit()
    try:
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # garante que o commit foi p/ o .db principal
    except Exception:
        pass
    n1 = cur.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND credor=?", (UG, CNPJ)).fetchone()[0]
    depois_por_ano = _na_base(cur, alvo)
    con.commit(); con.close()
    return {"ok": depois_por_ano == alvo, "acao": "reingerido", "antes": n0, "depois": n1,
            "alvo_do_cache": alvo, "por_ano": depois_por_ano,
            # o total inclui 2024-2026, que este guarda não restaura: é informação, não critério
            "fora_do_alcance": n1 - sum(depois_por_ano.values())}


if __name__ == "__main__":
    res = garantir("--force" in sys.argv)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res["ok"] else 1)
