#!/usr/bin/env bash
# keepalive.sh — guarda anti-idle LEVE para Oracle Cloud Always Free.
#
# Motivo: o Oracle "Always Free" pode RECLAMAR (parar) instâncias compute
# consideradas ociosas. Critério oficial (avaliado em janela de 7 dias):
#   - CPU usada < 20% (no agregado ~<10%) em 95%+ do tempo, E
#   - tráfego de REDE < 10%, E
#   - memória < 10%.
# A instância só é candidata a reclaim se TODAS as condições baterem.
# Esta guarda gera, a cada disparo do timer (~7 min), uma pequena atividade
# de CPU + um pouco de REDE EXTERNA real, o suficiente para não parecer ociosa,
# mantendo consumo baixíssimo (alguns segundos de 1 core, poucos KB de rede).
#
# NÃO gera custo: usa apenas requisições HTTP/DNS triviais e CPU local.
# Roda via systemd --user (keepalive.timer), independente de sessão.
set -euo pipefail

LOG_DIR="/home/ubuntu/JFN/data"
LOG="${LOG_DIR}/keepalive.log"
mkdir -p "${LOG_DIR}"

ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }

# --- 1) Pequena atividade de CPU (~1-2s de 1 core) -------------------------
# Loop curto de cálculo. Limitado por tempo para não passar de ~2s.
cpu_burn() {
  local end=$(( $(date +%s) + 2 ))   # no máximo ~2 segundos
  local x=0
  while [ "$(date +%s)" -lt "${end}" ]; do
    # 200k iterações de aritmética por rodada antes de reavaliar o relógio
    local i=0
    while [ "${i}" -lt 200000 ]; do
      x=$(( (x * 1103515245 + 12345) & 0x7fffffff ))
      i=$(( i + 1 ))
    done
  done
  echo "${x}"
}

# --- 2) Toque no serviço local (health) ------------------------------------
local_code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/status 2>/dev/null || echo "ERR")

# --- 3) Atividade de REDE EXTERNA leve --------------------------------------
# HEAD/GET minúsculos em endpoints públicos estáveis (poucos KB no total).
# Múltiplos alvos: se um falhar, ainda gera tráfego com os outros.
net_ok=0
for url in \
  "https://www.cloudflare.com/cdn-cgi/trace" \
  "https://1.1.1.1/" \
  "https://www.google.com/generate_204" ; do
  if curl -s -m 8 -o /dev/null "${url}" 2>/dev/null; then
    net_ok=$(( net_ok + 1 ))
  fi
done

# Ping leve (3 pacotes) — tráfego ICMP externo adicional, best-effort.
ping_ok="no"
if ping -c 3 -i 0.3 -W 3 1.1.1.1 >/dev/null 2>&1; then
  ping_ok="yes"
fi

burn=$(cpu_burn)
echo "[$(ts)] keepalive cpu_burn_tail=${burn: -4} local_status=${local_code} net_ok=${net_ok}/3 ping=${ping_ok}" >> "${LOG}"

# Mantém o log curto (últimas ~500 linhas).
if [ -f "${LOG}" ]; then
  tail -n 500 "${LOG}" > "${LOG}.tmp" 2>/dev/null && mv "${LOG}.tmp" "${LOG}" || true
fi

exit 0
