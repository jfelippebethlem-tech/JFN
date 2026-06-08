# OTIMIZAÇÃO DO ECOSSISTEMA — índice único (tokens · CPU · storage · memória)

> **Ponto de entrada único** para otimização do ecossistema (JFN + Yoda/Hermes + Massare). Este doc **não move
> nem duplica** os documentos existentes — ele os **indexa, analisa e registra decisões**. Os docs de origem
> continuam sendo a fonte de verdade de cada tema. Última campanha: **2026-06-07**.
>
> Regra-mãe (de `CLAUDE.md §5`): **racionalizar é cortar DESPERDÍCIO, jamais profundidade/qualidade.** A economia
> existe para **liberar orçamento para mais trabalho bom** — nunca para entregar versão rasa.

## 1. Mapa dos documentos que regem otimização (NÃO mover — são referenciados)
| Tema | Documento | O que cobre |
|---|---|---|
| **Tokens da IA / cota** | [`../CLAUDE.md`](../CLAUDE.md) §5 + [memory `racionalizacao-token-sessao`] | Cortar só desperdício (re-leitura, polling); offload p/ subprocesso; nunca despachar pela metade. |
| **Storage / disco** | [`STORAGE.md`](STORAGE.md) | 48GB VM; o que já foi liberado (Docker −23,5GB, torch CPU −3,3GB); o que NÃO tocar; poda automática de relatórios. |
| **Roadmap de arquitetura** | [`ECOSSISTEMA-EVOLUCAO.md`](ECOSSISTEMA-EVOLUCAO.md) | Plano P0/P1/P2 (PyOD, DuckDB, Splink, semantic-router, Mem0…), 3 lentes, ondas. |
| **Comandos / operação** | [`PLAYBOOK-EXECUTOR.md`](PLAYBOOK-EXECUTOR.md) | TL;DR de comandos; §0 codegraph/graphify antes de grep; rotas do barramento. |
| **Manutenção de DB/caches** | `compliance_agent/manutencao.py` | checkpoint WAL + VACUUM + **ANALYZE** + gzip caches + poda relatórios. Cron domingo 03:00. |

## 2. Otimizações JÁ no roadmap/playbook (análise — feito vs. pendente)
Extraído de `ECOSSISTEMA-EVOLUCAO.md` e `PLAYBOOK-EXECUTOR.md`, recortado pelo ângulo de **economia de
tokens/CPU/latência**:

| Item (origem) | Ganho de otimização | Status |
|---|---|---|
| **DuckDB como camada OLAP** sobre o SQLite (roadmap P0) | queries de relatório **20–50× mais rápidas** (CPU/latência) lendo o próprio `compliance.db` | Parcial — `duckdb_util.conectar()` existe e é usado (calibrar/eval); migração ampla dos relatórios pendente |
| **vLLM Semantic Router** pré-LLM (roadmap Yoda P1) | classifica o pedido por regra **antes** de gastar token de LLM; semantic tool filtering | Pendente (adiado até logs provarem necessidade — decisão das 3 lentes) |
| **Mem0 (memória mínima, 3–4 fatos)** (roadmap Yoda) | contexto enxuto = menos tokens por turno | Pendente; hoje memória via `~/.hermes/state.db` |
| **codegraph + graphify antes de grep** (playbook §0) | **menos tokens de exploração** (1 chamada traz o código relevante vs. dezenas de grep/read) | ✅ Ativo (índice pronto; pre-commit hook — ver memory `codegraph-graphify-precommit`) |
| **Roteamento por regra antes do LLM no Yoda** (roadmap) | evita chamada de LLM em comandos determinísticos | Parcial (comandos `/...` são determinísticos) |
| **Poda automática de relatórios** `JFN_REPORTS_RETENCAO_DIAS=7` (STORAGE.md) | storage não incha com PDFs/XLSX regeneráveis | ✅ Ativo (`_prune_reports`) |
| **OCR/torch lazy** (STORAGE.md §torch) | não pagar RAM de ML fora do caminho que usa | ✅ Reforçado nesta campanha (ver §4.3) |

> **Conclusão:** o roadmap já prioriza as otimizações certas (DuckDB e roteamento pré-LLM são os maiores ganhos
> futuros de CPU/token). Esta campanha foca os ganhos **seguros e imediatos** que não estavam feitos.

## 3. Achados VERIFICADOS ao vivo (2026-06-07) — corrigem suposições
1. `manutencao --tudo` **já está no cron** (`0 3 * * 0`) → não mexer no cron; só enriquecer a função.
2. `ordens_bancarias` (1,12M linhas) **já é fortemente indexada** → **não** adicionar índices duplicados.
3. `ob_anomaly.ob_id` **já é `INTEGER PRIMARY KEY`** (= rowid, indexado nativamente) → o índice extra cogitado
   seria **redundante** (EQP confirmou que a query de ranking já usa `ix_anomaly_score`). **Não criado.**
4. **Não existia `ANALYZE`** no DB → adicionado ao `manutencao` (maior win de DB, risco zero).
5. `easyocr` instanciava o `Reader` **no top-level** de `sei_driver.py` (puxa torch ~750MB) → tornado lazy.
6. **Não removível:** `~/.agent-browser` (browsers re-baixáveis, mas o pacote npm `agent-browser` é dep ativa do
   Hermes); `~/.cache/ms-playwright` (scrapers usam). `~/.npm/_npx` (73MB) não encolhe com `npm cache clean`.

## 4. Campanha 2026-06-07 — Fases

### FASE 1 — ganhos seguros (FEITO)
| # | Otimização | Arquivo | Ganho | Status |
|---|---|---|---|---|
| 1.1 | `ANALYZE` no manutencao (após VACUUM) | `compliance_agent/manutencao.py` | planner escolhe índices melhores num DB de 1M+ | ✅ |
| 1.2 | ~~Índice `ix_anomaly_ob`~~ | — | **cancelado**: ob_id já é PK (redundante) | ✅ (não feito, justificado) |
| 1.3 | Lazy-load easyocr/torch | `compliance_agent/sei_driver.py` | torch (~750MB) só carrega no 1º CAPTCHA real; import instantâneo | ✅ |
| 1.4 | Remover dead-code | `collectors/sei_sei_direct.py` (0 callers via codegraph) | −81 LOC, menos torch top-level | ✅ |
| 1.5 | Este doc-índice | `docs/OTIMIZACAO.md` + ponteiro em `CLAUDE.md §5` | navegação única de otimização | ✅ |
| 1.6 | `ruff` report-only | toolchain | **156 achados** (118 imports não usados, 29 vars, 9 redefinições) — triar manualmente | ✅ (report) |
| 1.7 | Limpezas seguras | `manutencao` | **ANALYZE rodado** (sqlite_stat1=48); VACUUM/checkpoint deferidos ao cron de domingo (sweep S2 escrevendo agora — evitar lock); `npm cache` sem ganho real | ✅ (parcial por segurança) |

### FASE 2 — N+1 e sleep→wait (com validação por snapshot)
| # | Otimização | Arquivo | Verificação | Status |
|---|---|---|---|---|
| 2.1 | N+1 → `executemany` (1 SQL unificado, ordem preservada) | `compliance_agent/correlacao_sei.py` | 3 contadores idênticos; **311,9s → 49,4s (6,3×)** | ✅ |
| 2.3 | `time.sleep(3)` → `wait_for_selector` | coletores browser | — | ⏸️ **diferido p/ Fase 3** (ver nota) |

> **F2.3 — por que diferido (decisão honesta):** dos 9 `sleep(3)` no core, **nenhum é alvo seguro e aplicável agora**:
> `groq_agent.py:289`/`groq_explorer.py:170` são **backoff de LLM** (não espera de elemento); `auditar_fornecedor.py:166`
> é **pacing humano deliberado** entre anos; os de browser (`sei_driver.py`, `siafe_session.py`, `siafe_ob.py`)
> estão nos **caminhos de scraper recém-estabilizados** — trocar por `wait_for_selector` exige validação ao vivo
> contra os sites gov e arrisca o que acabou de ser estabilizado, para um ganho **só de latência** (não de
> token/CPU/storage/memória). Entra na Fase 3, atrás dos testes-caracterização.

### FASE 3 — EM EXECUÇÃO (2026-06-08; cada passo com rede de segurança + verificação)
- **3.0** ✅ Rede de segurança: `tests/test_imports_smoke.py` (importa **103 módulos** core, ~5,5s) + removido lixo
  `tests/__tmp_verify.py`. (Golden tests de browser-login são inviáveis de forma determinística — o smoke de
  import + os snapshots por função fazem o papel de rede.)
- **3.2a** ✅ `diagnose_siafe.py` (2944 LOC, script de debug, 0 imports) → **`tools/debug/diagnose_siafe.py`**
  (rodar com `PYTHONPATH=. .venv/bin/python tools/debug/diagnose_siafe.py`). Raiz do repo mais limpa.
- **3.2b** Split de `telegram.py` — ⏸️ **avaliado → não fazer agora.** O arquivo é majoritariamente **handlers
  de comando assíncronos com estado** (DB/API), não formatters puros (só 3 helpers triviais: `_base_url`,
  `_ip_local`, `_painel_reply`). Não há cluster limpo para extrair; reorganizar handlers do bot que a família
  usa = risco alto sem ganho. Adiado.
- **3.1** Dedup de login — ⏸️ **avaliado → diferido.** Os 5 logins são **genuinamente diferentes** (SEI vs SIAFE;
  Selenium vs Playwright; `page` vs método de classe vs `exercicio`): `sei_cdp.login_sei_interno`,
  `siafe_browser.login`, `sei_browser.login`, `siafe_ob._fazer_login`, `siafe_ob_orcamentaria._login` (este
  recém-estabilizado). Não compartilham lógica real → dedup é alto-risco/baixo-valor e mexeria no login SIAFE
  estável. `compliance_agent/siafe_login.py` é um **utilitário CLI de login manual** (0 imports mas executável,
  citado em docs) — **não** é dead-code, manter.
- **server.py / hermes_goal.py split** — ⏸️ adiado: mesma classe de risco (servidor FastAPI vivo / orquestrador),
  só com cobertura comportamental real (gate honesto). A rede de smoke (3.0) cobre import, não comportamento.

> **Conclusão honesta da Fase 3:** as wins seguras foram entregues (rede de smoke + relocação do diagnose, além
> da Fase 1/2). Os refactors grandes restantes, investigados a fundo, são **alto-risco/baixo-valor no sistema
> vivo recém-estabilizado** — a decisão correta (alinhada a "não quebrar") é **não forçá-los** sem cobertura
> comportamental. Ficam especificados acima para execução futura deliberada.

## 5. Decisões de ferramentas externas
- **`ruff` — SIM** (1 binário; linter + dead-imports). Uso **report-only**; **sem `--fix` em massa** (imports com
  side-effects em coletores/registro). Os 156 achados são backlog de limpeza manual.
- **`vulture`/`deptry`/`pip-autoremove` — NÃO agora**: redundantes com codegraph/ruff e arriscados (imports
  dinâmicos do Playwright/easyocr). Reavaliar só com necessidade medida.
- **`orjson` — NÃO**: micro-otimização sem gargalo medido = bloat.
- **DuckDB / semantic-router / Mem0** — ficam no roadmap (`ECOSSISTEMA-EVOLUCAO.md`), são os próximos grandes
  ganhos de CPU/token mas exigem trabalho dedicado.

## 6. Como usar codegraph/graphify para racionalizar (sempre)
- `projectPath="/home/jfelippebethlem/JFN"` nas chamadas codegraph.
- Antes de remover símbolo: `codegraph_impact` + `codegraph_callers` (só remover se impacto = interno ao arquivo).
- Exploração: `codegraph_explore "..."` (1 chamada ≈ Read do código relevante) **antes** de grep/read em massa — é
  o jeito de gastar **menos tokens** investigando. `graphify query "..."` p/ visão de grafo/dependências.

## 7. Resultados medidos
- **Lazy-load:** `python -X importtime -c "import compliance_agent.sei_driver" | grep torch` → **vazio** (torch
  não carrega mais no import). ✅
- **N+1 correlacao_sei:** **311,9s → 49,4s (6,3× mais rápido)**; os 4 contadores idênticos ao baseline
  (`pares=43165, atualizadas=22654, com_sei=33687, proc_distintos=12041`). ✅ (parte do tempo é contenção de
  lock com o sweep S2 ativo no mesmo DB; o ganho de Python-overhead do executemany é real e estável.)
- **ANALYZE:** `sqlite_stat1` populada após `manutencao --tudo`.
- **ruff:** 156 achados report-only (backlog de limpeza manual; sem `--fix` em massa).

## Sessão 2026-06-08 (fim) — storage + backlog de qualidade
- **Storage −3,1 GB:** removidos os ZIPs brutos `data/tse_cache/*.zip` (já ingeridos em `doacoes_eleitorais`=542244;
  o coletor re-baixa se precisar). Disco 19G→16G usados. `data/tse_cache/` agora no `.gitignore`.
- **Higiene:** debris `data/_*.out|json` e `__pycache__` (fora do venv) limpos; órfão `tools/mgs_relatorio_full.py` removido.
- **Pendente (não-feito p/ não arriscar com o sweep ativo):**
  - **VACUUM/ANALYZE** `compliance.db` (1,2 GB) + gzip `tfe_cache` (138 MB) — `python -m compliance_agent.manutencao --tudo`
    SÓ com o sweep idle (trava o DB). Já no cron de domingo 03:00.
  - **Rapidez do /relatorio:** paralelizar as chamadas de rede (enriquecimento+TCE-RJ+conflito+OSINT+mídia) com
    `asyncio.gather` — hoje sequenciais.
  - **Split de módulos grandes:** `server.py` (1952), `reporting/inteligencia.py` (1752), `hermes_goal.py` (1260),
    `siafe_ob_orcamentaria.py` (963), `lex.py` (916) — dívida da Onda 11.
