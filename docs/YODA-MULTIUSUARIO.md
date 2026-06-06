# Yoda multiusuário — bot-convidado SEGURO (sua filha e outros sem acesso a código)

## Por que um bot SEPARADO (e não liberar no bot admin)
O bot admin do Yoda roda sobre o **Hermes**, que é um agente de código completo — a ferramenta `terminal`
é um **shell**. O allowlist do Hermes é **binário** (`telegram.allowed_users`) e `disabled_toolsets` é
**global**: não há como dar a um convidado um acesso *parcial* seguro. Adicionar a filha ao bot admin daria
a ela poder de rodar comandos/editar o ecossistema. **Não fazer isso.**

## A solução: `tools/guest_bot.py` — mínimo e estrutural-seguro
Um bot dedicado que **não tem shell, não executa código, não acessa arquivos**. Ele só faz chamadas HTTP de
**leitura** à API do JFN (`127.0.0.1:8000`) e devolve texto formatado. É impossível, por construção, um
convidado alcançar o código do ecossistema por ele.

- **Token próprio** (`TELEGRAM_BOT_TOKEN_GUEST`) — um bot SEPARADO criado no @BotFather. NUNCA o token do admin.
- **Allowlist própria** (`TELEGRAM_GUEST_USERS`, IDs separados por vírgula). Quem não está na lista é recusado.
- **Comandos read-only:** `/relatorio <empresa|cnpj>`, `/anomalias [arg]`, `/cartel [captura|<cnpj>]`, `/ajuda`.

## Como ativar (passos do Mestre Jorge — uma vez)
1. **Criar o bot-convidado:** no Telegram, fale com **@BotFather** → `/newbot` → copie o token.
2. **Descobrir o ID da filha:** peça para ela mandar uma mensagem ao bot **@userinfobot** (ele responde o `id`),
   ou rode o guest_bot e veja o log quando ela escrever (o ID recusado aparece).
3. **Preencher o `.env`** (em `/home/jfelippebethlem/JFN/.env`):
   ```
   TELEGRAM_BOT_TOKEN_GUEST=<token do BotFather>
   TELEGRAM_GUEST_USERS=<id_da_filha>            # vários: 111,222,333
   ```
4. **Subir o serviço:**
   ```
   systemctl --user enable --now hermes-guest-bot.service
   systemctl --user status hermes-guest-bot.service
   ```
   (O serviço já está instalado em `~/.config/systemd/user/hermes-guest-bot.service`; sem token ele apenas sai.)

## Garantias de segurança
- Sem `terminal`/shell, sem `eval`/`subprocess`, sem filesystem — só `httpx` para rotas GET/POST de leitura do JFN.
- Usuário fora da allowlist recebe "Acesso restrito" e nada é executado.
- Não altera nada no sistema; não toca o bot admin nem o `jfn.service`.
- Mesma cláusula de honestidade: tudo é **indício**, nunca acusação.

## Adicionar/remover usuários depois
Edite `TELEGRAM_GUEST_USERS` no `.env` e `systemctl --user restart hermes-guest-bot.service`.

> Conteúdo do serviço (para referência/reprovisionamento), em `~/.config/systemd/user/hermes-guest-bot.service`:
> `ExecStart=.venv/bin/python tools/guest_bot.py`, `EnvironmentFile=.../JFN/.env`, `WorkingDirectory=.../JFN`.
