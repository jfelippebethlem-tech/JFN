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

## 🛰️ SIAFE — coordenação de sessão
- `/siafelivre` — Liberar SIAFE para o JFN
- `/siafeocupado` — JFN espera você sair

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
