#!/bin/bash
# Verifica o fix do abrir_processo (fallback quicksearch) e PUXA a íntegra do processo-mãe da SEAS
# (contrato de gestão 001/2021 + aditivos + prestação de contas) do Ambiente Jovem. Espera uma janela
# de browser REALMENTE livre (sem sweep SEI/SIAFE e load baixo — VM 2 vCPU, 1 browser por vez), então
# baixa a íntegra e envia no Telegram. Serializado e paciente (o cron do SEI roda 07/13/19h).
cd /home/ubuntu/JFN || exit 1
LOG=data/sei_prestacao_contas.log
PROC="070026/000705/2021"

esperar_livre() {
  for _ in $(seq 1 480); do   # até ~4h de paciência
    if pgrep -f "sei_sweep|sei_integra_completa|siafe_ob_orcamentaria|siafe_runner|coleta_esporte" >/dev/null 2>&1; then
      sleep 30; continue
    fi
    L=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
    if [ "${L:-9}" -lt 2 ]; then return 0; fi
    sleep 30
  done
  return 1
}

echo "[prest] aguardando janela de browser livre $(date '+%F %T')" >> "$LOG"
esperar_livre || { echo "[prest] sem janela livre em 4h — abortando" >> "$LOG"; exit 1; }
echo "[prest] janela livre — puxando íntegra SEI-$PROC $(date '+%T')" >> "$LOG"
SEI_MAX_PAG=300 .venv/bin/python tools/sei_integra_completa.py "$PROC" >> "$LOG" 2>&1
echo "[prest] FIM $(date '+%F %T')" >> "$LOG"
tail -3 "$LOG" | grep -q "ÍNTEGRA:" && echo "[prest] OK — árvore abriu (fix funcionou)" >> "$LOG" || echo "[prest] árvore NÃO abriu — investigar abrir_processo/quicksearch" >> "$LOG"
