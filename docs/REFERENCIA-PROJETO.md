# JFN — DOCUMENTO ÚNICO DE REFERÊNCIA

> **Único doc de referência do projeto** (decisão do dono). Mantido ENXUTO de propósito (contexto é caro):
> estado vivo + regras + lições duras + retomada. Histórico detalhado vai para o git (commits) e docs por tema.
>
> **Como trabalhar (loop de qualidade máxima):** (1) ler este doc + o código real → (2) pesquisar best-practice →
> (3) planejar com visão global → (4) executar pequeno/isolado/**verificado** → (5) testar e corrigir →
> (6) **gerar o produto real e medir se melhorou/piorou** (PDF entregue, não só MD) → (7) commit + atualizar este
> doc (1 linha no §10). Detalhismo proporcional à complexidade; **testar tudo, nunca às cegas**; ao fim avaliar
> storage/RAM/CPU. **Honestidade sempre:** indício≠acusação, INDISPONÍVEL≠0, nunca inventar número, CPF PF mascarado.

Última atualização: 2026-06-13.

---

## 1. NORTE
JFN = motor + barramento de **auditoria/compliance do Estado do RJ** (TCE-RJ/controle externo). Propósito legítimo:
o dono é **Deputado Estadual** no dever de fiscalizar/combater corrupção (base legal LGPD art. 7º,II/23). Ecossistema:
**JFN** (relatórios/risco) · **Lex** (parecer jurídico) · **Massare** (mercado/previsão) · **Yoda/Hermes** (bot
Telegram = maestro, aciona o JFN pela API `127.0.0.1:8000`). Padrão de saída: Kroll/Deloitte, grátis, honesto.
**Regra-mãe: OB (Ordem Bancária) = verdade de pagamento**, nunca empenho.

## 2. ESTADO VIVO
- **VM Linux GCP**, `~/JFN`. Branch **`feat/lista-limpa`** (não pushado; tudo commitado).
- **`jfn.service`** (user; `systemctl --user restart jfn.service`) → API `127.0.0.1:8000`. **`hermes-gateway.service`** =
  Yoda (`~/hermes-agent`). Ambos auto-start no boot.
- **DB** `data/compliance.db` (1,2G): `ordens_bancarias` (OB 2019-2026, 1,12M, 77% c/ CNPJ; `favorecido_cpf`=CNPJ(14)/
  CPF(11)) + `ob_orcamentaria_siafe` (95k). **UG 133100=ITERJ** (`data/ug_canonico.json`). WAL via cron dom 03:00.
- **SWEEPS = INDIVIDUAIS, escalonados no cron, 1 por vez (cont.25 — o "2-lane serial" foi REVERTIDO: lane contínuo
  segurava Chromium 24h e a sessão única itkava do SEI competia → leitura manual dava 0).** Calibrado à VM real
  **(2 vCPU · 7,8GB · SEM swap)**: `nice -n10 ionice -c2 -n6` (best-effort = qualidade, progride sem starvar),
  bounded (`timeout`), `load-guard ≥4`, single-pass (cron repete; sem `while true`). Scripts:
  **`tools/sweep_sei.sh`** (07/13/19h, itkava SOZINHO) · **`tools/sweep_dados.sh`** (10/16h, endereço+benefícios+
  fachada) · **`tools/cruzador.sh`** (23h, OB↔SEI + concentração-grupo, à noite sozinho) · base **SIAFE 05:00**
  (`siafe_runner diario`) + backfill_enderecos 05:40. Pausas: `data/.pause_sweeps` (tudo) / `.pause_{sei,endereco,
  beneficios,fachada}_sweep`. SIAFE 1 = conta ALERJ-only (pende chave do dono). Backup crontab: `data/crontab.backup.*`.
  ⚠ `pkill` de chromium SÓ órfão (`ppid=1`) — server.py também usa ms-playwright (§8); pkill sempre bracket-safe.

## 3. LLM — ALOCAÇÃO (isolamento de qualidade)
- **Sweep SEI** (triagem + raciocínio de fraude em massa) → **nous `stepfun:free`** (ilimitado/grátis). **Cerebras
  NUNCA no volume do sweep** (não é ilimitado). Modelo de raciocínio → `max_tokens` alto + ler `reasoning` se `content` vazio.
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** (qualidade) + **cerebras** rede de segurança. LLM nos produtos só
  **assíncrono + bounded(45s) + degrada honesto + medido no PDF** (lição V2, §8).
- **Pool free_llm e Yoda** → cerebras + gemini (redundância). Chaves em `~/.hermes/.env`/`~/JFN/.env`/`auth.json`
  (pool gemini 10 chaves c/ rotação; cooldown 12h p/ billing esgotado; nous = rede de segurança grátis).

## 4. PRONTO (produtos · coletores)
**Produtos** (md+pdf+xlsx): **/relatorio** fornecedor (`reporting/inteligencia.py`) — perfil, rede sócio×OB×SEI×
endereço, pagamentos/ano, HHI, contratos, matriz P×I, red flags RF-01..05, sanções CEIS/CNEP via API, OSINT (Querido
Diário), §11-B análise raciocinada + **§II-E investigação fachada/laranja** (via Lex). **/orgao**
(`inteligencia_orgao.py`) — concentração, recorrentes idênticos, raciocínio, Lex de órgão. **Lex** (`lex.py`) — parecer
+ investigação DD (ver §7). **Dossiê** (`dossie.py`). **Massare** (backtest 356k pregões). **Yoda** — `/lista` curado,
"Bom dia" multi-fonte política.
**Refs Massare (vendor, fora do git/Yoda — `~/vendor/`):** **TradingAgents** (TauricResearch, **Apache** → integrável/adaptável; blueprint multi-agente LangGraph: analysts/researchers/trader/risk_mgmt + dataflows + graph + llm_clients) · **FinceptTerminal** (Fincept-Corp, **AGPL-3.0 + comercial** → ⚠ SÓ referência de fontes/analytics, NÃO copiar código p/ projeto público). **agent-skills** (addyosmani) instalado no Claude Code (plugin, melhora a CODIFICAÇÃO; não é produto JFN).
**Mapa de sinais Massare (ref. StocksToBuyNow.ai — SaaS fechado, só conceito; hype sem backtest):** combinar insider (`FMP.insiderTrades`) + **políticos/congresso** (`FMP.senate`) + 13F (`FMP.form13F`) + earnings/surpresa (`earningsTranscript`+`analyst`) + macro CPI/FOMC (`economics`) + técnicos (`technicalIndicators`) + fundamentos EPS/PE/margem (`statements`). **Acesso FMP (verificado 06-11, honesto):** **chave REST grátis** (`FMP_API_KEY` no .env, `massare/fmp.py`) cobre **fundamentos/ratios/key-metrics/earnings/grades/quote/histórico**; insider/senate/13F/macro/técnicos/news = **PAGOS** (402). Via **MCP do FMP**: o macro (`economics` treasury/CPI) e os feeds **"latest" amplos** retornaram dados, MAS as queries **por-símbolo** de senate/insider deram **ACCESS DENIED (plano pago)** — ou seja o MCP **também** respeita o tier; NÃO é fonte grátis confiável dos sinais por-ticker. Conclusão: sem plano FMP pago, o diferencial real disponível é **fundamentos (chave) + macro (MCP)**; senate/insider/13F por-ticker exigem upgrade. `massare/sinais_fmp.py` = coletor DORMENTE pronto p/ ativar quando houver plano/feed. Diferencial honesto do Massare: cada sinal entra **com backtest OOS + proveniência** (≠ hype).
**Coletores/base:** TFE OB (1,1M), SIAFE 1+2 (23 col.), TSE 542k doações, PNCP, correlação OB↔SEI, CEIS/CNEP/CEPIM (API),
GDELT, providers (registry/sanctions/ownership/leaks/links/gazettes/eleitoral — `compliance_agent/providers/`).
**Infra:** pyproject (ruff/pytest), golden numbers, scorecard, pre-commit lint.

## 5. ROADMAP (priorizado)
**P0:** proveniência/INDISPONÍVEL padronizada (modelo `providers/base.Resultado`) · resolução de entidade (Splink,
CNPJ-raiz) → destrava grafo/concentração + matriz+filial · score anomalia ensemble (PyOD) · DuckDB.
**P1:** circuit-breaker no enriquecimento · resolução de entidade · cruzamento SEI×OB + Docling/VLM · Mem0 no Yoda.
**P2:** grafo fornecedor-órgão (GNN) · SHAP no relatório · calibração por UG.
**Investigação DD (em curso):** Loop 1 feito (motor + Lex II-E). **Loop 2 (próximo):** coletor `beneficios_sociais.py`
(PETI/Safra/Seguro-Defeso por CPF, param `codigo`, header `chave-api-dados`) + `/peps` por cpf — só em CPF COMPLETO
(PF favorecida/SEI/TSE; QSA público=CPF mascarado=INDISPONÍVEL). Bolsa Família por-CPF descontinuado (só por NIS).

## 6. GAPS CONHECIDOS
Lex×SEI precisa input SEI real (sweep rodando aos poucos) · Massare hit-rate OOS (mitigado por backtest) · conluio
intra-licitação (PNCP só expõe vencedor) · quarentena de ingestão stale mas base já limpa (baixa alavancagem) ·
god-files (server.py ~2000, inteligencia.py ~1800, lex.py ~1100 — split só oportunístico) · ~~server.py leak de
browser Playwright~~ **RESOLVIDO (cont.31, `afeba84`):** guard de idle fecha o Chromium ocioso após 15min
(env `JFN_BROWSER_IDLE_MIN`, 0=off) e relança lazy; seguro sob `_agent_lock`.

## 7. INVESTIGAÇÃO DE DUE DILIGENCE (fachada/laranja) — o Lex conduz e apresenta
`compliance_agent/investigacao_dd.py::investigar(cnpj, cadastral, pagamentos, usar_rede, geocode)` → hipóteses
`{codigo,titulo,status,nivel,evidencia,fonte,base_legal,peso}` com **status CONFIRMADO/INDICIO/AFASTADO/INDISPONIVEL**
(INDISPONÍVEL≠achado), score+grau com corroboração. Hipóteses: endereço residencial/baldio (markers + Nominatim opc.),
co-endereço, capital ínfimo, recência, situação irregular, porte, sócio único. O **Lex** chama no `_analise` → cada
hipótese vira achado `DD/*` (entra no grau) + seção **II-E** dedicada no parecer (status/evidência/fonte/base legal +
cobertura honesta). Degrada honesto (try/except). Best-practices: TCU; OECD Bid Rigging 2025; ACFE; corroboração ≥2.

## 8. LIÇÕES DURAS (não repetir)
- **⛔ V2 (2026-06-08):** LLM síncrono no hot-path + mudar o que funcionava = regressão. Gerar o **artefato real cedo**
  como baseline; perfeição = perfeiçoar o existente.
- **Auto-pkill / auto-pgrep:** `pkill -f "x"` (ou `pgrep -f "x" && kill`) com o padrão "x" no PRÓPRIO comando se
  auto-mata/auto-casa → usar colchete `x[_]y` ou PID. **Variante do cron-respawn (06-11 cont.18):** o guard
  `* * * * * pgrep -f superv.sh || nohup superv.sh` **casa o próprio sh do cron** (o cmdline tem "superv.sh") →
  nunca faz bootstrap nem respawn de verdade. Fix: **bracket no pgrep** `pgrep -f 'superv[i]sor.sh'` (casa o
  processo real, não o guard) + lançar 1× DIRETO no boot/@reboot. ⚠ o cron do `sei_supervisor.sh` tem o mesmo
  bug latente (só não morde porque o SEI nunca morre); brackear se for mexer nele.
- **Verificar o dono do processo antes de matar/concluir** (o Chromium vivo era do server.py, não de sweep).
- **Reboot-safe lock:** lock por PID não basta (PID reusado após boot parece vivo) → ancorar no boot time
  (`/proc/stat btime`): lock anterior ao boot = obsoleto na hora (`recursos._lock_obsoleto`).
- **Ler a doc da API (swagger) > adivinhar:** param de filtro varia por endpoint (CEIS `codigoSancionado` vs CEPIM
  `cnpjSancionado`); endpoint pode morrer (Bolsa Família por-CPF). Distinguir verificado=False (INDISPONÍVEL) de "limpo".
- **Ler o código real > confiar no handoff/doc** (a doc envelhece; medir o produto/código cedo revela o gap real).
- **Notícia robusta = RSS de seção dos veículos** (URL real), não Google News (`batchexecute` quebrado) nem GDELT (429 da VM).
- **Verificar o PDF ENTREGUE** (3 renderizadores): glifos fora da fonte DejaVu viram tofu; emoji nunca cru p/ DejaVu.
- **⛔ OSM "não localizado" ≠ endereço inexistente** (lição NEW LINK, 06-11): cobertura do OpenStreetMap na
  periferia é ruim; a Rua Tapajós/Meriti existe mas o Nominatim só resolveu COM CEP + prefixo "Rua". Geocode
  precisa tentar variantes (CEP/logradouro) e distinguir `exato` (nº) de centroide da rua antes de afirmar
  baldio/inexistência. Sempre conferir no mapa real (CEP/Google) antes de tratar como achado. INDISPONÍVEL ≠ baldio.
- **⛔ Divergência de município só com geocode EXATO** (036100, 06-11): match coarse (logradouro/CEP) cai em
  cidade errada por fallback do Nominatim → 83 falsas "divergências" (todas exato=False). Só afirmar com o nº resolvido.
- **⛔ Verificação de endereço por Nominatim/OSM = falso-positivo em massa** (auditoria 06-13): os 62 INDÍCIO de
  `endereco_verificacao` eram lugares REAIS difíceis de geocodar (Min. da Fazenda, Praça dos Três Poderes, rodovias,
  "S/N") flagrados só por buraco do OSM. **Substituído pela tríade Google** (`sede_google.py`): a Address Validation
  (`addressComplete`/`validationGranularity`) é o sinal HONESTO de existência; Places dá negócio operante; Geocoding
  ROOFTOP prova o prédio. `verificacao_sede` é a fonte boa; `endereco_verificacao` (OSM) ficou DEPRECADA.
- **⛔ Todo sweep/CLI novo TEM que carregar o `.env`** (bug recorrente, 3ª vez 06-13): `os.environ.get('GOOGLE_MAPS_KEY')`
  é vazio rodando como módulo (no `jfn.service` está no ambiente, no CLI não) → as chamadas viram **no-op silencioso**
  (cotas não baixam, tudo INDISPONIVEL). Padrão `_carregar_env()` no início do `main()`. Pegar no teste ao vivo (a cota
  que não baixa denuncia).
- **⛔ NUNCA buscar imagem (Street View/satélite) na coord `exato=0`** (lição doubt-sender, 06-13): a coord coarse
  do Nominatim (logradouro/CEP, sem o nº) cai EM CIDADE ERRADA por fallback (Araçatuba↔SP, Guapimirim↔Freguesia) →
  a foto não bate o endereço. Para imagem, **geocodificar o ENDEREÇO COMPLETO como string** no próprio Street View
  (ele resolve o nº internamente; metadata confirma cobertura) — nunca reusar a coord podre guardada. Sem cobertura
  no endereço → não enviar (≠ inventar foto de outro lugar). Vale p/ QUALQUER produto que mostre foto de endereço.
- **⛔ Satélite (entorno) NUNCA acusa baldio/barraco** (lição Banco do Brasil, 06-11): coord no nível da rua
  (±100m) + VLM alucinou "barraco 80%" p/ o BB e p/ Polis Informática. Satélite só AFASTA área edificada;
  acusação de baldio/barraco/casa SÓ por Street View (rooftop, requer GOOGLE_MAPS_KEY). Nunca acusar com evidência fraca.
- **⛔ Sweeps concorrentes precisam de `busy_timeout` (cont.21, 06-12):** `sqlite3.connect()` sem `busy_timeout`
  **erra na hora** ("database is locked") se outro sweep segura o write lock → o endereço parava (02:22 e ao
  rodar os 3 juntos). Fix: `connect(timeout=30)` + `PRAGMA busy_timeout=30000` + WAL nos writers (esperar o lock,
  não errar). Validado ao vivo com os 3 sweeps concorrendo. **Todo writer novo do `compliance.db` deve setar isso.**
- **⛔ Teste NUNCA escreve na `compliance.db` de produção (cont.33-34, 06-13):** isolar via env `JFN_DB` +
  fixture `_MODULOS_ISOLAR_DB` no `conftest` (tmp DB descartável). Sintoma da violação: teste lento/hang (lock
  com o `jfn.service`) + linhas "TESTE LTDA" na prod. Ver [[aprendizados/isolamento-db-teste]].
- **⛔ Dedup de responsabilidade SOLIDÁRIA no TCE (cont.21):** o mesmo débito imputado a N responsáveis vem como N
  linhas idênticas em `penalidades_tcerj` (402/910). **Somar infla o erário** (Saúde R$66M bruto → R$28,5M real).
  Contar o débito 1× por evento (processo+valor+sessão), registrar nº de responsáveis. Nunca superestimar (regra-mãe).
- **Vínculo nome↔código que muda (cont.21):** órgão do TCE↔UG re-derivado dos dados vivos (auto-matcher + tipo +
  override mínimo + `depurar()`), NÃO dict chumbado (apodrece). Discriminador de TIPO evita o bug órgão→fundo homônimo.
- **⛔ Comando do Yoda que "não vem legal" → conserte na CAMADA certa:** o roteamento real é a `SKILL.md` em
  `~/.hermes/skills/yoda-commands/<cmd>` (cada `/cmd` carrega a skill que dá `curl` no JFN), **não o system-prompt**
  (`config.yaml` = reforço fraco). **Bug do queue (real, 06-13):** o Yoda DESCARTAVA um pedido NOVO achando que era
  duplicata do que já gerava ("já em processamento conforme as solicitações anteriores" e NÃO rodava o curl — ex.:
  pediu "R c vieira", depois "/orgao iterj" → o ITERJ sumiu). Fix nas skills `relatorio/orgao/dossie`: **cada comando
  é tarefa INDEPENDENTE e ASSÍNCRONA — sempre dispara o curl; "já em processamento" só pro MESMO alvo.** Resolver de
  NOME é código do JFN: `REPLACE(nome,' ','')` p/ casar `'engeprat'`↔`'ENGE PRAT'` (`LIKE %termo%` não casa espaço).
  Skill nova `/dossie` + `/api/dossie` async+push (`_gerar_e_enviar_dossie`, como /relatorio; antes era síncrono).

## 9. PENDÊNCIAS DO DONO
- **✅ Hermes ATUALIZADO (cont.20):** `~/hermes-agent` saltou de 11.416 commits atrás → `origin/main` v0.16.0
  (branch `jfn-updated-2026-06-12`, f3f2386), preservando os **4 commits locais** + as customizações do
  `gateway/run.py` (speaker marking + resposta vazia cortês) — todas reaplicadas LIMPO via 3-way (`git am`/`apply`).
  Deps reinstaladas no venv; gateway estável (NRestarts=0, sem crash). Backup: tag `jfn-backup-pre-update-2026-06-12`
  + patches em `~/hermes-jfn-customizacoes/`. ⚠ **AÇÃO DO DONO:** há um **2º poller usando o mesmo bot token fora
  desta VM** (app desktop? outro deploy?) — conflito `getUpdates` PRÉ-EXISTENTE (10 conflitos já às 03:00, antes do
  update). **Desligar a instância duplicada** para o Yoda parar de competir pelo Telegram. (O update NÃO causou isso.)
  Reaplicar customizações após futuros `hermes update` (os patches estão preservados).
- **✅ Yoda RESOLVIDO (cont.21, 06-12) — era o DESKTOP do dono.** Mensagens duplicadas/triplicadas = 2º poller
  do bot disputando `getUpdates`. Diag provou externo (gateway parado → ainda 409). O dono fechou o **Hermes
  Desktop** e os conflitos **cessaram às 12:51:55 UTC** (24 nos 20 min anteriores → 0). Update do hermes INOCENTE
  (1º conflito 01:37 precede o update 03:07–03:39 em ~1h30). **Sem fix de token necessário.** Recidiva futura:
  `bash tools/rotate_telegram_token.sh '<token>'` após `/revoke` no BotFather. (Histórico abaixo, cont.20.)
  **[cont.20 — contexto preservado]** começou **01:37:36** (166 conflitos vs 1 em dias normais); VM 100% limpa
  (1 só hermes por `ps`/`ss`/diag; sem docker; branch do update nunca pushado; bot sem webhook). Externo às **01:37 UTC
  (22:37 BRT de 11/06)** — dono confirma que NÃO é o desktop dele = outro dispositivo com o token. **FIX a 1
  comando:** BotFather `/revoke` → `bash tools/rotate_telegram_token.sh '<token>'` (valida getMe, backup+troca em
  ~/.hermes/.env **e** ~/JFN/.env, religa o gateway, confirma 0 conflito; mata o externo na hora). Agente/envio OK.
SIAFE 1 (liberar chave p/ todas as UGs) — **sweep PAUSADO até a chave (06-11 cont.17):** flag `data/.pause_sweep_1`
+ cron de respawn `* * * * * siafe_supervisor.sh` REMOVIDO (não funciona sem chave). Reativar: `rm data/.pause_sweep_1`
e recolocar a linha do supervisor no crontab. (SIAFE 2 incremental 05:00 segue ativo, funciona por login.) · SEI de
outras unidades (acesso do itkava) · repor/rotacionar billing das chaves Gemini sem saldo e renovar tokens OAuth "AQ."
manuais quando expirarem (caem no nous até lá).

## 10. CHANGELOG (1 linha/sessão — detalhe no git)
- **06-13 cont.36 (loop de qualidade, isolamento de DB):** continuação do loop de melhoria com subagentes em
  background. **Unificação de resolução de DB:** `dossie/grafo_poder/lex_conflito` hardcodavam `data/compliance.db`
  e ignoravam `JFN_DB` (achado pelo smoke do Dossiê, que precisava de `monkeypatch.setattr` gambiarra) → agora
  resolvem via `_resolver_db()` (env `JFN_DB`→`DB_PATH`); produção inalterada (OB 1.121.301 antes/depois), smoke
  simplificado, 2 passed (`727e61d`). **Sweep de sede saudável:** 9.602 sedes, distribuição honesta AFASTADO 78% /
  INDÍCIO 13% / INDISPONÍVEL 8%; para limpo em time-bound (resumível), cron retoma 2/2h; cota geo/addr 966 restante,
  `herda_cep` wired. **Remoção de código morto:** 6 funções 0-callers (132 linhas) + imports/constantes órfãos
  (`ca7446e`). **`/api/compliance/buscar` (FTS) — bug achado:** os `buscar_*_fts` mascaravam `no such table` como
  "0 resultados" (`except: pass`), e `criar_indices_fts()` é ÓRFÃ (nunca chamada no bootstrap) → o endpoint retorna
  vazio para TODO termo (não só MGS; e MGS é favorecido de OB, fonte que o FTS nem indexa — só contratos/doerj/alertas).
  Fix de honestidade: trocado o `pass` por log que distingue índice-ausente (`bd73959`). **FIX FUNCIONAL FEITO
  (cont.37):** (1) `init_db` chama `criar_indices_fts` (import tardio + try/except, não derruba boot); (2) `fts._get_conn`
  passou a resolver `JFN_DB` (era `DB_PATH` fixo, furava isolamento) + `busy_timeout=30000` + guard de existência
  (no-op se já criado, pois `init_db` roda por request); (3) `/buscar` ganhou chave `fornecedores` via `buscar_candidatos`
  → **q=MGS agora retorna MGS CLEAN (R$136M) e MGS BRASIL** (antes: vazio). Commits `203612a`/`93ac556`/`98d072e`.
  **Honestidade provada em prod:** logs mostraram "índice ausente... rode criar_indices_fts" (não mais silêncio).
  CLAUDE.md: bloco do gitnexus reinjetado pelo `analyze` e MANTIDO a pedido do dono.
- **06-13 cont.38 (janela 23:55 sem sweep — fecha as pendências do cont.37):** (a) **`fts_*` materializadas em prod**
  (`criar_indices_fts()` rodou sem lock) → `/buscar?tabela=contratos` responde em **0,05s** (FTS vivo, fim do
  "índice ausente"). (b) **Latência do `fornecedores` diagnosticada certo:** ~6-12s mesmo SEM sweep (intrínseco, não
  contenção). Minha nota anterior de "índice em `favorecido_nome`" estava ERRADA — B-tree não cobre `LIKE '%termo%'`
  (substring + `lower()`). Fix correto: **tabela-resumo `favorecido_resumo`** — há só **73.881 favorecidos distintos**
  vs 1,12M OBs (15×), então o mesmo LIKE numa tabela de 74k linhas cai pra sub-segundo. Otimização de `buscar_candidatos`
  (alto risco — é o resolver do `/relatorio`) com FALLBACK seguro (usa a tabela só se existir; senão cai no scan
  atual). **FEITO:** `favorecido_resumo` (73.881 linhas; `favorecido_nome`=display, `nome_match`=todas as grafias
  do CPF concatenadas, `nome_ns`=só-alfanumérico p/ o fallback sem-espaço — 949 CPFs têm >1 grafia); `buscar_candidatos`
  → **7,4s → 0,04s** (~150×), paridade idêntica nos termos específicos (1 efeito-de-borda benigno do `LIMIT 50` em termo
  genérico). Commits `f710c4e`+`a8c2223`. **Wiring (à prova de stale):** refresh no `siafe_runner.atualizar_diario`
  (cron 05:00) + cron de fallback decoupled `45 5 * * *` (`tools/refresh_favorecido_resumo.sh`, auto-cria se faltar,
  VM-safe). Refresh usa `BEGIN IMMEDIATE`+`busy_timeout` (robusto sob sweep; leitor vê snapshot até o commit). FTS:
  triggers auto-sincronizam + `init_db` recria no boot. **Sweep pausado durante a obra (autorizado) e recomeçado ao fim.**
- **06-13 cont.35 (comandos do Yoda):** comandos `/cmd` ficaram **tappáveis no `/lista`** (auto-link do Telegram);
  **fix do resolver `engeprat`** (`REPLACE(nome,' ','')` casa `'ENGE PRAT'`); skill **`/dossie`** + endpoint
  **`/api/dossie` async**; **queue tratado na SKILL.md** (não no system-prompt) — o Yoda descartava pedido novo
  como duplicata do que já gerava. Commits `900b9a7` (lista) · `7456f49` (engeprat) · `a37a47f` (dossie async +
  skills queue/dossie no `~/.hermes`, fora do git). Simulação do dono ao vivo achou os bugs; lição da camada certa em §8.
- **06-13 cont.34 (goal "perfeito", QA + cota):** **QA geral + eficiência de cota + wiring + fixes.** (1)
  **Sweep eficiente:** Places era chamado em **99%** (esgotaria a cota mais valiosa na cauda barata antes dos
  grandes, já que varre menor→maior) → `_suspeito` só gasta Places em residencial/>R$100k/geo-não-fixado →
  **0.99→0.20 places/row**; dedup por prédio confirmado (1 geocode/prédio). **Cron** `sweep_sede.sh` (flock,
  a cada 2h) finaliza a base sozinho. (2) **QA da suíte (1040 passed/11 failed):** TODAS explicadas — 7 eram
  **lock de DB por rodar junto do sweep** (consertado com **busy_timeout no engine SQLAlchemy**, lição §8),
  2 fixture obsoleto de /orgão (`n_fornecedores`, corrigido), 2 ambiente (chrome-9222: sei_cdp vira skip;
  goal_agent **hang consertado** via `usar_llm=False`, mas segue pesado por usar a `compliance.db` de produção).
  **Zero regressão de produto.** (3) **Documentos testados de verdade:** /relatorio HEBARA → MD+PDF(14pág)+XLSX+
  Lex, renderiza Kroll/Deloitte sem tofu, seção II-E + veredito humano + rating. (4) **Wiring:** o campo
  "Realidade da sede" do relatório agora **prefere `verificacao_sede` (Google)** com fallback OSM. ⚠ Rodar a
  suíte completa SEMPRE com o sweep pausado (`touch data/.pause_sede_sweep` + matar o worker) senão dá falso-failed.
- **06-13 cont.33 (goal grande, APIs Google ligadas):** **⭐ VERIFICAÇÃO DE SEDE VIA GOOGLE — substitui o
  Nominatim** (que dava INDÍCIO falso: Min.Fazenda/Praça dos Três Poderes — auditoria confirmou). Dono ligou
  **Geocoding + Address Validation + Places (New)** (cada 9999/31d free tier). **`compliance_agent/sede_google.py`**:
  3 coletores quota-guarded + `verdict_de_sinais` honesto (negócio operante DA empresa afasta; ROOFTOP=existe;
  Address Validation residencial=indício; ausência de perfil≠prova; rodovia/'S/N' não é fachada). **`tools/
  sweep_sede_google.py`**: varre menor→maior R$ (pedido do dono), **dedup por PRÉDIO** (12.801 distintos;
  empresas no mesmo prédio herdam 1 verificação), overflow herda de prédio-irmão no CEP (9.190 CEPs), Places só
  nos suspeitos, resumível, VM-safe, quota-bounded. Grava `verificacao_sede`. **DD**: novas hipóteses
  **H-END-RESID-GOOGLE / H-SEM-PERFIL / H-ENDERECO-INVALIDO** (gated por veredito humano). **Cota cabe no mês:**
  ~12,8k prédios > 9999, então building-dedup + CEP-fallback cobrem ~100% (sweep atravessa o mês, resumível).
  **Heading da foto** (Geocoding→prédio→bearing) corrige o ângulo (NRTT). **34 testes novos** (32 coletor mockado
  via subagente + 2 DD) + 83 do grupo verdes. **Sweep RODANDO** (background, ~30 prédios/min): 1ºs 230 = 83%
  AFASTADO/13% INDÍCIO/4% INDISP; **Min.Fazenda agora AFASTADO** (bug consertado). Browser-screenshot REMOVIDO
  (WebGL/swiftshader travava a VM de 2 vCPU). **Pendência:** sweep terminar a base (resume mensal na cota).
- **06-13 cont.32-c (dono pegou bug):** **FIX do doubt-sender — foto não batia o endereço** (`d07e291`). O dono
  revisou o 1º lote e TODAS as fotos estavam erradas. Causa: eu buscava o Street View na coord guardada
  (`endereco_verificacao`, `exato=0` = Nominatim coarse/fallback) que **cai em cidade errada** (Araçatuba↔São
  Paulo, Guapimirim↔Freguesia, Mesquita↔Centro) — violei a minha própria §8 (OSM coarse engana). Fix: `foto_rua`
  passa o **endereço completo como string** ao Street View, que geocodifica o nº internamente (funciona mesmo com
  a Geocoding API negada na chave) → coord/pano CORRETOS; metadata confirma cobertura antes do download pago; sem
  cobertura → não envia; legenda traz data do pano + link do mapa (removida a linha falsa "±100m"); Mapillary
  removido. Verificado 5/5 (coords certas + fotos conferidas a olho). Lote corrigido reenviado (msgs 3771-3775).
- **06-13 cont.32-b (goal, "faça tudo isso"):** **⭐ DESMASCARAMENTO DE CPF DE SÓCIO — 3 camadas** (pedido do
  dono; refs **osint-brazuca**/`fernandobortotti/CPF-Tools` + **OSINTKit-Brasil**). Descoberta: o JFN **já tinha o
  método osint-brazuca** em `resolucao_cpf.py` (`gerar_cpfs_da_mascara`=os 1000 candidatos dos 6 díg centrais +
  `confirmar_cpf`=anti-homônimo + `resolver_multi`=favorecidos-PF/TSE/SEI). **(A)** `tools/resolver_cpf_socios.py`
  aplicou o resolver a TODOS os 27.729 sócios mascarados → **1.190 resolvidos (4,3%)** gravados em
  `socios_fornecedor` (fav_pf=482, tse=704, sei=4) — confirma a parede interna ~4%. **(B) FUSÃO DE MÁSCARAS
  folha×QSA** (nova, 100% legal): a folha mascara pos.3-8 (`XX######XXX`) e o QSA pos.4-9 (`***######**`) →
  cruzando por nome+dígitos consistentes (a) acha **sócio que é SERVIDOR público** (7 achados, ex.: PEDRO DANIEL
  STROZENBERG — indício de conflito/laranja → nova hipótese **H-SOCIO-SERVIDOR** na DD) e (b) revela pos.3-9 (7
  díg) estreitando 1000→~100 candidatos. **(C)** `compliance_agent/cpf_externo.py` + `tools/desmascarar_cpf_
  externo.py` (DORMENTE/GATED, por alvo, default dry-run): motor gerar→consulta externa nome↔CPF→`confirmar_cpf`,
  2 modos (cpf→nome tipo situação-cadastral/Receita; nome→cpf judicial Escavador/Jusbrasil/TRT) + provider
  `ProviderSituacaoCadastral` best-effort honesto (captcha/bloqueio→INDISPONÍVEL); usa o estreitamento da fusão.
  **Honestidade/LGPD:** match 1:1 obrigatório, CPF resolvido = uso INTERNO (produto mascara), sem confirmação →
  INDISPONÍVEL, ToS respeitado, volume baixo. **23 testes novos verdes (17 resolucao_cpf + 6 cpf_externo); 60 do
  grupo CPF/DD/fachada sem regressão.** Provado ao vivo: dry-run no CNPJ 00343941000128 estreitou Strozenberg p/
  100 candidatos. **Pendência do dono:** decidir a fonte externa real (TRT expõe CPF completo? confirmar) p/ ligar
  a camada C nos alvos (Vieira/4 fortes/MUV).
- **06-13 cont.32 (goal "continuar"):** **⭐ DOUBT-SENDER DE FACHADA POR TELEGRAM** (pedido do dono, cont.31-d).
  `compliance_agent/fachada_doubt.py` + `tools/doubt_sender_fachada.py` (envia) + `tools/registrar_vereditos_
  fachada.py` (captura). Quando a verificação de endereço fica em **DÚVIDA** (`endereco_verificacao` INDISPONIVEL/
  VLM indeterminado — não decide baldio/residencial/sede real), seleciona as dúvidas com **perfil de fachada**
  (exclui órgãos/bancos por blocklist + exige **marcador residencial** no endereço, ranqueado por R$ OB recebido),
  busca a **foto Street View** do ponto e **envia foto+contexto honesto ao Telegram do dono** (sendPhoto +
  código curto). O dono responde `<código> fachada|real|pular`; a captura é **PASSIVA** (lê `~/.hermes/state.db`
  do Yoda, casa o código) — **sem 2º bot, sem editar o Hermes vendored, sem conflito getUpdates** (lição §9). O
  veredito humano vira **VERDADE na DD** (`investigacao_dd` → hipótese `H-END-HUMANO` CONFIRMADO/AFASTA, override
  do automático). **Lição §8 reconfirmada (artefato real cedo):** dry-run mostrou que rankear só por R$ traz
  Min.Fazenda/Banco do Brasil (legítimos) → adicionei blocklist+filtro residencial; e que o CLI não carregava o
  `.env` p/ `GOOGLE_MAPS_KEY` (foto vinha "sem cobertura" embora SV-meta=OK) → `_carregar_env()`. **19 testes
  novos verdes + 48 DD sem regressão.** SV fetch provado ao vivo (Copacabana 69KB; 4/4 candidatos com foto 52-86KB).
  **Smoke test real:** msg 3750 ao dono (TERAPIA INTENSIVA NEONATAL, R$18,7M) + pendência registrada + recorder
  lê o state.db real (249 msgs, cursor inicializado). **⚠ NÃO posto em cron** (cadência/volume = decisão do dono):
  ativar com `*/30 * * * * cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.registrar_vereditos_fachada` (captura,
  leve) + envio diário `tools/doubt_sender_fachada --limite N`. Upgrade opcional: 2º bot dedicado (UX com botões
  inline) se o dono quiser evitar o eco do Yoda nas respostas.
- **06-13 cont.31-d (segue):** **Cobertura total dos sweeps + consolidação de ferramentas.** (1) `tools/sweep_full.sh`
  (`69edd51`): drena o universo INTEIRO — endereço (gap ~4,5k) + fachada DD (TODAS as 151 UGs, `--limite 0`, não só
  cauda) + sócios/CPF (resolver). VM-safe (nice/ionice, load-guard≥3, slices bounded, SERIALIZADO, **lock flock**
  single-instance, time-bounded MAXH=6h, resumível via tabelas+cache+`data/.sweep_full_fachada_done`). **Está
  RODANDO** (nohup; se morrer no fim da sessão, relançar `bash tools/sweep_full.sh 6` continua de onde parou).
  (2) **CPF de sócio — verdade honesta:** teto ≈ **1.081** (TSE 624 + favorecidos-PF 457); QSA público mascarado
  por LGPD = parede. `ingerir_cpf_oficial` é DORMENTE (depende de base oficial que o dono pode não obter — NÃO é
  alavanca). Único crescimento legítimo = docs contrato-social/habilitação no SEI (sweep lento; cache hoje é
  financeiro → só 10 em `sei_cpf`). NÃO chega a ~100%. (3) **gitnexus** instalado (CLI 1.6.7 + índice 126M: 8155
  símbolos/20651 arestas) e agora **ÚNICO MCP de código** — codegraph REMOVIDO do `~/.claude/mcp-local.json`
  (backup `.bak`; binário inerte em disco); graphify mantido (escopo qualquer-input). (4) Guard de idle do browser
  SIAFE (server.py) OK; **Chrome 9222 = `chrome-jfn.service`** (systemd Restart=always, NÃO leak — reaper revertido).
  **>>> PRÓXIMA SESSÃO (pedido do dono):** construir o **doubt-sender de fachada por Telegram** — quando a DD de
  fachada ficar em DÚVIDA num endereço (não decide baldio/residencial/sede real), buscar **Street View**
  (`GOOGLE_MAPS_KEY` ✓ no .env) e **enviar a foto+contexto ao Telegram do dono** (envio via `tools/enviar_sessao_
  telegram.py` + TELEGRAM_BOT_TOKEN/CHAT_ID ✓), registrar a resposta humana (fachada/legítimo) como veredito.
- **06-13 cont.31-c (segue):** **SWEEPS À PROVA DE CRASH + todos provados verdes** (pedido do dono: "os sweeps
  não podem dar crash"). O SEI sweep morria com Node EPIPE não-tratado quando o `timeout` matava o browser à
  força. Fixes: (`1664aac`) sessão de browser sob try/except → morte de browser/pipe vira saída LIMPA logada,
  `b.close()` defensivo, `_browser_morto()` aborta sessão em vez de insistir, backstop de processo no `main()`;
  (`fd3ebfb`) **SIGTERM gracioso** — `timeout` agora fecha o browser limpo (mata o EPIPE). **+ fim do exit
  silencioso** nos `.sh` (todo `.pause_*` loga; cruzador loga rc do DuckDB) → resolve a anomalia do cruzador 23h
  (era o `.pause` saindo sem traço). **12 testes** (crashproof + idle-guard). **Provados AO VIVO 02:00-02:08:**
  SEI rc=124 (timeout=bound, +17 cdp 848→865) · CPF rc=0 (1ª vez via orquestrador, `sei_cpf` populada) ·
  cruzador correlacao+concentração rc=0/fim (12/60 UGs) · endereço/benefícios/fachada rc=0/fim. VM estável
  (load pico transitório 3,9 do DuckDB esfriando, nunca OOM, ≥5,6GB livres). Limpei chromium leftover do sweep
  pré-fix; idle-guard do server.py reapou às 01:33 ok. ⚠ **Chrome 9222 do Hermes** (pid 1086, `/tmp/chrome-jfn`)
  vivo ~35h ocioso = candidato a guard de idle próprio (outro subsistema; não mexido).
- **06-13 cont.31-b (segue):** **GUARD DE IDLE DO BROWSER** (`afeba84`, fecha o gap do §6). O Chromium do
  server.py vivia 24h ocioso (~200MB presos numa VM sem swap — diagnosticado ao achar 1 chrome de 20,5h com só
  16s de CPU). Reaper async encerra após 15min sem uso (env `JFN_BROWSER_IDLE_MIN`, 0=off) + relança lazy no
  `get_agent()`; seguro sob `_agent_lock` (re-checa o ócio após o lock). Login SIAFE best-effort unificado em todo
  launch fresco. 4 testes + verificado no jfn.service (boot OK, API 200, guard ativo). **Também:** restart limpo
  liberou o Chromium preso de 20,5h a pedido do dono (ocioso confirmado antes). **Sweeps checados:** SEI 848 cdp
  (progredindo, +145 em 06-12), benefícios 23.691 (completo), sem pausa, crons disparando. Anomalia leve a olhar:
  cron do cruzador 23h disparou mas não deixou "início" no log (não foi load-guard nem pausa).
- **06-13 cont.31 (goal, agentes):** **⭐ 30/30 DETECTORES DE LICITAÇÃO COMPLETOS** (`cefeee6`). Os 13 cards que
  faltavam, em 4 lotes de subagentes VM-safe (ruff+pytest isolados por arquivo, eu integrei o `__init__`):
  **J5** digitais compartilhadas, **J6** subcontratação cruzada/consórcio, **J7** inabilitação seletiva ·
  **E4** visita técnica, **E5** edital iterado, **E6** pontuação dirigida (simula troca de vencedor) ·
  **X1** crescimento aditivo (teto art.125→crítico objetivo), **X2** prorrogação perpétua, **X3** execução
  financeira (tríade SIAFE), **X4** carona abusiva ARP (art.86), **X5** jogo de planilha (Pearson inline),
  **X6** entrega fantasma (gera roteiro de diligência) · **C6** vínculo político-financeiro (TSE, conservador/
  multiplicador). Todos no schema §1.4 (âncoras, rubrica fechada LLM-opcional, exculpatória, nao_avaliavel≠0).
  REGISTRO=26; orquestradores `rodar_edital`(+E4-6)/`rodar_julgamento`(+J5-7)/`rodar_fornecedor`(+C6)/novo
  **`rodar_execucao`**(X1-6). **129 testes novos + fix fixture obsoleta (n_fornecedores) → 254 verdes.**
  **VALIDAÇÃO em DADO REAL (sem browser):** rodei o pipeline completo sobre o cache SEI Vieira
  `data/sei_cache/cdp_SEI_510001_000876_2024.json` → 21 detectores `nao_avaliavel` HONESTOS (não quebra, não
  inventa). **⚠ CORREÇÃO de premissa do handoff:** `510001/000876` **NÃO é o edital Vieira** — é um processo de
  *Acompanhamento Especial* (só Despachos/E-mails/Ofícios; sem habilitação/lotes/valores/propostas), por isso
  nao_avaliavel é o ground-truth correto. Varredura dos 848 cdp do cache: dominado por **execução financeira**
  (OBs/Programação de Desembolso/Liquidação) e admin — **não há edital/contrato com tabelas** no cache para
  exercitar os detectores de planejamento/edital/julgamento. **Próximo gargalo REAL = INPUT, não detector:** ler
  via SEI o processo do EDITAL/CONTRATO Vieira correto (número a achar; browser/itkava, VM-heavy, owner/dado) +
  coletor PNCP de propostas p/ alimentar o `ctx`. O coletor `montar_ctx_de_sei` mira edital (modalidade/habilit/
  lotes/propostas); para a execução financeira já cacheada, X3 precisaria de um extrator da tríade SIAFE do SEI.
### Histórico condensado (cont.≤30 — detalhe completo no git)
- **06-12 cont.30:** QA dos produtos + 6 correções (`02f16e4`..`306518f`): enriquecimento+retry+cache, score recalibrado, §1-G TCE Cidades 660100, off-by-one. 224 testes verdes; obsidian-save da sessão.
- **06-12 cont.29:** Pipeline de detectores de licitação 17/30 nas 5 fases (P1/2/4/5, E1-3, J1-4, C1-5, P3); orquestradores `rodar_*`; ~140 testes. Spec `notas/detectores-corrupcao-licitacoes-v2`.
- **06-12 cont.28:** Detectores operacionais e vivos no produto (`01ccd00`): J1/P3/C1-5 wrappers + §1-I Painel de detectores no relatório de órgão (`d2869ea`). 54+ testes.
- **06-12 cont.27:** ⭐ SEI port funcionou (`59360d0`) — `_ler_cracked` lê processo de outra unidade (510001 Vieira) sem regredir ITERJ. Framework de detectores (`380a967`): schema base + P4 fracionamento; 33 testes.
- **06-12 cont.26:** Manual de detecção de corrupção em licitações (vault) + 4 builds (§1-H concentração-grupo `897edb3`, Lex exculpatório+destinatário `2317395`, priorização `034b062`). ⭐ SEI cracked (mecânica da busca itkava abre outra unidade) + OCR de docs digitalizados (`189d117`/`fdcd9cf`); reader em estado seguro (`fa16348`). ~38 testes.
- **06-12 cont.25:** Sweeps rearquitetados — "2-lane serial" REVERTIDO p/ sweeps individuais escalonados (VM 2vCPU/7,8GB/sem swap): nice/ionice, bounded, load-guard=4, 1-por-vez. `cc7aaa0`.
- **06-12 cont.24:** SEI entendido/documentado (itkava lê TODAS as unidades, output=`cdp_*.json`); grupo Vieira sócio-elo + tier-2 (+5 candidatos); 4 fortes do Fundo TJ end. residenciais (H-END-RESID); context-economy (memória→vault, MCP lean).
- **06-12 cont.23:** Migração da memória `.claude`→vault Obsidian (digest SEMPRE-ON no SessionStart); ⛔ queda da VM diagnosticada (DuckDB+2 sweeps sem swap=OOM → lição vm-nao-crashar); grupo Vieira quantificado R$543M/56,9%; varredura 30 maiores UGs.
- **06-12 cont.22:** Novo detector `grafo_cartel.concentracao_por_grupo(ug)` (concentração oculta por grupo, union-find; 660100=57%/R$543M, `756c58d`); reconciliação honesta (H-PEP/H-BENEFICIO/PyOD/DuckDB/CAGED/OpenSanctions já existiam; único gap P0=Splink); regra de roteamento de memória.
- **06-12 cont.21:** Yoda resolvido (poller externo=Hermes Desktop); §1-G Sanções TCE-RJ no relatório de órgão (`6017ede`, vínculo TCE↔UG re-derivado + dedup de responsabilidade solidária); fix sweep `database is locked` (busy_timeout+WAL); docs leves (53→33 + INDEX); segundo cérebro Obsidian; +12 testes. (cont.) sweeps 2-lane serial; módulo `relacoes.py` (grupo Vieira R$189M); sobrepreço `precos_extract.py`; coletor ALERJ; acúmulo de cargos; acima do teto; SEI pensante `sei_recomendacoes.py`; caso MUV São Gonçalo; recon folha RJ. +38 testes.
- **06-12 cont.20:** Sweep detached de benefícios dos sócios no ar (`socio_beneficio`+`beneficios_sweep.py`+supervisor bracket; universo 23.691 mascarados); `resolucao_cpf` com índice (VM-safe); fix Bolsa Família `anoMesReferencia`. (cont.) relatórios Fase 1 (benefícios surfados nos 3 produtos `beneficios_view.py`) + Fase 2 (fornecedor §1-C a §1-F: TSE/capital/rodízio/conflito pessoal; commits 6e50b15/c75c02b/d2e023b/b62fe6b/4d7c918). Cobertura CPF ~4,7%. 106 testes.
- **06-12 cont.19:** Imagem de rua (Mapillary prioritário + Street View fallback capado 9999/31d; casebre precede edificado-OSM) + benefícios 3→6 (+Bolsa Família/BPC/Aux.Emergencial). Pendência: sweep só dispara visual no geocode `exato`. ⛔ NUNCA leak/detetive de CPF. +8 testes.
- **06-11 cont.18:** Relatórios de órgão/fornecedor enriquecidos (§1-D triagem DD + rodízio, §1-E realidade do endereço; veredito "a empresa é real?"); FIX `backfill_verificacao_endereco` quebrava desde cont.15; sweep de endereços detached. Suíte 465 passed/5 failed (pré-existentes/ambientais).
- **06-11 cont.17:** ⭐ Edge do Massare virou ≥0 — `engine_regime4.py` (4 regimes + drift-aware; OOS +0.0006/+0.0005/+0.0070); produto real edge médio +0.0027 (356.655 pregões); motor de produção trocado p/ regime4. `825d0f5`.
- **06-11 cont.16:** 3 specs greenfield avaliadas (~70% já existia; geocoding=regressão); novo `rodizio_temporal.py` (rodízio de cartel OCDE, 20 UGs com indício); FMP chave grátis (fundamentos BR+US); ensemble regime-condicional (edge OOS ainda neg.). 9 commits/32 testes.
- **06-11 cont.15:** Verificação de endereço endurecida (divergência/baldio só com geocode `exato`); resolução por imagem (satélite Esri AFASTA, Street View acusa); dono pausou o visual. +8 testes.
- **06-11 cont.14:** Geocoder corrigido (CEP+variantes, distingue `exato`); verificação de endereço de TODAS as fornecedoras via backfill diário (cron 06:45); DD Fundo 036100 → 64 candidatos (8🔴/56🟡); back-off OSM. +5 testes.
- **06-11 cont.13:** Verificação de realidade do endereço (`verificacao_endereco.py`: geocode-match + edificação/baldio Overpass + hook imagem→VLM); sweep `endereco_sweep --todos` resumível. +6 testes.
- **06-11 cont.12:** Alvo 2 — triagem de DD priorizada por órgão (`investigacao_orgao_dd.py`); achado: fachada/laranja mora na CAUDA, não no topo. 3 testes.
- **06-11 cont.11:** Alvo 1 fechado — `beneficios_sociais` no motor DD+Lex (H-PEP + H-BENEFICIO); br-acc agregado → ponte CPF mascarado middle-6 (`resolucao_cpf.py`). +16 testes.
- **06-11 cont.10:** FIX conceitual OB≠contrato≠processo (`cardinalidade_contratual`, `4fff8bd`); coletor benefícios sociais+PEP `beneficios_sociais.py` (DD Loop 2 base).
- **06-11 cont.9:** Lex seção II-E + sweeps reboot-safe (`recursos` boot-time + @reboot). `8c6c7e4`,`4981323`.
- **06-11 cont.8:** motor `investigacao_dd` (fachada/laranja Loop 1) + wiring no Lex + BrasilAPI capital/porte. `63070cd`.
- **06-11 cont.7:** bom dia multi-fonte política; CEIS/CNEP corrigido (3 bugs); relatórios raciocinados + OSINT Querido Diário.
- **06-11 (1–6):** Cerebras em todos os pools; /orgao rico; SEI sweep destravado; rotação de chaves LLM (cooldown 12h); erros do Yoda corrigidos.
- **06-09:** 23 loops de benchmark (ruff 733→37, 4 bugs reais); frente SEI (reader, sei_sweep/sei_ficha); /UG + busca de órgão; Lex de órgão; glifos PDF; este doc criado.
- **Anterior:** SIAFE 1+2 sweeps supervisionados + correlação OB↔SEI↔CNPJ; JFN 2.0 (12 ondas); Yoda/Hermes na VM.

## 11. ⏯️ RETOMADA (sessão nova: "continue pelo docs/REFERENCIA-PROJETO.md e tasks/todo.md")
> **Estado vivo da cont.20 em `tasks/todo.md`** (CPF engine completa, SEI CPF sweep, suíte 8→2, relatórios
> Fase 1/2/3). **2 itens travados que dependem do DONO** (não-autônomos): **(1) Yoda** — poller externo em outra
> máquina (rode `bash tools/diag_telegram_poller.sh` p/ confirmar; fix: BotFather `/revoke` → token novo no
> `~/.hermes/.env` → `systemctl --user restart hermes-gateway`). **(2) CPF em massa** — toda fonte grátis mascara;
> passar CSV `nome,cpf` p/ `python -m tools.ingerir_cpf_oficial` (valida DV + confirma contra a máscara).

> **⚠ ESTADO REAL (cont.22 — auditoria do código):** a lista numerada abaixo está MUITO desatualizada. JÁ EXISTEM
> (não reconstruir): item 1 (**H-PEP/H-BENEFICIO** wired no `investigacao_dd.py` linhas 453-473) · item 2 (**`investigacao_orgao_dd.py`**
> = o "investigar órgão" batch, com CLI) · `cardinalidade_contratual` · **PyOD** ensemble · **DuckDB** · **CAGED/RAIS** ·
> **OpenSanctions**. ALVO Nº1(c) (agregado de benefícios no relatório) **FEITO** (testes verdes). **Único gap real do
> roadmap P0 = Splink** (entity resolution). **NOVO (cont.22):** `grafo_cartel.concentracao_por_grupo` (concentração
> oculta por grupo; achou MUV/Vieira 57%/R$543M na 660100). **Trabalho autônomo restante** = operar o produto
> (rodar `investigar_orgao`/`concentracao_por_grupo` nas UGs e gravar casos no vault) + Splink. O resto está bloqueado
> no DONO (SEI de outra unidade, Street View/`GOOGLE_MAPS_KEY`, CPF em massa).

**Branch `feat/lista-limpa`, tudo commitado, serviços/sweeps vivos.** Instruções permanentes do dono:
1. Melhorar o projeto INTEIRO em **loops de qualidade máxima** (metodologia no topo deste doc).
2. **Testar tudo, nunca às cegas**; medir o **produto real** (PDF entregue) antes/depois.
3. **Honestidade** (§topo). **Isolamento de LLM** (§3). **Sweeps vivos** respeitando CPU (não rodar sweep+suíte+
   Playwright juntos — a VM já caiu por isso).
4. **Um só doc** = este, enxuto, 1 linha/sessão no §10. Detalhe no git.
5. Ao FIM de cada loop: debug + avaliar storage/RAM/CPU + registrar.

**▶ ALVO Nº1 — SWEEP DE BENEFÍCIOS DOS SÓCIOS: MONTADO E NO AR (cont.20).** (a) `socio_beneficio` +
`tools/beneficios_sweep.py` e (b) `tools/beneficios_supervisor.sh` + cron bracket + @reboot = **FEITOS** (não
reconstruir; o supervisor varre os 23.691 sócios distintos mascarados). **Resta (c):** surfar `socio_beneficio`
no relatório de órgão/fornecedor (agregado "N sócios de fornecedores desta UG recebem benefício" — o H-BENEFICIO/
Lex II-E por-pessoa já existe; falta o AGREGADO pré-computado). **Subir cobertura de CPF** (~5% hoje via favorecidos
PF + TSE 542k): próxima fonte LEGÍTIMA = **parsing de CPF nos docs do SEI** (contrato social/procuração;
`processos_sei` ainda não extrai). **⚠ verificar:** endpoints BF/BPC do Portal deram HTTP 400 numa consulta —
conferir contrato (yield do sinal forte). **Base legal:** LGPD art. 7º,II/23 (interno, mascarado nos produtos).
**⛔ NUNCA** base de vazamento/"detetive".
1. **Wirar `beneficios_sociais` no motor DD + Lex** — H-PEP (PEP por NOME dos sócios do QSA, desmascarados →
   relação política) + H-BENEFICIO (benefício por CPF, só em CPF completo: PF favorecida; QSA mascarado=INDISPONÍVEL).
   Bounded+cacheado+honesto. Alimenta a seção II-E do Lex.
2. **Investigação priorizada TJRJ (030100) + Fundo Especial do TJ (036100)** — rodar a DD nos fornecedores dessas
   UGs (fachadas/laranjas) e priorizar o SEI sweep nesses processos. Considerar comando "investigar órgão".
3. **Cruzar OB+SEI+DD com inteligência** — agrupar OBs por processo/contrato (cardinalidade já medida em
   `cardinalidade_contratual`), seguir a árvore SEI (processo→atas/SRP→contratos→aditivos→OBs).
4. **br-acc** (github enioxt/br-acc): AVALIADO/AGREGADO → `docs/AVALIACAO-BR-ACC.md`. Já adotado: ponte
   CPF mascarado middle-6 (`resolucao_cpf.py`). PENDENTE: Splink (config br-acc = base) p/ resolução de
   entidade; ativar providers dormentes (GLEIF/OffshoreLeaks/OpenSanctions/TSE×contrato) nos produtos;
   ingerir CAGED/RAIS (anti-laranja por headcount) + PGFN. NÃO adotar Neo4j (SQLite/networkx).
5. proveniência/INDISPONÍVEL padronizada · resolução de entidade (Splink) · rodar SEI sweep aos poucos.
**Medir o produto antes/depois em cada um. Erros conceituais/conteúdo/código = NÃO permitidos (dono).**

---
*Doc enxuto de propósito. Conhecimento jurídico/operacional completo: `docs/CLAUDE-REFERENCIA-COMPLETA.md`.*
