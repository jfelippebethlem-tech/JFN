#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUTO-CURA da base ITERJ×MGS: garante as 55 OBs (2022/2023 somem intermitentemente da
ob_orcamentaria_siafe). Reingere do cache estável (siafe1_iterj_2022/2023.json) se a contagem
cair abaixo do esperado. Idempotente, barato, sem browser. Roda no cron diário (após o siafe_runner)
e é chamado pelo gerador do laudo. Exit 0 sempre que terminar com >=ESPERADO.

Uso: python tools/garantir_obs_iterj_mgs.py [--force]
"""
import json, sqlite3, sys, time
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data" / "compliance.db"
UG, CNPJ, ESPERADO = "133100", "19088605000104", 55
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


def garantir(force: bool = False) -> dict:
    con = sqlite3.connect(DB); cur = con.cursor()
    n0 = cur.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND credor=?", (UG, CNPJ)).fetchone()[0]
    if n0 >= ESPERADO and not force:
        con.close()
        return {"ok": True, "acao": "nada", "n": n0}
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
    con.commit(); con.close()
    return {"ok": n1 >= ESPERADO, "acao": "reingerido", "antes": n0, "depois": n1}


if __name__ == "__main__":
    res = garantir("--force" in sys.argv)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res["ok"] else 1)
