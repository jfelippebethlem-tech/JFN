# JFN — DOCUMENTO ÚNICO DE REFERÊNCIA

> **Único doc de referência do projeto** (decisão do dono). Mantido ENXUTO de propósito (contexto é caro):
> estado vivo + regras + lições duras + retomada. Histórico detalhado vai para o git (commits) e docs por tema.
>
> **Como trabalhar (loop de qualidade máxima):** (1) ler este doc + o código real → (2) pesquisar best-practice →
> (3) planejar com visão global → (4) executar pequeno/isolado/**verificado** → (5) testar e corrigir →
> (6) **gerar o produto real e medir se melhorou/piorou** (PDF entregue, não só MD) → (7) commit + atualizar este
> doc (1 linha no §10). Detalhismo proporcional à complexidade; **testar tudo, nunca às cegas**; ao fim avaliar
> storage/RAM/CPU. **Honestidade sempre:** indício≠acusação, INDISPONÍVEL≠0, nunca inventar número, CPF PF mascarado.

Última atualização: 2026-06-12.

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
- **Sweeps:** **SEI** vivo e supervisionado (`tools/sei_supervisor.sh`, cron-minuto relança; resumível por checkpoint
  `data/sei_cache/sei_sweep_progress.json`; reboot-safe — ver §8). **SIAFE 2** = varredura completa; incremental
  diário via cron 05:00 (`siafe_runner diario`). SIAFE 1 = conta ALERJ-only (pende chave do dono).
- **Cron (DIÁRIO ESCALONADO, ordem lógica, VM-safe — cont.20):** base → SIAFE 05:00 · backfill_enderecos 05:40 ·
  folha 06:00 · massare 06:15 (+ manutenção/backtest dom). Sweeps de enriquecimento **diários, sessão limitada
  `SWEEP_MAX_SECONDS=9000` (~2h30), sem overlap, resumíveis:** **SEI 07:00 → endereço 10:00 → benefícios 13:00**.
  `@reboot` só limpa `browser.lock` (a agenda diária cuida dos lançamentos). Respawn por-minuto REMOVIDO (era o
  modelo contínuo). Backup do crontab antigo em `data/crontab.backup.*`; agenda nova em `data/crontab.novo`.

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
god-files (server.py 1959, inteligencia.py ~1800, lex.py ~1100 — split só oportunístico) · server.py possível leak
de browser Playwright (investigar guard).

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

## 9. PENDÊNCIAS DO DONO
- **Hermes Desktop (Linux) — update grande (cont.20):** `~/hermes-agent` (fork NousResearch) tem `apps/desktop`
  (Electron) e instalador Tauri. Branch local `claude/fix-memory-resolve-for-weaker-models` está **11.416 commits
  ATRÁS** de `origin/main` (4 à frente). Atualizar = decisão do dono (serviço `hermes-gateway` ativo do qual o JFN
  depende; preservar 4 commits locais + `.env`). Fazer com branch + estratégia segura quando o dono autorizar.
SIAFE 1 (liberar chave p/ todas as UGs) — **sweep PAUSADO até a chave (06-11 cont.17):** flag `data/.pause_sweep_1`
+ cron de respawn `* * * * * siafe_supervisor.sh` REMOVIDO (não funciona sem chave). Reativar: `rm data/.pause_sweep_1`
e recolocar a linha do supervisor no crontab. (SIAFE 2 incremental 05:00 segue ativo, funciona por login.) · SEI de
outras unidades (acesso do itkava) · repor/rotacionar billing das chaves Gemini sem saldo e renovar tokens OAuth "AQ."
manuais quando expirarem (caem no nous até lá).

## 10. CHANGELOG (1 linha/sessão — detalhe no git)
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

## 11. ⏯️ RETOMADA (sessão nova: "continue pelo docs/REFERENCIA-PROJETO.md")
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
