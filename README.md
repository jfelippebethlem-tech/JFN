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
- **Rotina diária "BOM DIA"** — a funcionalidade-assinatura do bot original,
  migrada: um briefing matinal agendado, com cotações reais (dólar, Ibovespa,
  ouro, petróleo) e notícias do Brasil e do Rio, links sempre completos.

## Arquitetura

```
Telegram  ──►  Mestre Yoda (bot.py)        camada de persona / I/O
                   │   monta o AgentRequest (protocol.py)
                   ▼
               Hermes (hermes.py)          raciocínio + ferramentas (Claude)
                   │   usa memória, mercado e tools
                   ▼
               Memória (memory.py)         SQLite: mensagens, resumos, fatos
```

| Módulo | Responsabilidade |
| --- | --- |
| `mestre_yoda/config.py` | Configuração via variáveis de ambiente. |
| `mestre_yoda/persona.py` | Personalidade do Mestre Yoda (system prompt). |
| `mestre_yoda/protocol.py` | Contrato `AgentRequest` / `AgentResponse` entre camadas. |
| `mestre_yoda/memory.py` | Memória persistente (SQLite) + resumo automático. |
| `mestre_yoda/market.py` | Cotações reais (yfinance) — dólar, Ibovespa, ouro, petróleo. |
| `mestre_yoda/tools.py` | Ferramentas do Hermes (hora, fatos, mercado). |
| `mestre_yoda/briefing.py` | Roteiro da rotina diária "BOM DIA". |
| `mestre_yoda/hermes.py` | Agente Hermes: loop agêntico com Claude. |
| `mestre_yoda/bot.py` | Handlers do Telegram + agendamento da rotina diária. |
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
| `YODA_ENABLE_WEB_SEARCH` | não | `true` | Liga a busca na web do Hermes (fatos atuais). |
| `YODA_ALLOWED_CHAT_IDS` | não | — | Lista de chat IDs permitidos (separados por vírgula). Vazio = todos. |
| `YODA_LOG_LEVEL` | não | `INFO` | Nível de log. |
| `YODA_BRIEFING_ENABLED` | não | `false` | Liga o envio automático da rotina "BOM DIA". |
| `YODA_BRIEFING_CHAT_ID` | quando ligado | — | Chat que recebe a rotina diária. |
| `YODA_BRIEFING_TIME` | não | `07:00` | Horário de envio (`HH:MM`, 24h). |
| `YODA_BRIEFING_TIMEZONE` | não | `America/Sao_Paulo` | Fuso do horário acima. |

## Executando

```bash
python -m mestre_yoda
```

### Com Docker (recomendado para produção)

O Docker evita problemas de bibliotecas nativas do host e mantém a memória num
volume persistente:

```bash
cp .env.example .env   # preencha os tokens
docker compose up -d --build
docker compose logs -f
```

A memória fica no volume `yoda_data` (`/data/yoda_memory.db` dentro do
contêiner), então sobrevive a reinícios e atualizações.

## Comandos do bot

| Comando | Ação |
| --- | --- |
| `/start` | Apresentação do Mestre Yoda. |
| `/help` | Lista de comandos. |
| `/bomdia` | Monta a rotina matinal (mercado + notícias) sob demanda. |
| `/esquecer` | Apaga a memória da conversa atual. |
| `/lembrancas` | Mostra os fatos que o Yoda guardou sobre você. |
| _(qualquer texto)_ | Conversa com o Mestre Yoda. |

## Rotina diária "BOM DIA"

Funcionalidade-assinatura do bot original, agora montada pelo Hermes em vez de
um template preenchido à mão. Quando `YODA_BRIEFING_ENABLED=true`, o bot agenda
um envio diário (via `JobQueue`) no horário/fuso configurados, para o
`YODA_BRIEFING_CHAT_ID`. O `/bomdia` dispara a mesma rotina sob demanda.

O Hermes usa a ferramenta `get_market_data` (cotações reais via yfinance) e a
busca na web (clima e notícias). As regras herdadas do formato original
continuam valendo: **links sempre completos** (nunca encurtados), **dados de
mercado reais** (nunca inventados) e notícias do **Brasil e do Rio**. Se a
fonte real falhar, o Yoda diz que faltou em vez de fabricar números.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes de memória e protocolo rodam sem rede. O agente Hermes é exercitado
com um cliente Claude *fake*, então `pytest` não consome créditos da API.

## O que veio do bot original

Com os dois repositórios no escopo da sessão, comparamos esta reescrita com o
bot original (`Yoda-Telegram-e-Agente-Hermes`) e migramos o que fazia sentido:

| Recurso do original | Situação na reescrita |
| --- | --- |
| Rotina "BOM DIA" às 7h (mercado + notícias) | **Migrada** — `briefing.py` + agendamento no `bot.py`. |
| Cotações reais (yfinance: `^BVSP`, `USDBRL=X`, `GC=F`, `CL=F`) | **Migradas** — `market.py` + ferramenta `get_market_data`. |
| Regras "links completos / dados reais / Brasil + Rio" | **Migradas** — codificadas no roteiro do briefing. |
| Persona Yoda, memória, notícias na web | Já existiam — reescritas e ampliadas. |
| Scripts Windows de auto-start / self-heal (`.cmd`) | **Não migrados** — substituídos por `docker compose` com `restart: unless-stopped`. |
