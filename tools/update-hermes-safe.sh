#!/bin/bash
# ============================================================================
# update-hermes-safe.sh — atualiza o Hermes SEM quebrar (com auto-revert)
# ----------------------------------------------------------------------------
# Por que existe: "toda vez que faço o hermes update ele para de funcionar".
# Causas: (1) deps mudam e o venv fica stale; (2) o serviço systemd não é
# reiniciado e roda código velho/quebrado; (3) merge clobbera config.
# Este script faz a sequência SEGURA e, se algo falhar, REVERTE sozinho.
#
# Uso:  ~/hermes-agent/update-hermes-safe.sh
# ============================================================================
set -uo pipefail
H="$HOME/hermes-agent"; HC="$HOME/.hermes"; SVC="hermes-gateway"
ts=$(date +%s)
log(){ printf '\033[36m→\033[0m %s\n' "$*"; }
ok(){  printf '\033[32m✓\033[0m %s\n' "$*"; }
err(){ printf '\033[31m✗\033[0m %s\n' "$*"; }

# Notificação Telegram INDEPENDENTE do gateway (curl direto na API do bot) — o update
# não pode ser mudo: se reverter/conflitar às 04h, o dono precisa saber de manhã.
notificar(){
  local msg="$1"
  local tok chat
  tok=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' "$HC/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'")
  chat=$(grep -m1 '^TELEGRAM_CHAT_ID=' "$HC/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'")
  [ -n "$tok" ] && [ -n "$chat" ] || return 0
  curl -sS -m 15 "https://api.telegram.org/bot${tok}/sendMessage" \
    -d chat_id="$chat" --data-urlencode text="$msg" >/dev/null 2>&1 || true
}

cd "$H" || { err "repo $H não existe"; exit 1; }

# 1) BACKUP de config e .env (vivem em ~/.hermes, fora do repo — mas garantimos)
log "backup de .env e config.yaml…"
[ -f "$HC/.env" ]        && cp -a "$HC/.env"        "$HC/.env.bak.update-$ts"
[ -f "$HC/config.yaml" ] && cp -a "$HC/config.yaml" "$HC/config.yaml.bak.update-$ts"
ok "backup em $HC/*.bak.update-$ts"
# prune: mantém só os 5 backups mais recentes de cada série (estavam acumulando)
ls -t "$HC"/.env.bak.update-* 2>/dev/null | tail -n +6 | xargs -r rm -f
ls -t "$HC"/config.yaml.bak.update-* 2>/dev/null | tail -n +6 | xargs -r rm -f

# 2) preserva qualquer modificação local do repo
BEFORE=$(git rev-parse HEAD)
STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "guardando mods locais (git stash)…"; git stash push -u -m "pre-update-$ts" && STASHED=1
fi
# BUG corrigido 2026-07-04: o stash era engolido nos exits (conflito/já-atualizado) — mods
# locais sumiam silenciosamente a cada update. Agora todo caminho de saída devolve o stash.
restaurar_stash(){
  [ "$STASHED" = 1 ] || return 0
  if git stash pop >/dev/null 2>&1; then ok "mods locais restaurados do stash"; STASHED=0
  else
    err "stash não aplicou limpo — mods preservados (git stash list)"
    notificar "⚠️ Hermes update: mods locais ficaram presos no stash (não aplicou limpo). Recuperar com 'git stash pop' em ~/hermes-agent."
  fi
}

# 3) ATUALIZA (merge do upstream). Conflito → aborta e mantém tudo como estava.
log "buscando upstream…"; git fetch origin || { err "fetch falhou (rede?)"; restaurar_stash; exit 1; }
log "merge origin/main…"
if ! git merge --no-edit origin/main; then
  err "CONFLITO no merge — abortando e mantendo a versão atual (nada quebrou)."
  git merge --abort 2>/dev/null
  restaurar_stash
  notificar "⚠️ Hermes update: CONFLITO no merge com o upstream — mantive a versão atual (nada quebrou), mas o Hermes está ficando PARA TRÁS. Resolver o conflito manualmente em ~/hermes-agent."
  exit 1
fi
AFTER=$(git rev-parse HEAD)
[ "$BEFORE" = "$AFTER" ] && { ok "já estava atualizado — nada a fazer."; restaurar_stash; exit 0; }

# 4) reinstala deps (uv preferido, do lockfile)
reinstalar(){
  if command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="$H/.venv" uv pip install -e . >/tmp/hermes_deps.log 2>&1 \
      || "$H/.venv/bin/pip" install -e . >>/tmp/hermes_deps.log 2>&1
  else
    "$H/.venv/bin/pip" install -e . >/tmp/hermes_deps.log 2>&1
  fi
}
log "reinstalando dependências…"; reinstalar && ok "deps ok" || err "deps com aviso (ver /tmp/hermes_deps.log)"

# 5) garante que config/.env continuam lá (merge não vive em ~/.hermes, mas conferimos)
[ -f "$HC/config.yaml" ] || cp "$HC/config.yaml.bak.update-$ts" "$HC/config.yaml"
[ -f "$HC/.env" ]        || cp "$HC/.env.bak.update-$ts" "$HC/.env"

# 6) valida import ANTES de reiniciar; se quebrou → REVERTE
reverter(){
  err "update quebrou → revertendo para $BEFORE"
  git reset --hard "$BEFORE"; restaurar_stash; reinstalar
  systemctl --user restart "$SVC"; sleep 5
  if systemctl --user is-active --quiet "$SVC"; then
    ok "revertido e ativo"
    notificar "⚠️ Hermes update: a versão nova QUEBROU → auto-revert OK, Yoda continua no ar na versão anterior ($(git rev-parse --short "$BEFORE")). Investigar o que quebrou antes do próximo update."
  else
    err "revertido, mas serviço não subiu — checar manual"
    notificar "🔴 Hermes update: quebrou E o auto-revert não subiu o serviço — YODA PODE ESTAR FORA DO AR. Checar hermes-gateway na VM urgente."
  fi
  exit 1
}
log "validando import do hermes_cli…"
"$H/.venv/bin/python" -c "import hermes_cli" 2>/dev/null || reverter

# 7) reinicia o serviço e faz healthcheck (is-active + sem traceback recente no log)
log "reiniciando $SVC…"; systemctl --user restart "$SVC"; sleep 8
if ! systemctl --user is-active --quiet "$SVC"; then
  reverter
fi
# healthcheck profundo: o serviço pode subir "ativo" mas estar logando exceção em loop.
GLOG="$HC/logs/gateway.log"
if [ -f "$GLOG" ] && tail -n 40 "$GLOG" | grep -qiE "Traceback|CRITICAL|Fatal|ImportError|ModuleNotFound"; then
  err "serviço ativo mas log mostra erro pós-update:"
  tail -n 8 "$GLOG"
  reverter
fi
restaurar_stash
ok "Hermes atualizado ($BEFORE → $AFTER), ATIVO e sem erro no log. Backups: $HC/*.bak.update-$ts"
notificar "✅ Hermes atualizado com sucesso ($(git rev-parse --short "$BEFORE") → $(git rev-parse --short "$AFTER")), serviço ativo e sem erro no log."
