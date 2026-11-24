#!/bin/bash
# montar_d.sh — confere o HD externo (D:, Seagate) em /mnt/d e o monta se faltar (O1.10). Roda como root do WSL
# (wsl -u root), chamado por jfn_fluxo_boot.ps1. Idempotente. rc 0 = montado e conferido; 3 = D: ausente no Windows.
# Por que não só o automount: o D: é USB; se não estiver no ar quando o WSL sobe, o automount não o vê depois,
# e o que existe hoje foi montado à mão (com `metadata`, que o automount padrão não põe).
set -u
ALVO=/mnt/d
OPC="metadata,uid=1000,gid=1000"
CONFERE=/mnt/d/JFN-Frio/_indice           # índice do HD (hd_indice --publicar); sem ele o D: não é o nosso HD
if mountpoint -q "$ALVO" && [ -d "$CONFERE" ]; then echo "montar_d: $ALVO já montado e conferido"; exit 0; fi
mountpoint -q "$ALVO" && umount "$ALVO" 2>/dev/null      # montagem velha/vazia (HD replugado)
mkdir -p "$ALVO"
for i in 1 2 3 4 5 6; do                                  # o HD USB pode demorar a aparecer no boot
  if mount -t drvfs D: "$ALVO" -o "$OPC" 2>/dev/null && [ -d "$CONFERE" ]; then
    echo "montar_d: D: montado em $ALVO ($OPC) na tentativa $i"; exit 0
  fi
  mountpoint -q "$ALVO" && umount "$ALVO" 2>/dev/null
  sleep 20
done
echo "montar_d: D: AUSENTE (ou sem $CONFERE) — o fluxo segue sem o HD (o HD é morno, §3.5)"; exit 3
