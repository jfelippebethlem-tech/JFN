#!/bin/bash
# migracao_bringup.sh — sobe o JFN no DESTINO depois da transferência via Tailscale.
# IDEMPOTENTE (pode rodar de novo). HONESTO (PASS/FAIL por etapa, nunca falha em silêncio).
#
# Uso:
#   bash tools/migracao_bringup.sh           # setup + checks (NÃO liga serviços nem mexe no crontab)
#   bash tools/migracao_bringup.sh --ativar   # + enable/start dos serviços/timers + instala o crontab (GO-LIVE)
#
# O modo padrão é SEGURO (não ativa nada) p/ você poder rodar e revisar antes do go-live — e p/ não re-ligar
# por acidente se rodar na própria origem. Só o --ativar coloca no ar.
set -u
ATIVAR=0; [ "${1:-}" = "--ativar" ] && ATIVAR=1
cd "$HOME/JFN" || { echo "FATAL: ~/JFN não existe — copie o diretório primeiro."; exit 1; }
PY=.venv/bin/python
ok(){ echo "  [PASS] $*"; }
no(){ echo "  [FAIL] $*"; FAILS=$((FAILS+1)); }
warn(){ echo "  [WARN] $*"; }
FAILS=0

echo "==================== JFN bring-up (destino) ===================="
echo "USER=$USER  HOME=$HOME  modo=$([ $ATIVAR = 1 ] && echo GO-LIVE || echo 'setup+checks (sem ativar)')"

echo; echo "── 0) Preflight de caminho ──"
# units usam %h (portáveis); MAS venv-shebang e crontab têm caminho absoluto /home/jfelippebethlem.
if [ "$HOME" != "/home/jfelippebethlem" ]; then
  warn "HOME != /home/jfelippebethlem → o venv copiado e o crontab-backup têm paths absolutos antigos."
  warn "  → o passo do venv vai RECRIAR (resolve o shebang); o crontab você revisa antes do --ativar."
else ok "mesmo HOME — paths absolutos batem"; fi

echo; echo "── 1) Segredos gitignored presentes? ──"
for f in "$HOME/JFN/.env" "$HOME/.hermes/.env" "$HOME/.hermes/auth.json" "$HOME/.config/rclone/rclone.conf"; do
  [ -s "$f" ] && ok "$f" || no "$f AUSENTE/vazio (copie à mão — não está no git)"
done

echo; echo "── 2) DB consistente? ──"
if [ -s data/compliance.db ]; then
  SZ=$(du -h data/compliance.db | cut -f1); ok "compliance.db ($SZ)"
  [ -f data/compliance.db-wal ] && warn "existe -wal (copie junto OU rode checkpoint) " || ok "sem -wal pendente"
else no "data/compliance.db ausente"; fi

echo; echo "── 3) venv (Python 3.12) ──"
NEED_VENV=0
if [ -x "$PY" ] && $PY -c "import playwright, fastapi" 2>/dev/null; then ok "venv funcional (playwright+fastapi importam)"
else NEED_VENV=1; warn "venv ausente/quebrado → recriando"; fi
if [ $NEED_VENV = 1 ]; then
  command -v python3.12 >/dev/null || { no "python3.12 não instalado no destino"; }
  if command -v python3.12 >/dev/null; then
    rm -rf .venv && python3.12 -m venv .venv && $PY -m pip -q install -U pip wheel \
      && $PY -m pip -q install -r requirements.txt $( [ -f requirements-sei.txt ] && echo -r requirements-sei.txt ) \
      && $PY -m playwright install chromium \
      && $PY -c "import playwright, fastapi" 2>/dev/null \
      && ok "venv recriado + chromium" || no "recriação do venv falhou (ver erro acima)"
  fi
fi

echo; echo "── 4) ms-playwright (browsers) ──"
if [ -d "$HOME/.cache/ms-playwright" ] && ls "$HOME/.cache/ms-playwright"/chromium-* >/dev/null 2>&1; then ok "browsers presentes"
else warn "sem browsers em cache → rode: $PY -m playwright install chromium"; fi

echo; echo "── 5) systemd user units ──"
if ls "$HOME/.config/systemd/user/jfn.service" >/dev/null 2>&1; then
  systemctl --user daemon-reload && ok "daemon-reload"
  loginctl enable-linger "$USER" 2>/dev/null && ok "linger ON (serviços sobem sem login)" || warn "enable-linger falhou (precisa de sudo? rode: sudo loginctl enable-linger $USER)"
else no "units não copiados p/ ~/.config/systemd/user/"; fi

if [ $ATIVAR = 1 ]; then
  echo; echo "── 6) GO-LIVE: enable + start ──"
  for s in jfn.service hermes-gateway.service chrome-jfn.service; do
    systemctl --user enable --now "$s" 2>/dev/null && ok "up $s" || no "falhou $s (systemctl --user status $s)"
  done
  for t in jfn-ronda.timer jfn-tfe.timer jfn-tfe-ob.timer massare-daily.timer massare-market.timer; do
    systemctl --user enable --now "$t" 2>/dev/null && ok "timer $t" || warn "timer $t (opcional)"
  done
  # NÃO ativar sweeps-serial (lane contínuo revertido — cont.25). Sweeps rodam pelo CRONTAB.
  echo; echo "── 7) crontab (re-ativa os sweeps agendados) ──"
  BK=$(ls -1t data/crontab.backup.* 2>/dev/null | head -1)
  if [ -n "$BK" ]; then
    if crontab -l 2>/dev/null | grep -qE '^\s*[0-9*].*JFN'; then warn "crontab já tem jobs JFN — NÃO sobrescrevi (revise: crontab -l)"
    else crontab "$BK" && ok "crontab instalado de $BK" || no "crontab falhou"; fi
    warn "confira os paths do crontab se o HOME mudou: crontab -l | grep -v '^#'"
  else no "nenhum data/crontab.backup.* encontrado"; fi
  # garante que NÃO há pause flags travando os sweeps no destino
  rm -f data/.pause_sweeps data/.pause_*_sweep 2>/dev/null && ok "pause flags removidos (sweeps liberados)"
else
  echo; echo "── 6/7) (pulados — rode com --ativar p/ ligar serviços/timers/crontab) ──"
fi

echo; echo "── 8) Sanidade ──"
if [ $ATIVAR = 1 ]; then
  sleep 4
  systemctl --user is-active jfn.service hermes-gateway.service chrome-jfn.service | tr '\n' ' '; echo
  if curl -s --max-time 5 127.0.0.1:8000/api/lista | head -c 120 | grep -q "."; then ok "API 127.0.0.1:8000/api/lista respondeu"
  else no "API não respondeu (systemctl --user status jfn; journalctl --user -u jfn -n50)"; fi
else
  echo "  (sanidade de API só no --ativar)"
fi

echo; echo "── 9) Tailscale ──"
command -v tailscale >/dev/null && { tailscale status >/dev/null 2>&1 && ok "tailscale conectado" || warn "instalado mas não logado → sudo tailscale up"; } || warn "tailscale não instalado"

echo; echo "==================== RESUMO: $([ $FAILS = 0 ] && echo 'TUDO OK ✅' || echo "$FAILS FALHA(S) ❌ — ver [FAIL] acima") ===================="
[ $ATIVAR = 0 ] && echo "Setup/checks OK? rode de novo com:  bash tools/migracao_bringup.sh --ativar"
exit $([ $FAILS = 0 ] && echo 0 || echo 1)
