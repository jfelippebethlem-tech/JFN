#!/usr/bin/env bash
# sweep_sei_noturno — preenche as JANELAS OCIOSAS (madrugada) rodando o sweep SEI
# back-to-back, sem aumentar o pico de carga (continua 1 sessão itkava por vez).
#
# Segurança (por que NÃO quebra a VM):
#   • guarda de load/RAM a cada iteração (vm_guard.preflight) — pula se a VM estiver carregada
#   • lock single-instance do próprio sei_sweep (pgrep) — nunca abre 2ª sessão itkava
#   • só roda na JANELA NOTURNA (fora dos sweeps de dados/sede/SIAFE do dia)
#   • respeita data/.pause_sei_sweep e data/.pause_sei_noturno
#   • cada iteração é bounded (timeout) e resumível — o sweep continua de onde parou
#
# Uso: nohup tools/sweep_sei_noturno.sh >> data/sweep_sei_noturno.log 2>&1 &
#   --dry-run : exercita TODOS os guards e imprime as decisões SEM abrir browser (p/ teste)
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

# janela noturna: 22h–05h (fora de dados 10/16h, sede a cada 2h de dia, SIAFE 05h, integra 04h)
JANELA_INI=22
JANELA_FIM=5
MAX_ITER_DRY=3

say(){ echo "[$(date '+%F %T')] $*"; }

na_janela(){ local h; h=$(date +%H); h=${h#0}; [ "$h" -ge "$JANELA_INI" ] || [ "$h" -lt "$JANELA_FIM" ]; }
outro_sweep_browser(){ pgrep -f 'tools.sei_sweep|siafe_ob_orcamentaria|sweep_sede|coletar_por_ug' >/dev/null; }
pausado(){ [ -f data/.pause_sei_sweep ] || [ -f data/.pause_sei_noturno ]; }

iter=0
say "início (dry=$DRY) — janela ${JANELA_INI}h–${JANELA_FIM}h"
while : ; do
  iter=$((iter+1))
  if pausado; then say "pausado (.pause_*) — encerrando"; break; fi
  if ! na_janela; then say "fora da janela noturna — encerrando"; break; fi
  # guarda de recursos
  guard=$($PY -c "from tools.vm_guard import preflight; ok,m=preflight(); print(('OK' if ok else 'BUSY')+'|'+m)")
  if [ "${guard%%|*}" != "OK" ]; then say "VM carregada (${guard#*|}) — espero 120s"; [ $DRY -eq 1 ] && { [ $iter -ge $MAX_ITER_DRY ] && break; }; sleep 120; continue; fi
  # não abrir 2ª sessão itkava
  if outro_sweep_browser; then say "já há sweep de browser rodando — espero 90s (lock preserva a sessão única)"; [ $DRY -eq 1 ] && { [ $iter -ge $MAX_ITER_DRY ] && break; }; sleep 90; continue; fi

  if [ $DRY -eq 1 ]; then
    say "DRY-RUN: rodaria agora → nice -n15 timeout 1200 sei_sweep --max 16 (guards OK: ${guard#*|})"
    [ $iter -ge $MAX_ITER_DRY ] && { say "dry-run: $MAX_ITER_DRY iterações OK — fim"; break; }
    sleep 2; continue
  fi

  say "rodando sei_sweep (guards OK: ${guard#*|})"
  nice -n 15 ionice -c3 timeout 1200 $PY -m tools.sei_sweep --max 16 >> data/sei_cache/sei_sweep_loop.out 2>&1
  say "sei_sweep rc=$?"
  sleep 15   # respiro entre sessões (deixa a VM e o itkava respirarem)
done
say "fim"
