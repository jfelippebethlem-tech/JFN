#!/bin/bash
# OCR em CPU no it-campo, EM PARALELO ao Surya (dono 18/11/2026: "acelera tudo e usa o it-campo").
# Roda no WSL (24 núcleos ociosos; a GPU fica com o Surya). Disparado pela VM-1 (tools/itcampo_ocr_cpu.sh, cron)
# — single-pass com teto, nada de `while true`. Cada processo é um nó próprio (itcampo-1..K) para a VM-1: as reservas
# nunca se cruzam (trava + estado na VM-1) e a GPU nunca vê o item (sai do FIM do ocr_fila.txt antes da leitura).
# Freio: o worker da GPU espera abaixo de 3 GB livres; cada processo daqui só começa um PDF com >= 6 GB livres
# (3 do freio da GPU + ~1,5 GB de pico por processo × 2) — medido 18/11: a memória livre do WSL oscila 3–8 GB.
set -u
# O script chega pela entrada padrão (bash -s): tudo dentro de main() é lido ANTES de rodar, e main roda com
# stdin = /dev/null — senão o primeiro ssh/rsync filho comeria o resto do script.
main() {
  B=~/jfn-gpu/ocr-cpu
  K=${1:-2}; T=${2:-6}; ORC=${3:-1500}
  cd "$B" || return 1
  exec 9>"$B/.ocr_cpu.lock"
  flock -n 9 || { echo "rodada anterior viva — pula"; return 0; }
  [ -e "$B/PAUSA" ] && { echo "pausado ($B/PAUSA)"; return 0; }
  # código atual da VM-1, conferido por md5 nas duas pontas
  rsync -a vm1-ts:JFN/tools/sei_ocr_reserva.py "$B/sei_ocr_reserva.py.novo" || return 1
  L=$(md5sum < "$B/sei_ocr_reserva.py.novo" | cut -d' ' -f1)
  R=$(ssh -o BatchMode=yes vm1-ts 'md5sum < JFN/tools/sei_ocr_reserva.py' | cut -d' ' -f1)
  [ "$L" = "$R" ] || { echo "md5 do código diverge ($L != $R)"; return 1; }
  mv "$B/sei_ocr_reserva.py.novo" "$B/sei_ocr_reserva.py"
  export JFN_FRIO_REMOTO=vm2-ts:arquivo_frio/sei_cache/ JFN_OCR_MEM_MIN_GB=6 JFN_OCR_THREADS=$T \
         JFN_OCR_RESERVA_DIR=$B JFN_VM1_SSH=vm1-ts OMP_NUM_THREADS=$T
  for k in $(seq 1 "$K"); do
    timeout -k 60 $((ORC + 300)) nice -n 10 "$B/.venv/bin/python" "$B/sei_ocr_reserva.py" rodar --paralelo \
        --orcamento "$ORC" --n 8 --no "itcampo-$k" >> "$B/ocr_cpu_$k.log" 2>&1 &
    sleep 20      # escalona: as reservas na VM-1 são serializadas por trava, e a carga sobe aos poucos
  done
  wait
  tail -qn1 "$B"/ocr_cpu_*.log
}
main "$@" < /dev/null
