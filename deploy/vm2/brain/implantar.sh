#!/usr/bin/env bash
# Implanta o jfn-brain na VM-2 a partir DESTE diretório versionado. A pasta ~/brain de lá não é git.
#   deploy/vm2/brain/implantar.sh            implanta, migra, reinicia e confere
#   deploy/vm2/brain/implantar.sh --reverter <carimbo>   volta os arquivos de ~/brain/bak-<carimbo> e reinicia
# Regras: só arquivo COMMITADO (recusa se houver diferença para o HEAD); md5 conferido nas duas pontas; cópia de
# segurança antes; healthcheck REAL (REST + MCP pela Tailnet, com busca devolvendo resultado); falhou → volta sozinho.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../../.." && pwd)"
AQUI="$RAIZ/deploy/vm2/brain"
VM=vm2-ts
URL=https://jfn-agent-2.tailbbe6c9.ts.net:8443
ARQS=(brain_core.py indexer.py server.py brain_notas.py migracao_f4.sql ug_cores.json)
FTS="$RAIZ/compliance_agent/cerebro_fts.py"

saude() {  # REST: saúde, busca com resultado, recall; MCP: lista de ferramentas com brain_search
  for _ in $(seq 40); do
    if curl -fsS -m 10 "$URL/healthz" >/dev/null 2>&1 \
       && [ "$(curl -fsS -m 25 "$URL/api/search?q=pericia+bombeiros&k=5" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')" -ge 1 ] \
       && curl -fsS -m 25 "$URL/api/recall?q=decisao+do+dono&k=3" | python3 -c 'import json,sys; json.load(sys.stdin)' \
       && curl -fsS -m 25 -X POST "$URL/mcp/" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
            -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | grep -q brain_search; then
      return 0
    fi
    sleep 3
  done
  return 1
}

reiniciar() { ssh -o BatchMode=yes "$VM" 'systemctl --user restart brain-api.service'; }

if [ "${1:-}" = "--reverter" ]; then
  ssh -o BatchMode=yes "$VM" "cd ~/brain && test -d bak-$2 && cp -p bak-$2/* . && echo revertido para bak-$2"
  reiniciar; saude && echo "SAÚDE OK depois de reverter" || { echo "SAÚDE FALHOU depois de reverter"; exit 1; }
  exit 0
fi

cd "$RAIZ"
git diff --quiet HEAD -- "${ARQS[@]/#/deploy/vm2/brain/}" "$FTS" \
  || { echo "RECUSADO: há alteração não commitada nos arquivos do deploy"; exit 1; }
git ls-files --error-unmatch "${ARQS[@]/#/deploy/vm2/brain/}" "$FTS" >/dev/null \
  || { echo "RECUSADO: arquivo do deploy fora do git"; exit 1; }

TS=$(date +%Y%m%d-%H%M%S)
ssh -o BatchMode=yes "$VM" "cd ~/brain && mkdir -p bak-$TS novo-$TS && for f in ${ARQS[*]} cerebro_fts.py; do [ -f \$f ] && cp -p \$f bak-$TS/; done; true"
scp -q -o BatchMode=yes "${ARQS[@]/#/$AQUI/}" "$FTS" "$VM:brain/novo-$TS/"
LOCAL=$(cd "$AQUI" && md5sum "${ARQS[@]}" | awk '{print $1}'; md5sum "$FTS" | awk '{print $1}')
REMOTO=$(ssh -o BatchMode=yes "$VM" "cd ~/brain/novo-$TS && md5sum ${ARQS[*]} cerebro_fts.py | awk '{print \$1}'")
[ "$LOCAL" = "$REMOTO" ] || { echo "RECUSADO: md5 diferente entre as máquinas"; exit 1; }
echo "md5 conferido (${#ARQS[@]} + 1 arquivos) · cópia de segurança em vm2:~/brain/bak-$TS"

ssh -o BatchMode=yes "$VM" "set -e; cd ~/brain; cp -p novo-$TS/* .; rmdir novo-$TS 2>/dev/null || rm -rf novo-$TS
  set -a; . ./.env; set +a
  psql \"\$DATABASE_URL\" -v ON_ERROR_STOP=1 -q -f migracao_f4.sql
  nice -n 10 .venv/bin/python indexer.py --fts"
reiniciar
if saude; then
  echo "SAÚDE OK (REST + MCP) · reverter: deploy/vm2/brain/implantar.sh --reverter $TS"
else
  echo "SAÚDE FALHOU — voltando para bak-$TS"
  ssh -o BatchMode=yes "$VM" "cd ~/brain && cp -p bak-$TS/* ."
  reiniciar; saude && echo "revertido e saudável" || echo "ATENÇÃO: revertido e AINDA sem saúde"
  exit 1
fi
