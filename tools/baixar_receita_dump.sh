#!/usr/bin/env bash
# baixar_receita_dump — baixa os ZIPs do dump CNPJ da Receita (Dados Abertos) de forma RESUMÍVEL e VM-safe.
# Fonte (jan/2026 RFB/SERPRO mudou o layout): o host dadosabertos.rfb.gov.br (SERPRO 200.152.38.155) é
# INALCANÇÁVEL desta VM (TCP 443 timeout). O mirror oficial é o Nextcloud em arquivos.receitafederal.gov.br
# (share público YggdBLfdninEJX9, WebDAV). Pasta mais recente resolvida = 2026-05.
# Baixa SÓ Socios*.zip + Empresas*.zip + Qualificacoes/Naturezas (NÃO Estabelecimentos/Simples).
# Uso: tools/baixar_receita_dump.sh [socios|empresas|lookup|all]   (default: all)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO/data/receita_dump"
SHARE="YggdBLfdninEJX9"
MES="2026-05"
BASE="https://arquivos.receitafederal.gov.br/public.php/webdav/$MES"
mkdir -p "$DEST"
ALVO="${1:-all}"

baixar() {
  local f="$1"
  # guarda de recursos: pausa se load alto ou pouca RAM (VM 7,8GB sem swap)
  while :; do
    load=$(awk '{print int($1)}' /proc/loadavg)
    free_mb=$(free -m | awk '/^Mem:/{print $7}')
    if [ "$load" -ge 4 ] || [ "$free_mb" -lt 800 ]; then
      echo "[baixar] pausa: load=$load free=${free_mb}MB — aguardando 30s"; sleep 30
    else break; fi
  done
  echo "[baixar] $f → $DEST/"
  nice -n10 ionice -c2 -n6 wget -c -q --show-progress \
    --user="$SHARE" --password="" --tries=0 --timeout=60 --waitretry=10 \
    -O "$DEST/$f" "$BASE/$f"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "[baixar] FALHA ($rc) em $f — resumível, rerodar"; return $rc; fi
  # valida que é zip íntegro (testa só o catálogo central, barato)
  if ! unzip -l "$DEST/$f" >/dev/null 2>&1; then
    echo "[baixar] $f baixou mas zip inválido/parcial — manter p/ resume"; return 2
  fi
  echo "[baixar] OK $f ($(du -h "$DEST/$f" | cut -f1))"
}

SOCIOS=$(for i in 0 1 2 3 4 5 6 7 8 9; do echo "Socios$i.zip"; done)
EMPRESAS=$(for i in 0 1 2 3 4 5 6 7 8 9; do echo "Empresas$i.zip"; done)
LOOKUP="Qualificacoes.zip Naturezas.zip"

case "$ALVO" in
  socios)   LISTA="$SOCIOS" ;;
  empresas) LISTA="$EMPRESAS" ;;
  lookup)   LISTA="$LOOKUP" ;;
  all)      LISTA="$LOOKUP $SOCIOS $EMPRESAS" ;;
  *) echo "uso: $0 [socios|empresas|lookup|all]"; exit 1 ;;
esac

t0=$(date +%s)
for f in $LISTA; do baixar "$f"; done
echo "[baixar] FIM ($ALVO) em $(( $(date +%s) - t0 ))s — total: $(du -sh "$DEST" | cut -f1)"
