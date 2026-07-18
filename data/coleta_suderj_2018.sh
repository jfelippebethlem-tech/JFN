#!/bin/bash
# Coleta SIAFE-1 (www5) da SUDERJ (UG 173100, Superintendência de Desportos) e reforça a Secretaria
# de Esporte (170100) nos exercícios 2017 e 2018 (gestão Pampolha), depois consulta SOLAZER e ECOS
# e reporta no Telegram. A hipótese do dono: a execução dos contratos de OS de esporte saiu pela
# SUDERJ, não pela Secretaria (que voltou 0 OBs em 2017-18). Serializado (1 browser por vez).
cd /home/ubuntu/JFN || exit 1
LOG=data/coleta_suderj_2018.log
SIAFE1="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"

for _ in $(seq 1 240); do
  pgrep -f "sei_sweep|sei_integra_completa|siafe_ob_orcamentaria|siafe_runner" >/dev/null 2>&1 && sleep 30 || break
done
sleep 5
echo "[suderj] início $(date '+%F %T')" >> "$LOG"
for UG in 173100 176100; do
  for ANO in 2018 2017; do
    echo "[suderj] SIAFE-1 UG $UG exercício $ANO $(date '+%T')" >> "$LOG"
    JFN_SIAFE_LOGIN_URL="$SIAFE1" .venv/bin/python -m compliance_agent.siafe_runner ug "$UG" "$ANO" >> "$LOG" 2>&1
    sleep 8
  done
done

.venv/bin/python - <<'PY' >> "$LOG" 2>&1
import sqlite3, os, re, asyncio
c=sqlite3.connect('file:data/compliance.db?mode=ro',uri=True); c.row_factory=sqlite3.Row
norm="REPLACE(REPLACE(REPLACE(credor,'.',''),'/',''),'-','')"
def brl(v): return f"{v or 0:,.2f}".replace(',','X').replace('.',',').replace('X','.')
L=["🏟️ *SIAFE-1 — SUDERJ (173100) e FUNJOVEM (176100), 2017/2018*"]
# SOLAZER por CNPJ; ECOS por nome (não temos CNPJ certo)
for ug in ('173100','176100','170100'):
    for nome,filtro in [('SOLAZER', f"{norm}='28008530000103'"),
                        ('ECOS', "upper(nome_credor) LIKE '%ECOS%'")]:
        rows=c.execute(f"SELECT exercicio,COUNT(*),ROUND(SUM(valor),2),MIN(data_emissao),MAX(data_emissao),MAX(nome_credor) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND {filtro} AND exercicio IN (2017,2018) GROUP BY exercicio",(ug,)).fetchall()
        for r in rows:
            L.append(f"• UG{ug} *{nome}* {r[0]}: {r[1]} OB, R$ {brl(r[2])} ({r[3]}→{r[4]}) — {(r[5] or '')[:32]}")
# cobertura coletada por UG/ano
L.append("\\n*Cobertura coletada (OBs no SIAFE-1):*")
for ug in ('173100','176100','170100'):
    for ano in (2017,2018):
        n=c.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND exercicio=?",(ug,ano)).fetchone()[0]
        L.append(f"  UG{ug}/{ano}: {n} OBs")
# maiores credores SUDERJ 2018 (contexto)
tops=c.execute(f"SELECT MAX(nome_credor),ROUND(SUM(valor),2) FROM ob_orcamentaria_siafe WHERE ug_emitente='173100' AND exercicio=2018 GROUP BY {norm} ORDER BY 2 DESC LIMIT 8").fetchall()
if tops:
    L.append("\\n*Maiores credores da SUDERJ em 2018:*")
    for t in tops: L.append(f"  – {(t[0] or '')[:38]}: R$ {brl(t[1])}")
c.close()
msg="\\n".join(L)
for ln in open('.env',encoding='utf-8',errors='replace'):
    m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$',ln)
    if m: os.environ.setdefault(m.group(1),m.group(2).strip().strip('"').strip("'"))
os.environ["TELEGRAM_CHAT_ID"]=os.environ.get("TELEGRAM_OWNER_ID","")
from compliance_agent.notifications.telegram import enviar_mensagem
asyncio.run(enviar_mensagem(msg, chat_id=os.environ.get("TELEGRAM_OWNER_ID","")))
print(msg)
PY
echo "[suderj] FIM $(date '+%F %T')" >> "$LOG"
