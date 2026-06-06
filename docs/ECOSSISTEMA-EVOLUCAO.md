# Ecossistema "Mestre Jorge" — Plano de Evolução

> Documento de arquitetura consolidado. Agentes: **JFN** (auditor de compliance das finanças do RJ), **Yoda** (maestro/bot Telegram), **Massare** (super-agente financeiro/mercado), **Lex** (agente jurídico). Roda em VM Ubuntu GCP, tudo Python. JFN expõe FastAPI no barramento `127.0.0.1:8000`; banco SQLite `compliance.db` (~612k OBs, 2019–2026).
>
> Última consolidação: 2026-06-06. Base: pesquisas estruturadas + 3 lentes (Pragmático/MVP, Visionário/SOTA, Cético/Risco) por agente.

---

## 1. Sumário executivo

O ecossistema já tem a fundação certa (FastAPI + SQLite + coletores Playwright + barramento), e a evolução não exige reescrita: ela exige **subir de "consulta" para "detecção de risco calibrada e explicável"** sem quebrar o que funciona. O maior ganho imediato vem de rodar **PyOD (ECOD + IForest)** e **três regras determinísticas portadas do RUBLI/yangwenli** (same-day threshold splitting, concentração de fornecedor, fracionamento) sobre os 612k de OBs que já estão no banco, expondo tudo como endpoint `/anomalias` + skill no Yoda. Para o Yoda, a prioridade é UX (aiogram 3.x com botões inline + confirmação humana), roteamento por regra antes do LLM e memória mínima (Mem0 com 3–4 fatos) — adiando Agent SDK e semantic-router até que logs provem necessidade. Os três gargalos de infra (SIAFE ADF anti-Playwright, SEI bloqueado por WAF, enriquecimento Receita/PNCP instável) têm soluções ranqueadas, com preferência por **acesso oficial/replay HTTP/cache antes de evasão**. Transversalmente, qualidade de dado, proveniência, LGPD (mascarar CPF de sócio), cifragem em repouso e reprodutibilidade forense de cada relatório são pré-condições — não opcionais — porque a saída do JFN pode virar peça de controle externo (TCE-RJ/TCU). A regra de ouro: **score é indício interno, nunca acusação pública**.

---

## 2. Planos por agente

### 2.1 JFN — auditor de compliance

#### (a) Ferramentas a adotar

| Ferramenta | Para que | URL | Esforço |
|---|---|---|---|
| PyOD 3 (+ ADEngine) | Detecção de anomalia benchmark-backed sobre as 612k OBs; ensemble ECOD/COPOD/IForest/LODA (robustos em tabular sem rótulo); ADEngine roteia detector via ADBench/TSB-AD | https://github.com/yzhao062/pyod | médio |
| RUBLI / yangwenli (Apache-2.0) | Plataforma de detecção de corrupção em compras públicas, MESMA stack (FastAPI+SQLite WAL). Reutilizar 9 features, regressão logística calibrada por setor, PU-learning (Elkan-Noto), SHAP, pipeline ARIA | https://github.com/rodanaya/yangwenli | alto |
| Camoufox | Anti-detect browser (fork Firefox, patches stealth em C++, 0% headless-detection) p/ coletores TFE pegos por fingerprint | https://github.com/daijro/camoufox | médio |
| Claude Computer Use tool | Operar SIAFE ADF/Oracle por screenshot+mouse/teclado como humano (ignora selectors); batch noturno supervisionado | https://docs.claude.com/en/docs/agents-and-tools/tool-use/computer-use-tool | alto |
| Splink (backend DuckDB) | Resolução de entidade/dedup de fornecedores (razão social, CNPJ-raiz, sócios, endereço); escala ~1M registros em ~1min | https://github.com/moj-analytical-services/splink | médio |
| DuckDB | Camada OLAP sobre o compliance.db: queries 20–50x mais rápidas, lê o próprio SQLite; SQLite p/ ingestão, DuckDB p/ análise/relatórios | https://github.com/duckdb/duckdb | baixo |
| Docling + Granite-Docling-258M (IBM) | Parsing de docs gov (editais, contratos, notas de empenho, integra SEI) preservando tabelas/layout p/ alimentar Lex | https://github.com/docling-project/docling | médio |
| Cliente PNCP (API consulta pública) | Fonte oficial de licitações/contratos p/ enriquecer e validar OBs (modalidade, valor homologado vs. pago); API pública sem auth; fallback quando Receita cai | https://pncp.gov.br/api/consulta/swagger-ui/index.html | médio |

#### (b) Funções/endpoints novos

| Nome | Descrição | Prioridade |
|---|---|---|
| Score de anomalia por OB (ensemble PyOD) | ECOD+COPOD+IForest agregados sobre features valor/fornecedor/órgão/temporalidade; persiste tabela `ob_anomaly`; expõe `GET /anomalias`; skill `/anomalias` no Yoda | P0 |
| Detector de red-flags de compras (port RUBLI) | 9 features sobre dados RJ: fracionamento same-day, concentração fornecedor por UG (>30%), licitante único, dispensa/inexigibilidade, sobrepreço vs. mediana setorial; cada flag com peso e parecer textual | P0 |
| Camada DuckDB de relatórios | Migrar queries pesadas dos Relatórios de Fornecedor/Órgão p/ DuckDB lendo o SQLite; séries por UG, top fornecedores, evolução 2019–2026 | P0 |
| Resolução de entidade de fornecedores (Splink) | Unificar por CNPJ-raiz/razão social/endereço; tabela canônica `fornecedor_id -> [OBs]`; pré-requisito p/ grafo e concentração | P1 |
| Grafo fornecedor-órgão + co-contratação | Grafo bipartite (fornecedor x UG) + co-contratação p/ cartel/bid-rigging; começar com networkx antes de GNN (GraphSAGE/GAT) | P2 |
| Coletor SIAFE via Computer Use (batch supervisionado) | Extração da UG travada do ADF/Oracle por Computer Use, agendado à noite, checkpoint + replay HTTP quando possível | P1 |
| Coletores Camoufox + rotação de IP/proxy | Trocar navegador stealth dos coletores TFE/portais por Camoufox; proxy residencial p/ SEI | P1 |
| Extração de docs gov (Docling/VLM + validação hierárquica) | Editais/contratos/notas → dados estruturados (300 DPI → VLM, contexto sequencial, checagem de somatórios por nível ~84% acc); alimenta Lex | P1 |
| Fallback PNCP no enriquecimento | Quando Receita/PNCP-enriquecimento dá INDISPONIVEL, consultar API pública PNCP por contrato/fornecedor; cache local + marcação de procedência | P1 |
| Explicabilidade SHAP no Relatório | Anexar contribuições SHAP de cada flag/score ao Relatório (por que este fornecedor é alto risco); fortalece parecer do Lex e defensibilidade TCE/TCU | P2 |

#### (c) Técnicas de IA

- **PU-learning (Elkan-Noto 2008)**, piso c≈0.30: treinar com apenas casos confirmados de irregularidade como positivos e o resto como não-rotulado — adequado a auditoria sem rótulos negativos.
- **Calibração por setor/UG**: 1 modelo global + modelos por órgão (RUBLI usa 13: 1 global + 12 setoriais) para que o limiar respeite a norma de cada UG (ex.: ITERJ UG 133100), evitando falsos positivos cross-setor.
- **Ensemble não-supervisionado com roteamento benchmark-informed** (PyOD ADEngine sobre ADBench/TSB-AD): escolher detector pelo tipo de dado, agregando ECOD/COPOD/IForest.
- **Detecção de fracionamento same-day-threshold-splitting**: agrupar OBs por fornecedor+órgão+data e somar contra o limite legal de dispensa.
- **Stealth em nível de binário** (Camoufox, patches C++) > stealth em JS (playwright-extra está desatualizado desde 2023 e é detectado); combinar com proxy residencial (stealth não cobre reputação de IP/TLS).
- **Computer Use por visão** (screenshot + ações) para apps legados/ADF que ignoram selectors; batch por causa da latência, com humano no loop.
- **Resolução de entidade probabilística** com term-frequency adjustments (Splink) sobre CNPJ-raiz+razão social+endereço, backend DuckDB.
- **OLAP embarcado**: SQLite (OLTP/ingestão) + DuckDB (análise/relatórios) lendo o mesmo arquivo — padrão complementar, não migração.
- **Extração de PDF gov por VLM a 300 DPI** com contexto sequencial entre páginas e validação por somatório hierárquico (~84% acc numérica).
- **Explicabilidade obrigatória (SHAP)** acoplada a cada score/flag para tornar o achado auditável perante TCE-RJ/TCU.

#### (d) Síntese das 3 lentes

**Consenso (as três lentes concordam):**
- PyOD + 3 regras RUBLI sobre os dados que já existem é o caminho — não reescrever nada para começar.
- Expor via endpoint `/anomalias` + skill no Yoda (reaproveita o barramento).
- Camoufox resolve fingerprint do TFE, mas **não** resolve o filtro-por-UG do ADF nem a reputação de IP do SEI.
- Score precisa de explicabilidade (no mínimo `top_features` do ECOD; SHAP é fase 2).
- SIAFE/ADF e SEI são problemas mais caros — não atacar na primeira onda.

**Divergências:**
- **MVP** quer ECOD + 3 regras no mesmo dia, calibração manual de corte com 15 exemplos, e adia SHAP/PU-learning/Computer Use. **Visionário** quer já o ensemble completo (ECOD+COPOD+IForest+LODA), regressão logística calibrada por setor, PU-learning, grafo de fraude e relatório agentico gerado por LLM. **Resolução:** começar MVP, evoluir para o desenho do Visionário sob calibração contra ground-truth.
- **Cético** impõe pré-condições que as outras lentes não priorizam: qualidade de dado + quarentena (Great Expectations) ANTES de qualquer ML (senão "anomalia" = erro de ingestão); proveniência por enriquecimento (INDISPONIVEL ≠ 0/null); LGPD (mascarar CPF de sócio, SQLCipher); **score = indício interno, nunca acusação pública** (risco de dano moral); replay HTTP preferível a Computer Use (custo/fragilidade); reprodutibilidade forense (hash do dataset + commit + thresholds no rodapé do PDF). **Resolução:** as travas do Cético entram como Onda 1 transversal (ver §6), não como fase posterior.

---

### 2.2 Yoda — maestro / bot Telegram

#### (a) Ferramentas a adotar

| Ferramenta | Para que | URL | Esforço |
|---|---|---|---|
| Claude Agent SDK (Python) | Reescrever núcleo como orquestrador supervisor; JFN/Massare/Lex viram `AgentDefinition` com handoff nativo (atenção: limite de 1 nível de subagente; consumo de tokens) | https://code.claude.com/docs/en/agent-teams | alto |
| vLLM Semantic Router | Roteador semântico pré-LLM (LoRA+ModernBERT) p/ classificar pedido antes de gastar token; faz semantic tool filtering; roda local na VM | https://github.com/vllm-project/semantic-router | médio |
| Mem0 | Memória de longo prazo do chat único do Jorge (UGs de interesse, fornecedores investigados, formato preferido) via ADD/UPDATE/DELETE/NOOP | https://github.com/mem0ai/mem0 | médio |
| Letta (ex-MemGPT) | Gestão de contexto estilo SO p/ investigações longas Lex+JFN+Massare que estouram a janela | https://github.com/letta-ai/letta | médio |
| aiogram 3.x | Camada Telegram async; InlineKeyboardMarkup/callback_data p/ menus de skill, confirmações humanas, paginação | https://docs.aiogram.dev/en/latest/ | baixo |
| API PNCP — Consultas | Enriquecer respostas e cruzar com OBs do JFN; REST público sem cadastro; fallback quando Receita cai | https://pncp.gov.br/api/consulta/swagger-ui/index.html | baixo |
| LangMem (LangChain) | Memória caso o Yoda adote LangGraph; alternativa a Mem0/Letta no ecossistema LangChain | https://github.com/langchain-ai/langmem | médio |
| Braintrust / detectores de alucinação + eval | Pipeline de avaliação com ground-truth p/ medir roteamento e pareceres antes de chegar ao Jorge; bloquear/reescrever/escalar respostas de alto risco | https://www.braintrust.dev/articles/best-hallucination-detection-tools-2026 | médio |

#### (b) Funções/endpoints novos

| Nome | Descrição | Prioridade |
|---|---|---|
| Router semântico de intenção (NLU → skill) | Mapear pedido livre p/ skill/agente certo com score de confiança; abaixo do limiar, perguntar (desambiguação) em vez de chutar | P0 |
| Memória persistente do chat do Jorge | Mem0/Letta lembra UGs (ITERJ=133100), fornecedores/órgãos investigados, período padrão (2019–2026), formato (PDF+XLSX); comandos `/esquecer` e `/memoria` | P0/P1 |
| Skills com botões inline + confirmação humana | `/relatorio`, `/orgao`, `/mercado`, `/lista` como InlineKeyboardMarkup; confirmação antes de ação cara (gerar PDF/XLSX, disparar coletor); paginação | P0 |
| Fallback PNCP direto no Yoda | Quando enriquecimento do JFN dá INDISPONIVEL, chamar API pública PNCP e devolver o que houver | P1 |
| Tratamento de erro humano dos 3 gargalos | Mensagens claras + fallback p/ SIAFE/Playwright, SEI/WAF, Receita/PNCP (ex.: "SEI bloqueado pelo IP da VM; preciso de proxy residencial") | P0/P1 |
| Catálogo de tools curado (function-calling enxuto) | Expor só 5–6 tools (relatorio_fornecedor, relatorio_orgao, mercado, juridico_lex, lista, pncp_fallback) com boas descrições | P1 |
| Log de interação (pedido → rota → tool → resultado) | CSV/SQLite simples p/ decidir com dados reais quando vale subir semantic-router/Agent SDK/Letta | P0 |

#### (c) Técnicas de IA

- **Roteamento por regra/regex antes do LLM**: classificador trivial (fornecedor, órgão, UG, dólar/ibov, processo/SEI) cobre ~80% dos pedidos; só cai no Claude quando a regra não casa (corta token no caminho feliz).
- **Semantic tool filtering**: reduzir o catálogo de tools entregue ao modelo por contexto, cortando custo e alucinação de function-calling (após log provar ambiguidade real).
- **Padrão supervisor** com handoff nativo (Agent SDK): Opus 4.8 no Yoda-maestro, Sonnet nos subagentes p/ custo; Lex+JFN coexistem no mesmo nível coordenados pelo Yoda (não Lex chamando JFN — limite de 1 nível).
- **Separação de memória**: Mem0 = preferências/fatos persistentes; Letta = estado de uma investigação longa específica. Não usar os dois para a mesma coisa.
- **Human-in-the-loop** antes de ações caras (rodar coletor, emitir parecer).
- **Eval com ground-truth** p/ medir se roteamento e pareceres estão corretos (gasto público = alto risco jurídico).

#### (d) Síntese das 3 lentes

**Consenso:** aiogram 3.x é o maior ganho/menor esforço (UX com botões inline + confirmação humana); memória escopada ao chat único do Jorge com poucos fatos; PNCP como fallback direto traz ganho visível ("menos INDISPONIVEL na tela").

**Divergências:**
- **MVP** é enfático: **NÃO** reescrever no Agent SDK ainda (over-engineering, limite de 1 nível, queima de token) — congelar o roteador atual; roteamento por regra/regex antes do LLM (sem semantic-router); Mem0 mínimo (3–4 fatos no system prompt); **pular Letta** (problema de janela ainda não existe); logar tudo para decidir o futuro com dados. **Visionário** quer o oposto: reescrita como orquestrador supervisor (Agent SDK), semantic-router na frente de tudo, Mem0 + Letta com papéis distintos. **Resolução:** seguir MVP agora; o log de interação é o gatilho objetivo que libera as peças do Visionário (Onda 2/3) quando provarem necessidade.

---

### 2.3 Massare — super-agente financeiro/mercado

> Massare: predição diária (dólar, Ibov, ouro, WTI), aprendizado contínuo, base BR+EUA. As pesquisas estruturadas e as 3 lentes deste lote focaram JFN e Yoda; abaixo, as recomendações aplicáveis a Massare derivadas do material comum (PNCP/dados, memória, eval, fallback robusto).

#### (a) Ferramentas a adotar

| Ferramenta | Para que | URL | Esforço |
|---|---|---|---|
| API PNCP — Consultas | Cruzar contratos/atas públicas com séries de mercado quando relevante a gasto público; REST público sem cadastro | https://pncp.gov.br/api/consulta/swagger-ui/index.html | baixo |
| DuckDB | OLAP embarcado p/ séries históricas BR+EUA e backtesting de predição (zero-copy de DataFrames) | https://github.com/duckdb/duckdb | baixo |
| Mem0 | Persistir preferências do Jorge sobre formato/ativos de interesse, reaproveitando a mesma camada de memória do Yoda | https://github.com/mem0ai/mem0 | médio |
| Braintrust / eval | Backtesting/avaliação da predição diária contra ground-truth (acerto direcional, erro), antes de a resposta chegar ao Jorge via Yoda | https://www.braintrust.dev/articles/best-hallucination-detection-tools-2026 | médio |

#### (b) Funções/endpoints novos

| Nome | Descrição | Prioridade |
|---|---|---|
| Skill `/mercado` via Yoda com fallback de fonte | Predição diária roteada pelo Yoda; degradar com transparência quando fonte de dados cair (nunca inventar número) | P0 |
| Proveniência da fonte de mercado | Campo fonte+timestamp+status por cotação; INDISPONIVEL ≠ 0/null (mesma disciplina do enriquecimento do JFN) | P1 |
| Backtesting de predição (DuckDB) | Medir acerto direcional histórico por ativo; calibrar confiança exibida ao Jorge | P1 |

#### (c) Técnicas de IA

- **Aprendizado contínuo com versionamento de modelo+threshold+dataset** (mesma disciplina anti-drift do JFN) para poder reverter e auditar uma predição passada.
- **Degradação transparente**: dependência externa que cai vira mensagem clara + última cotação com timestamp, nunca valor inventado.
- **Eval com ground-truth** (acerto direcional) como atributo de primeira classe.

#### (d) Síntese das 3 lentes

Não houve lentes dedicadas a Massare neste lote. Por consistência arquitetural, valem os consensos transversais: **MVP** = expor `/mercado` com fallback e proveniência, reaproveitar Mem0/DuckDB já adotados; **Visionário** = backtesting contínuo e calibração de confiança; **Cético** = nunca exibir número inventado, versionar modelo/dataset, e tratar predição como estimativa (linguagem condicional), não como certeza.

---

### 2.4 Lex — agente jurídico

> Lex: Direito Administrativo / controle externo (TCU/TCE-RJ). Lê a íntegra de processos SEI e cruza red flags (dispensa/inexigibilidade, fracionamento, sobrepreço, aditivos) com os dados de pagamento; emite parecer. Depende criticamente de destravar o SEI (gargalo nº2) e do cruzamento com os scores/flags do JFN.

#### (a) Ferramentas a adotar

| Ferramenta | Para que | URL | Esforço |
|---|---|---|---|
| Docling + Granite-Docling-258M (IBM) | Parsing da íntegra SEI/editais/contratos preservando tabelas/layout p/ extração estruturada; roda local | https://github.com/docling-project/docling | médio |
| Proxy residencial / acesso oficial SEI | Destravar leitura da íntegra (WAF bloqueia IP GCP); preferir convênio/LAI antes de evasão | (acesso/convênio; sem URL específica) | médio |
| SHAP (via JFN) | Receber as contribuições SHAP de cada red-flag p/ embasar o parecer com justificativa auditável | https://github.com/yzhao062/pyod (pipeline JFN) | médio |
| Claude Agent SDK (subagente Lex) | Lex como `AgentDefinition` coordenado pelo Yoda, coexistindo com JFN em investigação cruzada (mesmo nível) | https://code.claude.com/docs/en/agent-teams | alto |

#### (b) Funções/endpoints novos

| Nome | Descrição | Prioridade |
|---|---|---|
| Cruzamento integra-SEI × pagamento (OBs) | Pipeline que liga achados da íntegra (modalidade, aditivos, sobrepreço) às OBs/flags do JFN p/ compor o parecer | P1 |
| Parecer com linguagem condicional | Saída sempre em "merece apuração", nunca "houve fraude"; valida juridicamente antes de qualquer saída externa | P0 |
| Extração estruturada de documentos gov | Docling/VLM a 300 DPI + validação por somatório hierárquico; alimenta o cruzamento | P1 |
| Validação jurídica das saídas do Yoda (gate) | Lex revisa pareceres/afirmações de risco antes de chegar ao Jorge (gasto público = alto risco jurídico) | P1 |

#### (c) Técnicas de IA

- **Cruzamento red-flag × dado de pagamento**: cada flag (dispensa/inexigibilidade, fracionamento, sobrepreço, aditivos) ancorada na OB/processo citado.
- **Extração por VLM a 300 DPI** com contexto sequencial entre páginas e checagem de somatórios por nível hierárquico (~84% acc numérica).
- **Explicabilidade SHAP** acoplada para tornar o parecer defensável perante TCE-RJ/TCU.
- **Linguagem condicional obrigatória** e validação jurídica antes de saída externa.

#### (d) Síntese das 3 lentes

Não houve lentes dedicadas a Lex. Aplicam-se diretamente as travas do **Cético/JFN**: score/flag é indício, parecer público só afirma fatos verificáveis (valor, data, modalidade, fornecimento), CPF de sócio mascarado, e cada parecer reproduzível (hash do dataset + versão dos thresholds). **MVP**: parecer com linguagem condicional e cache da íntegra já lida. **Visionário**: cruzamento integral automatizado SEI×OB com narrativa gerada por LLM sobre scores+SHAP.

---

### 2.5 Infra

#### (a) Ferramentas a adotar

| Ferramenta | Para que | URL | Esforço |
|---|---|---|---|
| Great Expectations (qualidade de dado) | Testes no pipeline de ingestão de OBs (não-nula, valor>0, CNPJ válido módulo-11, UG em domínio, soma OB = soma itens, dedup por hash OB+data+valor); quarentena, nunca descarte silencioso | (qualidade de dados; sem URL no insumo) | médio |
| SQLCipher | Cifrar o compliance.db em repouso (VM GCP) | (cifragem SQLite; sem URL no insumo) | médio |
| Secret Manager GCP + `.env` | Secrets fora do repo; rotacionar token no remote git (já na memória — fazer agora) | (GCP) | baixo |
| DuckDB | Camada OLAP sobre o mesmo arquivo SQLite (compartilhada JFN/Massare) | https://github.com/duckdb/duckdb | baixo |
| Proxy residencial dedicado | Reputação de IP p/ SEI; isolar coletores "agressivos" com rate-limit humano e kill-switch | (acesso) | médio |

#### (b) Funções/endpoints novos

| Nome | Descrição | Prioridade |
|---|---|---|
| Quarentena de ingestão | Linhas que falham nos testes vão p/ quarentena auditável; reprocesso manual | P0 |
| Proveniência por enriquecimento | Campo fonte+timestamp+status; INDISPONIVEL tratado como ausência, não zero; cache com TTL | P0 |
| Backup cifrado off-VM do compliance.db | Snapshot diário versionado fora da VM (612k OBs = ativo crítico) | P0 |
| Trilha de auditoria | Registrar quem consultou o quê via Yoda; base legal por consulta | P1 |
| Rodapé forense nos relatórios | Hash do dataset + commit + parâmetros/thresholds em cada PDF/XLSX | P1 |

#### (c) Técnicas de IA / engenharia

- **OLTP/OLAP separados** (SQLite ingestão + DuckDB análise) sobre o mesmo arquivo.
- **Circuit breaker + retry com backoff exponencial** no enriquecimento; cache persistente com TTL.
- **Versionamento de modelo+threshold+dataset** p/ reprodutibilidade e reversão.
- **Replay HTTP da sessão autenticada** preferível a Computer Use sempre que possível (custo/fragilidade).
- **Isolamento + kill-switch** para coletores que contornam anti-bot.

#### (d) Síntese das 3 lentes

A lente **Cético** domina Infra e define as pré-condições: qualidade de dado e quarentena vêm ANTES do ML; proveniência e degradação transparente; LGPD (mascarar CPF, SQLCipher, base legal, trilha de auditoria); segurança da stack (`:8000` só em 127.0.0.1, sem auth pública; rotacionar token; backup cifrado off-VM); reprodutibilidade forense. **MVP** concorda em manter o que funciona e não reescrever infra. **Visionário** quer endurecer enriquecimento (circuit breaker + nível de confiança) e backtesting contra ground-truth do TCE. Consenso: nada de evasão de WAF sem base legal documentada.

---

## 3. Problemas de infra — opções ranqueadas

### 3.1 SEI (sei.rj.gov.br) — WAF bloqueia IP da VM (GCP)

| # | Opção | Prós | Contras |
|---|---|---|---|
| 1 | **Acesso oficial / convênio de dados (LAI, transparência ativa)** | Sem risco legal; estável; defensável; resolve a raiz | Depende de trâmite administrativo; pode demorar |
| 2 | **Proxy residencial dedicado + cache local da íntegra** | Resolve reputação de IP (que stealth não cobre); cache evita re-bater no WAF | Custo recorrente; possível violação de termos de uso; precisa rate-limit humano + kill-switch + base legal documentada |
| 3 | **Camoufox (stealth de binário)** | Elimina fingerprint que derruba Playwright headless | **Não resolve** o bloqueio por IP/reputação isoladamente — só faz sentido combinado com proxy |

**Recomendação:** perseguir (1) em paralelo; usar (2)+(3) apenas como ponte, isolado e documentado. Cachear sempre a íntegra já lida.

### 3.2 SIAFE ADF/Oracle — ignora eventos sintéticos do Playwright (filtro por UG travado)

| # | Opção | Prós | Contras |
|---|---|---|---|
| 1 | **Replay HTTP da sessão autenticada** | Mais barato e estável que Computer Use; reproduz o request real | Exige capturar/manter o request autenticado; pode quebrar se a sessão/token mudar |
| 2 | **Claude Computer Use (batch noturno supervisionado)** | Opera por screenshot+mouse/teclado como humano; SOTA em WebArena; não depende de selectors | Latência alta; cobrança por screenshot; quebra a cada mudança de UI; precisa supervisão + teto de custo + alarme |
| 3 | **Manter o que hoje funciona e priorizar análise sobre os 612k já no banco** | Zero esforço; foca ganho onde há dado | Não destrava a UG travada |

**Recomendação:** (1) primeiro; reservar (2) só para o que não dá para replicar via HTTP, orçado e com kill-switch; (3) é a postura correta para a primeira semana (não atacar agora).

### 3.3 Enriquecimento Receita/PNCP — instável, cai p/ INDISPONIVEL

| # | Opção | Prós | Contras |
|---|---|---|---|
| 1 | **Cache persistente + retry com backoff + circuit breaker + proveniência** | Resolve ~80% da instabilidade sem redesenho; INDISPONIVEL vira ausência marcada, não 0/null | Implementação de 0.5–1 dia; precisa schema de cache/proveniência |
| 2 | **Fallback API pública de Consultas do PNCP** | Fonte oficial independente da Receita; valida modalidade e valor homologado vs. pago; sem auth | Dados pulverizados em vários endpoints; sem download em massa |
| 3 | **Manter INDISPONIVEL explícito** | Já existe; honesto; não polui o ML | Cobertura de dado menor |

**Recomendação:** (1) + (2) juntos: cache/retry/proveniência como base e PNCP público como fonte de fallback. Nunca transformar INDISPONIVEL em zero.

---

## 4. Roadmap priorizado

### Onda 1 — P0 (esta semana)

| Item | Agente | Ganho esperado |
|---|---|---|
| Qualidade de dado + quarentena (Great Expectations) | Infra | Blindar a fonte de verdade antes do ML (evita "anomalia" = erro de ingestão) |
| Proveniência por enriquecimento (fonte+timestamp+status; INDISPONIVEL≠0) | Infra/JFN | Dado confiável p/ o detector; não inventa sinal |
| Backup cifrado off-VM + rotacionar token git + secrets fora do repo | Infra | Proteger ativo crítico (612k OBs) e fechar exposição de credencial |
| Score de anomalia por OB (PyOD ECOD+IForest → tabela `ob_anomaly`) | JFN | Risco calibrado por OB sobre dados existentes |
| 3 regras determinísticas (same-day splitting, concentração, fracionamento) | JFN | Red-flags defensáveis sem ML, no mesmo dia |
| Endpoint `GET /anomalias` + skill `/anomalias` no Yoda | JFN/Yoda | Entrega visível no Telegram: ranking de OBs suspeitas com justificativa em 1 linha |
| Camada DuckDB de relatórios | JFN | Relatórios Fornecedor/Órgão mais rápidos; agregações 2019–2026 |
| aiogram 3.x: botões inline + confirmação humana + paginação | Yoda | UX melhor; roteamento determinístico no caminho feliz; zero token no comum |
| Roteamento por regra/regex antes do LLM | Yoda | Corta custo/ambiguidade em ~80% dos pedidos |
| Log de interação (pedido→rota→tool→resultado) | Yoda | Dados p/ decidir Onda 2/3 com evidência |
| Mensagens de erro humanas p/ os 3 gargalos | Yoda | Confiabilidade percebida |
| Calibração manual de corte (top-50, marcar 10–15) | JFN | Evita relatório cheio de falso-positivo |
| Parecer Lex com linguagem condicional ("merece apuração") | Lex | Defensibilidade jurídica; reduz risco de dano moral |

### Onda 2 — P1

| Item | Agente | Ganho esperado |
|---|---|---|
| Cache + retry + circuit breaker no enriquecimento | JFN/Infra | ~80% da instabilidade Receita/PNCP resolvida |
| Fallback PNCP (cliente API pública) | JFN/Yoda | Menos INDISPONIVEL; validação modalidade/valor homologado |
| Resolução de entidade de fornecedores (Splink) | JFN | Tabela canônica fornecedor_id; base p/ concentração e grafo |
| Detector de red-flags completo (port RUBLI, 9 features) | JFN | Cobertura de corrupção em compra pública |
| Camoufox no(s) coletor(es) TFE pegos por fingerprint | JFN | Coleta restaurada sem reescrever pipeline |
| Replay HTTP / Computer Use noturno p/ SIAFE (UG travada) | JFN | Destrava a ingestão bloqueada nº1 |
| Proxy residencial + cache p/ SEI (com base legal) | Infra/Lex | Destrava a íntegra p/ o Lex |
| Cruzamento integra-SEI × OB + extração Docling/VLM | Lex | Parecer cruzado pagamento×processo |
| Memória persistente do Jorge (Mem0 mínimo) | Yoda | Personalização entre sessões sem inflar contexto |
| Catálogo de tools curado (function-calling enxuto) | Yoda | Menos erro de tool-use e token |
| Proveniência + backtesting de mercado (DuckDB) | Massare | Predição auditável, sem número inventado |
| Trilha de auditoria + rodapé forense nos relatórios | Infra | Reprodutibilidade e LGPD |

### Onda 3 — P2

| Item | Agente | Ganho esperado |
|---|---|---|
| Grafo fornecedor-órgão + co-contratação (networkx → GNN) | JFN | Detecção relacional de cartel/bid-rigging |
| Explicabilidade SHAP no Relatório de Inteligência | JFN/Lex | Justificativa auditável defensável (TCE/TCU) |
| Calibração por UG + PU-learning + monitor de drift | JFN | Modelo de risco calibrado, sem feedback loop de viés |
| Relatório agentico (LLM sobre scores+SHAP+grafo, pipeline ARIA) | JFN | Narrativa priorizada por tier, linguagem de parecer |
| Reescrita Yoda como orquestrador supervisor (Agent SDK) | Yoda | Delegação nativa JFN/Massare/Lex (se log provar necessidade) |
| vLLM Semantic Router (NLU + tool filtering) | Yoda | Roteamento semântico local (após medir ambiguidade) |
| Letta p/ investigações longas Lex+JFN+Massare | Yoda | Contexto estilo SO quando estourar a janela |
| Eval com ground-truth do TCE-RJ (precision@k por UG) | JFN/Lex | Separa "brinquedo" de ferramenta de auditoria |

---

## 5. Workflow de evolução (passo a passo, idempotente)

> Premissa: outra IA mais simples deve conseguir executar. Sempre branch + validação + commit só quando o Mestre Jorge pedir. Use caminhos absolutos. **A branch de trabalho NESTA VM é `linux`** (separação por SO — ver `docs/BRANCHES-POR-SO.md`); merges para `windows`/`gitactions` são por cherry-pick seletivo.

### Regras gerais (valem para todo passo)
1. **Branch:** trabalhar a partir da `linux` (default da VM). Para mudanças grandes, criar `git checkout -b claude/<onda>-<item>` a partir de `linux` e abrir PR/cherry-pick.
2. **Idempotência:** todo script deve poder rodar 2x sem efeito colateral (criar tabela com `IF NOT EXISTS`, checar se coluna existe antes de adicionar, cache com chave determinística).
3. **Não tocar o schema das OBs.** Toda análise grava em tabelas novas (`ob_anomaly`, `enriquecimento_cache`, `fornecedor_canonico`).
4. **Validação obrigatória** antes de commit: rodar `pytest` em `/home/jfelippebethlem/JFN/tests`, subir o server e bater no endpoint novo, conferir saída no Yoda.
5. **Commit só quando o Jorge pedir.** Mensagem termina com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
6. **Secrets fora do repo.** Nunca commitar `.env`; confirmar `.gitignore`.

### Onda 1 — sequência exata

**Passo 0 — Infra mínima (faz primeiro, destrava confiança no resto):**
1. Confirmar que `:8000` está em `127.0.0.1` e sem auth pública (não expor).
2. Rotacionar o token no remote git (está pendente na memória) e mover secrets para `.env` + Secret Manager GCP; conferir `.gitignore`.
3. Criar script de **backup cifrado off-VM** do `compliance.db` (snapshot diário versionado).
4. Adicionar **testes de qualidade** no pipeline de ingestão (OB não-nula, valor>0, CNPJ módulo-11, UG em domínio, soma OB=itens, dedup por hash) e **quarentena** das linhas que falham. Validar: rodar ingestão de uma amostra e conferir tabela de quarentena.

**Passo 1 — Score de anomalia (JFN, mesmo dia que Passo 2):**
1. Branch `claude/onda1-pyod-anomalias`.
2. Ler OBs via `pandas.read_sql` de `compliance.db`. Features: valor, log(valor), frequência/concentração do fornecedor, UG/órgão, dia-da-semana, mês.
3. Rodar `pyod` ECOD + IForest; agregar score 0–1.
4. Persistir em tabela nova `ob_anomaly(ob_id, score, top_features, modelo_versao, dataset_hash, gerado_em)` com `CREATE TABLE IF NOT EXISTS`.
5. Validar: conferir que `SELECT count(*) FROM ob_anomaly` bate com nº de OBs e que `top_features` não é nulo.

**Passo 2 — 3 regras determinísticas (JFN):**
1. SQL/pandas sobre os dados atuais: (a) same-day threshold splitting (mesmo fornecedor+UG, várias OBs no mesmo dia somando perto do limite de dispensa); (b) concentração de fornecedor por UG (>30%); (c) fracionamento temporal (sequência logo abaixo de limites).
2. Gravar flags com peso e parecer textual de 1 linha em tabela `ob_redflag`.
3. Validar: inspecionar manualmente 5 casos de cada regra.

**Passo 3 — Endpoint + skill:**
1. No FastAPI (`server.py`): `GET /anomalias?orgao=&fornecedor=&top=` lendo `ob_anomaly` JOIN `ob_redflag`, retornando ranking.
2. No Yoda: skill `/anomalias <órgão|fornecedor>` que só chama o endpoint.
3. Validar: subir server, `curl` o endpoint, e testar `/anomalias` no Telegram.

**Passo 4 — Calibração de corte (JFN):**
1. Pegar top-50 por score, marcar a mão 10–15 como "faz sentido / não faz", fixar corte.
2. Persistir o threshold versionado (p/ reprodutibilidade).

**Passo 5 — DuckDB nos relatórios (JFN):**
1. Migrar as queries pesadas dos Relatórios de Fornecedor/Órgão para DuckDB lendo o próprio arquivo SQLite.
2. Validar: comparar saída PDF/XLSX antiga vs. nova (mesmos números, mais rápido).

**Passo 6 — Yoda UX + roteamento + log:**
1. aiogram 3.x: transformar `/relatorio`, `/orgao`, `/mercado`, `/lista` em InlineKeyboardMarkup; confirmação humana antes de ação cara; paginação.
2. Roteador por regex antes do LLM (fornecedor/órgão/UG/dólar-ibov/processo-SEI); só cai no Claude quando não casa.
3. Mensagens de erro humanas para os 3 gargalos.
4. Log de interação (pedido→rota→tool→resultado) em CSV/SQLite.
5. Validar: exercitar cada botão e conferir o log.

**Passo 7 — Proveniência de enriquecimento (Infra/JFN):**
1. Tabela `enriquecimento_cache(chave, fonte, status, valor, timestamp)`; INDISPONIVEL gravado como status, nunca 0/null.
2. O detector trata INDISPONIVEL como ausência.

### Onda 2 e 3
Repetir o padrão (branch → implementar idempotente → validar com pytest+endpoint+Yoda → commit sob pedido), seguindo a ordem das tabelas do §4. **Gatilho objetivo para liberar peças do Visionário do Yoda (Agent SDK, semantic-router, Letta):** o log de interação da Onda 1 mostrar ambiguidade real / estouro de janela / volume que justifique o esforço.

### Validação de cada entrega
- `pytest /home/jfelippebethlem/JFN/tests`
- Subir o server e bater no endpoint afetado (`curl localhost:8000/...`)
- Exercitar a skill correspondente no Yoda (Telegram)
- Conferir rodapé forense (hash do dataset + commit + thresholds) em qualquer relatório gerado

---

## 6. Riscos & mitigações

| Risco | Mitigação |
|---|---|
| **Score tratado como acusação** (dano moral / risco reputacional p/ o deputado) | Score/flag é **fila de investigação interna**, nunca saída pública. Relatório público só afirma fatos verificáveis (valor, data, modalidade, fornecimento). Linguagem condicional ("merece apuração"). Lex valida antes de qualquer saída externa. |
| **ML sobre dado sujo** ("anomalia" = erro de ingestão) | Great Expectations + quarentena ANTES do ML (valor>0, CNPJ módulo-11, UG em domínio, soma OB=itens, dedup por hash). Nunca descarte silencioso. |
| **LGPD** (CPF de sócio/PF é dado pessoal; CNPJ é público) | Mascarar CPF nos relatórios; minimizar retenção de PF; registrar base legal (interesse legítimo/controle externo); SQLCipher em repouso; trilha de auditoria de consultas via Yoda. |
| **Evasão de WAF/anti-bot** (SEI) — fragilidade legal | Preferir acesso oficial/convênio/LAI antes de evasão. Se inevitável: proxy residencial dedicado, rate-limit humano, kill-switch, base legal documentada. |
| **Computer Use** — custo e fragilidade silenciosa | Preferir replay HTTP; reservar Computer Use ao irreplicável; orçar custo por execução e alarmar acima de teto; humano no loop. |
| **Dependências externas instáveis** (Receita/PNCP/mercado) | Proveniência (fonte+timestamp+status); INDISPONIVEL ≠ 0/null; cache com TTL; circuit breaker + backoff. Nunca inventar número. |
| **Drift / viés do modelo** (PU-learning amplifica viés contra órgãos já investigados) | Calibração por UG com baseline; monitorar taxa de flag por órgão no tempo; revisão humana obrigatória; versionar modelo+threshold+dataset para reverter/auditar. |
| **Custo de token (Yoda)** | Roteamento por regra antes do LLM; catálogo de tools enxuto; Opus só no maestro, Sonnet nos subagentes; semantic-router só após log provar ambiguidade. |
| **Over-engineering** (Agent SDK/semantic-router/Letta cedo demais) | Congelar roteador atual; log de interação como gatilho objetivo; adiar tudo "médio/alto esforço" até evidência. |
| **Segurança da stack** | `:8000` só em 127.0.0.1 sem auth pública; rotacionar token git agora; secrets fora do repo; backup cifrado off-VM; snapshot diário versionado. |
| **Relatório contestado em controle externo** | Reprodutibilidade forense: cada PDF/XLSX carrega hash do dataset + commit + parâmetros/thresholds no rodapé; congelar query, data de corte e versão de código. |

---

### Fontes (dos insumos)
- https://github.com/rodanaya/yangwenli
- https://github.com/yzhao062/pyod
- https://github.com/daijro/camoufox
- https://docs.claude.com/en/docs/agents-and-tools/tool-use/computer-use-tool
- https://github.com/moj-analytical-services/splink
- https://github.com/duckdb/duckdb
- https://github.com/docling-project/docling
- https://pncp.gov.br/api/consulta/swagger-ui/index.html
- https://code.claude.com/docs/en/agent-teams
- https://github.com/vllm-project/semantic-router
- https://github.com/mem0ai/mem0
- https://github.com/letta-ai/letta
- https://docs.aiogram.dev/en/latest/
- https://github.com/langchain-ai/langmem
- https://www.braintrust.dev/articles/best-hallucination-detection-tools-2026
- https://arxiv.org/html/2511.10659v1
- https://link.springer.com/article/10.1140/epjds/s13688-025-00569-3
- https://arxiv.org/pdf/2507.12369
- https://arxiv.org/html/2410.07091v1
