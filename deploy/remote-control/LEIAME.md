# Remote Control sempre no ar (24/11/2026)

O dono controla tudo pelo app Claude do celular e pelo claude.ai/code, sem pedido de permissão e sem bloqueio.

| Máquina | Como roda | Nome no app |
|---|---|---|
| VM-1 | tmux `rc` → `~/bin/claude-rc vm1-jfn-core` | vm1-jfn-core |
| VM-2 | tmux `rc` → `~/bin/claude-rc vm2-jfn-agent-2` | vm2-jfn-agent-2 |
| it-campo (Windows) | tarefa `JFN-RemoteControl` (no logon) → `C:\Users\iterj\JFN-rc\rc.ps1` | itcampo-windows |

- **Por que `--permission-mode bypassPermissions`.** Sem essa flag, as sessões criadas pelo app ligam o modo "auto". O
  classificador desse modo barra ações (por exemplo, disparar agente sem restrição), e foi isso que barrou o agente
  do PL 6065. Os `deny` do `~/.claude/settings.json` (WhatsApp) continuam valendo.
- **O laço reinicia o servidor se ele cair** (ele sai após ~10 min sem rede). `claude-rc` responde sozinho às duas
  perguntas de início (confiança na pasta home e "Enable Remote Control?").
- **No Windows**, a confiança da pasta `C:\Users\iterj\JFN-rc` está gravada em `~/.claude.json`, nas duas grafias
  (`\` e `/`).
- **`claude-tarefa <pasta>`** lança um agente headless pelo BRIEF.md da pasta, sem flag perigosa (que o app recusa).
  As permissões vêm do settings.
- **Credencial que faltar:** `python -m compliance_agent.credenciais com NOME -- comando` acha a credencial na VM-1,
  sem copiar nada.
- **Pendência:** o WSL do it-campo não tem login do Claude, e a distro encerra sem processo vivo (vmIdleTimeout).
  Por isso o it-campo usa o Claude do Windows.
