#!/bin/bash
# diag_telegram_poller — detecta se EXISTE um 2º poller do bot do Yoda em OUTRA máquina (desktop/cloud/etc.).
# Método: PARA o gateway da VM por ~40s (zera o nosso poller), chama getUpdates em loop e vê se vem 409
# (= alguém mais está pollando) ou limpo (= ninguém). Depois RELIGA o gateway. ⚠ Yoda fica ~40s fora no teste.
#
# Uso típico: feche o app/serviço suspeito (desktop, outro deploy) e rode isto. Se der LIMPO, era ele.
# Fix garantido sem caçar: BotFather → /revoke → token novo no ~/.hermes/.env → restart do gateway.
set -u
cd /home/jfelippebethlem/JFN || exit 1
TK=$(grep -oE 'TELEGRAM_BOT_TOKEN=[^"'"'"' ]+' ~/.hermes/.env 2>/dev/null | head -1 | cut -d= -f2)
[ -z "$TK" ] && { echo "sem TELEGRAM_BOT_TOKEN no ~/.hermes/.env"; exit 1; }

echo "1) parando o gateway da VM (Yoda fica ~40s fora)…"
systemctl --user stop hermes-gateway.service 2>/dev/null
pkill -9 -f 'hermes_cli[.]main gateway' 2>/dev/null
sleep 3
echo "   conexões telegram LOCAIS agora: $(ss -tnp 2>/dev/null | grep -c '149\.154\.') (esperado 0)"

echo "2) sondando getUpdates por ~36s (com o nosso gateway parado)…"
conf=0; limpo=0
for i in $(seq 1 12); do
  R=$(curl -s -m 8 "https://api.telegram.org/bot$TK/getUpdates?timeout=2&offset=-1" 2>/dev/null)
  if echo "$R" | grep -q '"error_code":409'; then conf=$((conf+1)); echo "   [$i] 409 → OUTRO poller ATIVO";
  elif echo "$R" | grep -q '"ok":true'; then limpo=$((limpo+1)); fi
  sleep 3
done
echo "   resultado: $limpo limpas, $conf conflitos"
[ "$conf" -gt 0 ] && echo ">>> HÁ um 2º poller em OUTRA máquina (não nesta VM). Feche-o, ou /revoke no BotFather." \
                  || echo ">>> NENHUM poller externo agora — o conflito sumiu (era o que você acabou de fechar)."

echo "3) religando o gateway da VM…"
systemctl --user reset-failed hermes-gateway.service 2>/dev/null
systemctl --user start hermes-gateway.service
sleep 4
echo "   gateway: $(systemctl --user is-active hermes-gateway.service)"
