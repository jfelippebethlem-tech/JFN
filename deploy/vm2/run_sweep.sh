#!/bin/bash
# Sweep SEI-PCRJ (VM-2): ddddocr local, sem LLM. N shards paralelos ADAPTATIVOS à carga.
# Robusto: single-instance (flock), limpa chromium ÓRFÃO (ppid=1) de runs mortos, timeout -k
# garante o kill, trap fecha browsers na saída, limpa DBs de shard após merge, sync p/ VM-1.
set -u
cd /home/ubuntu/sei-pcrj || exit 1

# 1) single-instance: se já há um sweep, sai (evita empilhar browsers com o timer 2x/dia + start manual)
exec 9>/tmp/sei-pcrj.lock
flock -n 9 || { echo "$(date -Is) já em execução — pula" >> data/sweep_cron.log; exit 0; }

[ -f data/.pause ] && { echo "$(date -Is) pausado (.pause)" >> data/sweep_cron.log; exit 0; }

# limpa chromium ÓRFÃO (parent = init) de execuções anteriores mortas por timeout/kill
limpa_orfaos() {
  for p in $(pgrep -f "ms-playwright/chromium" 2>/dev/null); do
    ppid=$(awk '/^PPid:/{print $2}' "/proc/$p/status" 2>/dev/null)
    [ "$ppid" = "1" ] && kill -9 "$p" 2>/dev/null
  done
}
limpa_orfaos
trap 'pkill -P $$ 2>/dev/null; sleep 1; limpa_orfaos' EXIT

# 2) fila fresca da VM-1
/home/ubuntu/sei-pcrj/refresh_fila.sh

# 3) shards adaptativos à carga (2 vCPU): 2 se load1<1.5, senão 1 (folga p/ Massare)
L=$(awk '{print int($1*10)}' /proc/loadavg)
N=2; [ "${L:-0}" -ge 15 ] && N=1
echo "$(date -Is) iniciando $N shard(s) (load10=$L)" >> data/sweep_cron.log
for s in $(seq 0 $((N-1))); do
  nice -n 15 timeout -k 30 7200 .venv/bin/python sei_pcrj_sweep.py \
    --fila fila.txt --max 400 --segundos 6600 --shard "$s" --nshards "$N" >> data/sweep_cron.log 2>&1 &
done
wait

# 4a) Relação de Contratos do ContasRio (ano corrente) — 1×/semana; anos anteriores só à mão
ANO=$(date +%Y)
if [ -z "$(find data/contasrio -name "contratos_${ANO}.csv" -mtime -7 2>/dev/null)" ]; then
  nice -n 15 timeout -k 30 900 .venv/bin/python contasrio_export.py --anos "$ANO" >> data/sweep_cron.log 2>&1
  nice -n 15 timeout -k 30 900 .venv/bin/python contasrio_export.py --vista fiscais --anos "$ANO" >> data/sweep_cron.log 2>&1
fi

# 4b) íntegras pela conferência de autenticidade (pares verificador+CRC vindos da VM-1 via shared-brain)
pgrep -f "^\.venv/bin/python sei_pcrj_conferir" >/dev/null || nice -n 15 timeout -k 30 1900 .venv/bin/python sei_pcrj_conferir.py --max 200 --segundos 1800 >> data/sweep_cron.log 2>&1

# 4c) anexos (inteiro teor) dos contratos municipais via CCON — contratos vindos dos CSVs do ContasRio
pgrep -f "^\.venv/bin/python ccon_anexos" >/dev/null || nice -n 15 timeout -k 30 1900 .venv/bin/python ccon_anexos.py --max 60 --segundos 1800 >> data/sweep_cron.log 2>&1

# 4) consolida, limpa DBs de shard, sincroniza p/ a VM-1
.venv/bin/python sei_pcrj_sweep.py --merge >> data/sweep_cron.log 2>&1
rm -f data/sei_pcrj_[0-9]*.db
cp -f data/sei_pcrj.db ~/shared-brain/sei_pcrj.db 2>/dev/null
echo "$(date -Is) sweep concluído ($N shards); DB -> shared-brain" >> data/sweep_cron.log
