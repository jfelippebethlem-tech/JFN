# CLAUDE.md — Guia do Projeto JFN

> **Para qualquer agente (Claude no Desktop, no app do celular ou nesta VM):**
> Leia este arquivo **antes** de mexer em qualquer coisa. Ele resume o projeto,
> a arquitetura, as variáveis de ambiente e como rodar. As regras de governança
> em [`CONSTITUICAO.md`](CONSTITUICAO.md) são **obrigatórias** e prevalecem.

---

## 1. O que é o JFN

**Agente auditor autônomo de compliance** para dados públicos do Estado do Rio de
Janeiro. Coleta e cruza informações de:

- **SIAFE2** — execução orçamentária / Ordens Bancárias (OBs). Só acessível na rede interna do governo RJ.
- **DOERJ** — Diário Oficial do Estado do RJ.
- **SEI-RJ** — processos administrativos (com resolução automática de CAPTCHA por OCR).
- **PNCP** — compras públicas nacionais.
- **Dados Abertos RJ** (portal CKAN) — datasets de despesas, contratos, servidores.

Aplica um **motor de regras** de auditoria, detecta anomalias, monta um **grafo de
relacionamentos**, gera **alertas** e exporta **relatórios** (TXT/PDF/DOCX/MD).
Pode rodar em modo **"Auditor 24 horas"**, executando ciclos completos sem parar.

Faz parte do **ecossistema "Mestre Jorge"** (ver [`README-AGENTES.md`](README-AGENTES.md)):
- **JFN** — este repo (auditoria/compliance RJ).
- **Hermes** — agente desktop/CLI pessoal.
- **Mestre Yoda** — bot do Telegram (rotina diária "Bom dia do Mestre Jorge").

---

## 2. Stack

| Camada            | Tecnologia                                              |
|-------------------|---------------------------------------------------------|
| Linguagem         | Python 3.12                                             |
| API / Web         | FastAPI + Uvicorn (`server.py`)                         |
| Banco             | SQLAlchemy + SQLite (em `data/`)                        |
| Automação web     | Playwright + Puppeteer, via Chrome remoto na porta 9222 |
| OCR (CAPTCHA SEI) | pytesseract + OpenCV + Pillow                           |
| LLM               | Groq / OpenRouter / Ollama / Anthropic, com fallback    |
| Notificações      | Telegram                                                |
| Deploy            | Docker / docker-compose (alvo: Oracle Cloud VM)         |

Dependências: [`requirements.txt`](requirements.txt) (Python) e
[`package.json`](package.json) (Puppeteer/Node).

---

## 3. Arquitetura e estrutura

```
JFN/
├── server.py                 # API FastAPI — núcleo web/REST (~1050 LOC)
├── main.py                   # entrypoint CLI do agente SIAFE (interativo / --query)
├── checar.py / diagnostico.py# diagnóstico de Chrome 9222, DOERJ, SIAFE2
├── analisar.py               # relatório do banco de dados
│
├── compliance_agent/         # MÓDULO CENTRAL — auditoria de compliance
│   ├── collectors/           # siafe_ob, doerj, sei_portal, sei_cdp, pncp, caged, web_research
│   ├── rules/                # engine + detectores (preco.py, obra.py, generate_alerts.py)
│   ├── analysis/             # anomaly_detector.py, graph_analyzer.py
│   ├── llm/                  # router, orquestrador, memoria, free_llm (multi-provider c/ fallback)
│   ├── reports/              # text_report, pdf, charts
│   ├── database/             # models, cache, fts (full-text search)
│   ├── notifications/        # telegram
│   ├── captcha_solver.py     # OCR do CAPTCHA do SEI
│   └── scheduler.py          # ciclo de coleta agendado
│
├── siafe_agent/              # agente dedicado ao SIAFE (browser + tools + groq_explorer)
├── hermes-yoda/              # scripts de orquestração do bot Telegram (Windows: .cmd/.ps1/.vbs)
│
├── _PROTEGIDO/               # "cópia-ouro" — NUNCA editar/apagar/sobrescrever
├── _SANDBOX/                 # área livre de experimentos
│
├── tests/                    # smoke + testes offline
├── docs/                     # análises de falhas / fallback
├── data/                     # SQLite, cache, diagnósticos (gitignored)
├── reports/                  # relatórios gerados
│
├── Dockerfile, docker-compose.yml
├── iniciar.sh / iniciar.bat  # launchers (Linux / Windows)
└── *.bat, *.ps1, *.cmd       # utilitários Windows
```

### Endpoints REST principais (`server.py`)

| Método | Rota | Função |
|---|---|---|
| GET | `/`, `/chat`, `/hermes` | Painéis / chat |
| GET | `/api/hermes/estado` | Estado do agente (usado pelo healthcheck) |
| POST/GET | `/api/hermes/missoes` | Criar / listar missões paralelas |
| POST | `/api/hermes/trabalhar` | Disparar execução da missão |
| GET | `/api/hermes/stream` | Stream de progresso |
| POST | `/api/hermes/auditor24h/iniciar\|parar` | Liga/desliga auditoria 24h |
| GET | `/api/hermes/auditor24h/status` | Status da auditoria 24h |
| POST | `/api/hermes/relatorio` | Gerar relatório |
| GET | `/api/compliance/painel` | Snapshot do painel |
| GET | `/api/compliance/investigar` | Investigar pessoa/empresa |
| GET | `/api/compliance/relatorio_30d` | Relatório dos últimos 30 dias |
| GET | `/api/compliance/graph`, `/graph` | Grafo de relacionamentos |
| GET | `/api/compliance/alerts`, `/stats`, `/buscar` | Alertas, estatísticas, busca textual |

---

## 4. Variáveis de ambiente

Copie [`.env.example`](.env.example) para `.env` e preencha. **Nunca** commite o `.env`
(já está no `.gitignore`).

### Obrigatórias (pelo menos um provider de LLM)
| Variável | Descrição |
|---|---|
| `GROQ_API_KEY` | Chave Groq (grátis em console.groq.com). |
| `OPENROUTER_API_KEY` | Alternativa grátis (openrouter.ai). |
| `FREE_LLM_PREFER` | Qual usar primeiro: `groq` \| `openrouter` \| `ollama`. |

### LLM — opcionais / modelos
| Variável | Padrão | Descrição |
|---|---|---|
| `OPENROUTER_SMART_MODEL` | `nousresearch/hermes-3-llama-3.1-405b:free` | Modelo "inteligente". |
| `OPENROUTER_FAST_MODEL` | `google/gemma-2-9b-it:free` | Modelo "rápido". |
| `OLLAMA_MODEL` | `llama3.2:3b` | Modelo local Ollama. |
| `ANTHROPIC_API_KEY` | — | Claude API (opcional, pago). |
| `HERMES_MAX_TOKENS` | `8000` | Teto de tokens do raciocínio do Hermes. |
| `MONTHLY_TOKEN_LIMIT` | `500000` | Limite mensal de tokens. |

### SIAFE2 (só funciona na rede interna do governo RJ)
| Variável | Descrição |
|---|---|
| `SIAFE_USER` | CPF sem pontos. |
| `SIAFE_PASS` | Senha do SIAFE. |
| `SIAFE_CLIENTE` | Campo "Cliente" (organização), opcional. |
| `SIAFE_EXERCICIO` | Ano fiscal (ex.: 2025), opcional. |

### Telegram (opcional — alertas no celular)
| Variável | Descrição |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot. |
| `TELEGRAM_CHAT_ID` | Chat de destino. |

### Outras
| Variável | Padrão | Descrição |
|---|---|---|
| `SEI_CAPTCHA_TENTATIVAS` | `4` | Tentativas de OCR no CAPTCHA do SEI. |
| `AUDITOR_24H_INTERVALO` | `1800` | Segundos entre ciclos do auditor 24h. |
| `TRANSPARENCIA_API_KEY` | — | Chave do Portal da Transparência (opcional). |

---

## 5. Como rodar

### Pré-requisitos
```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # e preencha as chaves
```

### Diagnóstico rápido
```bash
python checar.py        # verifica Chrome debug 9222, DOERJ e SIAFE2
```

### Servidor web (API + painel)
```bash
python server.py --host 0.0.0.0 --port 8000
# painel em http://localhost:8000/  e  /hermes
```

### Agente SIAFE (CLI)
```bash
python main.py                          # interativo (credenciais do .env)
python main.py --visible                # browser visível
python main.py --query "..."            # consulta única, não-interativo
```

### Launcher tudo-em-um (Linux)
```bash
./iniciar.sh            # scheduler diário (08:00)
./iniciar.sh --agora    # roda um ciclo de coleta agora e sai
./iniciar.sh --groq     # explora SIAFE2 com IA (Groq)
./iniciar.sh --analisar # mostra relatório do banco
```

### Chrome com porta de debug (necessário p/ coleta SIAFE2/SEI)
```bash
google-chrome --remote-debugging-port=9222 &
```

### Docker
```bash
docker compose up -d --build       # sobe jfn-agent na porta 8000
# healthcheck: GET /api/hermes/estado
```
Deploy em Oracle Cloud: ver [`DEPLOY_ORACLE.md`](DEPLOY_ORACLE.md) e
[`setup_oracle_cloud.sh`](setup_oracle_cloud.sh).

---

## 6. Regras de governança (OBRIGATÓRIAS)

Fonte de verdade: [`CONSTITUICAO.md`](CONSTITUICAO.md). Resumo:

- **`_PROTEGIDO/`** → trabalho validado (cópia-ouro). **NUNCA** editar, apagar, mover ou sobrescrever.
- **`_SANDBOX/`** → criar e testar à vontade. É onde coisas novas nascem antes de serem promovidas.
- **Regra de ouro:** adicionar e testar = SIM. Apagar/sobrescrever trabalho validado = NÃO.
  Se algo validado precisa mudar, faça uma **cópia** no `_SANDBOX/`, teste, e só então
  o Mestre Jorge valida e promove.
- **Git:** sempre commitar antes de mudanças grandes. **NUNCA** `git reset --hard`,
  `git clean -fdx` ou `git push --force` em branch protegida.
- **Segredos:** `.env`, `.pem`, tokens — **NUNCA** commitar nem expor em chat/log.
- **Ética:** não burlar TLS/SSL, não se passar por terceiros.

---

## 7. Trabalhando em múltiplos dispositivos (Desktop / Celular / VM)

Este `CLAUDE.md` é o ponto único de contexto. Qualquer agente Claude deve:

1. Ler este arquivo + `CONSTITUICAO.md` antes de agir.
2. **Commitar e dar push** após alterações de código (regra do ecossistema), respeitando
   a branch de trabalho configurada.
3. Manter este `CLAUDE.md` atualizado quando a arquitetura, env vars ou forma de rodar mudarem.

> ⚠️ **Segurança:** se o `git remote` contiver um token embutido na URL
> (`https://github_pat_...@github.com/...`), isso é um vazamento de credencial.
> Revogue o PAT no GitHub e reconfigure o remote (SSH ou credential helper).
