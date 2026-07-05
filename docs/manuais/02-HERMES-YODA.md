# Manual — Hermes / Yoda (gateway Telegram)

## O que é
**Yoda** é o rosto no Telegram. Por trás dele roda o **Hermes** (`~/hermes-agent`, fork do
NousResearch/hermes-agent) como `hermes-gateway.service`. Você fala em português; ele decide se
responde direto ou aciona a API do JFN (`127.0.0.1:8000`).

## Como ligar/ver
```bash
systemctl --user status hermes-gateway.service
systemctl --user restart hermes-gateway.service
journalctl --user -u hermes-gateway -f
```

## Comandos essenciais (o que uma pessoa leiga digita)
- `/relatorio <empresa>` · `/orgao <UG ou nome>` · `/dossie <alvo>`
- `/pericia <CNPJ|OB|nome>` — perícia com laudo
- `/veredito <ref> confirmado|descartado|inconclusivo` — fecha o ciclo
- `/promover <ref>` — perícia confirmada vira caso-ouro
- Ou simplesmente escreva: *"quanto o ITERJ pagou em 2024?"*

## Atualização automática (auto-update noturno)
- `hermes-update.timer` (~04:00) roda `update-hermes-safe.sh`: backup → merge do upstream →
  valida `import hermes_cli` → restart → healthcheck → **auto-revert se quebrar**.
- **Clone NÃO pode ser shallow** (senão dá `unrelated histories`). Corrigido 2026-07-05 com
  `git fetch --unshallow`. Se voltar o erro, checar `git rev-parse --is-shallow-repository`.

## IAs que ele usa (custo controlado)
- Sweep SEI em volume → **nous stepfun:free** (única IA do volume; grátis).
- Produtos (/relatorio, Lex) → gemini (qualidade) + cerebras (rede de segurança).
- OpenRouter: **somente modelos :free**.

## Sono REM (metacognição)
`jfn-metacognicao.timer` (06:50) — reflexão + auto-melhoria + rebuild do RAG só-se-mudou +
backup da memória no vault.

## Quando algo falha
- Telegram "network error / reconnect" nos logs = flap de rede transitório; ele reconecta sozinho
  (fallback de IPs). Só agir se ficar minutos sem `is-active`.
