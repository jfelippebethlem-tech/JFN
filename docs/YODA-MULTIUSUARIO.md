# Yoda multiusuário — decisão e configuração (atualizado 2026-06-07)

## Decisão final: BOT ÚNICO (sem 2º bot), aberto, com poder por usuário
O Mestre Jorge optou por **manter o Yoda aberto** (qualquer pessoa pode falar) e **não criar outro bot** no
@BotFather. O poder fica **por usuário**:
- **Admin (Jorge, ID `45338178`)** = acesso TOTAL (todos os comandos + chat livre + ferramentas, inclusive shell).
- **Convidados (qualquer outro ID)** = somente os slash commands seguros listados; e **comando perigoso
  (shell/`execute_code`) exige APROVAÇÃO do admin** (botão no Telegram) — convidado **não codifica nada sozinho**.

> O `tools/guest_bot.py` (bot separado read-only) foi **DESCONTINUADO/REMOVIDO** — recuperável via git se um dia
> se quiser o caminho de 2º bot. Storage do guest bot era ~7 KB + unit `disabled` (nunca rodou): **nada relevante
> a liberar**. A remoção foi por **clareza** (evitar dois caminhos contraditórios), não por espaço.

## Como está configurado (no `~/.hermes/`, fora do git — reproduza se reinstalar)
`~/.hermes/.env`:
```
GATEWAY_ALLOW_ALL_USERS=true          # bot ABERTO: qualquer um manda mensagem (auto, sem allowlist manual)
TELEGRAM_ALLOWED_USERS=45338178       # (mantido; o allow-all já libera todos)
```
`~/.hermes/config.yaml` (bloco `telegram:`):
```yaml
telegram:
  allowed_users: '45338178'
  allow_admin_from: '45338178'        # quem é ADMIN (full). Todo o resto = convidado.
  user_allowed_commands: ['relatorio', 'anomalias', 'cartel', 'status', 'help', 'whoami']
```
`~/.hermes/config.yaml` (bloco `approvals:`): `mode: manual`  (comando perigoso pede aprovação do admin).
Aplicar mudanças: `systemctl --user restart hermes-gateway.service`.

## Como funciona (mecanismo nativo do Hermes)
- `gateway/slash_access.py`: com `allow_admin_from` setado, **não-admins só rodam os `user_allowed_commands`**
  (+ piso `/help`, `/whoami`). Admin roda tudo.
- `approvals: mode=manual` + `gateway/run.py`: comando perigoso dispara pedido de aprovação; **só usuário
  autorizado (admin) aprova** — convidado não executa shell/código.

## ⚠️ Resíduo conhecido (e como apertar)
O gate nativo é por **slash command**; o **chat livre** de convidado ainda chega ao agente (custa token e pode
acionar ferramentas de leitura). O `approvals: manual` impede a EXECUÇÃO de código/shell, mas não o chat em si.
**Para travar o chat livre de convidados** (só permitir os slash commands) — recomendado num sistema com dados
sensíveis — adicionar um *hook* de mensagem que nega entrada de não-admin fora da allowlist. Item p/ próxima run.
