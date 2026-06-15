# PLAYBOOK DO EXECUTOR (Hermes/Yoda e qualquer IA) — o que rodar e onde achar

> Objetivo: qualquer IA do ecossistema (mesmo modelo fraco) consegue **fazer o que o Claude faz** e
> **achar onde está cada coisa**, sem reinventar. Passos explícitos e idempotentes (re-rodar é seguro).
> Ambiente: VM Linux GCP, `/home/ubuntu/JFN`. SEMPRE prefixar `PYTHONPATH=. .venv/bin/python`.
> Ver também: [`AMBIENTE.md`](AMBIENTE.md), `CLAUDE.md`. Princípio: [[diretriz-workflows-para-ias]].

## ⭐ TL;DR (os comandos mais usados — copie e cole)
Sempre `cd ~/JFN && PYTHONPATH=. .venv/bin/python ...`. SÓ UMA coleta SIAFE por sistema (lockfile cuida).
| Quero… | Comando |
|---|---|
| Atualizar SIAFE 2 hoje (incremental, é o do cron 05:00) | `-m compliance_agent.siafe_runner diario` |
| Coletar UMA UG (fura o teto 1000) | `-m compliance_agent.siafe_runner ug <UG> [ANO]` |
| Sweep completo (backfill) SIAFE 2 / SIAFE 1 | `-m compliance_agent.siafe_runner sweep 2` · `-m tools.siafe_sweep_full 1` |
| Conferir/completar um dia (overflow >1000) | `-m compliance_agent.siafe_runner verificar DD/MM/AAAA` |
| Sócios/diretores por OB | `-m tools.enriquecer_socios_ob` |
| Login FlexVision (folha) | `-m tools.flexvision_cdp auto` |
| Status (vivo? quanto coletado?) | `curl -s 127.0.0.1:8000/api/siafe/status` · `.../api/siafe/stats` |
| Massare diário (preços+cobrança das previsões) | `-m massare.daily` (no **cron 06:15**) |
| Massare backtest OOS (atualiza /placar) | `-m massare.backtest --stamp "$(date -Iseconds)"` (no **cron dom 04:30**) |
SIAFE 1 (2016-23) = mesmos comandos com `JFN_SIAFE_LOGIN_URL=https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp`
(sessão independente do 2.0 → roda em paralelo). Receita do filtro que destrava tudo: §2 abaixo.

## 0. INTELIGÊNCIA DE CÓDIGO — use ANTES de grep/ler tudo
O repo é indexado por **codegraph** (MCP) e **graphify** — consulte primeiro pra achar função/arquivo/fluxo:
- **codegraph** (MCP, sub-ms): `codegraph_explore "como funciona X"` (1 chamada já traz o código relevante);
  `codegraph_search <nome>`, `codegraph_callers/callees/impact`. É o índice pronto — não faça grep do repo todo.
- **graphify**: `graphify query "where is the auth logic?"` (grafo persistente; god nodes/comunidades).
- Atualizar índices ANTES de commit (git hook): ver [[codegraph-graphify-precommit]]. Índices ficam **só locais**
  (nunca no git). Regerar JFN: `cd ~/JFN && codegraph index . ` e `graphify` (ver SKILL `/graphify`).

## 1. COLETORES — comandos prontos (terminal)
### 1z. PONTO ÚNICO: `siafe_runner` (use ESTE no dia a dia) + atualização DIÁRIA
`compliance_agent/siafe_runner.py` orquestra tudo com **LOCKFILE de sessão única** (impede coletas SIAFE
concorrentes que se derrubariam). Comandos:
```
PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_runner diario [ANO]   # incremental: OBs novas da aba (sem filtro). Ano corrente por default.
PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_runner ug <UG> [ANO]  # uma UG (fura o teto; cai p/ subdivisão se capar)
PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_runner sweep [2|1]    # sweep completo (backfill)
```
**ROTINA DIÁRIA (cron, 05:00):** `siafe_runner diario` mantém a base FRESCA sem sweep — a aba OB Orçamentária
lista as OBs mais novas primeiro e o volume/dia é <1000, então uma passada sem filtro capta o que entrou
(idempotente, PK numero_ob). Sweep só p/ BACKFILL histórico ou quando comandado.
**ROTAS NO JFN (pro Yoda via curl; ativas após reload do jfn.service):**
`POST /api/siafe/atualizar {exercicio?}` · `POST /api/siafe/sweep {sistema|ug,exercicio}` · `GET /api/siafe/status` (lock) · `GET /api/siafe/stats`.
Enquanto o jfn.service não recarrega, o Yoda roda o CLI acima via a ferramenta `terminal`.

### 1a. SIAFE-Rio 2 (2024–2026) — OBs por UG (FURA o teto de 1000) [detalhe; prefira o siafe_runner acima]
```
PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria --por-ug <UG> --exercicio <ANO>
```
Ex.: ITERJ 2026 → `--por-ug 133100 --exercicio 2026`. Ingere em `ob_orcamentaria_siafe`. UG pequena cabe;
UG grande (>1000/ano: SEEDUC, TJRJ) bate o teto → precisa sub-filtro por período (fase 2, ver §3).
Sweep de várias UGs prioritárias: `PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_ugs` (resumível, checkpoint).

### 1b. SIAFE 1 (2016–2023) — MESMO coletor, outra URL (sessão independente do 2.0 → roda em PARALELO)
```
JFN_SIAFE_LOGIN_URL="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp" \
  PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria --por-ug <UG> --exercicio <ANO 2016..2023>
```
✅ SIAFE 1 DESTRAVADO (2026-06-07): o coletor já trata o filtro do SIAFE 1 (operador "começa com" + commit do
valor via cliente ADF, embutido em `_set_valor`). Sweep completo: `-m tools.siafe_sweep_full 1`. Roda em paralelo ao 2.0.

### 1c. FlexVision (folha/BI da SEFAZ) — login + export
```
PYTHONPATH=. .venv/bin/python -m tools.flexvision_cdp auto      # loga (Chrome CDP 9222), MFA via log do Hermes, salva sessão 30 dias
PYTHONPATH=. .venv/bin/python -m tools.flexvision_cdp status     # SINAL=LOGADO|MFA_PENDENTE|SESSAO_OCUPADA|...
```
MFA: o código chega no Telegram → está em `~/.hermes/logs/gateway.log` (`msg='<COD>'`); `auto` lê sozinho.
Doc completa: [`docs/FLEXVISION-EVOLUCAO.md`](docs/FLEXVISION-EVOLUCAO.md).

### 1d. Sócios/diretores por OB (BrasilAPI QSA) — enriquece CNPJs credores das OBs
```
PYTHONPATH=. .venv/bin/python -m tools.enriquecer_socios_ob     # idempotente; grava em socios_fornecedor
```

## 2. RECEITA-CHAVE (decifrada) — filtro ADF do SIAFE (vale p/ TODAS as telas)
O ADF ignora eventos sintéticos (`isTrusted=false`). Por isso `select_option`/`fill`/`dispatch` NÃO filtram.
- `<select>` (Propriedade/Operador) → **TYPEAHEAD**: foco por mouse real + `keyboard.type(label)` + Enter + Tab.
- Campo de VALOR → digitar e **commitar com `Tab` (blur), NÃO Enter** (Enter não aplica; Tab dispara o PPR).
Código reutilizável: `siafe_ob_orcamentaria._typeahead()` e `_filtrar_ug()`. Detalhes: `docs/SIAFE-RIO2-GUIA-AUTOMACAO.md` (§8b).

## 3. MAPA DE DOCS (onde achar cada coisa)
- **SIAFE-Rio 2** (telas, IDs, filtro, §8b resolvido, SIAFE 1, paralelismo): `docs/SIAFE-RIO2-GUIA-AUTOMACAO.md`
- **FlexVision** (login, MFA, export, DOM): `docs/FLEXVISION-EVOLUCAO.md`
- **Sites difíceis** (WAF/SPA/ADF/HTTP replay — hierarquia de esforço): `docs/SCRAPING-SITES-DIFICEIS.md`
- **Folhas — fontes por órgão**: `docs/FOLHAS-FONTES.md`
- **Barramento/relatórios + rotas HTTP**: `CLAUDE.md` (seção MOTOR DE RELATÓRIOS) + `AMBIENTE.md`
- Tentativas/erros do SIAFE (não repetir): `docs/SIAFE-EVOLUCAO-TENTATIVAS.txt`

## 4. BARRAMENTO JFN (como o Yoda já aciona — via curl/terminal)
`POST /api/relatorio/inteligencia {empresa|cnpj}` · `POST /api/relatorio/orgao {orgao|ug}` ·
`GET /api/massare/{placar,cenarios}` · `POST /api/hermes/missao {missao}` · `GET /api/cruzamento?cnpj=` ·
`GET /api/siafe/stats`. JFN vivo: `curl -s http://127.0.0.1:8000/status`. NUNCA parar `jfn.service`.

## 5. REGRAS DE OPERAÇÃO (não tropeçar)
- **SIAFE = sessão ÚNICA por sistema**: 2 coletas no MESMO SIAFE se derrubam; SIAFE 1 e 2 são independentes (paralelizáveis).
- **Browser**: usar Chrome CDP 9222 (`chrome-jfn.service`) p/ MFA entre turnos; Playwright em background trava — preferir foreground + redirect p/ arquivo, ou os módulos prontos.
- **Idempotência**: todos os coletores podem re-rodar sem duplicar (chave por OB/CNPJ/competência).
- **Documentar sempre** tentativas que falham (pra não repetir) nos docs acima.

## 6. QUALIDADE & BENCHMARK (medir antes de dizer "melhorou") — desde 2026-06-09
> Plano completo: [`PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md`](PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md).
> Regra de ouro: **não declare melhoria sem número**. A cada checkpoint, rode o scorecard e compare o delta.

| Quero… | Comando |
|---|---|
| Scorecard objetivo (ruff·LOC·god-files·golden) com delta | `python tools/scorecard.py --stamp "<ISO>"` → `data/scorecard.md` |
| Suíte RÁPIDA (sem rede, não pendura) | `.venv/bin/pytest -m "not network and not integration" -q --timeout=90` |
| Só a rede (quando precisar) | `.venv/bin/pytest -m network -q` |
| Lint (sinal; baseline ~43) | `.venv/bin/ruff check .` · auto-fix seguro: `ruff check . --fix` |
| Regressão factual (golden numbers) | `.venv/bin/pytest tests/test_golden_numbers.py -q` |

**Gate de lint no commit (best-effort):** `tools/precommit_ruff.sh` roda ruff só nos `.py` STAGED e AVISA
sobre lint novo (não bloqueia; ignora `_SANDBOX/`, `tools/debug/`). É chamado pelo hook local
`.git/hooks/pre-commit` (local-only — reinstalar num clone novo: copiar o trecho que chama o script, ou rodar
`bash tools/precommit_ruff.sh` à mão). Não deixa lint novo entrar nos arquivos que você toca, sem brigar com o
baseline legado (39).

**Regras (aplicam a TODA mudança de relatório/parecer/previsão):**
1. **Gere o ARTEFATO REAL** antes e depois (`-m compliance_agent.reporting.inteligencia "MGS Clean"` /
   `...inteligencia_orgao "ITERJ"`) e compare. Baseline gold em `data/baseline_2026-06-09/`.
2. **Verifique o PDF ENTREGUE, não só o MD** — há 3 renderizadores (MD, FPDF, HTML→PDF). Use pypdf p/ extrair
   o texto e conferir que o achado novo está no PDF (lição cara: um red flag pode existir no MD e faltar no PDF).
3. **Honestidade**: tudo é **indício a verificar**, nunca acusação; nunca inventar número; afirmar só dentro
   da cobertura da base (o cabeçalho de frescor diz qual é). Objeto contratual real vem do **TCE-RJ**
   (`tcerj_itens`), NÃO do `contratos.objeto` do SIAFE (que só guarda "Aditivos:N").
4. **Pequeno, isolado, verificado** > camada grande. Commit por unidade; documentar erros & acertos.

## 🔜 TODO PÓS-SWEEP (fazer quando os sweeps terminarem — não mexer mid-run)
- **Lock por sistema:** hoje `siafe_lock.json` é único (SIAFE 1 e 2 compartilham via heartbeat). É SEGURO
  (erra pro lado de não colidir), mas o diário do 2.0 pode ser bloqueado à toa enquanto só o SIAFE 1 roda.
  Refatorar p/ `siafe_lock_{1,2}.json` (NÃO trocar o nome mid-run — quebraria a proteção do sweep ativo).
- **VACUUM** no compliance.db após o sweep (recupera churn de re-ingestão) — `python -m compliance_agent.manutencao`.
- **Limpeza de código morto** via graphify (cuidado: modelo branch-por-SO — não apagar _SANDBOX/win sem checar).
- **Stats com "frescor"**: adicionar data da última OB por ano em /api/siafe/stats (saber se o diário está em dia).
- **SIAFE 1 UG grande**: validar a subdivisão (ug-grande) no SIAFE 1 (a coleta direta capou em 1000 p/ ALERJ).

## ✅ TESTE YODA end-to-end (2026-06-07) — leitura E ação validadas
- LEITURA: Yoda (`hermes -z`) consultou /api/siafe/stats e reportou totais por ano + cobertura SEI. OK.
- AÇÃO: Yoda rodou `siafe_runner diario` via terminal; com o sweep ativo, o **lockfile RECUSOU** ("coleta SIAFE
  em andamento por sweep:2") e Yoda reportou isso corretamente ao Mestre Jorge. → comando de ação + proteção de
  sessão única VALIDADOS. (Quando não houver sweep, o mesmo comando dispara a atualização incremental.)
