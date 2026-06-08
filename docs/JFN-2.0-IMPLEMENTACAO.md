# JFN 2.0 — Log de Implementação (para avaliação posterior)

## 📍 VOCÊ PAROU AQUI (último checkpoint: 2026-06-08)
> **Feito:** Onda 0 ✅ (capabilities.yaml+validador+obs_trace) · Onda 1 🟡 (geradores ✅, política de modelo no
> config ✅, roteador adaptativo 3-trilhas codificado+testado ✅ — `tools/hermes_model_router.py`; **SKILLTREE ✅**
> `compliance_agent/skilltree.py` reload fail-safe+sync+render, +5 capacidades `sistema`, 8 testes — commit `5279edf`)
> · Onda 2 🟡 (`lex_conflito.py` doador↔SÓCIO↔OB ✅ testado) · pesquisa DD+OSINT ✅ · deps grátis instaladas ✅.
> **PRÓXIMO PASSO:** **Onda 13** (ÚLTIMA, adiada pelo dono): wiring dos slash commands/roteador no gateway Hermes
> VIVO (`~/hermes-agent/gateway/run.py` — MessageHandler catch-all + `hermes_cli/commands.py`; gating admin via
> `slash_access.py`); + itens SIAFE da Onda 11 quando os sweeps pararem. **TODAS as Ondas 0–12 com CORE ✅ e
> commitadas; suíte JFN 2.0 = 92 TESTES VERDES (validação integral feita).** ~38 capacidades PRONTO. **Estratégia
> de modelos: `docs/MODELO-ESTRATEGIA.md`** (free; default `gemini-2.5-flash`; pago só sob confirmação). **Chaves
> Gemini: 9 chaves de 9 PROJETOS distintos = 9× cota free (rotação nativa Hermes).** Verificador: `tools.check_gemini_key`.
> **MODELO (corrigido — verificado jun/2026): default/pesado = `gemini-2.5-flash` (ÚNICO Gemini free junto do
> flash-lite; Pro e 3.x são PAGOS); `gemini-2.5-pro` só sob "usar o modelo melhor" + confirmação. Rotação de 8
> chaves Gemini JÁ ATIVA no `~/.hermes/auth.json` (pool nativo Hermes) — commit `0f1b8aa`.** Adiado p/ última
> onda: wiring slash no Yoda vivo. ⚠️ Sweep SIAFE 2 rodando = não tocar módulos SIAFE. **ADIADO p/ ÚLTIMA ONDA
> (dono):** wiring dos slash commands/roteador no gateway Hermes VIVO (`~/hermes-agent/gateway/run.py`; Hermes É
> python-telegram-bot mas usa MessageHandler catch-all + `hermes_cli/commands.py`, NÃO CommandHandler). **Política de
> modelo: manter `gemini-2.5-pro`** (decisão do dono). **REGRA PERMANENTE:** toda skill nova → `capabilities.yaml` + `/lista`.
> **Estado vivo:** sweep SIAFE 2 **RETOMADO** (pid via supervisor; resume do checkpoint 86 UG:ano em
> `data/sei_cache/siafe_sweep_full_2.json`; re-pausar com `touch data/.pause_sweep_2` ANTES de tocar módulo SIAFE);
> download TSE **rodando**; Yoda gateway no ar; jfn.service ativo. ⚠️ Sweep rodando = NÃO mexer em módulos SIAFE.
> **Branch `jfn-2.0`** (pushada). Tudo abaixo é o detalhe.

## ▶ RETOMADA RÁPIDA (ler PRIMEIRO se a sessão caiu / contexto estourou)
> Trabalho de DIAS — projetado para sobreviver a quedas de sessão. **Para continuar exatamente de onde parou:**
> 1. `cd ~/JFN && git checkout jfn-2.0` (branch de trabalho; `linux` é o estável/rede de segurança).
> 2. Ler **este doc inteiro** + os specs-fonte em `docs/refs/` (preservados porque o cache do Hermes auto-limpa):
>    **`JFN-DOCUMENTO-MESTRE-CONSOLIDADO-v2.{pdf,txt}`** (VERSÃO ATUAL — usar esta; §7 = `capabilities.yaml`, §5 =
>    passo-a-passo por onda) e **`JFN-ADICIONAL-DUE-DILIGENCE-OSINT.{pdf,txt}`** (metodologia DD/OSINT + catálogo de
>    ferramentas grátis). (`...-CONSOLIDADO.{pdf,txt}` sem sufixo = v1, histórico.)
> 3. Olhar a tabela **"Progresso por onda"** e o **"Diário de execução"** (fim do doc) — a última linha diz o
>    ponto exato. Pegar a primeira onda/ item não-✅ e seguir o §5 do spec.
> 4. Regras inquebráveis: **branch `jfn-2.0`**; **aditivo**; `pytest -q` antes de cada commit; **commitar cada
>    unidade** (estado salvo cedo); **NÃO tocar módulos SIAFE enquanto os sweeps rodarem** (`pgrep -f siafe_sweep_full`);
>    **TODAS as ferramentas/fontes 100% GRATUITAS** (sem IBKR/nada pago — §4 do spec); invariantes §0.
> 5. **Pesquisa DD+OSINT** (pedida pelo dono) roda em agentes de background; quando concluírem, os relatórios são
>    salvos em `docs/research/DD-METODOLOGIA.md` e `docs/research/OSINT-METODOLOGIA.md`. **Se esses arquivos NÃO
>    existirem**, a sessão caiu antes — RELANÇAR a pesquisa (DD: padrão Kroll/ACFE/FATF; OSINT: grafo/adverse-media/
>    fontes BR grátis) e dobrar nas Ondas 4/6/7/10.
> 6. Estado vivo a conferir: `git log --oneline -15`, `git status`, `pgrep -f siafe_sweep_full` (sweep S2),
>    `systemctl --user is-active hermes-gateway` (Yoda).

> **Fonte:** `docs/refs/JFN-DOCUMENTO-MESTRE-CONSOLIDADO.pdf` (recebido via Telegram 2026-06-08, autor: IA externa;
> original cacheado em `~/.hermes/cache/documents/`). **Branch de trabalho: `jfn-2.0`** (de `linux`; reverter = `git checkout linux`).
> Disciplina: 1 onda por vez, **aditivo**, `pytest -q` antes de cada commit, **TODAS as ferramentas GRATUITAS**,
> **não tocar nos módulos dos sweeps SIAFE enquanto rodarem**. Documentar cada passo aqui.

## Análise do documento (resumo)
Spec de 12 ondas (0–11) para elevar o JFN de "auditor reativo" a: **(1) vigilante** (Radar 24/7),
**(2) grafo único de poder** (sócios+servidores+doações+contratos+nomeações), **(3) instrumento de mandato**
(achado → minuta ALERJ/TCE/MP). Correção arquitetural central: **não são 5 agentes** — é **1 runtime (Hermes) +
1 orquestrador (Yoda) + 1 motor (JFN)** com módulos de domínio; o contrato único é `capabilities.yaml`.
Camada de dados **100% gratuita** (PNCP, TSE, BCB/Focus, FRED, brapi, Yahoo/Stooq, websocket cripto, GDELT, Finnhub).

## Invariantes (§0 — nunca violar)
OB=pagamento (≠empenho) · honestidade de dados (REAL vs CACHE, nunca fabricar) · honestidade jurídica
(indícios, nunca acusação) · honestidade de mercado (OOS+custos, nunca prometer certeza) · estética due
diligence · credenciais só em .env · SIAFE sessão única por sistema · LGPD.

## Decisões de execução (minhas, documentadas)
- **Ordem:** Onda 0 (fundação) → 2 (PNCP+conflito) → 3 (motor de risco) → 8 (Massare notícia/macro) → demais.
  As ondas 2/3/8 são prioridade do dono e majoritariamente **aditivas** (módulos/rotas novas; não tocam sweeps).
- **DIFERIDO com motivo:**
  - `siafe_worker.py` (Onda 0): extrair a sessão SIAFE da API para um worker. ⚠️ O sweep S2 está rodando e o
    próprio documento manda não mexer nos módulos SIAFE durante os sweeps → fazer só após os sweeps terminarem.
  - **Desbloqueio SEI via proxy** (Onda 0): exige `SEI_PROXY_URL` (proxy residencial BR) que não temos → pendente.
  - Deprecar `agent.py`/`scheduler.py` (Onda 1): risco em sistema vivo → após cobertura comportamental.
- **Chaves grátis a obter (§8):** Finnhub, brapi.dev (token grátis) — onde faltar, marcar INDISPONÍVEL (nunca fabricar).

## Progresso por onda
| Onda | Escopo | Status |
|---|---|---|
| 0 | capabilities.yaml + validador + obs_trace | 🟢 núcleo ✅ (gen_*→Onda 1; siafe_worker/SEI-proxy diferidos) |
| 1 | Orquestração (router do YAML, política de modelo) | 🟡 geradores+config+roteador adaptativo+**skilltree** ✅; dispatcher nativo no gateway VIVO = ADIADO p/ última onda (decisão do dono) |
| 2 | PNCP + conflito doador↔contrato (Lex) | ✅ `/api/conflito` (542k doações TSE) + `/api/pncp` (consulta+abertos+análise de edital). 2c: `id=` baixa edital ZIP/PDF→texto + red flags Lex (R7 validado em edital real) |
| 3 | Motor de risco (Benford/sobrepreço/score) | ✅ Benford 1º+2º díg MAD-Nigrini (`/api/anomalias`) + sobrepreço CATMAT/CATSER (`/api/sobrepreco`) + score convergência decomponível. Cartel R8 já tinha grafo |
| 4 | Grafo de Poder + Dossiê 360 | ✅ `grafo_poder.py` (vizinhança BFS local, `/api/grafo`) + `dossie.py` (cadastro+sanções+OB+conflito+rede+score→PDF, `/api/dossie`). Validado: BEST VIGILANCIA score 37 |
| 5 | SEI inteligência em escala | ✅ `sei_extract` (schema) + `sei_corpus` (FTS5) + `sei_direcionamento` (varredor R1/R7/R8/R12, `/api/sei/direcionamento`). **SEI consolidado no reader itkava** (porta única, sem captcha) |
| 6 | Radar 24/7 | ✅ `radar.py` (watchlist + ciclo PNCP-aberto-restritivo + OB-anômala → alerta Telegram, idempotente); `/api/radar/vigiar|status|ciclo`; systemd `jfn-radar.{service,timer}` (20min) |
| 7 | Relatório classe mundial (HTML→PDF) | ✅ `reporting/render_html.py` (Jinja2+CSS→PDF via Playwright) + `charts_svg.py` (sparkline/barras/heatmap P×I); dossiê usa o motor (rating card + ≥3 SVG + proveniência + hash SHA-256) |
| 8 | Massare notícia/macro/Focus | ✅ core: `focus.py`(BCB,sem chave) + `news.py`(GDELT) + `fundamentos.py`(brapi) + `calendar.py`(Finnhub). Rotas `/api/massare/focus\|noticias\|fundamentos\|calendario`. Validado live (Selic 13.25/PETR4 R$40,89). crypto_ws 24/7 (daemon) diferido |
| 9 | Massare teses + validação López de Prado | ✅ `theses.py` (narrativa→ativos→tese registrada OOS) + `validation.py` (DSR/PBO/custos, López) + `carteira.py` (manual). `/api/massare/teses\|carteira` |
| 10 | Lex + instrumentos de mandato | ✅ `mandato.py` gera minuta .docx (requerimento/representação/notícia de fato/post) c/ cláusula de honestidade + precedente LexML. `/api/mandato/minuta` |
| 11 | Higiene técnica | 🟡 `/api/memoria` (consolidação) ✅; siafe_lock/split de módulos/deprecar agent.py = DIFERIDO (sweep SIAFE rodando + risco em sistema vivo; parte feita na otimização anterior) |
| 12 | Enriquecimento OSINT/DD (hospedado) | ✅ `grafo_ftm.py` (export FollowTheMoney, `/api/grafo/ftm`) + `enrich/opensanctions.py` (PEP/sanções, key-gated, integrado no dossiê). OpenCorporates = key-gated futuro |
| 13 | Wiring slash commands no gateway Yoda VIVO | ⏳ ADIADO p/ última onda (decisão do dono) — não arriscar o bot vivo |

> **STATUS GLOBAL (2026-06-08): Ondas 0–12 com CORE implementado e commitado; suíte JFN 2.0 = 92 testes verdes.**
> Pendências EXPLÍCITAS (diferidas com motivo): wiring no gateway vivo (Onda 13, dono); itens SIAFE da Onda 11
> (sweep rodando); crypto_ws daemon (Onda 8); chaves grátis brapi/Finnhub/OpenSanctions/OpenCorporates (key-gated,
> reportam INDISPONÍVEL honestamente). **Chaves Gemini: 9 chaves de 9 projetos = 9× cota free (rotação nativa).**

## ✅ DEFINIÇÃO DE PRONTO + LIMPEZA DE MEMÓRIA (último passo — NÃO esquecer)
Quando **todas as 12 ondas estiverem ✅ e a suíte verde**, a sessão que concluir DEVE, como ato de encerramento:
1. Mesclar `jfn-2.0` → `linux` (PR/merge), confirmar `pytest -q`, e atualizar a tabela acima toda para ✅.
2. **Limpar a memória persistente** (o dono pediu): `rm` em
   `~/.claude/projects/-home-jfelippebethlem/memory/jfn-2.0-implementacao.md` e **remover a linha
   "▶ JFN 2.0 — CONTINUAR AQUI"** do `MEMORY.md` (o histórico permanece no git/docs; só sai o ponteiro de
   retomada que era carregado em toda sessão). Opcional: deixar 1 linha curta "JFN 2.0 entregue em <data>".
3. Anunciar conclusão ao dono no Telegram.
> ⚠️ Não há remoção automática por tempo; a limpeza é este passo deliberado. A IA NÃO lembra sozinha entre
> sessões — por isso esta instrução vive aqui e na memória: quem fechar a Onda 11 executa.

## ⏸️ SWEEP SIAFE 2 — PAUSADO (2026-06-08, a pedido do dono para implementar a Onda 1)
**Ponto de parada (para retomar):** 86 UG:ano feitos (29 UGs com dado), parou em **110100/2024** no meio de uma
subdivisão ug-grande; **48.600 OBs** (2024-26) no banco. Checkpoint: `data/sei_cache/siafe_sweep_full_2.json`
(resumível; o sub-checkpoint da ug-grande retoma sozinho). **Pausa:** flag `data/.pause_sweep_2` (supervisor
respeita e NÃO relança). **PARA RETOMAR:** `rm data/.pause_sweep_2` (o supervisor relança em ≤1 min) OU
`PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full 2`. SIAFE 1 (ALERJ) já estava completo. ⚠️ Com o sweep
PARADO, agora é seguro mexer nos módulos SIAFE (ex.: `siafe_worker.py` da Onda 0, diferido).
**Download TSE** (doações RJ+presidente, todos os anos) roda em processo SEPARADO (`/tmp/tse_load.py`,
`data/tse_load.out`) — NÃO é o sweep; deixar terminar (popula `doacoes_eleitorais` p/ o conflito da Onda 2).

## ⏳ DECISÃO PENDENTE DO DONO — roteamento de modelo do Hermes (Onda 1)
**Como está hoje (investigado):** Hermes NÃO é adaptativo por tarefa. Usa **1 modelo default p/ tudo**
(`gemini-2.5-flash`) e só troca em FALHA (fallback failure-based). Não há roteamento por dificuldade.
**Config atual aplicada** (`~/.hermes/config.yaml`, backup `config.yaml.bak.jfn2-onda1-*`): default
gemini-2.5-flash; `api_max_retries:3`; fallback ordem **gemini-lite → gemini-2.0 → mistral-large →
mistral-small → nous×3 (100% free, por último — a pedido do dono)**. Gateway reinicia saudável.
**DECISÃO TOMADA (2026-06-08):** **A — heurística simples**, **3 trilhas**: (1) chat/default = **gemini-2.5-flash**
(free); (2) caso difícil (parecer/jurídico/auditoria/edital/14.133/msg longa) = **gemini-2.5-pro**; (3) **bulk
simples/repetitivo** (extração SEI em massa, classificação de notícias em lote) = **nous (100% free, sem cota)**.
⚠️ O **sweep SIAFE e coletores NÃO usam LLM** (código determinístico) → fora dessa política. OCR/visão = easyocr/gemini.
✅ Lógica implementada e testada: `tools/hermes_model_router.py` (`escolher_modelo(texto, anexo)` → default
gemini-2.5-flash; gatilhos jurídico/auditoria/edital/dossiê/14.133 OU msg >600 chars → `gemini-2.5-pro`;
reforço mistral-large). `tests/test_hermes_model_router.py` (4 verdes). **FALTA o WIRING no gateway** (aplicar
`escolher_modelo` por request antes da chamada — ponto `run.py:13078`, via overlay idempotente p/ sobreviver a
`hermes update`): setar agent.model/provider por mensagem. É o último passo da Onda 1 (fazer com cuidado, bot vivo).

## Onda 1 — estado detalhado
✅ FEITO: `tools/gen_router_tools.py` (→ `data/jfn_tools.json` + `~/.hermes/jfn_tools.json`, 17 tools ativas/15
futuras), `tools/gen_capabilities_md.py` (→ `docs/CAPACIDADES.md` + `data/yoda_capabilities_prompt.txt`),
pre-commit (valida+regenera, local), política de modelo no config.yaml (acima).
⏳ FALTA: dispatcher NATIVO de tool-calling no gateway (injetar jfn_tools.json em `_tools` run.py:13078 +
executor function-call→HTTP/CLI, via overlay idempotente); injetar `yoda_capabilities_prompt.txt` no system
prompt (registro fechado, mata invenção de web_search); deprecar `agent.py`/`scheduler.py` (hermes_goal único);
roteamento adaptativo (decisão acima).

## Diário de execução
- **2026-06-08** — Branch `jfn-2.0` criada (de `linux`) e pushada p/ origin. Documento mestre lido e analisado;
  PDF+texto preservados em `docs/refs/`. Infra de RETOMADA + memória persistente criadas. Pesquisa DD+OSINT
  lançada em background (salvar em `docs/research/`). Invariante reforçado: **todas as ferramentas GRATUITAS**.
  Iniciada Onda 0 (fundação aditiva: capabilities.yaml → validador → obs_trace).
- **2026-06-08 (cont.)** — ✅ **Pesquisa DD + OSINT concluída e salva** em `docs/research/DD-METODOLOGIA.md` e
  `docs/research/OSINT-METODOLOGIA.md` (citadas, 2024-2026). Ambas trazem **"MAPA PARA O JFN"** com técnica → onda →
  lib/fonte grátis → critério de aceite. Achados-chave a aplicar: **proveniência por dado (lineage)** e **declarar
  nível de DD aplicado** (Onda 7) = maior salto rumo a Kroll; **screening CEIS/CNEP** via API Portal Transparência
  (Onda 2, chave grátis); **UBO regra-50%** sobre `rede_societaria.py` (Onda 4); **followthemoney+Splink+networkx**
  p/ Grafo de Poder (Onda 4); **GDELT DOC 2.0** p/ adverse media no Radar (Onda 6); **LGPD: base legal = obrigação
  legal/atribuição do Poder Público, NÃO legítimo interesse** (invariante a registrar). Libs novas grátis a pinar
  quando usadas: followthemoney, splink, python-louvain/leidenalg/igraph, pyvis, rapidfuzz.
- **2026-06-08 (Onda 0 núcleo ✅)** — Criados e TESTADOS (106 testes verdes):
  `capabilities.yaml` (32 capacidades: 17 PRONTO, 15 em onda); `tools/validate_capabilities.py` (schema + checa
  que rota PRONTO existe no server.py — CI-friendly); `compliance_agent/obs_trace.py` (correlation-id +
  `GET /api/trace/{id}`, wiring aditivo em `server.py` via `register_trace(app)`, best-effort); `tests/test_jfn2_onda0.py`.
  Aceite Onda 0(b) validado por TestClient (header X-Correlation-Id + /api/trace mostra etapas). ⚠️ Ativa no
  servidor vivo só no próximo reload do jfn.service (não reiniciei p/ não perturbar; sweeps rodam fora do jfn.service).
  **DIFERIDO:** `siafe_worker.py` (sweep S2 ativo) e desbloqueio SEI (sem `SEI_PROXY_URL`). `gen_router_tools.py`
  e `gen_capabilities_md.py` + hook pre-commit → **Onda 1** (onde o roteador do Yoda consome o YAML).
  **PRÓXIMO: Onda 2** (PNCP + conflito doador↔contrato) — prioridade do dono, aditiva. Ver mapa em
  `docs/research/DD-METODOLOGIA.md` (#1 screening, #10 COI) e `OSINT-METODOLOGIA.md` (doação↔contrato, cartel).
- **2026-06-08 (background deps + novos specs)** — ✅ Instaladas (todas GRÁTIS, núcleo intacto, 104 smoke verde):
  `rapidfuzz, python-louvain, igraph, leidenalg, pyvis, python-bcb, splink` (pinadas em `requirements.txt`).
  Diferidas com motivo: `followthemoney` (precisa libicu/apt), `sentence-transformers`/`vectorbt`/`weasyprint`
  (na sua onda). **Torch pode ser reinstalado SE preciso — sempre `--index-url .../whl/cpu`** (autorizado pelo dono).
  - ✅ **2 novos specs recebidos via Telegram e preservados:** `docs/refs/JFN-DOCUMENTO-MESTRE-CONSOLIDADO-v2.{pdf,txt}`
    (mestre atualizado — USAR ESTE) e `docs/refs/JFN-ADICIONAL-DUE-DILIGENCE-OSINT.{pdf,txt}` (metodologia DD/OSINT
    + catálogo de ferramentas grátis: Aleph/OpenCorporates/Brasil.io etc., marcando [JFN]/[INTEGRAR]/[MANUAL]).
  - 🔴 **REQUISITO CRÍTICO da Onda 2 (instrução do dono):** o conflito NÃO é só doador-CNPJ == fornecedor-CNPJ.
    Tem que **cruzar doadores TSE × SÓCIOS (QSA, `socios_fornecedor`) das empresas que têm contrato/OB** — i.e., o
    doador (CPF/CNPJ) pode ser SÓCIO da contratada, não a contratada em si. Estender `tse.cruzar_doacoes_contratos`
    (hoje só casa CNPJ direto) para incluir o join via QSA. Mesmo raciocínio p/ parentesco (DD #9/#10).
- **2026-06-08 (Onda 1 — SKILLTREE ✅, commit `5279edf`)** — 4º PDF do dono (`docs/refs/JFN-SPEC-SKILLTREE-YODA.pdf`,
  preservado): ver/atualizar a skilltree pelo Telegram a quente. Implementado o **registry puro** e testável:
  `compliance_agent/skilltree.py` (`SkillTree`: `reload()` fail-safe **em memória** — YAML inválido mantém o estado
  anterior, nunca derruba o roteador; `sync()` git pull+reload; `validate()`/`tool_specs()` **REUSAM**
  `tools.validate_capabilities`+`tools.gen_router_tools` = fonte única; `render()`/`detalhe()` p/ Telegram). +5
  capacidades domínio `sistema` no `capabilities.yaml` (skills, skill_detalhe, skills_reload, skills_sync,
  skills_validate). `tests/test_jfn2_skilltree.py` (8 verdes; 15 verdes no bloco jfn2). **Revisão pós-leitura dos
  4 PDFs+doc:** corrigido 1 acoplamento (o `reload()` chamava `gen_router_tools.gerar()` escrevendo em
  `~/.hermes/jfn_tools.json` no import — removido; `reload()` agora é puro, não toca o Hermes vivo). **ADIADO p/
  última onda (dono):** wiring dos 5 slash commands no gateway Hermes vivo (`gateway/run.py` — MessageHandler
  catch-all + `hermes_cli/commands.py`, gating admin via `slash_access.py`). **Política de modelo `gemini-2.5-pro`
  mantida** (decisão do dono). **Regra permanente:** toda skill nova → `capabilities.yaml` + `/lista`.
  **PRÓXIMO: Onda 2 rotas** `/api/conflito` (usa `lex_conflito.conflito()`, já existe e testado) + `/api/pncp`
  (expandir `collectors/pncp.py`) em `server.py`; validar com as **542k doações TSE** já no banco.
- **2026-06-08 (Onda 2a+2b ✅, commits `fb8b9ef`+`37e5922`)** — **`/api/conflito`** (GET): expõe
  `lex_conflito.conflito()` (doador TSE ↔ empresa|SÓCIO ↔ OB, via QSA = requisito do dono); validado contra
  **542.244 doações** reais. Honesto: indício/CPF mascarado (LGPD)/score≠prova. Obs de dados: top dominado por
  mega-empresa via sinal fraco (`cpf_mascarado` só) — tuning do `lex_conflito` p/ depois, não da rota.
  **`/api/pncp`** (GET): **sondei a API real de consulta ANTES de codar** (não às cegas) — `/contratacoes/publicacao`
  (histórico, janela `dataInicial..dataFinal`) e `/contratacoes/proposta` (abertos, `dataFinal≥hoje`, fiscalização
  preventiva); `uf=RJ` filtra; `tamanhoPagina≥10`; id=`numeroControlePNCP`. `pncp.buscar_contratacoes(uf,datas,
  modalidade,abertos,orgao_cnpj)` + `_simplificar_contratacao` (shape `{id_pncp,objeto,valor,docs,red_flags}`;
  `docs/red_flags=[]` até a Onda 2c). modalidade=None varre 6/8/9/4 (maior risco). Validado live: **64 editais RJ
  abertos**. 6 testes determinísticos (mock de rede). Ambas as capacidades → PRONTO no `capabilities.yaml`.
  **Sweep SIAFE 2 RETOMADO** (a pedido do dono) — `rm data/.pause_sweep_2`; supervisor (cron watchdog) relançou
  (resume do checkpoint). Onda 2 não toca SIAFE; re-pausar antes de qualquer módulo SIAFE.
- **2026-06-08 (Onda 3 ✅ COMPLETA, commits `d957a11`+`e2fe9c3`+`0d49b95`)** — **motor de risco**:
  (3a) `analysis/benford.py` — Lei de Benford 1º+2º dígito, MAD de Nigrini c/ faixas; `benford_ob(orgao,fornecedor)`
  sobre `ordens_bancarias`; integrado em `/api/anomalias` (quando há filtro). Validado: lognormal=conformidade alta,
  uniforme=não conformidade, **1,08M OBs reais MAD 0,0057**. (3b) `sobrepreco.py` — preço pago vs mediana
  CATMAT/CATSER do **Compras Dados Abertos** (substitui Painel de Preços); `/api/sobrepreco?codigo=&valor=`.
  Validado live: CATMAT 267758 R\$80 vs mediana R\$48,90 = **+63,6% indício de sobrepreço**; sem amostra=INDISPONÍVEL
  (não fabrica). (3c) `analysis/score_convergencia.py` — soma ponderada DECOMPONÍVEL de indícios (Benford+sobrepreço+
  conflito+red flags+concentração+empresa recente+sócio comum+CEIS/CNEP), 0–100 c/ contribuição por flag; risco de
  **ACHADO ≠ punição**. 15 testes. Sobrepreço/Benford PRONTO no `capabilities.yaml`. **Próximo: Onda 4** (Grafo de
  Poder + Dossiê 360; já há `grafo_cartel.py`/`rede_societaria.py` p/ reusar).
- **2026-06-08 (Onda 4 ✅, commits `5cab17d`+`2bc915e`+`9181084`)** — `grafo_poder.py` (vizinhança BFS local,
  `/api/grafo`, validado: CNPJ real 157 nós) + `dossie.py` (cadastro+sanções+OB+conflito+rede+score→PDF,
  `/api/dossie`, validado: BEST VIGILANCIA score 37 MÉDIO). Fix: grafo só trata CNPJ como nó se existe em fonte.
- **2026-06-08 (Onda 5 ✅ + consolidação SEI→itkava, commit `3cd55d2`)** — `sei_extract`/`sei_corpus`(FTS5)/
  `sei_direcionamento` (varredor R1/R7/R8/R12, `/api/sei/direcionamento`, fonte pncp|sei|ambos). **DECISÃO DO DONO:
  toda leitura SEI passa por UMA porta** (`sei_cdp.ler_processo_sei`) que **delega ao reader itkava/ITERJ**
  (`tools.sei_reader.ler`, login interno sem captcha, vence o WAF de fingerprint); o caminho antigo CAPTCHA/OCR não
  é mais invocado (só os extractors de DOM seguem, reusados pelo itkava). lex/hermes_goal/telegram/ler_sei_lote
  migrados. `/lista` ensina o formato do nº SEI (`SEI-UUUUUU/NNNNNN/AAAA` ou `E-NN/NNN/AAAA`); `ler()` documenta o padrão.
- **2026-06-08 (Onda 6 ✅ — Radar 24/7, commit `904cf72`)** — `radar.py`: watchlist `radar_watch` (alvo+tipo
  cnpj|ug|nome|objeto) + `ciclo()` que, por alvo, busca editais PNCP **EM ABERTO** (preventivo) e, se houver red flag
  do Lex (R7 etc.), **alerta no prazo de impugnação** via Telegram; também flag de OB anômala (reusa `anomalias`).
  Idempotente (`radar_alertas` por alvo+ref+motivo — nunca re-alerta). Rotas `/api/radar/vigiar|status|ciclo`;
  systemd `jfn-radar.{service,timer}` (ciclo 20min). **POR QUÊ assim:** o motor de editais (Onda 2) + red flags
  (2c) já existiam → o Radar é fina orquestração reusando-os, não código novo de coleta. 7 testes (DB temp + rede
  mockada). **DOERJ/GDELT no ciclo:** diferidos (DOERJ vazio no banco; GDELT é Onda 8) — o ciclo cobre o que tem dado real.
- **2026-06-08 (Infra de MODELO + CREDENCIAIS, commit `0f1b8aa` + config/.env/auth)** — **POR QUÊ:** o dono
  questionou se `gemini-2.5-pro` é grátis. **Verificado na web (jun/2026):** os ÚNICOS Gemini com free tier são
  `gemini-2.5-flash` e `gemini-2.5-flash-lite`; **Pro e toda a geração 3.x são PAGOS**; `gemini-2.0-flash` foi
  DESLIGADO em 01/06/2026. → roteador: default/pesado = `gemini-2.5-flash`; `gemini-2.5-pro` (pago) só via
  `forcar_melhor=True` APÓS o Yoda perguntar (`quer_modelo_melhor()` detecta o pedido; nunca troca sozinho).
  Fallback 100% grátis (Mistral "Experiment" tier ~1B tok/mês + Nous `:free`; OpenRouter fora, sem crédito).
  **Rotação de 8 chaves Gemini:** o dono lembrou que existia; **confirmado que JÁ ESTAVA ATIVA** no
  `~/.hermes/auth.json` → `credential_pool.gemini` (8 chaves únicas, rotação nativa `recover_with_credential_pool`
  em 429). As 8 também ficam em `GEMINI_API_KEYS` nos `.env` (backup de recuperação — Hermes usa o auth.json).
  Credenciais enviadas ao Telegram a pedido do dono (auth.json + .env).

## Erros & Aprendizados (honesto — "sempre é importante aprender onde estamos errando")
> O dono pediu para registrar os erros e correções, não só os acertos — para outra IA (e nós) aprender.
- **Premissa falsa sobre o Hermes (corrigida):** afirmei cedo que "Hermes não é python-telegram-bot" a partir de
  greps, sem ler o código. **Errado** — Hermes É PTB (usa `MessageHandler` catch-all + registro próprio de comandos).
  **Aprendizado:** ler o dispatch real ANTES de afirmar; o dono cobrou ("leia os documentos antes de assumir").
- **Acoplamento indevido no skilltree (pego na auto-revisão):** o `reload()` chamava `gen_router_tools.gerar()`
  escrevendo em `~/.hermes/jfn_tools.json` no import → tocava o bot vivo. Removido; `reload()` virou puro.
- **Modelo errado (corrigido após verificar):** escolhi `gemini-3-flash` para o pesado achando ser free — **3.x é
  PAGO**. Corrigido para `gemini-2.5-flash`. **Aprendizado:** verificar preço/free-tier na fonte, não de memória.
- **Bug do contador duplicado (pego por teste):** no varredor (Onda 5) deixei `analisados += 1` duas vezes → teste
  `n_analisados` falhou. Corrigido. **Erro de processo:** numa vez commitei junto de um teste vermelho (grafo Onda 4)
  porque rodei pytest no MESMO lote do commit — **lição:** rodar pytest e só então commitar (commit `2bc915e` foi o fix).
- **Grafo aceitava CNPJ inexistente como nó (pego por teste):** corrigido p/ só virar nó se o CNPJ existe em alguma fonte.
- **Demorei a achar a rotação de chaves:** procurei em `.env`/config antes de olhar o `auth.json` (onde o pool vivia).
  **Aprendizado:** o pool de credenciais do Hermes é o `auth.json`, não o `.env` — checar lá primeiro.
- **2026-06-08 (Onda 7 ✅ — relatório classe mundial, commit `add3e8e`)** — **POR QUÊ Playwright e não WeasyPrint:**
  WeasyPrint exige libs de sistema (cairo/pango) não instaladas; o Playwright já estava no projeto (SEI) → `page.pdf()`
  é o caminho grátis e sem dependência nova. `reporting/render_html.py` (Jinja2+CSS A4: capa, rating card colorido por
  faixa, score decomposto, tabela de proveniência REAL/CACHE+fonte+data, hash SHA-256 no rodapé) + `charts_svg.py`
  (matplotlib→SVG vetorial inline: sparkline, barras de concentração, heatmap P×I do TCU). O `dossie.py` passou a gerar
  o PDF por esse motor (`_gerar_pdf_classe_mundial`), com o FPDF compacto como fallback. Validado e2e: dossiê real → PDF
  60KB com 3 gráficos + rating + proveniência + hash. 4 testes (HTML/SVG determinísticos). **COMO o hash defende a peça:**
  SHA-256 dos dados no rodapé → prova de não-adulteração (padrão OSINT, reforça a defensabilidade perante TCE-RJ/MP-RJ).
- **2026-06-08 (Onda 8 core ✅ — Massare dados grátis, commit `0a0cc78`)** — **POR QUÊ é prioridade:** o Massare não
  tinha "notícia de mercado relevante" nem macro datada. **COMO (100% grátis por classe de fonte):** `focus.py` (BCB/
  Olinda Expectativas via python-bcb — Selic/IPCA/PIB/câmbio, SEM chave; validado: Selic 13.25, IPCA 5.09); `news.py`
  (GDELT DOC 2.0 — manchetes+tom por tema, sem chave; GDELT dá 429 sob chamadas rápidas → reportado honesto, não
  fabrica); `fundamentos.py` (brapi P/L/DY/ROE; PETR4 R$40,89); `calendar.py` (Finnhub key-gated → sem chave =
  INDISPONÍVEL, nunca inventa agenda). 4 rotas `/api/massare/*`. 6 testes (httpx mockado + honestidade). **DIFERIDO:**
  `crypto_ws.py` (websocket 24/7 Binance/Coinbase) é um **daemon** (processo contínuo, não rota) — fica p/ depois;
  o núcleo notícia/macro/fundamento (a prioridade do dono) está pronto. **Modelo:** ver `docs/MODELO-ESTRATEGIA.md`.
- **2026-06-08 (Ondas 9–12 ✅ + validação integral)** — **Onda 9** (`fd6c31a`): teses (narrativa GDELT→ativos→tese
  registrada via learning, cobrada OOS) + validação López de Prado (DSR deflacionado, custos sempre, maxDD) +
  carteira manual. **Onda 10** (`9a0e4a2`): instrumentos de mandato — minutas .docx (requerimento/representação/
  notícia de fato/post) c/ cláusula de honestidade (diligência, nunca condenação) + precedente LexML; python-docx
  pinado. **Onda 11** (`4cd4f9b`): `/api/memoria` (consolida Massare/Lex/Hermes); SIAFE-lock/split diferidos (sweep).
  **Onda 12** (`900fed0`): `grafo_ftm` (export FollowTheMoney, 49 entidades) + OpenSanctions (PEP/sanções key-gated,
  no dossiê). **VALIDAÇÃO FINAL: 92 testes JFN 2.0 verdes** (2m11s). **POR QUÊ as deferidas:** wiring do gateway vivo
  = decisão do dono (não arriscar o bot); SIAFE-lock = sweep rodando; crypto_ws = daemon; chaves brapi/Finnhub/
  OpenSanctions = key-gated (reportam INDISPONÍVEL, nunca fabricam). **Chaves Gemini: 9 chaves / 9 projetos = 9× free
  (dono confirmou projetos distintos); pool deduplicado; verificador `tools.check_gemini_key`.**
