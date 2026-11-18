"""Regrava NO LUGAR os alertas 'Remuneração acima do teto' com a régua honesta (acima_do_teto.classificar),
mesma lógica do engine.py pós-pente-fino (17/11/2026). Mantém id/status/created_at; backup antes."""
import json
import re
import sqlite3
import sys
import time
sys.path.insert(0, ".")
from compliance_agent.acima_do_teto import classificar
from compliance_agent.rules.engine import TETO_REMUNERATORIO_RJ as T
from compliance_agent.reporting.intel_base import moeda
EXEC = "--executar" in sys.argv
c = sqlite3.connect("data/compliance.db", timeout=120); c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute("select * from alertas where titulo like 'Remuneração acima do teto%' or tipo like 'emendas_%'")]
bk = f"data/backups/alertas_antes_regravacao_{time.strftime('%Y%m%d-%H%M')}.json"
if EXEC:
    json.dump(rows, open(bk, "w"), ensure_ascii=False, default=str); print("backup", bk, len(rows))
cont = {}
for a in [r for r in rows if r["titulo"].startswith("Remuneração acima do teto")]:
    ev = json.loads(a["evidencias"] or "{}")
    comp = (re.search(r"em (\d{4}-\d{2})", a["descricao"] or "") or [None, None])[1]
    liq = ev.get("remuneracao")
    br = None
    if comp:
        r = c.execute("select max(remuneracao_bruta) from registros_folha where nome=? and competencia=?", (ev.get("nome"), comp)).fetchone()
        br = r[0] if r else None
    cls = classificar(br or liq, None, teto=T)
    if not cls.get("acima"):
        cont["dentro"] = cont.get("dentro", 0) + 1
        sev, st, mot = "baixa", "DENTRO_NO_BRUTO", "o bruto da folha não supera o teto"
    else:
        st, mot = cls["status"], cls["motivo"]
        sev = "baixa" if st == "RRA_RETROATIVO_PROVAVEL" else "média"
    cont[st] = cont.get(st, 0) + 1
    desc = (f"'{ev.get('nome')}' recebeu R$ {moeda(liq or 0)} líquidos"
            + (f" (R$ {moeda(br)} brutos)" if br else "") + f" em {comp}; teto de referência R$ {moeda(T)}. "
            f"{st}: {mot} (verba indenizatória não entra no teto — CF art. 37 §11). Indício a conferir, não acusação.")
    ev.update(remuneracao_bruta=br, status_teto=st, regravado_em="2026-11-17 (pente fino)")
    if EXEC:
        c.execute("update alertas set severidade=?, descricao=?, evidencias=? where id=?",
                  (sev, desc, json.dumps(ev, ensure_ascii=False), a["id"]))
if EXEC: c.commit()
print("executado" if EXEC else "simulação", cont)
