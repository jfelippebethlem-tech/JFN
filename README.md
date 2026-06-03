# JFN — Mestre Yoda 🪐 & Agente Hermes

Bot de Telegram **Mestre Yoda** (a camada de persona e conversa) acoplado ao
**Hermes** (o agente de raciocínio movido a Claude, com ferramentas, memória e
protocolo próprio).

> "Fazer ou não fazer. Tentativa não há." — Mestre Yoda

Este repositório foi reescrito do zero a partir do bot original, com foco em:

- **Memória de verdade** — persistência em SQLite, resumo automático de
  conversas longas e um banco de *fatos* de longo prazo por usuário.
- **Protocolos reavaliados** — um contrato tipado e explícito entre o Yoda
  (Telegram) e o Hermes (agente), de modo que cada camada tenha uma única
  responsabilidade.
- **Adaptatividade** — _adaptive thinking_ do Claude, _prompt caching_,
  _retries_ com _backoff_ e degradação graciosa quando algo falha.

## Arquitetura

```
Telegram  ──►  Mestre Yoda (bot.py)        camada de persona / I/O
                   │   monta o AgentRequest (protocol.py)
                   ▼
               Hermes (hermes.py)          raciocínio + ferramentas (Claude)
                   │   usa memória e tools
                   ▼
               Memória (memory.py)         SQLite: mensagens, resumos, fatos
```

| Módulo | Responsabilidade |
| --- | --- |
| `mestre_yoda/config.py` | Configuração via variáveis de ambiente. |
| `mestre_yoda/persona.py` | Personalidade do Mestre Yoda (system prompt). |
| `mestre_yoda/protocol.py` | Contrato `AgentRequest` / `AgentResponse` entre camadas. |
| `mestre_yoda/memory.py` | Memória persistente (SQLite) + resumo automático. |
| `mestre_yoda/tools.py` | Ferramentas do Hermes (hora, fatos, etc.). |
| `mestre_yoda/hermes.py` | Agente Hermes: loop agêntico com Claude. |
| `mestre_yoda/bot.py` | Handlers do Telegram (a persona Yoda). |
| `mestre_yoda/__main__.py` | Ponto de entrada (`python -m mestre_yoda`). |

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencha os tokens
```

## Configuração

Defina no `.env` (ou no ambiente):

| Variável | Obrigatória | Padrão | Descrição |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | sim | — | Token do bot do Telegram (@BotFather). |
| `ANTHROPIC_API_KEY` | sim | — | Chave da API do Claude (Anthropic). |
| `ANTHROPIC_MODEL` | não | `claude-opus-4-8` | Modelo do Claude. |
| `YODA_DB_PATH` | não | `yoda_memory.db` | Caminho do banco SQLite. |
| `YODA_EFFORT` | não | `high` | Esforço de raciocínio (`low`/`medium`/`high`/`xhigh`/`max`). |
| `YODA_MAX_HISTORY` | não | `20` | Mensagens mantidas antes de resumir. |
| `YODA_ALLOWED_CHAT_IDS` | não | — | Lista de chat IDs permitidos (separados por vírgula). Vazio = todos. |
| `YODA_LOG_LEVEL` | não | `INFO` | Nível de log. |

## Executando

```bash
python -m mestre_yoda
```

## Comandos do bot

| Comando | Ação |
| --- | --- |
| `/start` | Apresentação do Mestre Yoda. |
| `/help` | Lista de comandos. |
| `/esquecer` | Apaga a memória da conversa atual. |
| `/lembrancas` | Mostra os fatos que o Yoda guardou sobre você. |
| _(qualquer texto)_ | Conversa com o Mestre Yoda. |

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes de memória e protocolo rodam sem rede. O agente Hermes é exercitado
com um cliente Claude *fake*, então `pytest` não consome créditos da API.
