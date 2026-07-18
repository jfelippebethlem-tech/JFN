#!/bin/bash
# Coleta SIAFE-1 (www5, 2016-2023) da UG 170100 (Secretaria de Esporte/Lazer/Juventude) nos
# exercícios 2017 e 2018 (gestão Thiago Pampolha), depois consulta SOLAZER e ONG Contato nesses
# anos e reporta no Telegram. SERIALIZADO: espera acabar qualquer pipeline/browser antes (VM 2 vCPU,
# nunca 2 browsers). SIAFE-1 é seguro só até 2023 (NUNCA 2024 aqui).
cd /home/ubuntu/JFN || exit 1
LOG=data/coleta_esporte_2018.log
SIAFE1="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"

# espera liberar: nada de extrator/cruzamento/browser SEI/SIAFE rodando
for _ in $(seq 1 240); do
  if pgrep -f "extrai_folha_ajovem|cruza_contratados|sei_integra_completa|siafe_ob_orcamentaria|siafe_runner" >/dev/null 2>&1; then
    sleep 30
  else
    break
  fi
done
sleep 5
echo "[coleta] início $(date '+%F %T')" >> "$LOG"
.venv/bin/python tools/vm_guard.py >> "$LOG" 2>&1

for ANO in 2018 2017; do
  echo "[coleta] SIAFE-1 UG 170100 exercício $ANO $(date '+%T')" >> "$LOG"
  JFN_SIAFE_LOGIN_URL="$SIAFE1" .venv/bin/python -m compliance_agent.siafe_runner ug 170100 "$ANO" >> "$LOG" 2>&1
  sleep 10
done

echo "[coleta] consultando SOLAZER e ONG Contato em 2017/2018 $(date '+%T')" >> "$LOG"
.venv/bin/python - <<'PY' >> "$LOG" 2>&1
import sqlite3, os, re, asyncio
c=sqlite3.connect('file:data/compliance.db?mode=ro',uri=True); c.row_factory=sqlite3.Row
norm="REPLACE(REPLACE(REPLACE(credor,'.',''),'/',''),'-','')"
linhas=["🏛️ *SIAFE-1 — Esporte (UG 170100) 2017/2018 (gestão Pampolha)*"]
def brl(v): return f"{v or 0:,.2f}".replace(',','X').replace('.',',').replace('X','.')
achou=False
for nome,cnpj in [('SOLAZER (Raphael)','28008530000103'),('ONG Contato','03686998000118')]:
    rows=c.execute(f"SELECT exercicio,COUNT(*),ROUND(SUM(valor),2),MIN(data_emissao),MAX(data_emissao) FROM ob_orcamentaria_siafe WHERE {norm}=? AND ug_emitente='170100' AND exercicio IN (2017,2018) GROUP BY exercicio ORDER BY exercicio",(cnpj,)).fetchall()
    if rows:
        achou=True
        for r in rows:
            linhas.append(f"• *{nome}* — {r[0]}: {r[1]} OB, R$ {brl(r[2])} ({r[3]}→{r[4]})")
    else:
        linhas.append(f"• *{nome}* — 2017/2018: nenhuma OB da UG 170100 na coleta (INDISPONÍVEL≠0; conferir se a UG do Esporte tinha outro código no SIAFE-1)")
# top credores 2018 p/ contexto
tops=c.execute(f"SELECT MAX(nome_credor),ROUND(SUM(valor),2) FROM ob_orcamentaria_siafe WHERE ug_emitente='170100' AND exercicio=2018 GROUP BY {norm} ORDER BY 2 DESC LIMIT 8").fetchall()
if tops:
    linhas.append("\\n*Maiores credores da UG 170100 em 2018:*")
    for t in tops: linhas.append(f"  – {(t[0] or '')[:40]}: R$ {brl(t[1])}")
n2018=c.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='170100' AND exercicio=2018").fetchone()[0]
linhas.append(f"\\n_(coletadas {n2018} OBs da UG 170100 em 2018)_")
c.close()
msg="\\n".join(linhas)
for ln in open('.env',encoding='utf-8',errors='replace'):
    m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$',ln)
    if m: os.environ.setdefault(m.group(1),m.group(2).strip().strip('"').strip("'"))
os.environ["TELEGRAM_CHAT_ID"]=os.environ.get("TELEGRAM_OWNER_ID","")
from compliance_agent.notifications.telegram import enviar_mensagem
asyncio.run(enviar_mensagem(msg, chat_id=os.environ.get("TELEGRAM_OWNER_ID","")))
print(msg)
PY
echo "[coleta] FIM $(date '+%F %T')" >> "$LOG"
