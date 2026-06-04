# MAPA de Segredos & Usos — ecossistema do Mestre Jorge

> Referência ÚNICA do que cada chave/arquivo é, quem usa e onde fica.
> AQUI NÃO TEM VALOR NENHUM (seguro pro git). Os valores reais ficam só no
> `.env`/`auth.json` locais e no arquivo único gerado (`hermes-tudo.sh`).

## Onde tudo mora
- **PC (fonte):** `C:\Users\socah\AppData\Local\hermes\` → `.env`, `config.yaml`, `auth.json`
- **VM GCP (server-1):** `~/.hermes/` (mesmos arquivos) — bot 24h roda aqui
- **Repo JFN:** só coisas SEM segredo (config.yaml, scripts, docs)

---

## 1) `.env` — tokens e credenciais (formato CHAVE=valor)
| Chave | Pra que serve | Quem usa |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | identidade do bot **Yoda** | gateway Hermes (Telegram) |
| `TELEGRAM_ALLOWED_USERS` | quem pode falar com o Yoda (seu ID: 45338178) | gateway |
| `TELEGRAM_HOME_CHANNEL` / `_THREAD_ID` | canal/tópico padrão | gateway |
| `GATEWAY_ALLOW_ALL_USERS` | liberar geral (normalmente off) | gateway |
| `GEMINI_API_KEY` | 1 chave Gemini (entra como a 9ª do rodízio) | modelo principal/visão |
| `OPENROUTER_API_KEY` | reserva (fallback) | rodízio de modelos |
| `MISTRAL_API_KEY` | reserva (código) | rodízio |
| `HF_TOKEN` | HuggingFace/Llama (reserva) | rodízio |
| `GITHUB_TOKEN` | clonar/commitar o repo **JFN** | git na VM e no PC |
| `SEI_USUARIO` / `SEI_SENHA` / `SEI_ORGAO` / `SEI_LOGIN_URL` | login interno **SEI** (ITERJ) | agente auditor JFN (SEI) |
| `BROWSER_*` / `BROWSERBASE_*` | navegador/automação web | ferramentas web (SEI/DOERJ/SIAFE) |
| `TERMINAL_*` | sandbox de terminal | execução de comandos |
| `*_TOOLS_DEBUG` (IMAGE/VISION/WEB/MOA) | liga logs de depuração | ferramentas |

## 2) `auth.json` — pool de credenciais (rodízio / fallback)
| Pool | Itens | Pra que |
|---|---|---|
| `gemini` | **9** (8 chaves suas `gemini-proj1..8` + a do `.env`) | rodízio: usa #1, cai pra #2,#3… quando estoura cota |
| `nous` | 1 | modelos free Nous (stepfun/ring/hy3) — fallback |
| `openrouter` / `huggingface` / `copilot` | 1 cada | reservas extras |

## 3) `config.yaml` — comportamento do agente (SEM segredo)
- `model.default = gemini-2.5-flash`, `provider = gemini`
- `fallback_providers` = 3 modelos free Nous
- `environment_hint` = quem é o Mestre Jorge + regras do time de IAs
- `toolsets`, limites, `reasoning_effort`, etc.
- ✅ Pode ir pro repo (não tem chave). Já está em `_SANDBOX/gcp/config/config.yaml`.

---

## 4) Credenciais que NÃO ficam no `.env`
| Sistema | Onde fica | Quem usa |
|---|---|---|
| **Oracle (OCI)** — user/fingerprint/tenancy + chave API | `criar_vm.py` (config) + `oci_key.pem.txt` | bot criador de VM Oracle |
| **SSH da VM Oracle** | `vm_ssh_key.pem` | acessar a VM Oracle |
| **Google Cloud (GCP)** | login `jfelippebethlem@gmail.com` (gcloud) | gerenciar a VM GCP |

---

## 5) Quem usa o quê (por agente/bot)
- **Yoda (Telegram, 24h na VM):** `.env` (TELEGRAM_*, chaves IA) + `config.yaml` + `auth.json` (rodízio).
- **Agente auditor JFN (SEI/SIAFE/DOERJ):** `SEI_*` do `.env` + `sei_auditor.py` + navegador.
- **Bot criador de VM Oracle:** credenciais OCI + `oci_key.pem.txt` + `vm_ssh_key.pem`.
- **Massare (analista financeiro):** dados públicos (BCB, sem chave) + mercado; usa o modelo do `config.yaml`.
- **/claude no Telegram:** Claude Code instalado e logado na VM (conta Claude).

---

## 6) Como levar tudo pra uma máquina nova (ex.: a VM)
Não precisa subir arquivo por arquivo. Rode o **gerador** (`gerar-bundle-vm`) no PC:
ele lê `.env` + `config.yaml` + `auth.json` e cria **UM arquivo único** `hermes-tudo.sh`.
Esse arquivo, ao rodar na máquina nova, recria os 3 arquivos em `~/.hermes/` (com backup,
nunca apaga). Você move 1 arquivo só. Os valores ficam só nele (não vai pro git).
