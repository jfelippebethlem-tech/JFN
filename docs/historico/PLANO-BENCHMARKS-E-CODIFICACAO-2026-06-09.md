# Plano de Benchmarks do Ecossistema + Melhoria de Codificação — 2026-06-09

> Pedido do dono: *"pesquise e planeje nossos benchmarks em tudo; como podemos melhorar nossa codificação."*
> Este é o **plano** (não execução). Princípios herdados: mudança pequena/isolada/**verificada com o artefato
> real**; nunca LLM no hot-path; grátis/respeita a VM; documentar tudo p/ a próxima IA. Ver
> [[licao-v2-revertida-2026-06-08]] e `docs/LOOP-MELHORIA-2026-06-09.md`.

## 0. Tese central
O "loop de melhoria" hoje mede qualidade **a olho** (lê o relatório/parecer e julga). Isso é frágil: não diz,
em número, se o Loop N melhorou ou **regrediu** vs N-1 (foi exatamente o que custou a reversão da V2 — saiu
"pior" e só percebemos gerando o artefato tarde). **Benchmark = transformar o julgamento em instrumento.**
Mesmo padrão dos 2 fixes profundos pendentes (Lex/Massare): *a estrutura existe, falta fechar o ciclo com
medição.* O objetivo é um **scorecard único** (`make bench`) que, a cada checkpoint, emite números comparáveis.

## 1. Diagnóstico medido (2026-06-09, branch `feat/lista-limpa`)
| Métrica | Valor hoje | Observação |
|---|---|---|
| LOC Python (sem .venv/_SANDBOX) | 57.101 | 254 arquivos |
| Arquivos de teste | 31 | ~322 testes verdes; 5-6 hangs de rede |
| Config de qualidade | **nenhuma** | sem pyproject.toml/ruff.toml/mypy/coverage |
| Erros ruff (defaults) | **733** | 206 auto-fixáveis seguros; 123 F401 (import morto), 362 E702 |
| `mypy` / `coverage` | **não instalados** | — |
| God-files | server.py 1959 · inteligencia.py 1789 · lex.py 1041 · diagnose_siafe.py 2944 | risco de regressão |
| Benchmark de output (relatório/parecer/previsão) | **inexistente** | só há benchmark de roteamento de IA |
| Massare OOS hit_rate | **null** (44 pendentes) | previsão sem accountability |

## 2. Os 4 eixos de benchmark (o "em tudo")

### Eixo A — Engenharia / código (objetivo, automatizável, roda na VM, grátis)
Mede a saúde do código e **trava regressão** sem depender de julgamento.
| Métrica | Ferramenta | Baseline hoje | Meta inicial | Como |
|---|---|---|---|---|
| Lint errors | `ruff check` | 733 | **ratchet**: auto-fix 206 seguros → baseline o resto → CI falha em erro NOVO | `pyproject.toml [tool.ruff]` |
| Imports mortos | ruff F401 | 123 | 0 | auto-fix |
| Cobertura de testes | `coverage` (instalar) | desconhecida | medir e proteger core (inteligencia/lex/ugs/correlacao_sei) | `coverage run -m pytest` |
| Pass rate / flaky | pytest markers | 322✓ + 5-6 hangs misturados | **isolar** rede com `@pytest.mark.network` → suíte unitária 100% verde e rápida | `pyproject.toml [tool.pytest]` markers |
| Tipos (gradual) | `mypy` (instalar) | 0% | tipar só o core que gera artefato (não tudo) | `mypy compliance_agent/reporting compliance_agent/lex.py` |
| Tamanho/complexidade | `ruff` (C901) + wc -l | server.py 1959, inteligencia.py 1789 | **não crescer**; split incremental só quando isolado | tracking, sem big-bang |
| Smoke de imports | já existe (`test_imports_smoke`) | 141-151 | manter verde | já no CI mental |

### Eixo B — Produto / qualidade do output (golden-set + rubrica)
O coração do "sistema pensante". Para cada um dos 3 produtos: **congelar um golden** (entrada fixa) e pontuar
por **rubrica determinística onde possível + juiz-LLM onde é prosa** (mesmo harness do `benchmark_runner.py`).

**B1 — Relatório JFN (fornecedor + órgão).** Golden: 3 CNPJs fixos (MGS Clean, ITERJ-órgão, +1 grande).
Rubrica 0-3 por critério, automatizável em parte:
- *Factual* (determinístico): total OB confere com `SELECT SUM` do DB? cobertura citada = COUNT real? UG resolvida pelo código (não texto da OB)?
- *Honestidade* (regex + juiz): nunca afirma crime; usa linguagem condicional; "indício, não acusação".
- *Estética* (checklist): capa, seções numeradas, 🔴🟡🟢 com score, números com milhar+2 casas, fontes citadas.
- *Enxutez* (determinístico): tamanho do PDF, top-12 OB/exercício respeitado, sem ruído.
- *Latência* (determinístico): tempo de geração (hoje 60-90s — alvo trackear, não regredir).

**B2 — Parecer Lex.** Golden: 2 fornecedores com processo SEI. Rubrica:
- Cita **onde** (§/cláusula) e **por quê** (mecanismo) — só real após o **fix do coletor SEI** (Fix profundo #1).
- Fundamento legal específico (artigo+lei). Encaminhamento por severidade (grav≥3→requerimento). grau_lex coerente.
- Guard honesto: se SEI não-lido, **declara** (não inventa). ← já implementado, virar asserção de teste.

**B3 — Massare (previsão).** Métrica clássica de forecasting:
- **Hit rate OOS** (resolver as 44 pendentes contra o realizado — Fix profundo #2).
- **Brier score** / calibração (a confiança declarada bate com a frequência de acerto?).
- Sem track record, previsão = opinião. Este eixo **depende** do scorer OOS.

### Eixo C — Roteamento de IAs (JÁ EXISTE — formalizar e automatizar)
`docs/IAS-ECOSSISTEMA-BENCHMARK.md` + `tools/benchmark_runner.py` + `data/benchmark_ias.csv`. Hoje roda à mão.
Melhoria: agendar (cron semanal), versionar o gold, e plotar o **gap IA-fraca × Claude** por tarefa → decide
roteamento (gap por ambiguidade = melhorar instrução; gap por capacidade = rotear pro modelo forte).

### Eixo D — Regressão factual (golden numbers — barato e altíssimo valor)
Um teste que congela **números canônicos** que NÃO podem driftar silenciosamente:
- Cobertura base = 1.121.306 OBs · 77% com CNPJ (atualizar quando ingerir, mas falhar se mudar sem querer).
- Total SIAFE ~R$ 20,16 bi (2016-2026). UG 133100 = ITERJ. Casa Civil→Consórcio RJ Cidadão 56,1%.
- Se um refactor mudar esses números, o teste **grita** antes do dono ver no relatório.

## 3. Como melhorar a codificação (as práticas, na ordem)
1. **`pyproject.toml` único** = fonte de verdade de ruff + pytest + coverage + mypy (hoje há ZERO config).
   Centraliza, versiona, e faz `ruff`/`pytest` se comportarem igual na VM, no Windows e no CI.
2. **Ratchet de lint** (não big-bang): `ruff check --fix` nos 206 seguros (F401/F541/E401 — import e f-string
   mortos, risco ~zero), commit isolado; baseline os 527 restantes; daí CI só falha em erro **novo**. Os E702/E701
   (statements em 1 linha) são estilo — auto-format com `ruff format` num commit separado e à parte (diff grande,
   não misturar com lógica). **Princípio:** cada categoria = 1 commit verificável; nunca "limpei tudo de uma vez".
3. **Marcar testes de rede** `@pytest.mark.network` → `pytest -m "not network"` vira a suíte rápida/100%-verde
   do dia a dia; os 5-6 hangs (PNCP/SEI/Receita) saem do caminho crítico. Resolve o "322 verdes + hangs" virar
   "verde limpo".
4. **Instalar `coverage` + `mypy`** (grátis, na VM). Medir cobertura só do **core que gera artefato** primeiro
   (inteligencia/lex/ugs/correlacao_sei/planilha) — é onde regressão dói. Não perseguir 100% global.
5. **Pre-commit**: já há hook codegraph+graphify ([[codegraph-graphify-precommit]]). **Adicionar `ruff check
   --fix` + `ruff format --check`** ao hook → nenhum lint novo entra. Barato, automático.
6. **God-files**: NÃO refatorar agora (lição V2 = não mexer no que funciona sem necessidade). Só **trackear LOC**
   no scorecard e dividir **quando uma feature já for tocar o arquivo** (oportunístico, isolado, com teste).
7. **`make bench`** (ou `tools/scorecard.py`): roda os 4 eixos e emite `data/scorecard.json` +
   `data/scorecard.md` (tabela: métrica · valor · delta vs último · 🟢/🟡/🔴). Vira o **artefato do loop** —
   cada checkpoint anexa o scorecard ao commit. Roda em subprocesso (não consome cota da sessão).

## 4. Plano faseado (cada item = 1 commit pequeno/isolado/verificado)
**Fase 0 — fundação (1 sessão, baixo risco, alto retorno):**
- [ ] `pyproject.toml` com [tool.ruff] (select sensato), [tool.pytest] (markers network), [tool.coverage].
- [ ] `pip install coverage mypy` no .venv; registrar em requirements-dev.txt.
- [ ] `ruff check --fix` (206 seguros) — 1 commit. `ruff format` — 1 commit separado.
- [ ] Marcar os ~6 testes de rede com `@pytest.mark.network`. Suíte `-m "not network"` 100% verde.
- [ ] Ruff + format-check no pre-commit.
→ Verificação: `ruff check` cai de 733 p/ ~527; `pytest -m "not network"` verde e rápido; pre-commit barra novos.

**Fase 1 — scorecard de engenharia (Eixo A + D):**
- [ ] `tools/scorecard.py`: coleta lint count, coverage %, pass rate, LOC dos god-files → `data/scorecard.json`.
- [ ] Teste de **regressão factual** (Eixo D): golden numbers (cobertura, total SIAFE, UG 133100, HHI Casa Civil).
- [ ] Rodar baseline e commitar o primeiro `scorecard.md`.

**Fase 2 — golden de produto (Eixo B), reusando o juiz-LLM existente:**
- [ ] `tests/golden/` com entradas fixas (3 CNPJs, 2 órgãos, 2 processos SEI).
- [ ] Rubrica B1 (relatório): metade determinística (SUM bate? cobertura bate? UG por código?) — vira pytest.
- [ ] Rubrica B2 (Lex): asserções do guard honesto + (pós SEI-fix) checagem de "cita §/mecanismo".
- [ ] Conectar o juiz-LLM (já em `benchmark_runner.py`) para a parte de prosa (honestidade/qualidade analítica).

**Fase 3 — fechar os ciclos (os 2 fixes profundos, que destravam B2 e B3):**
- [ ] Fix coletor SEI → inteiro teor (Fix #1 do handoff) → B2 vira real.
- [ ] Scorer OOS Massare (Fix #2) → B3 (hit rate + Brier) vira real.

**Fase 4 — automação:** cron semanal do scorecard + benchmark de IAs (Eixo C); anexar scorecard a cada checkpoint.

## 5. Quick wins (fazer já, risco ~zero, se o dono aprovar)
1. `ruff --fix` dos 206 seguros (remove 123 imports mortos + 57 f-strings vazias) — código mais limpo, zero lógica.
2. `pyproject.toml` mínimo — destrava todo o resto.
3. Marcar testes de rede — suíte do dia a dia deixa de "pendurar".
4. Teste de golden numbers (Eixo D) — 1 arquivo, protege os números canônicos contra refactor.

## 6. O que NÃO fazer (guard-rails da lição V2)
- Não refatorar os god-files em massa "por limpeza" — só oportunístico, com a feature que já vai tocar o arquivo.
- Não perseguir 100% de cobertura/lint global — ratchet, foco no core que gera artefato.
- Não meter o juiz-LLM no hot-path do relatório — benchmark roda **offline**, em subprocesso, fora da entrega.
- Não misturar `ruff format` (diff enorme) com mudança de lógica no mesmo commit.

## 7. Definição de sucesso
A cada checkpoint do loop, um `scorecard.md` com **delta vs anterior** responde, em número: o output ficou mais
honesto/enxuto/correto? o código ficou mais limpo? a suíte está verde? as previsões batem? — substituindo o
"acho que melhorou" por evidência. É o "sistema pensante" aplicado ao **próprio processo de melhoria**.
