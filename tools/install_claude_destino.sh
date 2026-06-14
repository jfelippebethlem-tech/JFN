#!/bin/bash
# install_claude_destino.sh — instala o Claude Code no DESTINO (Ubuntu, ex.: JFN-Worker), igual à origem:
# Node 22 + npm global SEM sudo (prefix ~/.npm-global) + @anthropic-ai/claude-code. IDEMPOTENTE e HONESTO.
#
# Uso:  bash install_claude_destino.sh
# Depois (paridade de skills/memória/MCP): copie ~/.claude e ~/.claude.json da origem via Tailscale.
set -u
ok(){ echo "  [PASS] $*"; }
no(){ echo "  [FAIL] $*"; FAILS=$((FAILS+1)); }
warn(){ echo "  [WARN] $*"; }
FAILS=0
echo "==================== Instalar Claude Code (destino) ===================="

echo "── 1) Node >= 20 ──"
NODE_OK=0
if command -v node >/dev/null 2>&1; then
  V=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  [ "${V:-0}" -ge 20 ] && { ok "node $(node --version)"; NODE_OK=1; } || warn "node antigo ($(node --version)) — instalando 22"
else warn "node ausente — instalando 22"; fi
if [ $NODE_OK = 0 ]; then
  if command -v apt-get >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - \
      && sudo apt-get install -y nodejs \
      && ok "node instalado $(node --version)" || no "instalação do node falhou (rode com sudo disponível)"
  else no "apt-get não encontrado — instale Node 22 manualmente (nvm)"; fi
fi

echo; echo "── 2) npm global sem sudo (prefix ~/.npm-global) ──"
if command -v npm >/dev/null 2>&1; then
  mkdir -p "$HOME/.npm-global"
  npm config set prefix "$HOME/.npm-global" && ok "prefix = ~/.npm-global"
  if ! grep -q '.npm-global/bin' "$HOME/.bashrc" 2>/dev/null; then
    echo 'export PATH=$HOME/.npm-global/bin:$PATH' >> "$HOME/.bashrc"; ok "PATH adicionado ao ~/.bashrc"
  else ok "PATH já no ~/.bashrc"; fi
  export PATH="$HOME/.npm-global/bin:$PATH"
else no "npm ausente (o passo 1 do node deveria tê-lo trazido)"; fi

echo; echo "── 3) @anthropic-ai/claude-code ──"
if command -v npm >/dev/null 2>&1; then
  if command -v claude >/dev/null 2>&1; then ok "claude já instalado ($(claude --version 2>/dev/null | head -1)) — atualizando"; fi
  npm install -g @anthropic-ai/claude-code \
    && ok "instalado: $(claude --version 2>/dev/null | head -1)" || no "npm install -g @anthropic-ai/claude-code falhou"
fi

echo; echo "── 4) Paridade de config (skills/memória/MCP/conta) ──"
[ -d "$HOME/.claude" ] && ok "~/.claude presente ($(du -sh "$HOME/.claude" 2>/dev/null | cut -f1))" \
  || warn "~/.claude AUSENTE → copie da origem (skills graphify/obsidian, memória, CLAUDE.md global, settings)"
[ -s "$HOME/.claude.json" ] && ok "~/.claude.json presente (MCP + conta)" \
  || warn "~/.claude.json AUSENTE → copie da origem, OU rode 'claude' e faça /login"

echo; echo "── 5) Teste ──"
if command -v claude >/dev/null 2>&1; then
  ok "binário: $(command -v claude)"
  echo "  → rode:  cd ~/JFN && claude    (se pedir login: /login)"
else no "claude não está no PATH — abra um novo shell ou: export PATH=\$HOME/.npm-global/bin:\$PATH"; fi

echo; echo "==================== $([ $FAILS = 0 ] && echo 'CLAUDE PRONTO ✅' || echo "$FAILS FALHA(S) ❌") ===================="
exit $([ $FAILS = 0 ] && echo 0 || echo 1)
