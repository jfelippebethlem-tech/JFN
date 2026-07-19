#!/usr/bin/env bash
# baixar_receita_estabelecimentos — Estabelecimentos*.zip do dump CNPJ (autorizado 2026-07-19).
# Mesma fonte/guards do baixar_receita_dump.sh (Nextcloud RFB, WebDAV, resumível, VM-safe).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO/data/receita_dump"
SHARE="YggdBLfdninEJX9"
MES="2026-05"
BASE="https://arquivos.receitafederal.gov.br/public.php/webdav/$MES"
mkdir -p "$DEST"
baixar() {
  local f="$1"
  while :; do
    load=$(awk '{print int($1)}' /proc/loadavg)
    free_mb=$(free -m | awk '/^Mem:/{print $7}')
    if [ "$load" -ge 4 ] || [ "$free_mb" -lt 800 ]; then
      echo "[baixar] pausa: load=$load free=${free_mb}MB — aguardando 30s"; sleep 30
    else break; fi
  done
  echo "[baixar] $f → $DEST/"
  nice -n10 ionice -c2 -n6 wget -c -q \
    --user="$SHARE" --password="" --tries=0 --timeout=60 --waitretry=10 \
    -O "$DEST/$f" "$BASE/$f"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "[baixar] FALHA ($rc) em $f — resumível, rerodar"; return $rc; fi
  if ! unzip -l "$DEST/$f" >/dev/null 2>&1; then
    echo "[baixar] $f zip inválido/parcial — manter p/ resume"; return 2
  fi
  echo "[baixar] OK $f ($(du -h "$DEST/$f" | cut -f1))"
}
t0=$(date +%s)
for i in 0 1 2 3 4 5 6 7 8 9; do baixar "Estabelecimentos$i.zip"; done
echo "[baixar] FIM estabelecimentos em $(( $(date +%s) - t0 ))s — total: $(du -sh "$DEST" | cut -f1)"
