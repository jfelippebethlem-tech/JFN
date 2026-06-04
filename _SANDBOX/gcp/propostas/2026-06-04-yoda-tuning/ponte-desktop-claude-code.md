# Tarefa 2 — Desktop ↔ Claude Code (VM) se falarem e continuarem sessão

**Status: PROPOSTO (pesquisa + recomendação). Nada aplicado.**
Parte disto depende do Desktop do Mestre Jorge (Mac/Windows), que eu não acesso da VM.

## O que NÃO existe (pra não criar expectativa errada)
- Não há "MCP server do Claude Code" que o Desktop adicione para **dirigir** o Claude Code
  da VM remotamente.
- Sessões **não** são compartilhadas entre superfícies por padrão: uma sessão do Desktop
  não é "resumida" pela CLI e vice-versa — cada superfície tem seu histórico próprio
  (`~/.claude/projects/<hash>/<session-id>.jsonl`).
- Não dá pra túnel de MCP stdio do VM → Desktop (só HTTP/SSE).

## O que JÁ existe neste repo
`_SANDBOX/gcp/claude_bridge.py`: ponte **Telegram `/claude` → Claude Code headless** na VM
(`claude -p "<texto>"`). É **uma direção** (mensagem → Claude Code) e exige um **2º bot**
(`CLAUDE_BOT_TOKEN`) para não conflitar com o poller do Yoda. Útil, mas não é "continuar
sessão do Desktop".

## Recomendação principal (caminho suportado): SSH do Desktop → VM
O Claude Desktop tem **suporte nativo a sessão por SSH**. Em vez de tentar fazer duas
sessões diferentes "conversarem", **unifica-se tudo na VM** e troca-se só a interface:

1. No Claude Desktop → aba Code → dropdown de ambiente → **+ Add SSH connection**:
   - Host: `jfelippebethlem@<IP-da-VM-GCP>`  • Porta: 22  • Identity file: sua chave SSH
   - Pasta inicial: `~/hermes-agent` (ou `~/JFN`)
2. Inicie a sessão escolhendo o ambiente **SSH**. O Desktop instala/usa o Claude Code na VM.
3. A sessão **roda na VM**; transcrição em `~/.claude/projects/...` na própria VM.
4. Continuidade: feche o Desktop → estado preservado na VM. Reabra na mesma conexão SSH, ou
   na CLI da VM rode `claude --continue` / `claude --resume` para retomar.

Assim, "Desktop" e "Code da VM" passam a ser a **mesma sessão** (mesmo disco, mesmo histórico),
só com pontos de entrada diferentes — que é exatamente "continuar de um no outro".

## Continuidade de contexto (qualquer cenário)
- **`CLAUDE.md` no repo** (`~/JFN/CLAUDE.md` e/ou `~/hermes-agent/CLAUDE.md`): carregado
  automaticamente por toda sessão (Desktop e CLI). É o "cérebro compartilhado" — decisões,
  caminhos, convenções. **Recomendo criar** (proposta separada).
- **`/export`**: dentro de uma sessão, `/export /tmp/handoff.md` salva a transcrição; cole o
  resumo na outra superfície.
- **Arquivo de handoff compartilhado**: um `~/.claude/handoff.md` (ou no repo) onde cada lado
  escreve "onde parei / próximos passos". Simples e robusto; serve de ponte assíncrona
  Desktop↔Yoda↔Code.

## Recomendação para o revisor decidir
1. **(Preferido)** Configurar SSH do Desktop → VM (passos acima). Resolve "continuar sessão"
   de verdade, é suportado, e não precisa de gambiarra.
2. **(Complementar)** Criar `CLAUDE.md` no repo como contexto compartilhado.
3. **(Opcional)** Manter o `claude_bridge.py` para perguntas rápidas ao Claude via Telegram.

Fontes: docs oficiais do Claude Code (desktop/SSH sessions, sessions/resume, mcp-servers).
