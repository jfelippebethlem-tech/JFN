#!/bin/bash
# rotate_telegram_token — troca o token do bot do Yoda em TODOS os .env e religa o gateway.
#
# QUANDO USAR: há um 2º poller do bot em OUTRA máquina disputando o getUpdates (mensagens do Yoda
# duplicadas/triplicadas; journal cheio de "Conflict: terminated by other getUpdates request").
# O ÚNICO fix garantido (sem caçar a máquina) é revogar o token: o instance externo morre na hora.
#
# PASSOS DO DONO (≈30s):
#   1. Telegram → @BotFather → /revoke → escolher @JorgeFelippe_bot → ele devolve um TOKEN NOVO.
#   2. Rodar:  bash tools/rotate_telegram_token.sh '<TOKEN_NOVO_COLADO_AQUI>'
# O script valida o token (getMe), faz backup dos .env, troca em ~/.hermes/.env e ~/JFN/.env,
# religa o hermes-gateway e confirma que o conflito sumiu.
set -u
NEW="${1:-}"
[ -z "$NEW" ] && { echo "uso: bash tools/rotate_telegram_token.sh '<token novo do BotFather>'"; exit 1; }

echo "1) validando o token novo (getMe)…"
ME=$(curl -s -m 10 "https://api.telegram.org/bot${NEW}/getMe")
echo "$ME" | grep -q '"ok":true' || { echo "   ✗ token INVÁLIDO (getMe não ok): $ME"; exit 1; }
USER=$(echo "$ME" | grep -oE '"username":"[^"]+"' | head -1 | cut -d'"' -f4)
echo "   ✓ token ok → bot @${USER}"

STAMP=$(date +%Y%m%d_%H%M%S)
for f in "$HOME/.hermes/.env" "$HOME/JFN/.env"; do
  [ -f "$f" ] || continue
  if grep -q '^TELEGRAM_BOT_TOKEN=' "$f"; then
    cp "$f" "${f}.bak_${STAMP}"
    # troca a linha inteira preservando o resto do arquivo
    python3 - "$f" "$NEW" <<'PY'
import sys, re
path, tok = sys.argv[1], sys.argv[2]
with open(path) as fh: lines = fh.readlines()
with open(path, "w") as fh:
    for ln in lines:
        if ln.startswith("TELEGRAM_BOT_TOKEN="):
            fh.write(f"TELEGRAM_BOT_TOKEN={tok}\n")
        else:
            fh.write(ln)
PY
    echo "2) ${f} atualizado (backup em ${f}.bak_${STAMP})"
  fi
done

echo "3) religando o hermes-gateway…"
systemctl --user reset-failed hermes-gateway.service 2>/dev/null
systemctl --user restart hermes-gateway.service
sleep 6
echo "   gateway: $(systemctl --user is-active hermes-gateway.service)"

echo "4) conferindo se o conflito sumiu (12s)…"
conf=0
for i in 1 2 3 4; do
  R=$(curl -s -m 8 "https://api.telegram.org/bot${NEW}/getUpdates?timeout=2&offset=-1" 2>/dev/null)
  echo "$R" | grep -q '"error_code":409' && conf=$((conf+1))
  sleep 3
done
if [ "$conf" -eq 0 ]; then
  echo "   ✓ SEM conflito — token novo exclusivo desta VM. O poller externo está morto (token velho revogado)."
else
  echo "   ⚠ ainda há 409 — improvável após /revoke. Confirme que usou /revoke (não /token) e que colou o token NOVO."
fi
echo "PRONTO. (As customizações do gateway no ~/hermes-agent seguem intactas — só o token mudou.)"
