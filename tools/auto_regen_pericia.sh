#!/bin/bash
# Espera o sweep da folha mensal terminar e então REGENERA os dois PDFs (Câmara/Prefeitura) com as
# janelas de vínculo já no mês exato, e envia no Telegram. Uma vez só (não fica em loop).
cd /home/ubuntu/JFN || exit 1
# espera o processo da folha mensal sair (checa a cada 60s; teto ~6h)
for _ in $(seq 1 360); do
  pgrep -f 'sweep_folha_mensal.sh' >/dev/null 2>&1 || break
  sleep 60
done
echo "[auto-regen] folha mensal concluída — regenerando perícia $(date '+%F %T')"
.venv/bin/python -m compliance_agent.pcrj.pericia_pcrj

.venv/bin/python - <<'PY'
import asyncio, os, re
for ln in open("/home/ubuntu/JFN/.env", encoding="utf-8", errors="replace"):
    m = re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$', ln)
    if m: os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
os.environ["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_OWNER_ID", "")
from datetime import date
from compliance_agent.notifications.telegram import enviar_arquivo, enviar_mensagem
async def main():
    o = os.environ.get("TELEGRAM_OWNER_ID", "")
    hoje = date.today().isoformat()
    await enviar_mensagem("🔄 Folha mensal completa — perícia regenerada com as janelas de vínculo no MÊS exato:", chat_id=o)
    for nome, cap in (("camara", "CÂMARA (folha mensal — vínculo no mês exato)"),
                      ("prefeitura", "PREFEITURA (folha mensal — vínculo no mês exato)")):
        await enviar_arquivo(f"reports/pericia_{nome}_{hoje}.pdf", caption=cap, chat_id=o)
asyncio.run(main())
PY
echo "[auto-regen] FIM $(date '+%F %T')"
