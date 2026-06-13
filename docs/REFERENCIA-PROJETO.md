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
- **⛔ Satélite (entorno) NUNCA acusa baldio/barraco** (lição Banco do Brasil, 06-11): coord no nível da rua
  (±100m) + VLM alucinou "barraco 80%" p/ o BB e p/ Polis Informática. Satélite só AFASTA área edificada;
  acusação de baldio/barraco/casa SÓ por Street View (rooftop, requer GOOGLE_MAPS_KEY). Nunca acusar com evidência fraca.
- **⛔ Sweeps concorrentes precisam de `busy_timeout` (cont.21, 06-12):** `sqlite3.connect()` sem `busy_timeout`
  **erra na hora** ("database is locked") se outro sweep segura o write lock → o endereço parava (02:22 e ao
  rodar os 3 juntos). Fix: `connect(timeout=30)` + `PRAGMA busy_timeout=30000` + WAL nos writers (esperar o lock,
  não errar). Validado ao vivo com os 3 sweeps concorrendo. **Todo writer novo do `compliance.db` deve setar isso.**
- **⛔ Dedup de responsabilidade SOLIDÁRIA no TCE (cont.21):** o mesmo débito imputado a N responsáveis vem como N
  linhas idênticas em `penalidades_tcerj` (402/910). **Somar infla o erário** (Saúde R$66M bruto → R$28,5M real).
  Contar o débito 1× por evento (processo+valor+sessão), registrar nº de responsáveis. Nunca superestimar (regra-mãe).
- **Vínculo nome↔código que muda (cont.21):** órgão do TCE↔UG re-derivado dos dados vivos (auto-matcher + tipo +
  override mínimo + `depurar()`), NÃO dict chumbado (apodrece). Discriminador de TIPO evita o bug órgão→fundo homônimo.

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
- **06-12 cont.30 (goal, agentes):** **QA dos produtos + correções.** Gerados /orgao 660100 e /relatorio MUV
  REAIS, **enviados ao Yoda** (msg 3745-48), laudo: completos/estéticos/prosa honesta (relatório até autocritica o
  rating). 6 correções (`02f16e4`..`306518f`): enriquecimento 35s→90s+retry+cache (§5/§6 CEIS/CNEP populam), score
  recalibrado (incorpora §1-B mesma-sede + §8-C PyOD), MD enviado ao Telegram, **§1-G TCE Cidades 660100→8 eventos/
  R$162k reais**, bullets `- -`, off-by-one 115/116. 43+181 testes verdes. **obsidian-save** da sessão (codigo/
  detectores-pipeline + 1º daily + lições). **Pendências p/ próxima sessão:** detectores restantes (J5-7/C6/E4-6/X1-6),
  rodar pipeline nos editais Vieira (SEI lê 510001 não-restrito agora), coletor PNCP p/ alimentar ctx (propostas).
- **06-12 cont.29 (goal, agentes, passo-a-passo):** **Pipeline de detectores de licitação — 17/30 nas 5 fases.**
  Planejamento P1/P2/P4/P5 (`613d1c0`,`380a967`) · Edital E1/E2/E3 (`58ba433`) · Julgamento J1/J2/J3/J4 (`93edb23`) ·
  Contratação C1-C5 (`01ccd00`) · Preço P3. Todos no schema §1.4 (score-âncoras, evidência, passo exculpatório,
  `nao_avaliavel` honesto — ex.: gap PNCP em J2-4 sem lista de propostas). Orquestradores `rodar_{orgao,fornecedor,
  edital,planejamento,julgamento}`. ~140 testes de detectores verdes. Falta: J5-7, C6, E4-6, X1-6 + coletor que
  alimenta o `ctx` (editais via SEI/PNCP). Spec [[notas/detectores-corrupcao-licitacoes-v2]].
- **06-12 cont.28 (goal, agentes):** **Detectores OPERACIONAIS + VIVOS no produto.** Wrappers reusando o código
  existente (`01ccd00`): **J1** cartel (concentracao_por_grupo+rodizio), **P3** sobrepreço (precos_extract), **C1-C5**
  fachada (investigacao_dd H-*) + orquestradores `rodar_orgao(ug)`/`rodar_fornecedor(cnpj)`. **§1-I Painel de
  detectores** no relatório de órgão (`d2869ea`, MD+PDF, alimenta o raciocínio, passo exculpatório visível). Framework
  agora: P4+J1+P3+C operacionais (REGISTRO), **54+ testes verdes**. Falta: 9 detectores novos (P5/E2-5/J5/X2/X4/X5) +
  rodar nos editais Vieira (SEI legível). Spec [[notas/detectores-corrupcao-licitacoes-v2]].
- **06-12 cont.27 (goal, agentes):** **⭐ SEI PORT FUNCIONOU** (`59360d0`) — fallback `_ler_cracked` lê processo de
  OUTRA unidade (510001 Vieira/Cidades = 10 docs reais, contrato 046/2022 Drenagem Av.22 Maio) SEM regredir o ITERJ
  (270042=10 docs); caminho SEPARADO, `ler_processo` intocado. **Destrava editais/sobrepreço no SEI.** **(2) FRAMEWORK
  DE DETECTORES** (`380a967`) — spec V2 do dono (30 detectores: P/E/J/C/X) → `compliance_agent/detectores/base.py`
  (schema JSON padrão + score-âncoras + verificador adversarial LLM-opcional + pipeline + convergência) + **P4
  fracionamento**; 33 testes; mapa 30→JFN (21 reusam concentracao_por_grupo/precos_extract/investigacao_dd/etc., 9 a
  construir). Spec completo em [[notas/detectores-corrupcao-licitacoes-v2]]. Roadmap: implementar os 29 restantes +
  rodar nos editais Vieira (agora legíveis via SEI).
- **06-12 cont.26 (goal, agentes):** **(1) MANUAL de detecção de corrupção em licitações** (playbook do dono) →
  `vault/notas/manual-deteccao-corrupcao-licitacoes` com **mapa de cobertura JFN** (✓/⚠/✗) + aplicação aos 12 grupos
  de cartel. **(2) 4 builds via subagentes (VM-safe, ruff, testes):** `/lista` capabilities + detectores novos
  (`0c269c5`); **§1-H Concentração-grupo (cartel)** no relatório de órgão (`897edb3`); **Lex** passo-exculpatório
  (defesa-contra-si → rebaixa achado fraco a monitoramento) + **destinatário** MP/CADE/TCE/CGE por família (`2317395`);
  **priorizacao** eixo risco-de-punição + quadrante alto-alto (`034b062`). **(3) ⭐ SEI CRACKED** — a busca itkava certa
  (☰→Pesquisa: radio **Processos** + ☑ **Considerar Documentos** + "Restringir" OFF + Órgão "Todos" + texto SEM prefixo
  + clicar **Pesquisar 1×** e **esperar a navegação**, sem duplo-submit nem `_abrir`) **ABRE processo de outra unidade**
  (510001/000876, provado por screenshot) — processo NÃO era restrito, era a mecânica da busca. `ler_processo`
  corrigido (espera ativa `ifrArvore`); falta afinar a extração dos docs da árvore. Método no vault [[sei-leitura-itkava]].
  **(4) OCR de docs DIGITALIZADOS** — helper `compliance_agent/sei/ocr_docs.py` (pytesseract+poppler+pdfminer, degrada
  honesto; `189d117`) **fiado no `ler_processo`** (`_conteudo_doc`: innerText vazio → download + OCR, `via=ocr`; `fdcd9cf`,
  aditivo). **(5) Reader SEI em ESTADO SEGURO** (`fa16348`): o port do método cracked regrediu o ITERJ 270042 → revertido
  ao fluxo dos 838; cracked fica como **caminho separado a portar com cuidado** (testar ITERJ+510001). Fallback público/captcha
  vivo em `ler()`. **Sessão toda VM-safe + agent-skills/subagentes** (7 builds, ~38 testes novos verdes, ruff). **Bloqueado
  (dono/dado):** editais×10-CNPJs e sobrepreço (PNCP só vencedor; SEI restrito precisa do port) · OCR ao vivo (acesso SEI).
- **06-12 cont.25 (goal):** **SWEEPS rearquitetados** — o "2-lane serial" (cont.21) foi RUIM (Chromium 24h +
  sessão única itkava competindo → leitura SEI manual dava 0; 2 lanes em 2 cores + DuckDB = crash) e foi REVERTIDO
  para **sweeps individuais escalonados** (`sweep_sei`/`sweep_dados`/`cruzador` + SIAFE), calibrados à VM real
  (**2 vCPU/7,8GB/sem swap**): nice/ionice best-effort (qualidade > leveza), bounded, load-guard=4, 1-por-vez,
  cron 07/10/13/16/19/23. **Lições §8 aplicadas:** mata só chromium ÓRFÃO (server.py tb usa ms-playwright); pkill
  bracket-safe (repeti o auto-pkill 2× hoje). Aprendizado no vault [[aprendizados/vm-nao-crashar]]. Commit `cc7aaa0`.
- **06-12 cont.24 (goal):** **(1) SEI ENTENDIDO/DOCUMENTADO** — corrigi 2 erros meus recorrentes: itkava lê
  **TODAS as unidades** (838 cdp de ~20 unidades, não só ITERJ) e o output são os **`cdp_*.json`**, não a tabela
  `processos_sei` (que fica 0 — NORMAL). Nota definitiva em `vault/aprendizados/sei-leitura-itkava`. **Edge MUV
  diagnosticado por screenshot:** login OK mas a nav da Pesquisa Avançada não dispara (cai no Controle de Processos)
  → fix apontado (caixa de busca do topo / link real da avançada). **(2) Grupo Vieira** — sócio-elo dos 10 CNPJs
  (R C / F P Vieira + família); **varredura tier-2** (UGs 31-80) +5 candidatos (Passarelli 54%, CONQUISTA/Agile/
  Montreal = grupos reais confirmados). **(3) 4 fortes do Fundo TJ:** endereços apurados (residenciais, 2 fora do RJ);
  flag **H-END-RESID confirmada** (dispara nos 4). **(4) Sweeps:** saudáveis (endereço 14,4k · benefícios 23,7k
  completo · SEI 838). **(5) Context-economy:** migração memória→vault, MCP lean (codegraph-only, −5-7k tok/turno
  via `~/.bashrc`), roteiro de skills.
- **06-12 cont.23:** **(1) MIGRAÇÃO da memória `.claude` → vault Obsidian** (ninguém em runtime lê os `.claude`):
  18 diretrizes/lições → 9 `aprendizados/` + 4 refs vivas → `notas/` (CNPJ, Yoda-render, FlexVision, codegraph, SEI-login),
  **digest do SessionStart agora carrega bloco "Diretrizes SEMPRE-ON"** (obediência·VM·cota·honestidade·aprender), `MEMORY.md`
  encolheu p/ 19 linhas; 24 originais arquivados em `vault/_archive/*.tar.gz` (nada perdido); 0 links quebrados. Regra de
  roteamento canônica no `vault/_CLAUDE.md`. **(2) ⛔ QUEDA da VM diagnosticada:** DuckDB pesado + 2 sweeps Playwright vivos
  numa VM **SEM SWAP** = OOM (sem cushion). Lição dura gravada ([[aprendizados/vm-nao-crashar]]): **parar sweeps antes de
  DuckDB**; recomendar swap 3-4GB ao dono. **(3) Grupo Vieira QUANTIFICADO** — `concentracao_por_grupo(660100)`: os **10
  CNPJs + sócio-elo** explícitos (R C/F P Vieira Engenharia + família ligam 6-7 cada), R$543M/56,9%; vault MUV atualizado.
  **(4) VARREDURA** nas 30 maiores UGs → 7 candidatos novos de concentração-grupo (CONQUISTA vigilância multi-UG, Agile/Milano,
  PC/Montreal; Supervia/Telemar excluídos como legítimos) → `casos/varredura-concentracao-grupo-2026-06-12`.
- **06-12 cont.22:** **(1) NOVO detector `grafo_cartel.concentracao_por_grupo(ug)`** — concentração OCULTA por
  grupo econômico (union-find por sócio, dedup raiz; HHI grupo vs CNPJ). Pega o que rodízio/captura-por-CNPJ não
  pegam: muitos CNPJs que parecem concorrentes mas são UM grupo (concorrência fictícia, Art. 90/337-F/CADE).
  **Medido real:** UG 660100 = 1 grupo (MUV São Gonçalo +9) **57% / R$543M**, HHI 1055→3575 (Δ+2520). Surfado no
  triage de órgão; +4 testes TDD (núcleo puro); 12 verdes; ruff ok. Commit `756c58d`. Vault MUV/Vieira atualizados.
  **(2) RECONCILIAÇÃO honesta:** auditoria provou que a doc estava muito atrás do código — **H-PEP, H-BENEFICIO,
  `investigacao_orgao_dd`, PyOD, DuckDB, CAGED/RAIS, OpenSanctions JÁ EXISTEM** (estavam listados como "próximos").
  **Único gap real do roadmap P0 = Splink** (entity resolution). **(3) Regra de roteamento de memória** (3 camadas,
  anti-duplicação, context-economy) em `~/vault/_CLAUDE.md` + 1 frase no `.claude/MEMORY.md`. **(4) Lição gravada:**
  obediência do dono > qualquer goal/loop; Stop hook/ralph-loop NUNCA ligado sem o dono no controle.
- **06-12 cont.21:** **(1) Yoda RESOLVIDO** — duplicação = poller externo, provado (diag) e identificado pelo dono
  como o **Hermes Desktop**; conflitos cessaram 12:51 UTC; update do hermes inocentado pela timeline (1º conflito
  01:37 < update 03:07). Ferramentas: `tools/diag_telegram_poller.sh` (já existia) + novo `tools/rotate_telegram_token.sh`
  (rotação a 1 comando p/ recidiva). **(2) NOVO no relatório de ÓRGÃO — §1-G Sanções do TCE-RJ** (`penalidades_tcerj`,
  910 condenações, controle externo, antes PARADO por falta de join). `reporting/penalidades_tce_view.py`: vínculo
  órgão-TCE↔UG **re-derivado dos dados vivos** (auto-matcher token-prefix + **discriminador de tipo** que corrige o
  bug clássico TJ→Fundo Especial; bônus de acrônimo) + **overrides curados só p/ exceções** (sucessões/multi-UG/sem-âncora)
  + **`depurar()`** auto-auditoria (0 sem_match; só CEDAE sem UG) + marcador temporal (EXTINTA=histórico). **Honestidade
  dura:** dedup de **responsabilidade solidária** (402/910 linhas eram o mesmo débito a vários responsáveis — somar
  inflava Saúde de R$27M→R$66M; agora conta o débito 1×, registra nº de responsáveis). MD §1-G + PDF + alimenta o
  raciocínio (IA conectou: "48 condenações do TCE… riscos de gestão"). Medido real (Saúde R$28,5M, PRODERJ R$35M,
  DETRAN; Fundo do TJ corretamente sem sanção). +12 testes (23 verdes nos módulos de órgão), ruff limpo. PDF entregue
  conferido (sem tofu). **Próximo M3 pendente:** UGs renomeadas → o `depurar()` já sinaliza drift p/ revisão.
  **(3) FIX sweep `database is locked`** — `busy_timeout`+WAL nos writers de endereço (§8); validado ao vivo; endereço
  voltou a avançar (3.9k→4.3k). Sweeps relançados (SEI/endereço/benefícios; benefícios=universo completo). **(4) docs
  LEVES** — 53 arquivos → 33 vivos + 20 em `docs/historico/` + `docs/INDEX.md` (catálogo); `CLAUDE.md` enxuto ~30%.
  **(5) SEGUNDO CÉREBRO Obsidian** (`~/vault`, fora do git do JFN) — motor `obsidian-second-brain` (44 cmds, MIT) +
  kepano; **memória de CASOS** (MOC-Casos + casos reais: 2 laranja BPC, Saúde/TCE); **MOC-Codigo/Dados/Mercado**
  (architect_scan do JFN/hermes → notas de arquitetura; esquema das 40 tabelas; FMP/OpenBB) correlacionando
  **código↔dado↔caso**; hook **SessionStart** injeta digest leve (~360 tok, casos abertos) — memória permanente sem
  poluir contexto; sync **Syncthing** (VM pronta, aguarda Device ID do desktop). **(6) OpenBB avaliado** (yfinance BR
  grátis; AGPL→fronteira; probe `~/openbb_probe`). Vault íntegro (health: 0 links quebrados). Diretriz nova: **usar
  agent-skills sempre**. Commits: TCE (`6017ede`), rotate (`0961e0a`), docs-leveza (`793f695`), sweep-lock fix.
  **(cont. — sweeps + 2 módulos novos):** **(7) SWEEPS 2-LANE SERIAL** — `tools/sweeps_serial.sh` + systemd
  `sweeps-serial@{browser,dados}` (browser=SEI+CPF | dados=fachada→benefícios→endereço; ≤2 concorrentes, sem
  contenção/lock/duplicação; crons individuais removidos). `fachada_sweep_rotativo.sh` (1 UG/passada, começa ALERJ/TJ).
  **(8) MÓDULO DE RELAÇÕES** `relacoes.py` — sócio↔empresa↔empresa↔órgão (sócio/endereço/UG em comum), **dedup por
  CNPJ raiz** (matriz/filial=1 PJ). Achou **grupo Vieira** (R$189M, 11 empresas, 7 na mesma UG de obras). CLI+5 testes.
  **(9) SOBREPREÇO** `precos_extract.py` — extrai preço unitário de edital/contrato + **sobrepreço interno** (mesmo
  item a preços ≥2× diferentes entre órgãos = indício, sem API). +6 testes. Ativa com editais do sweep SEI/PNCP.
  **(10) docigp ALERJ** = BLOQUEADO (login de deputado — dependência do dono, como SEI/SIAFE). **(11) Sobrepreço
  EXTERNO** (CATMAT via `sobrepreco.py`) pendente (mapear item→CATMAT). Vault: 26 notas / 7 casos / 0 links quebrados.
  **(cont. — investigação + folha):** **(12) Coletor ALERJ** (`collectors/alerj_transparencia.py`, dado ABERTO —
  `transparencia.alerj.rj.gov.br` report/120 pagamentos + report/73 folha; parser PDF: 293 pagamentos, 5.726
  servidores). **(13) Acúmulo de cargos** (`acumulo_cargos.py`: ALERJ folha ∩ `registros_folha`, com **classificação
  de LEGALIDADE** — comissionado/cessão/aposentadoria podem ser legais; 6 sobreposições, 5 verificar). **(14) Acima
  do teto** (`acima_do_teto.py`, CF 37 XI — separa RRA/indenizatórias do supersalário real; 32.353 acima bruto → 0
  confirmado por falta de composição). **(15) SEI pensante** (`sei_recomendacoes.py`: recomendações de PGE/CGE/jurídico
  NÃO ATENDIDAS, determinístico + nous). **(16) Caso MUV São Gonçalo** (grupo Vieira, R$182M, ~8 consórcios — vault
  cruzado OB↔processo↔sócios↔órgão). **(17) Folha RJ — recon** (TJRJ=B WebForms, DPRJ=A, Executivo=C gated, TCE-RJ
  domínio tcerj.tc.br) — providers a implementar. **fix sei_reader** (submit robusto). **+38 testes novos.**
  ⚠ **SEI reader NÃO lê árvore de outra unidade ainda** (abre a view mas pega processo errado; falta extrair frameset
  `ifrArvore`) → **debug VISUAL** (screenshot, não às cegas). **2-lane serial** (`sweeps-serial@{browser,dados}`) no ar.
- **06-12 cont.20:** **SWEEP DETACHED DE BENEFÍCIOS DOS SÓCIOS no ar (ALVO Nº1 cont.19 montado).** (1) Tabela
  `socio_beneficio` (resumível, PK nome_norm+doc, CPF resolvido INTERNO/LGPD) + `tools/beneficios_sweep.py`
  (1 lote: índices `carregar_indice_favorecidos`+`carregar_indice_tse` 1×, `resolver_multi`, `verificar_beneficios`
  dos resolvidos, grava honesto — não-resolvido=resolvido0/INDISPONÍVEL≠"não recebe"). (2) `resolucao_cpf`:
  novo `carregar_indice_favorecidos` + `pf_idx` em `resolver_multi` (helper `_match_indice`) p/ NÃO fazer 1
  full-scan de 1,1M OBs por sócio (§8 VM-safe; query `substr` não usa índice) — retrocompatível. (3)
  `tools/beneficios_supervisor.sh` (detached, load-guard, pausa `data/.pause_beneficios_sweep`) + cron **bracket**
  `pgrep -f 'beneficios_superviso[r].sh'` + @reboot. **Universo:** 23.691 sócios distintos mascarados.
  **Medido ao vivo:** lote OK; índices ~48s (custo fixo/lote); 1º resolvido (TSE) → benefício consultado,
  `recebe_beneficio=0` honesto. Supervisor VIVO (lote 800). +6 testes (21 verdes nos módulos tocados).
  **⚠ Achado a verificar (dono):** alguns endpoints do Portal (Bolsa Família/Aux.Emerg.) deram **HTTP 400**
  numa consulta. **(cont.) RESOLVIDO:** o contrato real (probe ao vivo) era **Bolsa Família exige
  `anoMesReferencia` (AAAAMM)** — corrigido em `_bolsa_familia_mensal` (varre as últimas 3 competências, para no
  1º registro); **Aux. Emergencial** dá 400 "CPF/NIS válido" p/ não-beneficiário → tratado como sem-benefício
  (não polui motivo); `_get` agora expõe o corpo do 400. BPC/PETI/Safra/Defeso OK só com `codigo`. Coletor
  verificado ao vivo: motivo vazio (6 endpoints respondem). +3 testes. **Reset honesto:** apaguei os 71
  resolvidos do 1º lote (BF estava bugado/cacheado) p/ reprocessar; 1.534 não-resolvidos mantidos.
  **OBS do dono — cruzar sócios+administradores+procuradores:** sócios e **administradores JÁ cobertos** (o
  universo é o QSA inteiro: Sócio-Adm 11.620, Administrador 2.830, Diretor 4.322, Presidente 2.603, Conselheiro
  467 — 14.916 mascarados c/ papel de gestão; o sweep não filtra por papel). **Procuradores=0 no QSA** (Receita
  não traz) → ficam nas **procurações do SEI** (extrator de CPF a construir; arquitetura já extensível: linha
  nova em `socios_fornecedor` com `qualificacao='Procurador'` é varrida automaticamente). **Próximo:** (c) surfar
  `socio_beneficio` no relatório (agregado) + extrator de CPF de SEI-docs (procuração/contrato social).
  **plugin agent-skills** re-cacheado (doctor). **(cont.) RELATÓRIOS 100% (Fase 1 — benefícios surfados nos 3
  produtos):** `reporting/beneficios_view.py` (agregar/por_fornecedor/leitura — cruzamento inteligente
  socio_beneficio×QSA, indício/AFASTADO/INDISPONÍVEL) → **órgão §1-F (MD+PDF)**, **fornecedor §1-C (MD)**,
  **Lex II-E agregado**, todos alimentando a análise raciocinada (IA conecta o sinal de laranja). Dado completo
  + leitura + conclusão (pedido do dono: inteligência/escrita/conclusão; cruzamentos inteligentes). Medido real
  (036100, 13210413000142). +14 testes. Pendente paridade: fornecedor PDF (render_pdf_html). Plano/todo em
  `tasks/`. **Cobertura do CPF medida ao vivo: ~4,7% resolvidos (favorecidos PF + TSE).** **AGENDA DE SWEEPS
  diária escalonada** (§2) substituiu o respawn contínuo. Próximo: Fase 2 (gaps ALTA: capital×recebido, QSA
  detalhe, aditivos, TSE-MD, rodízio no fornecedor, empenho→liquidação→OB, regularidade fiscal, terceirizados).
  **(cont.) FASE 2 (gaps ALTA com dado) entregue:** fornecedor ganhou **§1-C** benefícios (laranja), **§1-D**
  doações TSE (conflito doador↔contrato), **§1-E** rodízio/cartel (bid rotation, bounded top-3 UGs), **§1-F**
  conflito de pessoal (sócio resolvido na folha do Estado — `conflito_pessoal_view` × `registros_folha` 257k),
  e leitura **capital×recebido** (subcapitalização). Todos: dado + leitura + conclusão + alimentam o raciocínio
  (IA). **Achado honesto:** A1 aditivos, A2 empenho→liquidação→OB e A5 débito fiscal **NÃO têm dado** na base
  (colunas/feeds inexistentes) → viram "coletar primeiro", não "surfar". 106 passed/0 failed. Commits 6e50b15
  (TSE), c75c02b (capital), d2e023b (rodízio), b62fe6b (conflito pessoal), 4d7c918 (PDF benefícios). Fase 3
  (MÉDIA) pendente — M1 Benford já no PDF (falta MD). **Hermes Desktop:** ver §9 (update grande pendente).
- **06-12 cont.19:** **Imagem de rua (fachada/casebre) + benefícios sociais.** (1) `verificacao_endereco`: **Mapillary** (token grátis, rente ao chão) como fonte PRIORITÁRIA + **Street View** só de fallback, capado a **9999 req/31d** (`STREETVIEW_MAX_31D`; checa cobertura no `metadata` GRÁTIS antes de gastar) + satélite Esri (só afasta). Ordem `IMG_FONTE_ORDEM`. **Casebre PRECEDE "edificado-OSM"** (foto rente ao chão acusa `construcao_precaria_barraco` mesmo havendo construção — pedido do dono). Visual LIGADO no sweep via gate `ENDERECO_USAR_IMAGEM=auto` (liga só com MAPILLARY_TOKEN, p/ não queimar o teto pago). Chaves SV+Mapillary no `.env` (gitignored). +8 testes. Testado ao vivo (Copacabana/Maracanã/Centro = foto OK; Maracanã→INDÍCIO casebre). **⚠ Piloto 036100 com `--forcar` travou em back-off do Nominatim (re-geocodifica tudo); o sweep normal usa geocode CACHEADO e acumula visual aos poucos.** (2) **Benefícios** (`collectors/beneficios_sociais.py`) 3→**6**: +**Bolsa Família** +**BPC** +**Auxílio Emergencial** (por-CPF, verificados HTTP 200 ao vivo). Auxílio Brasil por-CPF=403; Novo BF/sacado=só NIS (não temos). **PENDENTE (próximo loop, sessão limpa):** **sweep de benefícios dos sócios** detached (universo `socios_fornecedor`=31.449; 27.729 mascarados) + **resolução de CPF de sócio** — gargalo: middle-6 resolve só **2%**; fontes LEGÍTIMAS a somar = **TSE** (`eleitoral_providers`/doacao_tse, doador/candidato) + **SEI docs** (contrato social/procuração têm CPF — exige PARSING; `processos_sei` ainda não extrai CPF). **NÃO usar serviços de leak/"detetive hacker" de CPF-por-nome** (risco LGPD, multa até R$50M; descaracteriza o JFN como ferramenta de compliance). 5 commits (inclui `resolver_multi`+TSE). **⚠ ACHADO A RESOLVER (próx. sessão):** o sweep do universo já verificou 3.320 sedes mas **0 com VISUAL** — a foto só dispara quando o geocode é `exato` (nº da casa), que o Nominatim grátis quase nunca acerta (cai antes, no `exato=False`). P/ o visual funcionar de fato: ou rodar foto de rua também no geocode coarse (centróide da rua — útil p/ "rua de favela", mas marcar como informativo, não acusatório/§8), ou melhorar a precisão do geocode. **Goal aberto do dono ("melhorar todo o ecossistema em loop") → retomar em sessão limpa (regra §5) por este doc.**
- **06-11 cont.18:** **Relatórios de ÓRGÃO e FORNECEDOR enriquecidos** (dono: "todos os cruzamentos, mais prosa/inteligência, não resumir"). ÓRGÃO ganhou seções (md+PDF): **1-D Triagem de DD dos maiores fornecedores** (fachada/laranja 🔴🟡🟢+score+hipóteses+SEI) + **rodízio temporal/cartel** (bid rotation, OCDE) + processos SEI a priorizar — via `investigacao_orgao_dd` (bounded/honesto); **1-E Realidade do endereço das sedes** ("as empresas são reais?", cruza `endereco_verificacao`; INDISPONÍVEL≠inexistência). Esses fatos alimentam a análise raciocinada (prosa ~450 palavras). FORNECEDOR: veredito **"a empresa é real?"** (realidade da sede) no §1. **FIX real:** `backfill_verificacao_endereco` quebrava em TODA linha desde cont.15 (tabela ganhou colunas visual_*→13; INSERT posicional de 9) → **nenhuma empresa era verificada**; INSERT agora nomeia colunas (+2 testes de regressão). **Sweep de endereços agora DETACHED** (`tools/endereco_supervisor.sh` + cron respawn/minuto + @reboot, igual SEI/SIAFE; pausa `data/.pause_endereco_sweep`; varre o universo até esvaziar, back-off 6h). Medido: FES regenerado com as seções (top-12 🟢 = instituições legítimas, correto). **Suíte (rodada inteira):** **465 passed, 5 failed** (2 arquivos FMP por-rede `--ignore` + 2 testes de integração `--deselect` que TRAVAM em SQL full-scan na DB 1,2GB sob carga: `test_offline::test_goal_agent_ciclo_autonomo`, `test_jfn2_onda10::test_gera_minuta_docx`). As 5 falhas são **pré-existentes e ambientais, NENHUMA nos arquivos alterados**: `test_jfn2_skilltree::test_render_menu_curado_e_enxuto` + 4× `test_offline` (roteamento hermes groq/openrouter/max_tokens + SEI-chrome — exigem chave/chrome). ⚠ os ~4 testes lentos/por-rede são candidatos a fixture-DB/markers `network`. Módulos tocados = 100% verdes (regime4 6, orgao/DD 21, relatório 17, cruzamentos 4). 4 commits.
- **06-11 cont.17:** **EDGE DO MASSARE VIROU ≥0** (alvo do dono). Novo `massare/engine_regime4.py`: ensemble **4 regimes** (grade 2×2 tendência×volatilidade) + **drift-aware** (EWMA por sub×regime, recência pesa mais, rampa anti-ruído por min-amostras). **Universo (26 ativos × 5/10/21d, walk-forward OOS):** naive −0.0133/−0.0163/−0.0082 → regime2 −0.0071/−0.0114/−0.0021 (ainda neg.) → **reg4+drift +0.0006/+0.0005/+0.0070 (≥0 nos 3)**. Ablação honesta: **4 regimes SEM drift PIORA** (esparsidade) — **o drift é o que vira**. **Produto real** (`backtest.json`, 356.655 pregões/78 séries): **edge médio +0.0027**, 38/78 positivas (ETH 21d +0.072, DXY +0.061, USDBRL +0.055). Robustez: positivo half_life 21..63; decai só >~90d. **Motor de produção trocado p/ regime4** (`backtest.run` padrão + `/api/massare/prever` + `daily`) SÓ após o backtest universo provar ≥0 (lição V2); naive mantido p/ comparação. Live OK (BTC bear_turb edge +0.017 tem_skill=True). +6 testes. Commit `825d0f5`.
- **06-11 cont.16:** Avaliadas 3 specs greenfield de IAs (fraude do Fable, geocoding, OSINT) contra o código real → **~70% já existe** (e mais honesto); geocoding seria REGRESSÃO (lições §8 já codificadas). Delta novo escolhido: **`rodizio_temporal.py`** — rodízio temporal de cartel (vencedores que se revezam no topo da UG ano a ano, OCDE bid rigging), aditivo ao `grafo_cartel` (que era só espacial). Núcleo PURO testável (5 testes TDD), DuckDB sobre 1,1M OBs, exclui intra-gov. CLI + rota `/api/rodizio` + capabilities. **Medido ao vivo:** TJRJ/Fundo 036100 = SEM indício (topo legítimo, correto); varredura achou **20 UGs** com indício (Transporte R$2,6bi, Pgto Concessionárias R$1,37bi, Fundo ALERJ, Comunicação Social). Honesto: OB=vencedor≠licitantes → corroborar no SEI/PNCP. **(cont.)** rodízio→QSA (`rodizio_com_qsa`: revezam+sócio comum=concorrência fictícia, eleva a ALTO) + integrado no `investigar_orgao` (aparece na triagem da UG). **Testado JFN ao vivo:** Fundo 036100 / TJRJ 030100 = top 🟢 legítimo (fachada na cauda); Esporte 170100 = rodízio score 74.1 aparece no relatório. **Massare testado:** funciona, mas edge OOS NEGATIVO (`tem_skill=False`, backtest defasado). **`/lista` ampliado:** bloco financeiro do Massare passou de 3→8 funções (regime/clima HMM [nova rota `/api/massare/regime`], teses, fundamentos, carteira, agenda). **FMP integrado:** chave grátis (`massare/fmp.py`) → fundamentos US TTM, ligado no fallback de `/api/massare/fundamentos` (agora cobre BR+US). Verificado honesto: senate/insider/13F por-ticker = PAGOS (até no MCP, ACCESS DENIED); `massare/sinais_fmp.py` fica DORMENTE até plano pago. Edge OOS do ensemble segue negativo (próximo alvo real). **Ensemble REGIME-condicional** (`massare/engine_regime.py`, experimento aditivo): pesos por acerto da sub DENTRO do regime (bull/bear via SMA200). **Medido OOS (5 ativos): edge −0.029→−0.017 (Δ+0.012, melhora nos 5)** — avanço real, MAS edge ainda NEGATIVO (não bate o ingênuo; não trocar produção sem backtest universo-inteiro). 9 commits; 32 testes verdes.
- **06-11 cont.15:** Verificação de endereço endurecida: divergência/baldio só com geocode `exato` (fim de 83 falsos); **resolução por imagem** (`classificar_local_por_imagem` + `tools/resolver_endereco_imagem`): satélite Esri grátis + Street View (chave) → VLM Gemini pool. **Satélite NUNCA acusa** (lição BB §8 — virou "barraco" falso), só AFASTA; acusação real só por Street View (`GOOGLE_MAPS_KEY`). Dono pausou o visual (decisão: caminho grátis afasta, não conclui). Tabela `endereco_verificacao` (2 INDÍCIO / 201 INDISP no Fundo). +8 testes.
- **06-11 cont.14:** Geocoder corrigido (lição NEW LINK §8: usa CEP+variantes, distingue `exato` do centroide). **Verificação de endereço de TODAS as fornecedoras via backfill incremental diário** (`backfill_verificacao_endereco.py` + tabela `endereco_verificacao` + cron 06:45 `--limite 600` → cobre 14.418 sedes em ~24d, educado/VM-safe; `--ug` prioriza órgão). DD estrutural Fundo 036100 fechou **1363/1363 → 64 candidatos (8🔴/56🟡)**; 🔴 = END-RESID+situação irregular+sócio único (ex.: HG REPRESENTACOES, A V SUPRIMENTOS, EMBRACOM). Lote OSM duplicado irritou rate-limit → back-off implementado + sweep ad-hoc trocado pelo cron. +5 testes.
- **06-11 cont.13:** **Verificação de realidade do endereço** (`verificacao_endereco.py`): geocode-match (bate município? Nominatim) + **edificação/baldio** (Overpass/OSM — sem prédio no ponto + landuse vago = indício de terreno não edificado; ressalva honesta de cobertura OSM incompleta) + hook imagem→VLM (ativa com chave Street View/Mapillary). Plugado no H-END-EXISTE. Back-off 429/5xx + cache 30d → **sweep `endereco_sweep --todos`** avalia TODAS as fornecedoras da UG (resumível/reboot-safe, educado). Rodando no Fundo 036100. Co-endereço = H-COEND (já existia). +6 testes.
- **06-11 cont.12:** **Alvo 2** — triagem de DD priorizada por órgão (`investigacao_orgao_dd.py`): ranqueia top fornecedores PJ da UG por grau/score + lista processos SEI a priorizar; CLI + render_md; 3 testes. Medido ao vivo TJRJ 030100/Fundo 036100: **top-por-valor = grandes prestadores legítimos (todos 🟢)** — achado honesto: **fachada/laranja mora na CAUDA, não no topo** (varredura de cauda = trabalho de background). Regra de corroboração confirmada (CAPITAL isolado score-8 não sobe a 🟡).
- **06-11 cont.11:** **Alvo 1 fechado** — `beneficios_sociais` wired no motor DD + Lex: **H-PEP** (PEP por nome do sócio = relação política) + **H-BENEFICIO** (benefício de subsistência por CPF = laranja), bounded/cacheado/honesto, seção II-E. Verificado ao vivo (PEP real, 2.9s). **br-acc avaliado/agregado** (`docs/AVALIACAO-BR-ACC.md`): NÃO Neo4j; **adotada a ponte de CPF mascarado middle-6** (`resolucao_cpf.py`, corpus 59,6k PF favorecidos) que **destrava H-BENEFICIO de sócio mascarado** (semente da resolução de entidade P0). +16 testes.
- **06-11 cont.10:** **FIX conceitual OB≠contrato≠processo** (`cardinalidade_contratual` honesta: TJRJ 1598 OBs/41 proc; Fundo 47895/338; nota + frase no relatório + skill Yoda) `4fff8bd`. Coletor **benefícios sociais (laranja) + PEP (relação política)** `beneficios_sociais.py` (DD Loop 2 base). br-acc entendido (grafo Neo4j de dados públicos — referência p/ fontes+entidade). Doc/MEMORY enxutos.
- **06-11 cont.9:** Lex seção II-E (apresenta a investigação DD) + sweeps reboot-safe (`recursos` boot-time + `@reboot` cron). `8c6c7e4`,`4981323`.
- **06-11 cont.8:** motor `investigacao_dd` (fachada/laranja, Loop 1) + wiring no Lex + BrasilAPI capital/porte. `63070cd`.
- **06-11 cont.7:** bom dia multi-fonte política + sempaywall; **CEIS/CNEP** corrigido (3 bugs, API); relatórios raciocinados (/relatorio+/orgao) + OSINT Querido Diário.
- **06-11 (1–6):** Cerebras em todos os pools; /orgao rico (sumário+geográfica+P×I); SEI sweep destravado (bug supervisor back-off infinito); rotação de chaves LLM (cooldown 12h billing); erros do Yoda mapeados/corrigidos.
- **06-09:** 23 loops de benchmark (pyproject/scorecard/golden, ruff 733→37, 4 bugs reais); frente SEI (reader funciona, `sei_sweep`/`sei_ficha`); /UG + busca de órgão; Lex de órgão; glifos do PDF corrigidos; este doc criado.
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
