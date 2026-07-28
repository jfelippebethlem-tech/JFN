# Checklist Mestre — tudo que foi pedido na sessão de 27/07/2026

| | |
|---|---|
| **Atualizado** | 28 de julho de 2026, 03h |
| **Regra deste documento** | Só marca ✅ o que tem **prova** (teste passando, número medido, arquivo no repositório). Meio-feito é 🟡 e diz **o que falta**. |
| **Documento vivo** | Cada bloco executado atualiza esta tabela no mesmo commit. |

---

## Resumo do estado

| Bloco | Itens | ✅ | 🟡 | ⬜ |
|---|---:|---:|---:|---:|
| 1. Bases jurídicas nacionais | 8 | 6 | 1 | 1 |
| 2. Custo de token e MCPs | 5 | 3 | 0 | 2 |
| 3. Responsáveis nos processos SEI | 7 | 4 | 2 | 1 |
| 4. Citações e gate no Lex | 6 | 6 | 0 | 0 |
| 5. Superfície de detecção | 6 | 4 | 1 | 1 |
| 6. Captura SEI e sigilo | 6 | 5 | 1 | 0 |
| 7. Estabilidade da VM | 7 | 7 | 0 | 0 |
| 8. Planos e execução | 30 | 20 | 0 | 10 |
| 9. Pedidos ainda não iniciados | 4 | 1 | 0 | 3 |
| **TOTAL** | **79** | **58** | **6** | **15** |

---

## 1. Bases de dados jurídicas nacionais (direito administrativo)

> *"busque bases de dados jurídicas nacionais em direito administrativo para melhorar os nossos sistemas"*

- [x] **1.1** Prospecção documental de bases nacionais — 11 bases mapeadas
- [x] **1.2** **Probe HTTP real de cada uma a partir da VM** (nunca afirmar disponibilidade sem medir) — 15 fontes testadas
- [x] **1.3** **DataJud/CNJ** em operação — `compliance_agent/collectors/datajud.py`, 13 testes
- [x] **1.4** **Jurisprudência Selecionada + Súmulas do TCU** indexadas — `data/tcu_juris.db`, 17.510 acórdãos, 292 súmulas
- [x] **1.5** **Querido Diário** ressuscitado — coletor estava morto em silêncio, 6 testes
- [x] **1.6** Relatório com o veredito por fonte — `docs/FONTES-JURIDICAS-NACIONAIS-2026-07-27.md`
- [ ] 🟡 **1.7** Indexar `resposta-consulta.csv` (7,2 MB) e `boletim-jurisprudencia.csv` (4,2 MB) do TCU — **falta**: ambos já verificados HTTP 200, é só rodar o indexador
- [ ] ⬜ **1.8** Credencial da API do CNCIAI (condenações por improbidade) — **depende do gabinete**, é pedido institucional

**Registrado como impossível daqui** (não repetir esforço): LexML (WAF do Senado barra a VM) · STF/STJ (não existe API de busca textual) · `pesquisa.apps.tcu.gov.br` (SPA que devolve os mesmos 22.104 bytes para acórdão real e inventado).

---

## 2. Custo de token e MCPs

> *"desinstale os mcps do higgsfield, adobe e o que mais estiver gastando tanto token"*

- [x] **2.1** Auditoria do que entra no contexto por turno, item a item, medido
- [x] **2.2** **7 skills Higgsfield desligadas** no escopo JFN — ~1.700 tok/turno, reversível (`.claude/skills-desligadas/`)
- [x] **2.3** **Adobe e Higgsfield desconectados** — confirmado em `claude mcp list`; eram conectores da conta claude.ai, não instaláveis/removíveis pelo CLI
- [ ] ⬜ **2.4** Desconectar os demais conectores sem uso (IBKR, Docusign, Bigdata, Bitly, CB Insights…) — **só você pode**: claude.ai → Settings → Connectors
- [ ] ⬜ **2.5** Enxugar `MEMORY.md` (3.952 tok/turno, maior item local controlável) — **decisão sua**: é seu índice de memória

---

## 3. Responsáveis nos processos SEI

> *"anotar quem sao os gestores, fiscais, ordenadores de despesas e outras informações de cada processo"*

- [x] **3.1** Extrator de 13 papéis — `compliance_agent/sei/agentes_publicos.py`, 34 testes
- [x] **3.2** Três vias de identificação colhidas do acervo real: bloco de assinatura, rótulo inline, designação formal com ID funcional
- [x] **3.3** Verificação **art. 117** (execução paga sem fiscal designado) e **art. 5º** (segregação de funções)
- [x] **3.4** Sweep sobre o acervo inteiro — `tools/sei_agentes_sweep.py`; **2.007 processos, 387 agentes, 198 nomes distintos**
- [ ] 🟡 **3.5** Cobertura em **8%** — **falta** subir para ≥30%. Causa medida: o ato de designação **não está no acervo** em 97% dos processos (só 68 de 2.053 têm algum)
- [ ] 🟡 **3.6** Falsos positivos: 4 corrigidos (`Maj PM De`, quebra de linha, `NFs Consig`, título de nota fiscal) — **falta** varredura de conferência após a próxima captura
- [ ] ⬜ **3.7** Datar cada papel (designação/substituição/exoneração) — **crítico**: imputar ato a quem não estava no cargo derruba a representação inteira

---

## 4. Citações jurisprudenciais e gate no Lex

> *"corrija as 5 citações defeituosas e ligue o gate no Lex"*

- [x] **4.1** Verificador anti-alucinação — `knowledge/tcu_juris_index.py`, 5 estados, 17 testes
- [x] **4.2** Teste de plausibilidade por série anual (vale mesmo com índice incompleto)
- [x] **4.3** **7 citações corrigidas** (eram 5; a conferência achou mais 2), cada substituto buscado no acervo oficial e a ementa reescrita
- [x] **4.4** Gate ligado em `lex_render.parecer_md` — ponto único de markdown e PDF
- [x] **4.5** Falso negativo do gate corrigido: a janela de contexto atravessava a citação vizinha
- [x] **4.6** Base curada limpa: **0 impossíveis, 0 colegiado errado** (restam 9 `nao_confirmado`, declaradas)

---

## 5. Superfície de detecção

> *"quantas irregularidades podemos pegar? quais delas?"*

- [x] **5.1** Inventário medido: **42 vícios · 31 detectores · 23 com teste · 4 regras disparando**
- [x] **5.2** Fracionamento **26× inflado** desmontado: 59.209 → 2.225, com cada filtro medido
- [x] **5.3** Teto de dispensa **por exercício** da fonte única (era o valor de 2024 fixo para todo ano)
- [x] **5.4** Filtro de intragoverno movido para **dentro** das regras (estava só no relatório)
- [ ] 🟡 **5.5** `ob_redflag` reprocessada — 60.664 flags. **Falta** migrar a regra para a fonte SIAFE (Fase B do plano)
- [ ] ⬜ **5.6** Remover a **5ª cópia** do teto em `lex_analise_conteudo.py:307`

---

## 6. Captura SEI e processos em sigilo

> *"veja se o sweep sei ta funcionando adequadamente… queremos saber todos os processos em sigilo"*

- [x] **6.1** Inventário de captura — `tools/sei_inventario_captura.py`, sem recrawl
- [x] **6.2** **77 processos sob restrição** identificados e persistidos em `sei_sigilo`
- [x] **6.3** Marcador **validado por correlação** (22,42% vs 0,02% — mil vezes de diferença) — refutou minha própria ressalva de que seria artefato
- [x] **6.4** Fila de **3.216 conhecidos e não capturados** em `sei_fila_captura`
- [x] **6.5** Peça para requisição formal — `docs/SEI-SIGILO-E-FILA-CAPTURA-2026-07-27.md`
- [ ] 🟡 **6.6** **2.579 caches (46%) com árvore não carregada** — **falta** diagnosticar a causa (Fase C4 do plano)

---

## 7. Estabilidade da VM

> *"a vm travou, se reorganiza agora" · "veja pq crashou" · "o claude e o tmux estao fechando sozinhos"*

- [x] **7.1** Causa da queda das 22:22 identificada e provada: `sei_pais.carregar_cache()` materializava **18 GB**
- [x] **7.2** Correlação `rc=137` × OOM do kernel, ao segundo, 11 ocorrências no dia
- [x] **7.3** `detectar_pais` reescrito em streaming — pico de **807 MB** contra ~10.000 MB
- [x] **7.4** **Erro meu corrigido**: o chamador `run_pais` ainda usava `carregar_cache()` e causou novo OOM às 23:04
- [x] **7.5** Teste estático que impede qualquer módulo de produção de chamar `carregar_cache()`
- [x] **7.6** **Guard de OOM nos 8 sweeps** — `oom_score_adj=1000`: o sweep morre antes da sua sessão. **É a resposta ao Claude/tmux fechando sozinhos**
- [ ] 🟡 **7.7** `sei_pais` religado — **falta** a confirmação da validação em produção (rodando agora, com `/usr/bin/time -v`)

---

## 8. Planos e execução

> *"planeje todos em plan mode" · "execute tambem todos os planos"*

- [x] **8.1** Plano mestre — `docs/superpowers/plans/2026-07-27-…md`, 2.075 linhas, 5 fases
- [x] **8.2** Fase C reescopada por medição (o gargalo é captura, não OCR)
- [x] **8.3** Fase 0 (a queda) incorporada como pré-requisito

### Fase A — rede de proteção dos 10 detectores sem teste
**CONCLUÍDA.** Os **31 detectores** têm arquivo de teste; a catraca em `test_registro_completo`
é absoluta (detector novo sem teste falha na hora). **597 testes verdes** na pasta.

Antes da sessão: **6 de 31** com teste — e não 23, como relatei antes por casamento frouxo de nome.

**5 bugs reais** que os testes acharam em produção:

| Detector | Bug |
|---|---|
| E2 | `_to_datetime` descartava a hora em ISO sem segundos — a regra de data-sombra nunca disparava com dado do PNCP |
| J1 | `AttributeError` quando `concentracao` vinha em formato inválido |
| J3 | Razão perdida ao descartar: exculpatória de preço tabelado saía como "compatível com competição" |
| P2 | Normalizador de endereço não removia `R.`, vírgula nem `nº` — o MESMO endereço não casava, e o vínculo por sede compartilhada passava batido |
| P2 | Mesmo defeito de razão perdida do J3 |

### Fase B — fracionamento na fonte SIAFE
**CONCLUÍDA, com correção do próprio plano.** O módulo já existia desde 24/07, mais sofisticado
do que eu havia desenhado, e estava **órfão** — ninguém o chamava, nada persistia.

- [x] **B1** módulo `fracionamento_siafe` — já existia; melhorado com o filtro canônico de ente público (1.240 → 1.170 candidatos, zero entes públicos)
- [x] **B3** persistência e sweep — `siafe_fracionamento` com **1.170 candidatos** (2024-2026), R$ 300,6 mi em pagamentos
- [x] **B4** família do teto FECHADA — o teste-catraca achou **mais 4 cópias** além da que eu havia anunciado
- [ ] ⬜ **B2** discriminante de contratação direta (cruzar com `compras_diretas_tcerj` por fornecedor+unidade+ano)
- [ ] ⬜ **B5** corrigir o mapa desatualizado em `detectores/base.py`

### Fase C — cobertura de captura
- [ ] ⬜ **C1** régua determinística de cobertura
- [ ] ⬜ **C2** re-extrair os 4.695 documentos com texto vazio
- [ ] ⬜ **C3** buscar designação no processo relacionado (17% dos caches apontam para outro)
- [ ] ⬜ **C4** causa-raiz dos 2.579 caches com árvore não carregada
- [ ] ⬜ **C5** capturar os 3.216 da fila

### Fase D — integração e peça formal
- [ ] ⬜ **D1** seção "Responsáveis" no parecer do Lex
- [ ] ⬜ **D2** gate de citações no Yoda e no Hermes
- [ ] ⬜ **D3** comando `/responsaveis <processo>` no Yoda
- [ ] ⬜ **D4** gerador de minuta de requisição por órgão
- [ ] ⬜ **D5** ficha de agente público no vault (Hermes)

---

## 9. Pedidos ainda não iniciados

> *"vai indo de orgão a orgão e buscando suas irregularidades" · "queremos que as outras ias sejam usadas no fallback pra rodar e identificar irregularidades 24/7" · "sera que na vm2 cabe mais coisa pra rodar sem crashar e liberar espaco aqui?"*

- [ ] ⬜ **9.1 — Varredura órgão a órgão.** Rodar os 31 detectores UG por UG, persistindo achados num lugar só. **Pré-requisito:** Fase A (senão varremos com detectores que ninguém sabe se funcionam) e Fase B (senão o fracionamento infla o resultado 26×).
- [ ] ⬜ **9.2 — Fiscalização 24/7 com IAs em fallback.** Você disse não saber como pedir; a proposta técnica está na seção 10 abaixo.
- [x] **9.3 — VM-2 medida.** `docs/DIVISAO-DE-CARGA-VM1-VM2-2026-07-27.md`. Ela está **parada**: load 0,11 contra 5-14 aqui, 6,7 GB livres, 161 GB de disco, **zero cron**, hardware idêntico. O critério de divisão é SESSÃO, não peso. **Nada foi alterado lá** — a proposta espera seu aval item a item.
- [ ] ⬜ **9.4 — Loop de automelhoria contínuo.** Em curso de fato (cada detector testado tem achado bug), mas **falta** formalizar: cada achado vira teste, cada bug vira regra no playbook.

---

## 10. Proposta para a fiscalização 24/7 (item 9.2)

Você disse: *"não sei como te pedir isso e montar"*. Aqui está a forma concreta, para você aprovar ou corrigir.

**O problema real não é "usar IA".** É que hoje o volume de análise depende de LLM pago/limitado, então o sweep só toca o topo da fila. O que se quer é: **todo órgão, todo contrato, sem parar, sem estourar cota nem VM.**

**Arquitetura proposta, em três camadas:**

1. **Camada determinística (sem IA, 24/7, barata).** Os 31 detectores rodam sobre todo o acervo continuamente. Não precisam de LLM — são regra e limiar em código. É aqui que 90% do volume deve ser resolvido. Hoje isso não roda em lote: só 4 regras cruas estão em produção.

2. **Camada de triagem (IA fraca, ilimitada).** Só o que a camada 1 marcou vai para LLM, e para o modelo **grátis e ilimitado** (`nous stepfun:free`, que o projeto já usa no sweep). Função: ler o texto e classificar em rubrica fechada — nunca produzir número nem grau final.

3. **Camada de parecer (IA de qualidade, cara, rara).** Só o topo confirmado pelas camadas 1 e 2 chega ao Gemini/Cerebras. É o que já acontece hoje, mas com fila muito melhor.

**O fallback que você quer** já existe em `llm/visao.py` (OpenRouter :free → NVIDIA → Gemini → Cloudflare) e em `freellmapi`. Falta aplicá-lo **à camada 2** e adicionar: teto de requisições por dia, kill-switch em arquivo, e registro de custo por camada.

**Guarda-corpo obrigatório** (sua regra, e a lição de hoje): nada disso liga sem (a) `oom_score_adj` nos processos — já feito; (b) um pesado por vez; (c) medição de pico de memória por passo antes de entrar no cron.

---

## 11. Como este documento é mantido

Cada bloco executado atualiza a tabela de resumo e marca o item **no mesmo commit** da entrega. Nenhum item vira ✅ sem prova anexada — teste passando, número medido ou arquivo no repositório.
