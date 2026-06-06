# COMANDOS — Ecossistema Mestre Jorge (Yoda · JFN · Massare · Hermes)

> Fonte canônica dos comandos que o Mestre Jorge usa no Telegram. O Yoda lê isto (espelhado na memória
> dele) para responder `/lista`. **Descrição de até 5 palavras por comando.** Atualize aqui ao criar/alterar
> um comando — e atualize também a memória do Yoda (`~/.hermes/memories/USER.md`).

## 📊 Relatórios — JFN
- `/relatorio <empresa ou CNPJ>` — Inteligência completa do fornecedor
- `/orgao <órgão ou UG>` — Inteligência completa do órgão

## 📈 Mercado — Massare
- `/mercado` — Cenários e sentimento do mercado
- `/prever <ativo>` — Previsão direcional de ativo

## 🛰️ SIAFE — coleta e coordenação de sessão
- `/siafe <ano>` — Coletar OBs do SIAFE (ano)
- `/siafestats` — Quantas OBs do SIAFE coletadas
- `/siafelivre` — Liberar SIAFE para o JFN
- `/siafeocupado` — JFN espera você sair

> `/siafe <ano>`: anos liberados 2024–2026 (2023 bloqueado pela conta — o coletor pula). Roda em background
> (Playwright + login; coordena sessão única via Telegram). Comando: `cd ~/JFN && .venv/bin/python -m
> compliance_agent.siafe_ob_orcamentaria --exercicio <ano> --max 1000 --ingerir --resiliente`.
> `/siafestats`: `curl -s http://127.0.0.1:8000/api/siafe/stats`.

## 🤖 Geral — Yoda / Hermes
- `/goal <objetivo>` — Definir meta principal
- `/lista` — Mostrar todos os comandos

---

### Como cada comando aciona o barramento (para o Yoda)
| Comando | Ação (via `terminal`/curl no barramento `127.0.0.1:8000`) |
|---|---|
| `/relatorio X` | `POST /api/relatorio/inteligencia {"empresa":"X"}` → envia PDF + XLSX + resumo |
| `/orgao X` | `POST /api/relatorio/orgao {"orgao":"X"}` → envia PDF + XLSX + resumo |
| `/mercado` | `GET /api/massare/cenarios` → resume no chat |
| `/prever X` | `POST /api/massare/prever {"symbol":"X"}` → resume no chat |
| `/siafelivre` | `python -m compliance_agent.siafe_coord livre` |
| `/siafeocupado` | `python -m compliance_agent.siafe_coord ocupado` |
| `/goal X` | meta principal (todo/delegate_task) |
| `/lista` | imprime esta lista |

> Regra de apresentação: ao **iniciar uma conversa** (1ª resposta) e ao final do `/lista`, o Yoda inclui a
> linha: **"Mais comandos em: /lista"**.
