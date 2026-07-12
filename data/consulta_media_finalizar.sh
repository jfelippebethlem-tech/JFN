#!/bin/bash
# Varredura MÉDIA + finalizador autônomo (setsid, sem LLM — padrão pcrj_finalizar/auto_regen):
# espera a regeneração corrente → consulta nominal dos MÉDIA não-informados (longa, retomável)
# → regenera os 4 PDFs da perícia → envia no Telegram com o placar.
cd /home/ubuntu/JFN || exit 1
LOG=data/consulta_media.log

# não competir com a regeneração de PDFs em andamento (1 pesado por vez na VM)
for _ in $(seq 1 120); do
  pgrep -f 'regen_pericias' >/dev/null 2>&1 || break
  sleep 60
done

echo "== consulta MÉDIA início $(date '+%F %T') ==" >> "$LOG"
.venv/bin/python tools/consulta_nominal_alta.py --certeza media >> "$LOG" 2>&1
PLACAR=$(grep -E '^\{"consultados"' "$LOG" | tail -1)

echo "== regenerando perícias $(date '+%F %T') ==" >> "$LOG"
.venv/bin/python tools/vm_guard.py >> "$LOG" 2>&1
.venv/bin/python -m compliance_agent.pcrj.pericia_pcrj >> "$LOG" 2>&1
.venv/bin/python -m compliance_agent.pcrj.pericia_beneficios >> "$LOG" 2>&1
.venv/bin/python -m compliance_agent.pcrj.pericia_socios_beneficio >> "$LOG" 2>&1

PLACAR="$PLACAR" .venv/bin/python - <<'PY' >> "$LOG" 2>&1
import asyncio, os, re
from pathlib import Path
for ln in open("/home/ubuntu/JFN/.env", encoding="utf-8", errors="replace"):
    m = re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$', ln)
    if m: os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))
os.environ["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_OWNER_ID", "")
from compliance_agent.notifications.telegram import enviar_arquivo, enviar_mensagem

def latest(pfx):
    fs = sorted(Path("reports").glob(pfx + "*.pdf"), key=lambda p: p.stat().st_mtime)
    return str(fs[-1]) if fs else None

async def main():
    o = os.environ.get("TELEGRAM_OWNER_ID", "")
    await enviar_mensagem(
        "👥 *Consulta nominal dos casos MÉDIA concluída* — cargos obtidos no contracheque "
        "(só nome ÚNICO classifica; homônimo ambíguo segue NÃO INFORMADO, por honestidade). "
        "Perícias regeneradas abaixo.\nPlacar da varredura: " + (os.environ.get("PLACAR") or "n/d"),
        chat_id=o)
    for pfx, cap in (
        ("pericia_camara_", "CÂMARA — pós-consulta nominal MÉDIA"),
        ("pericia_prefeitura_", "PREFEITURA — pós-consulta nominal MÉDIA"),
        ("pericia_beneficios_nomeados_", "CONSOLIDADO — pós-consulta nominal MÉDIA"),
        ("pericia_socios_fornecedores_beneficio_", "SÓCIOS — pós-consulta nominal MÉDIA"),
    ):
        p = latest(pfx)
        if p:
            try:
                await enviar_arquivo(p, caption=cap, chat_id=o)
            except Exception as e:  # noqa: BLE001
                print("falha no envio", p, e)
asyncio.run(main())
PY
echo "== FIM $(date '+%F %T') ==" >> "$LOG"
