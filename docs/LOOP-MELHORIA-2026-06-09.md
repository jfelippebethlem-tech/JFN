# Loop de Melhoria Contínua do Ecossistema JFN — log por checkpoint

> Meta (dono): 5 loops de **backtest → análise total → reavaliação → planejamento (best practices/benchmarks)
> → execução**, com checkpoints/commits e documentação de **erros & acertos** para as próximas IAs.
> Visão-norte: outputs perfeitos · ecossistema integrado, baixa fricção · grátis (respeita a VM) · rápido,
> fluido, belo, sem ruído · **sistema pensante** nos relatórios JFN, pareceres Lex e previsões Massare.
> Branch: `feat/lista-limpa` (mudanças pequenas, isoladas, verificadas com o artefato real).

## Princípios herdados (da V2 revertida — ver [[licao-v2-revertida-2026-06-08]])
1. Gerar o **artefato real** (relatório/parecer) como baseline e comparar a cada mudança.
2. **Wiring mínimo**: ligar uma peça nova só nos pontos certos; nunca LLM síncrono no hot-path sem cache+bound+verificação.
3. Mudança **pequena, isolada, verificada** > camada grande.

---

## ✅ Loop 1 — checkpoint (2026-06-08/09)

**Plano:** re-aplicar os ganhos de qualidade da V2 **sem a fragilidade**; começar pelo "sistema pensante" do Lex (onde/por quê).

**Execução (commits em `feat/lista-limpa`):**
1. `/lista` curado — 7426→1011 chars (10 funções/3 grupos vs 47 itens crus). Catálogo completo no `/skills`.
2. Sumarizar OBs — top-12/exercício no MD e PDF (fornecedor FPDF + órgão); lista completa na planilha XLSX.
   ITERJ: PDF 253KB→**63KB**. (O PDF-HTML do fornecedor já era agregado.)
3. LLM do motor robusto — rotação do pool de **9 chaves** (`~/.hermes/.env`, as do JFN/.env estavam mortas)
   + **multi-modelo** (flash→2.0-flash→flash-lite) + backoff + bridge `gerar_sync` (loop dedicado). 3/3 ao vivo.
4. **Análise DISCURSIVA do Lex** — `_trecho` captura o excerpt; `analise_discursiva` (1 chamada LLM, bounded
   45s, degrada honesto) escreve 2-4 frases **onde+por quê (mecanismo)** ancoradas no texto real; render no parecer.
5. Guard `_eh_interface_sei` — rejeita a tela/menu do SEI como conteúdo.

**ACERTOS:**
- O pipeline discursivo funciona e é **honesto** (o LLM flagrou sozinho que o trecho era menu, não documento).
- Relatórios enxutos + `/lista` limpo = menos ruído, mais beleza (alinha com a visão).
- LLM agora resiliente (multi-modelo+pool) sem bolar no hot-path de tudo — wiring mínimo (só no Lex, sob flag).

**ERRO/ACHADO CRÍTICO (avaliação do artefato real):** a **leitura do SEI retorna o MENU** ("Controle de
Prazos / Processos recebidos (N registros)"), não o inteiro teor → a análise "onde/por quê" fica sem input
real. O parecer chegava a "analisar o menu". Mitigado com o guard (agora honesto: "não lido"). **A RAIZ é o
coletor SEI** (`collectors/sei_cdp.py` / `sei_reader`): loga mas não navega até o documento do processo.

**Benchmark de referência:** due diligence padrão Kroll/Deloitte/Control Risks — prosa analítica que cita
**onde** (cláusula/§) e **por quê** (mecanismo: quem foi eliminado, qual o efeito). Só alcançável com o
documento real em mãos → depende do coletor SEI.

**→ Alvo do Loop 2:** consertar o coletor SEI para extrair o **inteiro teor do processo** (não o menu).
Sem isso, o "sistema pensante" do Lex fica honesto porém sem matéria-prima.

---

## ✅ Loop 1 — wiring Yoda↔JFN (teste end-to-end)
**Teste:** `hermes -z "qual o status da coleta do SIAFE? quantas OBs?"` (one-shot, sem mexer no bot vivo).
**ANTES:** Yoda respondia *"comando `status` desconhecido"* — `siafe_stats` existia mas o `quando_usar` só
cobria "quantas OBs"; não havia capability para `/api/siafe/status`.
**FIX:** enriqueci `siafe_stats.quando_usar` (status/cobertura/quanto coletamos) + registrei `siafe_status`
(lockfile). Regenerei os derivados (`~/.hermes/jfn_tools.json` lido pelo gateway).
**DEPOIS (verificado):** Yoda retorna OBs/ano (2016-2026), total R$ 20,16 bi, fonte SIAFE-Rio 2. ✅
**Aprendizado:** rota existir no `server.py` ≠ Yoda saber usá-la. O wiring real é o `capabilities.yaml`
(+ derivados regenerados) com `quando_usar` que casa a linguagem natural do dono. Testar com `hermes -z` pega
gaps que o curl não pega.

⚠️ **Pendente:** o `jfn.service` vivo ainda roda código anterior aos commits OB-enxuta/LLM/Lex-discursivo —
fazer `systemctl --user restart jfn.service` num momento ocioso (não durante geração de relatório do dono).

## 🔎 Loop 2 — ANÁLISE (root cause pinpointed) — FIX a executar em sessão nova
**Sintoma:** Lex "lê" o SEI mas a análise discursiva cita o MENU, não o documento.
**Evidência (cache real `data/sei_cache/cdp_SEI_070002_004332_2024.json`, processo da Extreme):**
- `texto` = menu lateral do SEI ("Acompanhamento Especial, Base de Conhecimento, Controle de Prazos…")
- `n documentos: 0` · `conteudo_documentos: 0` · **`cadeado: False`, `n_docs_restritos: 0`** (NÃO é restrição)
- `relacionados: 40` → o leitor ficou na **CAIXA/DESKTOP do SEI** (≈40 processos recebidos), **não abriu o
  processo individual** nem chegou à **árvore de documentos**.
**Root cause:** bug de NAVEGAÇÃO em `compliance_agent/collectors/sei_cdp.py::ler_processo_sei_via_chrome`
(≈linha 439; extração em 570/708). Loga (itkava, perfil ITERJ/CHEGAB) mas não pesquisa+abre o processo-alvo
→ captura o desktop. SEI usa **frames/iframes** (`ifrArvore`/árvore de documentos + `ifrVisualizacao`/conteúdo);
o conteúdo do documento está no iframe, não na página externa.
**FIX (próxima sessão, orçamento cheio):** em `ler_processo_sei_via_chrome`: (1) pesquisar o nº do processo
(campo de pesquisa SEI), (2) abrir o processo, (3) entrar no iframe da árvore (`ifrArvore`), iterar os
documentos, (4) abrir cada doc no `ifrVisualizacao` e extrair o texto → preencher `documentos` +
`conteudo_documentos`. Testar AO VIVO (Chrome 9222 itkava) com SEI-070002/004332/2024 e conferir que
`n documentos > 0` e o `texto` é do documento. Então o Lex discursivo passa a citar trecho REAL.
**Honestidade:** enquanto não navega, o guard `_eh_interface_sei` mantém o parecer honesto ("não lido").
**Benchmark:** prosa que cite "no §X do edital, a exigência Y eliminou as empresas A,B" só é possível com o
texto do documento — depende 100% deste fix.

## ✅ Loop 2 — frescor/cobertura no topo dos relatórios
`inteligencia.cabecalho_frescor()` (sem LLM, 1 COUNT) no topo de fornecedor+órgão. Honestidade: afirmar
dentro da cobertura. Verificado: "Cobertura da base: 1.121.306 OBs · 77% com CNPJ · OB mais recente:
2026-06-01". Serviço religado (autonomia dada pelo dono: "ligar/religar à vontade").

## ✅ Loop 3 — encaminhamento por severidade no parecer (acionável)
Cada indício do Lex passa a dizer O QUE FAZER: grav≥3 → **requerimento** + (se persistir) representação
TCE-RJ/MP; senão diligência/monitoramento. Sem LLM. "Sistema pensante": dirige a ação, não só descreve.
3 testes lex offline verdes.

## ✅ Loop 4 — sweep de wiring Yoda↔JFN (gaps achados e corrigidos)
Testes `hermes -z`:
- T2 "tem cartel na UG 133100?" → Yoda usou `terminal`+`curl` e **chutou POST → 405**; a capability ainda
  listava um param `ug` que a rota **não tem**. **FIX:** `/api/cartel` aceita **GET+POST** (robustez contra
  chute de método) + args fiéis (`modo|cnpj|top`, sem `ug`). **Verificado:** curl GET/POST=200; Yoda retorna
  a análise real (Casa Civil→Consórcio RJ Cidadão 56,1% de R$1,24bi…) com conclusão pensada.
- T1 "o que você faz?" → Yoda devolveu o menu de comandos do gateway (aponta p/ /lista). Menor; melhoria
  futura: surfaçar o `/lista` curado direto.
**Aprendizado:** o Yoda executa via `terminal`+`curl` e às vezes chuta o método → rotas GET sensíveis devem
aceitar POST também (ou o gateway ter um executor HTTP que respeite o `metodo` do contrato — TODO gateway).

## 🔎 Loop 5 — Massare (avaliação) + backtest final
**Massare (probe ao vivo):** o framework "pensante" EXISTE (registra cada tese como previsão e promete
cobrar OOS). MAS:
- `/placar`: **44 previsões PENDENTES, 0 resolvidas, hit_rate=null** → as previsões nunca são pontuadas
  contra o realizado. Sem track record OOS, o "honesto vs realizado" não fecha o ciclo.
- `/teses`: n=0 (sem narrativas→ativo no momento). `/cenarios`: ok (fear&greed=8 "medo extremo").
**FIX (sessão nova):** rodar/agendar o **scorer OOS do Massare** (resolver as 44 pendentes contra o preço
realizado no horizonte) → gerar hit_rate real. Provável módulo `massare/validation.py` / `learning.db`.
Sem isso, as previsões são opinião sem accountability — contraria a visão ("previsões pensantes + OOS honesto").
**Aprendizado:** "sistema pensante" exige FECHAR O CICLO (prever → registrar → COBRAR contra o real). O
Massare prevê e registra, mas não cobra. Igual ao Lex (lê o SEI mas não chega ao documento) — a estrutura
existe, falta o último elo de execução.

**Backtest total (00:31):** **~322 testes verdes, ZERO falhas**; 5 hangs de rede (integração PNCP/SEI/Receita
— pré-existentes); `imports_smoke` 141 (codebase importa limpo); `onda2` 10✓ (com rede). Ecossistema saudável
após os 5 loops; `jfn.service` religado (tudo live).

## 🏁 5 LOOPS CONCLUÍDOS
| Loop | Entrega | Verificação |
|---|---|---|
| L1 | /lista curado · OBs enxutas · LLM 9-chaves · Lex discursivo · wiring SIAFE | Yoda retorna os números |
| L2 | frescor/cobertura no topo dos relatórios | "Cobertura: 1.121.306 OBs · 77% CNPJ" |
| L3 | encaminhamento por severidade (acionável) | grav≥3→requerimento; lex offline ✓ |
| L4 | wiring /api/cartel GET+POST + prompt c/ método | curl GET/POST=200; Yoda end-to-end |
| L5 | Massare avaliado + backtest total | ~322 verdes, 0 falhas; Massare honesto |
**2 fixes profundos p/ sessão nova** (alto valor, precisam Chrome/live): coletor SEI → inteiro teor; scorer
OOS do Massare. Tema comum = **fechar o último elo do "sistema pensante"** (a estrutura existe nos dois).

---

# 🔁 SEGUNDA RODADA (Loops 6–10) — pedido 2026-06-09
> Dono: "pesquise e planeje benchmarks em tudo; melhore a codificação; mais 5 loops com playbook, /lista,
> /relatorio, /orgao e Massare; senior em cada área, não admite erro; amplitude de pensamento e honestidade."
> Plano-mestre: `docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md` (4 eixos de benchmark). Cada loop:
> **pesquisar best-practice → gerar/medir artefato real → mudança pequena verificada → checkpoint+commit+doc**.

## ✅ Loop 6 — Fundação de qualidade + scorecard (instrumentação)
**Pesquisa/tese:** o loop media qualidade "a olho"; sem instrumento não dá pra saber se melhorou/regrediu
(foi o que custou a reversão da V2). Benchmark = transformar julgamento em número.

**Execução (tudo verificado):**
1. **`pyproject.toml`** — config única (ruff+pytest+coverage). Ruff calibrado p/ SINAL: mantém pyflakes (F) e
   erros reais; ignora E701/E702 (estilo de uma-linha deliberado). Ruff 733→**43 de baseline** (174 auto-fix
   seguros aplicados: 117 imports mortos + f-strings vazias).
2. **3 BUGS REAIS achados pelo lint e corrigidos** (NameError em runtime que ninguém via):
   - `collectors/sei_portal.py`: `await asyncio.sleep()` no retry **sem `import asyncio`** (é o fallback do
     leitor SEI — crasharia ao reconectar; relevante ao Fix profundo #1).
   - `hermes_goal.py:1144`: `timedelta` usado sem import (crasha o agendador do loop de metas).
   - `server.py:366`: `StreamingResponse` usado sem import (endpoint SSE `/api/hermes` crasharia).
3. **`tests/conftest.py`** — auto-marca módulos de rede como `@pytest.mark.network` (um lugar só) → suíte
   rápida `pytest -m "not network and not integration"` roda limpa, sem os 5-6 hangs.
4. **`tests/test_golden_numbers.py`** (Eixo D) — congela os números canônicos (MGS 1127 OBs/R$136,2M; ITERJ
   UG133100 2457 OBs/R$292,3M; cobertura 1.121.307/76,6% CNPJ). 3 passed. Grita se um refactor driftar valor.
5. **`tools/scorecard.py`** — emite `data/scorecard.{json,md}` + histórico; ruff/LOC/god-files/golden num
   comando, com delta vs. snapshot anterior. Roda em subprocesso (não gasta cota).

**Baselines REAIS gerados** (antes de mexer, lição V2): `/relatorio` MGS (grau_lex AMARELO, fonte REAL) +
`/orgao` ITERJ (HHI 3854,4; Enge Prat 61,2%) em `data/baseline_2026-06-09/` — gold p/ os Loops 7/8 comparar.

**ACERTOS:** instrumentar JÁ pagou — o lint revelou 3 bugs latentes de runtime de graça. Scorecard dá o
"antes/depois" que faltava. Mudanças pequenas/isoladas/verificadas (smoke 141✓ após cada).
**Aprendizado:** `ruff check --output-format json` é a forma robusta de contar (o `--quiet`/"Found N" engana).
**→ Loops 7–10:** usar os baselines + scorecard p/ medir cada melhoria de /relatorio, /orgao, /lista, Massare.

## ✅ Loop 7 — Qualidade do /relatorio (fornecedor) — análise sênior do artefato real
**Pesquisa/avaliação (auditor sênior sobre o MGS real):** o relatório tinha fatos soltos não-conectados.
**Entregas (commit c37f339):**
- **RF-04 — controle societário posterior a receita pública**: ingresso no QSA em data > R$ já pagos
  (MGS: sócio entrou 2024-12-11 após R$35,7M/380 OBs, 26% do total). Geral, threshold R$1M+15%, honesto.
- **RF-05 — CNAE × objeto**: atividade-fim registrada incompatível com o objeto contratado. **Achado de
  dados:** `contratos.objeto` do SIAFE só guarda "Aditivos:N" → usei o objeto REAL do **TCE-RJ**
  (`tcerj_itens`). MGS: CNAE de internet (6319-4) × objeto de limpeza. Conservador (zero-overlap após
  remover boilerplate) = sem falso-positivo.
- **Crescimento honesto**: "+11133%" (1º×último ano parciais) → fator **pico/base** com ressalva de parciais.
**ERRO PEGO (lição do handoff aplicada):** 1ª versão só entrou no MD; o **PDF entregue NÃO continha** RF-04/05
(3 renderizadores; PDF usa lista própria na seção 11). Fix: wiring via **fonte única `_red_flags(ctx)`** em MD
+ PDF. Verificado com **pypdf extraindo do PDF** (não só grep no MD). 20 testes de relatório + golden verdes.
**Aprendizado:** o objeto contratual fica no TCE-RJ, não no SIAFE; e *sempre* verificar o artefato ENTREGUE.

## ✅ Loop 8 — Qualidade do /orgao — pagamentos recorrentes idênticos
**Pesquisa/avaliação (auditor sênior sobre o ITERJ real):** o sinal mais forte estava nos dados de pagamento
e não era explorado — a Enge Prat recebe **valores exatos repetidos** (9× R$3.708.333,33 em 2022; 9×
R$7.362.133,33 em 2024-26 = R$66,3M). É a assinatura de parcela fixa **e** red flag ACFE (identical payments).
**Entrega (commit 67b3387):** `_recorrentes_identicos()` (grupos fornecedor×valor exato ≥4× acima de R$50k) →
**seção 1-C** no MD + tabela no PDF (FPDF) + nota no parecer conectando ao fornecedor dominante (caracterizar
contrato/objeto/**medição** e aderência à **finalidade do órgão** — instituto de terras pagando R$179M a firma
de engenharia). **Verificado no PDF entregue** (pypdf: 1-C + parecer presentes). 3 testes orgao verdes.
**Aprendizado:** o ouro estava no padrão dos valores (não só no HHI). Repetir a checagem do PDF (Loop 7) já é hábito.

## ✅ Loop 9 — /lista + playbook
**Avaliação:** o /lista curado não surfaçava o sistema pensante de **mercado** (Massare — 6 caps existentes,
invisíveis) nem o status da coleta. **Entrega (commit b96eecc):** 2 grupos novos no `_MENU_PUBLICO`
(📈 Massare: cenários/previsão/placar-OOS · 🛰️ Coleta: siafe_status), ids reais do capabilities.yaml,
exemplos NL fiéis. Menu segue enxuto (14/5 grupos). 26 testes skilltree verdes. **Playbook §6**: disciplina
de qualidade p/ IAs executoras (scorecard+delta, suíte rápida, **verificar o PDF entregue**, objeto real=TCE-RJ,
honestidade). **Aprendizado:** "toda skill no /lista" vale p/ o sistema pensante inteiro — Massare é parte dele.

## ✅ Loop 10 — Massare: backtest OOS em TODOS os pregões + edge honesto
**Pedido do dono:** "reproduza como backtest de suas previsões como os mercados agiram; avalie todos os
pregões possíveis." **Entrega (commit efb33f7):** `massare/backtest.py` roda walk-forward (só passado) sobre
toda a série — **356.544 pregões** (26 ativos × horizontes 5/10/21). `engine.walk_forward` passa a expor a
**taxa-base** do mercado; `predict_today` carrega `edge_oos` + `tem_skill`.
**ACHADO HONESTO (o ponto do loop):** edge médio do ensemble = **−0,0127** (só **20/78** séries com edge>0).
Ex. matador: **^GSPC 21d acerta 61,9%** mas o ingênuo (S&P sobe 65,6% das vezes) é melhor → edge −0,036,
**sem skill** — o "62%" enganava. Skill real só em FX/dólar/ETH-longo (USDBRL 21d **+0,054**). **Sem Brier
calibrado** (sinal é direcional, não probabilístico — reportá-lo seria inventar). As 44 logadas têm alvo no
futuro (preço até 06-08) → pendentes, honesto. 3 testes verdes.
**Aprendizado:** track record só é honesto contra a **taxa-base certa**; hit-rate alto sem baseline mente.
Fechou o último elo do "sistema pensante" de mercado: agora o Massare sabe (e diz) onde NÃO tem skill.

## ✅ Loop 11 — Qualidade do parecer Lex (R11 CNAE×objeto)
**Avaliação (analista de tomada de contas):** o parecer Lex é sofisticado (achados R2/R5/R8/R12, dosimetria,
encaminhamento) mas **não tinha** o sinal estrutural do RF-05 do /relatorio. **Entrega (commit 127bbf6):**
achado **R11 — atividade-fim (CNAE) incompatível com o objeto contratado** (empresa de prateleira/fachada;
arts. 62-63 Lei 14.133; art. 337-F CP). Reusa `_termos_significativos` (DRY, import já existente, sem
circular); objeto REAL do TCE-RJ; conservador (zero-overlap). Flui à matriz/detalhamento/PDF pela mesma lista
`achados` que R5/R8. 2 testes offline (dispara em internet×limpeza; não em limpeza×limpeza).
**Aprendizado:** um sinal forte deve atravessar os produtos do sistema pensante — /relatorio E parecer Lex.

## ✅ Loop 12 — Massare honesto end-to-end (/placar com backtest)
**Avaliação:** "O Massare acerta?" (`/api/massare/placar`) devolvia só o diário logado (44 pendentes, hit_rate
null) — escondia o track record real. **Entrega (commit 211cba0):** `/placar` agora inclui `backtest_oos`
(hit-rate 0,5445 vs piso ingênuo 0,5572 → edge −0,0127; 20/78 séries com skill; 356k pregões). `backtest.py`
grava `backtest.json` estável + `resumo_overall()`. **Verificado END-TO-END** (serviço religado + curl). 4 testes.
**Aprendizado:** honestidade é arquitetural — o endpoint que o dono consulta tem de mostrar o número que cobra o agente.

## ✅ Loop 13 — Caça a bugs reais no baseline de lint (43→39)
**Pesquisa:** revisei os 43 ruff restantes atrás de bug real (não cosmético). **Entrega (commit 78f2a7b):**
- **router.py (bug real latente):** `classify()`/`summarize()` definidos **2×** na mesma classe → o Python
  descartava as versões Ollama-first silenciosamente (F811). Removidas as mortas; risco de alguém corrigir a
  errada eliminado. Comportamento idêntico.
- rules/engine.py: removida constante morta `JANELA_DIAS` — **confirmei que a regra de fracionamento NÃO tinha
  bug** (a janela de 30d é aplicada via `strftime` mensal).
- lex_base_empirica.py: removida query buscada e descartada (economiza 1 query).
- Os 11 F841 restantes são no script de debug `diagnose_siafe.py` — baixo valor, não tocados.
**Aprendizado:** o lint paga bugs (Loop 6: 3 NameError; Loop 13: duplicata silenciosa) — mas é preciso LER cada
um: a maioria dos F841 era código morto inócuo, não bug. Honestidade vale também na triagem do lint.

## ✅ Loop 14 — Lex: R6 troca de controle + helper compartilhado (DRY)
**Entrega (commit 77de9c6):** espelha o RF-04 do /relatorio no Lex (achado **R6** — controle alterado após
receita pública = sucessão/interposição/laranja). Extraí o helper PURO `troca_controle_societaria(emp,
pagamentos)` em inteligencia.py; RF-04 e R6 o reusam (DRY, sem circular). 4 testes (dispara/não-dispara nos
dois produtos). **Aprendizado:** sinal forte atravessa os produtos via **helper compartilhado**, não cópia.

## ✅ Loop 15 — Gate de lint no pre-commit (best-effort)
**Entrega (commit 352f2e7):** `tools/precommit_ruff.sh` (versionado) roda ruff só nos `.py` STAGED e avisa
sobre lint novo (não bloqueia; ignora `_SANDBOX/`, `tools/debug/`). Ligado ao hook local. Playbook §6 documenta.
Evita lint novo nos arquivos tocados sem brigar com o baseline (39). **Aprendizado:** gate por arquivos-staged
≠ gate global — ratcheta sem brigar com o legado.

## ✅ Loop 16 — Honestidade na concentração geográfica do /orgao
**Entrega (commit 0d0e086):** "61% PETROPOLIS" era marcado 🟡 como indício geográfico — mas a cidade-topo
do ITERJ tem **1 só fornecedor** (Enge Prat) → é a concentração de FORNECEDOR (Seção 1) restada, não sinal
independente. Agora: cidade-topo com 1 fornecedor → nota ℹ️ honesta; multi-empresa → mantém 🟡 (fachada real).
**Aprendizado:** não dupla-contar o mesmo sinal sob rótulos diferentes — inflar red flags é desonesto.

## ✅ Loop 17 — Bug Município/UF no perfil cadastral do /relatorio
**Entrega (commit 4e7ee18):** perfil mostrava "—/—" embora o endereço fosse MARICA/RJ (enrich sem município/UF
separados). Fallback ao endereço do cruzamento (mesma fonte da "Cidade-sede"). Corrigido nos 2 renderizadores
(MD+PDF), verificado no PDF entregue. **Aprendizado:** dado já existe noutra seção — reaproveitar antes de exibir "—".

## ✅ Loop 18 — Massare: teses carregam track record OOS por ativo
**Entrega (commit 4ba84f7):** `acerto_oos` das teses vinha do scoreboard logado (vazio) → null. Agora puxa do
**backtest** (`backtest.por_simbolo(ativo,21)`): hit_rate + edge + `tem_skill`. Tese sobre Ibovespa mostra
`tem_skill=False` (edge −0,021); USDBRL `True` (+0,054). **Aprendizado:** a opinião (tese) tem de carregar a
evidência (track record) do ativo que ela aposta.

## ✅ Loop 19 — Dossiê 360: red flags estruturais no score de convergência
**Entrega (commit 9fd5b23):** o dossiê convergia 3 sinais; faltavam os estruturais de fachada/laranja que o
/relatorio (RF-04/05) e o Lex (R6/R11) já detectam. Agora `_red_flags_estruturais` (CNAE×objeto + troca de
controle) alimenta `red_flag_edital` → MGS 25→30,3. Renderiza no **PDF entregue** (verificado: fachada/
prateleira/interposição/data). **Aprendizado:** o mesmo sinal forte agora converge em **4 produtos**
(/relatorio · Lex · dossiê · score) — sistema pensante coerente.

## ✅ Loop 20 — Frescor do backtest no /placar
**Entrega (commit 778d1b3):** o /placar mostrava o backtest sem dizer a cobertura temporal. Agora
`overall.dados_ate` (na corrida) + `resumo_overall` compara com o preço ao vivo → `preco_mais_recente` +
`defasado`. Verificado live (dados_ate 2026-06-08, defasado false). **Aprendizado:** número sem data de
cobertura mente por omissão quando envelhece.

## ✅ Loop 21 — /anomalias: filtrar ruído intra-governamental
**Avaliação do artefato real:** **12/20** das top anomalias eram entidades GOV (Estado do RJ, Ministério da
Fazenda/Economia, INSS) — transferências intra-gov/tributos, não fornecedores de compra. **Entrega (commit
16ce984):** `_eh_nao_fornecedor` (regex intra-gov/tributo) filtra o ranking por padrão (sobre-busca; robusto a
acento/caixa); `incluir_gov=1` reinclui. Verificado: 12/20→**0/20**; topo agora são fornecedores reais com red
flags reais. 2 testes. **Aprendizado:** o sinal só aparece depois de tirar o ruído estrutural (pagamento
obrigatório ≠ anomalia de compra) — mesma família do "ubíquos" do cartel.

## ✅ Loop 22 — Lint: resolver os 2 F821 forward-ref (39→37)
**Entrega (commit c1cc1fd):** server.py (HermesGoalAgent) e cnpj.py (Empresa) usavam anotação string com import
lazy → F821. Bloco `TYPE_CHECKING` (sem custo runtime). Silencia o aviso do gate de lint. **Aprendizado:**
forward-ref legítimo se resolve com TYPE_CHECKING, não suprimindo a regra.

## 🏁 RODADA ESTENDIDA (Loops 6–20) — 15 loops
| # | Entrega | Commit |
|---|---|---|
| 6 | Fundação: scorecard·golden·ruff 733→43·3 bugs reais | 0552059 |
| 7 | /relatorio RF-04·RF-05·crescimento honesto | c37f339 |
| 8 | /orgao pagamentos recorrentes idênticos | 67b3387 |
| 9 | /lista Massare+SIAFE·playbook §6 | b96eecc |
| 10 | Massare backtest 356k pregões + edge | efb33f7 |
| 11 | Lex R11 (CNAE×objeto) | 127bbf6 |
| 12 | /placar honesto (backtest_oos) | 211cba0 |
| 13 | lint 43→39 (dup router·código morto) | 78f2a7b |
| 14 | Lex R6 + helper compartilhado | 77de9c6 |
| 15 | gate ruff no pre-commit | 352f2e7 |
| 16 | /orgao honestidade geográfica | 0d0e086 |
| 17 | fix Município/UF | 4e7ee18 |
| 18 | teses Massare track record OOS | 4ba84f7 |
| 19 | dossiê red flags estruturais | 9fd5b23 |
| 20 | frescor do backtest no /placar | 778d1b3 |
**Tema:** instrumentar e ser honesto. Sinal de fachada (CNAE×objeto, troca de controle) converge em 4 produtos
(/relatorio·Lex·dossiê·score). Massare confessa onde não tem skill. Lint pagou 4 bugs/duplicatas. Ruff 733→39.

## 🏁 SEGUNDA RODADA (Loops 6–10) — CONCLUÍDA
| Loop | Entrega | Verificação | Commit |
|---|---|---|---|
| L6 | Fundação: pyproject, ruff 733→43, conftest, golden numbers, scorecard, **3 bugs reais** | 287 testes verdes; pypdf | 0552059 |
| L7 | /relatorio: RF-04 controle societário · RF-05 CNAE×objeto · crescimento honesto | PDF entregue (pypdf) | c37f339 |
| L8 | /orgao: pagamentos recorrentes idênticos (ACFE) — seção 1-C + parecer | PDF entregue (pypdf) | 67b3387 |
| L9 | /lista: surfaçar Massare/SIAFE · playbook §6 (disciplina de qualidade) | 26 testes skilltree | b96eecc |
| L10 | Massare: backtest 356k pregões + edge honesto vs taxa-base | 3 testes; achado real | efb33f7 |
**Tema da rodada:** *instrumentar e fechar ciclos com honestidade.* Cada loop trocou "acho que melhorou" por
número verificável; o lint pagou 3 bugs; os relatórios ganharam análise que **conecta fatos**; o Massare agora
**cobra a si mesmo** contra a taxa-base. Plano-mestre: `docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md`.

## APRENDIZADO TRANSVERSAL (atualizado)
- O dono deu **autonomia total** (mexer em tudo — JFN/Lex/Massare/Hermes/Yoda — e religar à vontade). Minha
  cautela com "o que está vivo" era o gargalo, não o sistema. Fluir > hesitar (mantendo verificação do artefato).
- Teste end-to-end (`hermes -z`) > curl: pega gaps de roteamento que o curl não vê (rota existir ≠ Yoda saber usar).
- **Instrumentar antes de melhorar**: sem scorecard/golden, "melhor" é opinião. O lint sozinho pagou 3 bugs reais.
