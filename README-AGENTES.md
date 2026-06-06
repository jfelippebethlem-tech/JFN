# Mapa de Repositórios e Agentes — Ecossistema Mestre Jorge

**Última atualização:** 2026-06-03  
**Mestre Jorge** | Telegram Bot: **Mestre Yoda** | Agente Desktop: **Hermes** | Auditoria: **JFN**

> ⚠️ **Os caminhos `C:\...` abaixo são do desktop Windows legado.** O ambiente de PRODUÇÃO é a **VM Linux
> GCP** — veja [`AMBIENTE.md`](AMBIENTE.md) para os caminhos e serviços reais (JFN em `~/JFN`, Yoda em
> `hermes-gateway.service`, barramento HTTP em `127.0.0.1:8000`). Em caso de divergência, **`AMBIENTE.md` vence.**

---

## Repositórios Principais

| Agente | Função | Repositório GitHub | Branch | Caminho Local |
|---|---|---|---|---|
| **JFN** | Agente auditor / compliance do governo RJ | https://github.com/jfelippebethlem-tech/JFN.git | `claude/rj-finance-agent-BYlhJ` | `C:\JFN\jfn` |
| **Massare** | Agente de análise de mercado autônomo (câmbio, bolsas, commodities, riscos e oportunidades) | Skill própria `investidor-mercados/market-analyst-massare` | Integrado ao briefing diário | `C:\Users\socah\AppData\Local\hermes\skills\investidor-mercados\market-analyst-massare` |
| **Hermes** | Agente desktop / CLI pessoal | https://github.com/nousresearch/hermes-agent | — | `C:\Users\socah\.hermes` |
| **Mestre Yoda** | Bot Telegram | *Não é repo separado* — usa a instância Hermes configurada como bot Telegram | — | `C:\Users\socah\.hermes` |

---

## Agentes e Suas Identidades

- **Mestre Yoda** — Bot do Telegram
  - Envia a rotina `BOM DIA DO MESTRE JORGE` todo dia às 7:30
  - Formato: clima Barra da Tijuca + piada + versículo bíblico + mercado (dólar, bolsa, ouro, petróleo) + 10 notícias (5 Brasil, 5 Rio) sem encurtar links
  - Token/chat: configurado no `config.yaml` do Hermes
  - gateway_state.json em `C:\Users\socah\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\hermes-start.cmd`

- **Hermes** — Agente desktop
  - CLI / TUI local em `C:\Users\socah\.hermes`
  - Providers configurados: Ollama local, OpenRouter, Mistral, HuggingFace, Gemini, Nemotron
  - Skills instaladas: `captcha-bypass-easyocr`, `devops/kanban-orchestrator`, observability/langfuse, disk-cleanup
  - Rotina de auto-start e self-heal para Telegram 24h

- **JFN** — Agente de auditoria compliance
  - Alvo: SEI do RJ (https://sei.rj.gov.br)
  - Scripts prontos: `compliance_agent/captcha_solver.py`, `compliance_agent/collectors/sei_cdp.py`
  - Coleta dados de DOERJ/SIAFE via OCR/CDP quando rota liberada
  - Branch: `claude/rj-finance-agent-BYlhJ`
  - **Todos os códigos devem ser commitados e enviados para o GitHub após alterações**

---

## Dados e Conteúdo Estático

| Item | Repositório/Arquivo | Finalidade |
|---|---|---|
| Notas de mercado e pesquisa | `/c/repos/Finance`, `/c/repos/free-market-data-widgets` | Fontes para a rotina do Yoda |
| Lista de plugins Hermes | `C:\Users\socah\Desktop\hermes-plugins-passo-a-passo.txt` | Instalação passo a passo |
| IAs boas para código | `C:\Users\socah\Desktop\IAs boas pra codigo.txt` | Referência de modelos |

---


---

## Questões Conhecidas

- **Memória do Agente Hermes**: O agente Hermes tem uma limitação na sua memória de usuário (user profile). A ferramenta `memory` exige uma correspondência exata de texto para remover ou substituir entradas, o que pode dificultar a atualização e o gerenciamento de informações. Esta questão precisa ser investigada e resolvida para garantir que o agente possa manter suas configurações e preferências de forma eficiente.

## Regras Fixas

- **Nunca encurtar links** de notícias — usar URLs completas dos portais
- **Todos os códigos** do JFN → commit + push na branch configurada
- **Telegram 24h** — usar `telegram-self-heal.cmd` e resetar `gateway_state.json` antes de `hermes gateway run`
- **Ética** — não burlar TLS/SSL, não usar ferramentas sem ética, não se passar por terceiros
