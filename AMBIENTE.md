# AMBIENTE — Fonte Única de Verdade do Ecossistema Mestre Jorge

> **Para qualquer IA/agente que abrir este arquivo:** isto descreve EXATAMENTE onde tudo roda e como
> os agentes se falam. Companheiro de máquina: [`ambiente.json`](ambiente.json) (mesma info, legível por
> script — use-o para não hardcodar caminhos). **Atualize os dois juntos quando a infra mudar.**
> Última curadoria: **2026-06-06**. **CUTOVER de infra: 2026-06-14** (server-1/GCP-x86 → jfn-agent-2/Oracle-ARM).

---

## 1. Onde estamos rodando (NÃO é Windows)

| Item | Valor |
|---|---|
| Nuvem | **Oracle Cloud Infrastructure (OCI)** — Ampere ARM |
| Instância | `jfn-agent-2` (hostname `jfn-core`), Tailscale `100.123.89.59` |
| SO | **Ubuntu 22.04.5 LTS** (Linux **aarch64 / ARM64**) |
| Usuário | `ubuntu` |
| Home | `/home/ubuntu` |

> 🔄 **Cutover 2026-06-14:** esta VM substituiu a antiga `server-1` (GCP, x86_64, `southamerica-east1-b`,
> Tailscale `100.72.107.116`), que foi **desligada** (serviços/timers/cron parados). Como o destino é **ARM**,
> os ambientes Python/Node e binários foram **reconstruídos** (não copiados do x86). O `chrome-jfn` usa
> **`/snap/bin/chromium`** (não há Google Chrome para ARM/Linux). Object storage = **Backblaze B2**
> (`b2:jfn-backup-jorge`) + **Cloudflare R2** (`r2:jorgefelippe`) via `rclone`. O `gcloud` precisa de
> **`gcloud auth login`** nesta VM (a auth antiga era do metadata-GCE, não portável); projeto default `jfn-vps`.

⚠️ **Caminhos `C:\...` em docs antigos (ex.: `C:\JFN\jfn`) são do desktop Windows legado e NÃO existem aqui.**
Na VM, o JFN fica em **`/home/ubuntu/JFN`** (ou `~/JFN`). Sempre use `Path` relativo / variável de
ambiente no código — nunca caminho fixo de SO.

---

## 2. Os agentes e quem é quem

```
┌──────────────────────────────────────────────────────────────────────┐
│  MESTRE JORGE  (Telegram, celular)                                     │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │  manda pedido em PT-BR / comandos /relatorio etc.
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  YODA  = bot assistente / MAESTRO                                      │
│  (instância Hermes  →  hermes-gateway.service)                         │
│  Decide QUAL agente aciona e chama a API do JFN (barramento único).    │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │  HTTP  →  http://127.0.0.1:8000
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│  JFN  = motor + BARRAMENTO DE AGENTES   (jfn.service, FastAPI :8000)   │
│   ├─ Auditoria/Compliance RJ  (OBs, contratos, red flags)             │
│   ├─ /api/relatorio/inteligencia   → relatório due-diligence          │
│   ├─ /api/hermes/missao            → auditoria autônoma (texto livre)  │
└──────────────────────────────────────────────────────────────────────┘
```

- **Hermes** — a *plataforma* (CLI/gateway) em `~/hermes-agent`, estado em `~/.hermes`. O Yoda É uma
  instância do Hermes. Não é um "agente de tarefa" separado.
- **Yoda** — o bot do Telegram (`hermes-gateway.service`, chat `45338178`). É o **maestro**: roteia o
  pedido do Jorge para o agente certo e responde no Telegram.
- **JFN** — o motor de auditoria/compliance do RJ **e** o barramento HTTP por onde o Yoda aciona tudo.
  Servidor FastAPI em `127.0.0.1:8000` (`jfn.service`). Código em `~/JFN`, venv `~/JFN/.venv`.
- **Massare** — agente de mercado: **SAIU DA VM em 2026-07-07** (pedido do dono). Vive só no GitHub
  (`jfelippebethlem-tech/Massare`, sessões cloud). Não há rota `/api/massare/*` nem timers dele aqui.

---

## 3. Workflow de boot (o que sobe e em que ordem)

Mecanismo: **systemd `--user`** com `linger=yes` → sobe no boot da VM mesmo sem login.

1. `hermes-gateway.service` → **Yoda** online no Telegram.
2. `jfn.service` → **API JFN** em `:8000` (auditoria + painel + barramento).
3. `chrome-jfn.service` → **ponte Chrome headless CDP** em `:9222` (coleta TFE/SIAFE ao vivo).
4. Timers por agenda:

| Timer | Quando (UTC) | O quê |
|---|---|---|
| `jfn-tfe.timer` | 08:00 diário | Coleta TFE Despesa (espelho D-1 do SIAFE, dados abertos RJ) |
| `jfn-tfe-ob.timer` | Seg 09:00 | Base completa de OBs 2023–2026 (download + ingestão) |
| `jfn-ronda.timer` | a cada 10 min | Ronda: saúde do serviço + alertas |

> ⛔ **`yoda.service` (nível de SISTEMA) foi DESABILITADO em 2026-06-06.** Era um duplicado que brigava
> com o `hermes-gateway.service` pelo mesmo bot do Telegram (causava loop de FAILURE/restart). **Não reativar.**
> O gateway canônico do Yoda é o `hermes-gateway.service` (user).

---

## 4. Como o Yoda aciona cada agente (barramento = API do JFN em :8000)

O Yoda chama via `terminal`/`execute_code` (ferramenta `curl`). **Não existe ferramenta `web_search`** no
Yoda — não inventar. Rotas oficiais:

```bash
# Relatório de inteligência de um FORNECEDOR (por nome — parcial serve — OU CNPJ):
curl -s -X POST http://127.0.0.1:8000/api/relatorio/inteligencia \
     -H 'Content-Type: application/json' \
     -d '{"empresa":"MGS Clean"}'
# → {ok, cnpj, empresa, risco, score, resumo, path_md, path_pdf, path_xlsx, fonte}
#   Se ambíguo: {ok:false, ambiguo:true, pergunta, candidatos} — pergunte ao Mestre Jorge.
#   Envie SEMPRE path_pdf E path_xlsx (planilha Excel interativa) no Telegram.

# Relatório de inteligência de um ÓRGÃO (por nome do órgão OU código de UG):
curl -s -X POST http://127.0.0.1:8000/api/relatorio/orgao \
     -H 'Content-Type: application/json' \
     -d '{"orgao":"iterj"}'   # ou {"ug":"133100"}
# → {ok, ug, orgao, resumo, path_md, path_pdf, path_xlsx, fonte}  (quem o órgão pagou, por ano)

# Auditoria autônoma aberta (pedido complexo em texto livre):
curl -s -X POST http://127.0.0.1:8000/api/hermes/missao \
     -H 'Content-Type: application/json' -d '{"missao":"investigar contratos do fornecedor X"}'

```

Roteamento (intenção → agente):
- "relatório / auditoria / fornecedor / CNPJ / SIAFE / OB / due diligence" → **JFN** (`/api/relatorio/inteligencia`).
- Pedido de auditoria aberto/complexo → **`/api/hermes/missao`**.
- Conversa geral / código / texto → o **próprio Yoda** (Hermes).

---

## 5. Comandos de operação rápidos (para humanos e IAs)

```bash
# Saúde dos serviços
systemctl --user status hermes-gateway jfn chrome-jfn --no-pager
curl -s http://127.0.0.1:8000/status           # JFN vivo?
curl -s http://127.0.0.1:9222/json/version     # ponte Chrome viva?

# Logs
journalctl --user -u jfn -n 50 --no-pager
journalctl --user -u hermes-gateway -n 50 --no-pager

# Rodar coisas do JFN à mão (sempre com o venv do JFN)
cd ~/JFN && .venv/bin/python -m compliance_agent.auditoria.auditar_fornecedor 19.088.605/0001-04 2025 2026
```

**Regra de ouro do JFN:** Empenho ≠ Pagamento. A Ordem Bancária (OB) é o dado definitivo de pagamento.
Todo número é marcado **REAL** vs **ESTIMADO/CACHE**; nunca fabricar valor. (Ver `CLAUDE.md`.)

## 6. Env vars de leitura/análise (catálogo único — antes espalhadas em 4 arquivos)

| Var | Default | Efeito | Onde |
|---|---|---|---|
| `JFN_LEX_LER_SEI` | `1` | `0` desliga a leitura da íntegra SEI no parecer Lex | `compliance_agent/lex.py` |
| `JFN_LEX_MAX_SEI` | `3` | nº máx de processos SEI lidos por parecer (priorizados: seleção > valor > OBs) | `lex.py` |
| `JFN_LEX_SEI_BUDGET` | `120` | orçamento (s) da leitura SEI do Lex | `lex.py` |
| `JFN_LEX_DISCURSIVO` | `1` | `0` desliga a análise discursiva LLM do parecer | `lex.py` |
| `LEX_TETO_DISPENSA` | `59906.02` | teto de dispensa usado no R2 do Lex (preferir `limites_dispensa.py`) | `lex_analise_conteudo.py` |
| `SEI_MAX_DOCS` | `40` | bound de documentos lidos/OCR por processo no reader | `tools/sei_reader.py` |
| `SEI_CACHE_TTL` | `86400` | TTL (s) do cache de leitura `data/sei_cache/` | `tools/sei_reader.py` |
| `SEI_MAX_PAG` | `40` | bound de páginas na íntegra completa | `tools/sei_integra_completa.py` |
| `SEI_DOC_TIMEOUT` | `15` | timeout (s) por documento na íntegra | `sei_integra_completa.py` |
| `SEI_INTEGRA_OCR` | `0` | `1` embute PDF escaneado + página OCR na íntegra (pesado — VM 2 vCPU) | `sei_integra_completa.py` |
| `SEI_SEM_TG` | — | `1` só arquiva a íntegra (não envia Telegram) | `sei_integra_completa.py` |
| `SEI_PROXY_URL` / `PROXY_URL` | — | proxy p/ furar WAF do SEI | `tools/sei_cdp.py` |
| `SEI_DEBUG_SHOT` | — | screenshots de debug do login/leitura | `tools/sei_reader.py` |
| `SEI_USER`/`SEI_PASS`/`SEI_ORGAO` | itkava/—/iterj | credenciais SEI (só via .env) | `sei_reader.py` |
