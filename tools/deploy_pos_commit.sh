#!/bin/bash
# deploy_pos_commit.sh — deploy do painel SEM o dono (Etapa 2, passo 7 — 24/11/2026).
#
# Chamado em 2º plano pelos ganchos locais .git/hooks/post-commit e post-merge (não versionados; ver o fim deste
# arquivo). Se o commit tocou rotas/, server.py ou compliance_agent/, reinicia o jfn.service e confere HTTP 200 em
# `/` e numa rota leve. Antes, código commitado só entrava no ar quando alguém lembrava de reiniciar — e a rota
# servia o módulo velho (o import fica em memória até o restart).
#
# Rajada de commits = UM restart: a trava é tomada já na chegada e a espera junta os commits seguintes (o gancho
# que chega com a trava ocupada sai — quem a segura compara com o HEAD depois da espera).
# Falha NÃO entra em laço nem reverte código: grava data/deploy_estado.json (ok=false + motivo) e loga; o sensor
# `deploy` da automelhoria (tools/automelhoria_geral.py) abre o item. Desligar: touch data/.pause_deploy
set -u
cd /home/ubuntu/JFN || exit 0
mkdir -p data/locks
LOG=data/deploy_pos_commit.log
ESTADO=data/deploy_estado.json
ULTIMO=data/deploy_ultimo_commit.txt
BASE_URL=${JFN_BASE:-http://127.0.0.1:8000}
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
[ -f data/.pause_deploy ] && { log "pausado (data/.pause_deploy)"; exit 0; }

exec 9>data/locks/deploy_pos_commit.lock
flock -n 9 || exit 0
sleep "${DEPLOY_ESPERA_S:-90}"

head=$(git rev-parse HEAD 2>/dev/null) || exit 0
base=$(cat "$ULTIMO" 2>/dev/null)
git cat-file -e "${base:-x}^{commit}" 2>/dev/null || base=$(git rev-parse HEAD~1)
[ "$base" = "$head" ] && exit 0
mudou=$(git diff --name-only "$base" "$head" -- rotas/ server.py compliance_agent/ | head -50)
if [ -z "$mudou" ]; then
  echo "$head" > "$ULTIMO"; exit 0
fi

estado() {  # ok motivo
  printf '{"ok": %s, "commit": "%s", "base": "%s", "quando": %s, "motivo": "%s"}\n' \
    "$1" "${head:0:12}" "${base:0:12}" "$(date +%s)" "$(printf '%s' "$2" | tr '"\n' "' " | cut -c1-300)" > "$ESTADO.tmp" \
    && mv "$ESTADO.tmp" "$ESTADO"
}

export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}   # gancho de agente/cron não tem o barramento
log "deploy ${base:0:8}..${head:0:8}: $(echo "$mudou" | wc -l) arquivo(s) de código — reiniciando jfn.service"
if ! systemctl --user restart jfn.service >> "$LOG" 2>&1; then
  log "FALHOU: systemctl restart"; estado false "systemctl --user restart jfn.service falhou"; exit 0
fi

# saúde: / e uma rota leve (só lê data/propagacao.db) com 200, até 180 s (a VM-1 sobe devagar em carga 15)
fim=$(( $(date +%s) + ${DEPLOY_SAUDE_S:-180} ))
while :; do
  a=$(curl -s -m 20 -o /dev/null -w '%{http_code}' "$BASE_URL/")
  b=$(curl -s -m 20 -o /dev/null -w '%{http_code}' "$BASE_URL/api/sistema/propagacao")
  [ "$a" = 200 ] && [ "$b" = 200 ] && break
  if [ "$(date +%s)" -ge "$fim" ]; then
    log "FALHOU: saúde / = $a, /api/sistema/propagacao = $b depois do restart (código ${head:0:8} no ar com erro?)"
    estado false "depois do restart: / = $a, /api/sistema/propagacao = $b (journalctl --user -u jfn)"
    exit 0
  fi
  sleep 5
done
echo "$head" > "$ULTIMO"
estado true "200 em / e /api/sistema/propagacao"
log "ok ${head:0:8} no ar (200 em / e /api/sistema/propagacao)"
exit 0

# Ganchos locais (.git/hooks/post-commit e .git/hooks/post-merge), conteúdo:
#   #!/bin/bash
#   setsid nohup bash /home/ubuntu/JFN/tools/deploy_pos_commit.sh >/dev/null 2>&1 < /dev/null &
#   exit 0
