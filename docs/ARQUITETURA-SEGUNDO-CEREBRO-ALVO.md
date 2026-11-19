# ARQUITETURA-ALVO DO SEGUNDO CÉREBRO — JFN

| | |
|---|---|
| **Documento** | Medição do estado atual, estado da arte conferido na fonte, arquitetura-alvo, plano em fases com critério mensurável, bateria de avaliação e Fase 1 implantada |
| **Pedido do dono** | "faça também a melhor arquitetura para segundo cérebro" · "eu quero uma arquitetura de segundo cérebro que seja o estado da arte" |
| **Medição** | 19/11/2026, 07:59–08:30 (BRT) — VM-1 `jfn-core` (carga 9 a 20 durante a medição) e VM-2 `JFN-Agent-2` |
| **Estado** | **Fase 1 implantada** (commit `09dec788`) · Fases 2 a 6 são proposta, com custo e decisão indicados (§8, §10) |
| **Antecessor** | `docs/ARQUITETURA-SEGUNDO-CEREBRO.md` (18/11/2026 — inventário e ponte). Este documento **substitui** as linhas "Khoj" e "hermes_rag" do §4.3 de lá e o §3 (que não tinha sido conferido na fonte) |
| **Irmãos** | `docs/ARQUITETURA-DE-CERTEZA.md` · `config/propagacao.yaml` · `config/cerebro_bateria.yaml` |

---

## 1. Resposta direta

> [!important] O que a medição mostrou
> **O segundo cérebro guardava bem e achava mal.** Em 56 perguntas reais, a busca do jfn-brain devolvia a nota
> certa entre as 10 primeiras em **33 (58,9%)** — e em **9 de 20** quando a pergunta era do dono, no jeito dele.
> Uma busca por palavra **por nota inteira**, com peso no título e no nome do arquivo (BM25), sobre o mesmo vault,
> acerta **56 de 56**. Ela está implantada desde hoje no comando `caso` (Fase 1), sem custo e sem tocar na VM-2.

| Medida (56 perguntas) | Antes (jfn-brain) | Depois (Fase 1) | Estado |
|---|---:|---:|---|
| Nota certa em 1º lugar | 20 (35,7%) | **46 (82,1%)** | VERIFICADO |
| Nota certa entre as 5 primeiras | 32 (57,1%) | **55 (98,2%)** | VERIFICADO |
| Nota certa entre as 10 primeiras (recall@10) | 33 (58,9%) | **56 (100,0%)** | VERIFICADO |
| MRR@10 | 0,439 | **0,893** | VERIFICADO |
| Só as 20 perguntas literais do dono — recall@10 | 9 | **20** | VERIFICADO |
| Só as 20 perguntas literais do dono — 1º lugar | 4 | **13** (Khoj: 14) | VERIFICADO |

Fonte: `data/cerebro_bateria/fase1-2026-11-19.json` (medição das 08:23 BRT, com o Khoj ligado para comparação).

**Três conclusões que mudam o desenho:**

1. **O estado da arte para este acervo não é um grafo construído por modelo.** As avaliações independentes de
   2025–2026 mostram a busca simples empatando ou vencendo o GraphRAG em pergunta factual (§3), e a medição da casa
   repete isso: o componente mais simples ganhou de dois buscadores por vetor.
2. **Somar buscadores por voto piorou.** Fundir as listas por RRF (o método da literatura) derrubou o primeiro lugar
   de 46 para 36–42: duas pernas fracas vencem uma forte. O desenho que ficou é **primária + resgate** (§5.4).
3. **O que falta é estrutura de fato, não busca**: tempo em duas linhas (quando valeu × quando soubemos), ponteiro de
   prova em todo fato e índice de entidade cobrindo o acervo inteiro — tudo determinístico, sem modelo criando aresta.

---

## 2. Estado atual medido

### 2.1 Componente por componente

| # | Componente | Onde | Vivo? | Volume medido | Frescor | Quem consulta (medido) | Achado |
|---|---|---|---|---|---|---|---|
| 1 | **jfn-brain** (API + MCP, Postgres 16 + pgvector) | VM-2 `brain-api` | SIM — 1,54 GB de RAM | 1.432 notas · 10.069 trechos · 11.275 arestas · 1.550 memórias ativas | indexa a cada 10 min (última 07:54 BRT) | Nos 6 dias anteriores às últimas 24 h (que incluem esta bateria): **84** `GET /api/search` e **8** `GET /api/recall` contra **366** `POST /api/memories`. MCP: 2.674 chamadas em 7 dias (o log não separa por ferramenta) | **Escreve-se 4× mais do que se lê** pela API. Recall@10 de 33/56 |
| 2 | **Registro de envio** (`data/propagacao.db`) | VM-1, despachante `*/5` | SIM | 1.419 chaves: 1.415 gravadas, 0 pendentes, 4 recusadas | último envio hoje | o próprio despachante | **1.011 das 1.419 (71,2%)** são `pericia-agente:*` e `licao-pericia:*`, geradas em série — disputam o `recall` com as decisões do dono |
| 3 | **Obsidian** (`~/vault`) | VM-1 + Syncthing | SIM | 1.406 notas `.md` (6,5 MB): 165 casos · 171 aprendizados · 518 perícias por agente · 169 processos · 138 diários | contínuo | sessões e geradores | **58,7% do acervo (825 notas) são geradas uma-por-processo/dia** |
| 4 | **Khoj** (piloto) | VM-2 | **Parado pela vigia de memória** em 18/11 11:40 BRT (MemAvailable 1.342 MB) | 810 notas · 4.705 trechos | **congelado em 18/11 02:17 BRT** | Ninguém: nenhuma chamada no código, no cron ou no Hermes; 2 buscas no log fora das comparações (as duas com a palavra "teste") | Reindexação **quebrada**: o vault passou de 1.000 arquivos e o Khoj recusa o envio (`Too many files. Maximum number of files is 1000`). Ver §6 |
| 5 | **hermes_rag** | VM-1 `data/rag/` | SIM | `chunks.jsonl` 12,1 MB | reindexado hoje 07:04 | só o Hermes/Yoda | Terceiro índice do mesmo vault; embeddings por API externa (Cohere, chave de teste) |
| 6 | **GitNexus** | VM-1 `.gitnexus/` | SIM | 29.042 símbolos | **índice de 08/11/2026 (11 dias)** | sessões (MCP) | Reindexação semanal segue falhando; impacto de código cego para 11 dias |
| 7 | **graphify** | VM-1 `graphify-out/` | SIM | relatório único no cérebro | 19/11 03:17 | 1 nota no cérebro | Grafo de conceito de código/documentação; não guarda fato de caso |
| 8 | **Certeza** (`data/certeza/certeza.db`) | VM-1 | SIM | 2,7 MB | 19/11 08:02 | painel, verificador | Única camada com versão só-acréscimo e nível de prova — modelo a estender (§5.2) |
| 9 | **Índice de entidade** (`ponte_entidade`) | VM-1 | SIM | 465 CNPJ · 518 processos · 394 UG | acompanha a ponte | `cerebro_ponte entidade` | Cobre **só** as perícias por agente; os 165 casos e as 1.550 memórias ficam fora |
| 10 | **Memória dos agentes** | VM-1 | SIM | 357 arquivos; `MEMORY.md` com 206 linhas (limite 200) | contínuo | toda sessão | Só 40 chaves `memoria:*` no cérebro |
| 11 | **Paleta de órgãos** (`cores_orgaos`) | VM-1 | SIM | 46 grupos de cor | — | grafo do Obsidian, galáxia | Implantada; falta a entidade "órgão" ser de primeira classe (§5.3) |

### 2.2 Por que o jfn-brain achava mal — o que foi e o que não foi medido

| Hipótese | Teste | Resultado | Leitura |
|---|---|---|---|
| Vários trechos da mesma nota ocupam a lista | pedir 40 trechos e reduzir a 10 notas | 33 → **34** | Não é a causa principal |
| O ramo textual exige todas as palavras (`websearch_to_tsquery`) | mesma busca com as palavras ligadas por OR | **31** (pior) | Não basta: `ts_rank_cd` não pesa palavra rara e ordena trecho, não nota |
| O modelo de vetor corta o trecho em 128 tokens | vetor de um texto × o mesmo texto com cauda diferente depois de 300 palavras | cosseno 0,9984 (≠ 1) · truncamento configurado em **512** | **Refutado nesta instalação.** A literatura diz 128; aqui o `fastembed` lê 512 |
| Falta peso para título e nome do arquivo e ordenação por nota | BM25 por nota (SQLite FTS5), título ×6, nome ×8, resumo ×4, corpo ×1 | **56** | É o que resolve |
| O modelo de vetor (`paraphrase-multilingual-mpnet-base-v2`, 2019) é fraco para pergunta curta | — | **NÃO MEDIDO** | Fica para a Fase 3, em coluna-sombra |

### 2.3 Duplicação

Três índices semânticos do mesmo vault (jfn-brain, Khoj, hermes_rag) → ficam **um e meio**: o jfn-brain e, por ora, o
hermes_rag (Fase 2). Dois grafos de código (GitNexus, graphify) → papéis já separados no documento antecessor.

---

## 3. Estado da arte (pesquisa de 19/11/2026)

Pesquisa na web feita por subagente nesta data; as URLs são as abertas ou devolvidas pela busca. "n.c." = não
confirmado na fonte. **Números de fornecedor estão marcados como tal.**

| Linha | O que é | Evidência medida | Contestação / limite | Infra e custo | Fonte (data) |
|---|---|---|---|---|---|
| **Graphiti / Zep** | Grafo temporal em duas linhas de tempo; aresta é invalidada, nunca apagada | DMR 94,8% × 93,4% (MemGPT); LongMemEval até +18,5% — **números da própria Zep** | Ganho quase nulo no DMR; sem reprodução independente encontrada | Servidor de grafo (Neo4j/FalkorDB/Neptune); **várias chamadas de LLM por episódio**; Apache-2.0 | arxiv.org/abs/2501.13956 (20/01/2025) · github.com/getzep/graphiti |
| **Disputa Zep × mem0** (LoCoMo) | — | Zep declara 75,14%; o mem0 refez e mediu 58,44% para a Zep; a conversa inteira no contexto (~73%) bate o mem0 com grafo (~68%) | Sem árbitro independente | — | getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory (06/05/2025) |
| **GraphRAG / LazyGraphRAG** (Microsoft) | Grafo de entidades + resumo por comunidade | Lazy indexa a 0,1% do custo do GraphRAG completo — **dado do fornecedor** | — | Completo: LLM em cada trecho na indexação | microsoft.com/en-us/research/blog/lazygraphrag (data n.c.) |
| **RAG × GraphRAG, avaliação independente** | Mesmo LLM e mesmos embeddings nos dois lados | **RAG simples vence em pergunta de um salto e de detalhe**; GraphRAG vence em multi-salto e resumo | Depende do desenho do GraphRAG | — | arxiv.org/abs/2502.11371 (17/02/2025) |
| **GraphRAG-Bench** (ICLR 2026) | Banco de prova para GraphRAG | RAG vence em extração simples (recall de evidência 83%); em multi-salto o ganho do grafo é modesto (+4,5% no HotpotQA) | O próprio artigo parte de que o GraphRAG "frequentemente perde" em tarefa real | — | arxiv.org/abs/2506.05690 (06/2025; v3 02/2026) |
| **LightRAG** | Grafo leve + busca em dois níveis | Declara 72% de vitórias com juiz LLM | **Corrigido o viés de posição e tamanho do juiz, o RAG ingênuo passa à frente** | LLM por trecho na indexação | arxiv.org/html/2506.06331 (06/2025) |
| **HippoRAG 2** (ICML 2025) | Triplas + PageRank personalizado | +7% em memória associativa — autores | Sem replicação encontrada | LLM na extração de triplas | arxiv.org/abs/2502.14802 (20/02/2025) |
| **Letta / MemGPT** | Memória hierárquica; agente com sistema de arquivos | **74,0% no LoCoMo só com grep + busca em arquivos**, contra 68,5% do mem0 com grafo — experimento da Letta | Conclusão deles: "o LoCoMo mede recuperação, não memória" | Arquivos + um índice | letta.com/blog/benchmarking-ai-agent-memory (12/08/2025) |
| **mem0** | Extração de fatos por LLM a cada mensagem | +26% relativo sobre a memória da OpenAI — autores | Ver a disputa acima | LLM por mensagem; versão com grafo usa Neo4j | arxiv.org/abs/2504.19413 (28/04/2025) |
| **A-MEM · MemOS · Cognee** | Nota agêntica · "sistema operacional" de memória | A-MEM: F1 45,85 × 25,52 (MemGPT) no LoCoMo | MemOS medido por terceiros bem abaixo do declarado (arxiv 2609.34545); Cognee só tem material próprio | LLM na escrita | arxiv.org/abs/2502.12110 · arxiv.org/html/2507.03724 |
| **Busca híbrida + reranker** (Contextual Retrieval, Anthropic) | BM25 + vetor + linha de contexto por trecho | Falha de recuperação no top-20: 5,7% → 2,9% (−49%); com reranker 1,9% (−67%) | Redução **relativa**; os 67% incluem o reranker | 1 chamada de LLM por trecho para o contexto | anthropic.com/research/contextual-retrieval (09/2024) |
| **Embeddings abertos em CPU** | Substitutos do modelo atual | gte-multilingual-base (305 M, 8.192 tokens, Apache-2.0) · snowflake-arctic-embed-m-v2.0 (305 M, 8.192, Apache-2.0) · bge-m3 (MIT) · multilingual-e5-small (384 dim., 512, MIT) · Qwen3-Embedding-0.6B (32 K, Apache-2.0, MMTEB 64,33) | Posição relativa em português: n.c. — **medir na bateria da casa**. Jina v3 é CC BY-NC (fora) | Local, sem API | cartões dos modelos em huggingface.co |
| **Reranker em CPU** | bge-reranker-v2-m3 (568 M, Apache-2.0) | — | **Sem medição publicada em ARM de 2 núcleos**; o Khoj com rerank levou ~15 s por consulta na VM-2 (rodada de 14/11) | Local | huggingface.co/BAAI/bge-reranker-v2-m3 |
| **Consolidação / "sono"** | Computar em tempo ocioso | Sleep-time compute: +13% a +18% — **em matemática (GSM-Symbolic, AIME), não em memória** | "Coerente não é correto" | LLM em tempo ocioso | arxiv.org/abs/2504.13171 (17/04/2025) |
| **Bitemporal** | Tempo de validade × tempo de registro | Modelo do Graphiti; PostgreSQL 18 traz `WITHOUT OVERLAPS` | **No PG 16 não existe**: o equivalente é `tstzrange` + `EXCLUDE USING gist` | Postgres, sem serviço novo | neon.com/postgresql/postgresql-18/temporal-constraints |
| **Avaliação** | LongMemEval (ICLR 2025): 500 perguntas, 5 habilidades | Queda de ~30% nos assistentes comerciais | LoCoMo: auditoria achou 6,4% do gabarito errado (autor é fornecedor rival) | — | arxiv.org/abs/2410.10813 · penfieldlabs.substack.com/p/we-audited-locomo-64-of-the-answer |
| **Postgres como base única** | pgvector `halfvec` (0.7.0); BM25 nativo (`pg_textsearch` 1.0) | — | `pg_textsearch` exige PG 17+; ParadeDB é AGPL-3.0; Apache AGE 1.6.0 serve ao PG 16 | Roda em ARM 2 vCPU nesta escala (estimativa) | postgresql.org/about/news/pg_textsearch-v10-3264 (03/04/2026) |
| **"LLM wiki"** (Karpathy) | A wiki reescrita pela fonte é o artefato | **Nenhuma medição** no texto original | Risco de deriva na reescrita por modelo | Zero | gist.github.com/karpathy/442a6bf555914893e9891c11519de94f (04/04/2026) |

### 3.1 Evidência × hype

| Tem evidência sólida | É hype ou evidência fraca |
|---|---|
| Busca simples empata ou vence o GraphRAG em pergunta factual (dois estudos independentes) | Placar de "estado da arte" no LoCoMo, de qualquer fornecedor |
| BM25 + vetor + reranker reduzem falha de recuperação | As vitórias de 70%+ do LightRAG (somem com o juiz corrigido) |
| Juiz LLM pareado sem correção de viés inverte resultado | "Sono" como ganho de memória (a prova é de matemática) |
| **Avaliar no próprio acervo vale mais que benchmark público** — confirmado aqui: a literatura diz que o modelo corta em 128 tokens, a instalação lê 512 | "LLM wiki" como substituto de busca (ideia sem medição) |

### 3.2 O que a casa adota e o que recusa

| Adota | Recusa | Por quê |
|---|---|---|
| Duas linhas de tempo em todo fato (Graphiti) | Graphiti, mem0, GraphRAG, LightRAG como produto | Todos chamam LLM por documento na ingestão: custo ≠ zero e **o modelo cria a aresta** — incompatível com "nada sem prova primária" |
| Busca híbrida com BM25 de verdade por nota | Servidor de grafo (Neo4j/FalkorDB) | VM de 2 vCPU; as entidades da casa já têm chave determinística (CNPJ, nº SEI, UG, nº da OB) |
| Conjunto-ouro próprio como catraca de regressão | Fusão por voto (RRF) entre pernas de qualidade desigual | Medido: piora o primeiro lugar |
| Consolidação noturna **determinística** + fila de proposta | Reescrita automática de fato ou de nota de caso por modelo | Deriva; indício ≠ acusação |

---

## 4. Princípios da arquitetura-alvo

1. **Fonte única por tipo de fato; o resto guarda ponteiro.**
2. **Todo fato tem prova, tempo e autor**: documento primário + trecho literal + hash; quando valeu; quando foi gravado; quem gravou.
3. **Nada é sobrescrito** — correção é versão nova; a anterior fica com a data em que deixou de valer.
4. **Aresta só determinística** — identificador validado por código; modelo propõe, nunca grava.
5. **Um ponto de leitura para todo agente, em toda máquina** (jfn-brain), com a mesma busca.
6. **O que não é medido não é promovido** — toda fase tem número de entrada e de saída na bateria.
7. **Invariantes da casa**: WhatsApp fora de toda camada; CPF, e-mail e segredo recusados na saída; pessoa física só com identificador mascarado; indisponível ≠ vazio.

---

## 5. Arquitetura-alvo

### 5.1 Camadas

```
 C6  AVALIAÇÃO CONTÍNUA   bateria (config/cerebro_bateria.yaml) → despachante → catraca → Sistema › Propagação
 C5  CONSOLIDAÇÃO         noturna, determinística: dedupe por chave · contradição · validade · fila de proposta
 C4  RECUPERAÇÃO          entidade citada → BM25 por nota → resgate por vetor        (um serviço: jfn-brain)
 C3  NARRATIVA            ~/vault  casos/ (autor) · jfn/ (gerador) · decisoes/ · aprendizados/
 C2  ENTIDADES E ARESTAS  empresa · pessoa* · órgão/UG · processo SEI · OB · contrato · caso   (*mascarada)
 C1  REGISTRO DE FATOS    número → certeza.db · fato de caso / decisão / lição → memórias do jfn-brain
 C0  FONTES PRIMÁRIAS     SIAFE (OB) · data/sei_arquivo · compliance.db · DOERJ · PNCP · TCE-RJ     (nunca copiadas)
```

### 5.2 C1 — fonte única por tipo de fato

| Tipo de fato | Fonte única | Identidade | Tempo | Prova exigida | Quem escreve |
|---|---|---|---|---|---|
| **Número publicado** (valor, contagem) | `certeza.db` › `fato_versao` | `familia:chave:medida` | só-acréscimo, com vigência | P1–P8 + `nivel_prova` | bloco `fatos:` do mapa de propagação |
| **Pagamento** | SIAFE (`ob_orcamentaria_siafe`) | UG + nº da OB | data da OB, status de envio | a própria OB — **só OB é "pago"** | coletor |
| **Fato de caso** (achado) | laudo de origem → memória com chave | `pericia-agente:<processo>` … | **alvo:** `valeu_de/valeu_ate` × `gravado_em/substituido_em` | **alvo:** `prova_doc` + `prova_trecho` + `prova_hash` obrigatórios para nível 2 | só código (`cerebro_compartilhado.registrar`) |
| **Decisão do dono** | memória dos agentes → memória `decisoria` | `memoria:<slug>` | `supersedes` | a palavra do dono, com data | sessão |
| **Lição** | taxonomia de armadilhas (perícia) · catálogo de falhas (engenharia) | id da armadilha / família | candidato → campeão | portão R1–R6 / catraca | só o portão |
| **Narrativa de caso** | `~/vault/casos/` | caminho da nota | git diário do vault | cita fato por id (`<!--fato:ID-->`) | autor |
| **Código** | git + GitNexus | símbolo | commit | — | — |

**O que muda em relação a hoje:** as memórias do jfn-brain ganham as duas linhas de tempo e os três campos de prova
(hoje têm `created_at`, `supersedes` e `valid_to`, e a prova vai no texto). No Postgres 16:
`valeu tstzrange`, `registrado tstzrange` e `EXCLUDE USING gist (chave WITH =, registrado WITH &&)`.

### 5.3 C2 — entidades e arestas (o cruzamento entre casos)

| Entidade | Chave | Extração | Cor |
|---|---|---|---|
| Empresa | CNPJ (14 dígitos, dígito verificador conferido) | regex + validador | pela régua de risco do Radar |
| Pessoa física | **hash do CPF + nome mascarado** — nunca o CPF | só a partir das tabelas próprias do `compliance.db` | neutra |
| Órgão / UG | código de UG (6 dígitos) | regex + `data/ug_canonico.json` | **`cores_orgaos` — a mesma em Obsidian, galáxia e interface do cérebro** |
| Processo SEI | `NNNNNN/NNNNNN/AAAA` | regex | herda a do órgão |
| OB | UG + `AAAAOBNNNNN` | regex + existência no SIAFE | herda a do órgão |
| Contrato | órgão + nº/ano | regex | herda a do órgão |
| Caso | caminho da nota em `casos/` | — | a do órgão predominante (regra de maioria estrita já implantada) |

Aresta = `(entidade, papel, onde aparece, prova)` — "credor em", "citada em", "paga por", "sócia de". Uma tabela no
Postgres do jfn-brain, preenchida pelo indexador a cada nota e a cada memória. **Sem servidor de grafo**: nesta
escala (milhares de nós) vizinhança e caminho curto são consultas SQL. O `ponte_entidade` de hoje é o protótipo —
cobre 518 perícias; o alvo cobre as 1.432 notas e as 1.550 memórias.

Pergunta que passa a ter resposta em uma chamada: *"em que casos, processos e órgãos esta empresa aparece, em que
papel, e com que prova?"* — ferramenta MCP `brain_entity` (Fase 4).

### 5.4 C4 — recuperação

| Etapa | O que faz | Estado |
|---|---|---|
| 1. Entidade | identificador na pergunta → notas da entidade, na frente | implantado (VM-1) |
| 2. Primária | BM25 por nota inteira; título ×6, nome do arquivo ×8, resumo ×4, corpo ×1 | implantado (VM-1, SQLite FTS5 sobre o vault local) |
| 3. Resgate | o vetor do jfn-brain põe até 2 notas que a primária não trouxe (pergunta sem palavra em comum; fontes fora do vault) | implantado |
| 4. Reordenação por modelo | cruzado, só no top-20 | **não adotado** — sem medição em ARM; a 15 s por consulta não serve |

Código: `compliance_agent/cerebro_busca.py`. Uso: `python -m compliance_agent.cerebro_compartilhado caso "<termo>"`
(é o caminho que a regra 9 do `CLAUDE.md` manda seguir) ou `python -m compliance_agent.cerebro_busca "<pergunta>"`.

**Limite da Fase 1:** vale para quem lê pela VM-1. O `brain_search` do MCP (sessões da VM-2, Yoda/Hermes, Claude
pela web) continua com a busca antiga até a Fase 2 levar a mesma lógica para dentro do serviço.

### 5.5 C5 — consolidação ("sono")

Roda de madrugada, **sem modelo decidindo**:

| Passo | Regra | Saída |
|---|---|---|
| Dedupe | mesma chave e mesmo texto = nada; mesma chave e texto novo = versão nova | já existe (`registrar`) |
| Contradição | mesma entidade + mesma medida + valores diferentes em fatos vigentes | fila "a conferir" — ninguém é corrigido sozinho |
| Validade | fato cuja fonte foi regravada sem ele → marca `valeu_ate` | registro |
| Higiene do recall | memórias geradas em série (71,2% do total) saem do `recall` padrão e ficam atrás do filtro por entidade | config |
| Proposta | resumo de caso, ligação sugerida, lição candidata — **por modelo, pela assinatura, 23h–06h** | fila de revisão; nada entra em nota de caso nem em prompt sem portão |

### 5.6 C6 — avaliação contínua

`tools/cerebro_bateria.py` é derivado `cerebro_bateria` do mapa de propagação: roda depois que as notas geradas
mudam, no máximo 1× por dia, e **falha de forma visível** (Sistema › Propagação) se o recall@10 cair abaixo de 53/56.

### 5.7 Multiagente e multimáquina

| Agente | Lê por | Escreve por | Depois da Fase 2 |
|---|---|---|---|
| Claude VM-1 (sessões, cron, subagentes) | `caso` (busca nova) · MCP | `lembrar --chave` | igual |
| Claude VM-2 · Claude web | MCP `brain_search` (busca antiga) | MCP `brain_remember` | busca nova no serviço |
| Yoda / Hermes | `hermes_rag` (índice próprio) | não escreve fato | lê o jfn-brain; `hermes_rag` fica só com o corpus legal |
| Despachante | — | `registrar` + envio em lote | igual |

---

## 6. Decisão sobre o Khoj

> [!warning] Decisão executada em 19/11/2026: **Khoj aposentado de forma reversível**
> Serviços parados e fora do boot na VM-2; **dados preservados** (`~/khoj-piloto/pgdata` 113 MB, `venv` 1,8 GB).
> Esta decisão **revê a de 14/11** ("Khoj mantido ligado"), tomada quando ele era o melhor buscador medido. O dono
> pode desfazê-la com uma linha (abaixo).

| Fato medido | Valor | Estado |
|---|---|---|
| Recall@10 do Khoj na bateria | 35 de 56 (dono: 17 de 20) | VERIFICADO |
| Recall@10 da busca nova **sem** o Khoj | 56 de 56 (dono: 20 de 20) | VERIFICADO |
| Recall@10 da busca nova **com** o Khoj como perna | 56 de 56 — idêntico em todas as medidas | VERIFICADO |
| 1º lugar nas 20 perguntas do dono | Khoj 14 · busca nova 13 | VERIFICADO — diferença de 1 pergunta em 20, dentro do ruído |
| Cobertura do índice do Khoj | 810 de 1.408 notas (57,5%), congelado em 18/11 | VERIFICADO |
| Reindexação | falha desde 19/11: limite de 1.000 arquivos por envio | VERIFICADO (`logs/reindex.log`) |
| Memória | 1,13 GB em uso; pico de 1,7–1,8 GB; parado pela vigia em 18/11 | VERIFICADO |
| Quem depende dele | nenhum chamador no código, no cron, no Hermes | VERIFICADO (grep + log de acesso) |

**Por que aposentar e não consertar:** consertar o envio em lotes devolveria um segundo serviço de 1,1–1,8 GB que
não melhora nenhuma medida da bateria. **O que o Khoj ensinou e fica como meta:** em pergunta curta do dono um bom
vetor acerta o primeiro lugar (14 de 20) — é a régua da Fase 3 para o vetor do próprio jfn-brain.

**Reverter:**
`ssh vm2-ts 'systemctl --user enable khoj-piloto-pg khoj-piloto khoj-piloto-vigia khoj-piloto-reindex.timer && systemctl --user start khoj-piloto-reindex.timer && ~/khoj-piloto/ligar.sh'`
— e medir com `tools/cerebro_bateria.py medir --sistemas khoj,fundido,fundido_com_khoj`.

**Apagar os 2,2 GB de disco** é decisão do dono (§10) — não foi feito.

---

## 7. Bateria de avaliação

| Item | Valor |
|---|---|
| Arquivo | `config/cerebro_bateria.yaml` — 56 perguntas |
| Grupo `dono` (20) | perguntas **literais** do dono (erros de digitação mantidos), tiradas do histórico do Claude Code e do Telegram do Yoda; gabarito pré-registrado em 14/11/2026 com sha256, antes de qualquer consulta |
| Grupo `casos` (36) | perguntas escritas em 19/11/2026 sobre 36 notas de `~/vault/casos`, no jeito curto do dono, com **resposta esperada** e um **trecho literal** que tem de existir na nota |
| Controle do gabarito | `tools/cerebro_bateria.py validar` — nota que sumiu ou perdeu o trecho derruba a validação, não o recall |
| Contaminação tratada | a ata da rodada cega transcreve as 20 perguntas do dono; ela sai da lista de todos os sistemas (`ignorar:`) |
| Medida | posição da primeira nota do gabarito entre as notas distintas devolvidas → recall@1/5/10, MRR@10 |
| Rodar | `python tools/cerebro_bateria.py medir [--sistemas …] [--minimo 53]` · resultado em `data/cerebro_bateria/` |

### 7.1 Resultado completo (19/11/2026, 08:23 BRT)

| Sistema | Grupo | n | 1º lugar | Top-5 | Top-10 | MRR@10 |
|---|---|---:|---:|---:|---:|---:|
| **jfn-brain** (como o agente recebia) | total | 56 | 20 | 32 | 33 | 0,439 |
| | dono | 20 | 4 | 9 | 9 | 0,283 |
| | casos | 36 | 16 | 23 | 24 | 0,526 |
| jfn-brain, 40 trechos → 10 notas | total | 56 | 21 | 32 | 34 | 0,450 |
| **Khoj** (índice de 18/11) | total | 56 | 28 | 34 | 35 | 0,551 |
| | dono | 20 | 14 | 16 | 17 | 0,758 |
| | casos | 36 | 14 | 18 | 18 | 0,435 |
| **Busca nova** (entidade + BM25 por nota + resgate) | total | 56 | **46** | **55** | **56** | **0,893** |
| | dono | 20 | 13 | 19 | 20 | 0,792 |
| | casos | 36 | 33 | 36 | 36 | 0,950 |
| Busca nova + Khoj | total | 56 | 46 | 55 | 56 | 0,893 |

Tempo por consulta da busca nova: mediana 1,14 s com a VM-1 em carga 20 (0,1 a 0,8 s por perna com a máquina calma).

### 7.2 Alternativas medidas e descartadas

| Alternativa (mesmas 56 perguntas) | 1º lugar | Top-5 | Top-10 | MRR@10 |
|---|---:|---:|---:|---:|
| Fusão por voto (RRF), pesos iguais: cérebro + cérebro-OR + BM25 + Khoj | 40 | 47 | 52 | 0,770 |
| RRF: BM25 + Khoj | 38 | 53 | 56 | 0,798 |
| RRF: BM25 com peso 4 + cérebro | 42 | 54 | 56 | 0,844 |
| Desconto de 40% para nota gerada em série | sem efeito mensurável | | | |
| **BM25 por nota dando a ordem + resgate** (adotado) | **46** | **55** | **56** | **0,893** |

### 7.3 Limites desta medição (honestidade)

- **O grupo `casos` favorece a busca por palavra**: as perguntas foram escritas por agente a partir do resumo da
  nota; mesmo sem copiar o título, compartilham vocabulário. O grupo `dono` não tem esse viés — e nele o ganho se
  mantém em top-5 (9 → 19) e top-10 (9 → 20).
- **20 perguntas do dono é amostra pequena**; 13 × 14 no primeiro lugar não distingue a busca nova do Khoj.
- O gabarito é de um avaliador só (agente); o dono não o revisou.
- A bateria mede **achar a nota**. Não mede: o `recall` de memórias, o cruzamento por entidade, nem se a resposta
  final do agente está certa. São os grupos novos das Fases 4 e 5.

---

## 8. Plano em fases

| Fase | O que entrega | Critério de pronto (mensurável) | Custo | Risco e reversão | Decisão |
|---|---|---|---|---|---|
| **1 — Medir e achar** | Bateria de 56 · busca por nota no `caso` · catraca no despachante · Khoj aposentado | recall@10 ≥ 53/56 — **medido: 56/56** (base: 33/56) | Zero | `JFN_CEREBRO_FUNDIDO=0` volta à busca antiga; Khoj volta com 1 linha | **FEITA** |
| **2 — A mesma busca para todo agente** | Perna "por nota" **dentro** do jfn-brain (coluna `tsvector` com pesos A/B/C/D por título, nome, resumo e corpo, ordenada por nota; ou o mesmo FTS5 ao lado); `brain_search` do MCP devolve notas; Hermes passa a ler o jfn-brain | sistema `brain` da bateria: recall@10 ≥ 53/56 e 1º lugar ≥ 40/56 (hoje 33 e 20) | Zero · ~1 sessão | Escreve na VM-2: cópia `brain_core.py.bak-<data>` + chave de configuração para a busca antiga | **Dono** (escrita na VM-2) |
| **3 — Vetor melhor, em sombra** | Coluna-sombra com 1 a 3 modelos abertos (gte-multilingual-base, arctic-embed-m-v2.0, multilingual-e5-small); cronometrar 200 trechos antes de reembutir os 10.069 | perna só-vetor: 1º lugar no grupo `dono` ≥ 14/20 (régua do Khoj) e recall@10 total ≥ 45/56 (hoje 34). Não bateu → fica o modelo atual | Zero de API; CPU da VM-2 com `nice` (tempo a medir nos 200 trechos) | Coluna nova; a antiga só sai depois da medição | Pode ser feita com o ok da Fase 2 |
| **4 — Entidades e tempo** | Tabela de entidades e arestas no Postgres para **todas** as notas e memórias; duas linhas de tempo e campos de prova nas memórias; `brain_entity` no MCP; cor do órgão na entidade | grupo novo `cruzamento` (≥ 20 perguntas "em que casos aparece X") com recall ≥ 95%; 100% dos fatos de nível 2 com `prova_doc` preenchido; 0 CPF em claro (catraca) | Zero · 2 a 3 sessões | Só acrescenta tabela e coluna; migração com cópia do banco antes | **Dono** |
| **5 — Consolidação e higiene** | Rotina noturna do §5.5; memórias em série fora do `recall` padrão; carga das memórias antigas dos agentes; `MEMORY.md` ≤ 200 linhas | grupo novo `memorias` (≥ 30 perguntas sobre decisões do dono) com recall@5 ≥ 90% — **base a medir antes de mexer**; contradições abertas listadas em Sistema | Zero de API (propostas por modelo só pela assinatura, 23h–06h) | Filtro é configuração; nada é apagado | Dono decide o teto da assinatura |
| **6 — Contexto por trecho** (opcional, pago) | Linha de contexto gerada por modelo para cada trecho (Contextual Retrieval) | só se, depois das Fases 2 e 3, o 1º lugar no grupo `dono` ficar < 16/20; ganho mínimo de +2 perguntas para manter | **API paga** — §9 | Coluna separada; desligar = ignorar a coluna | **Dono**, com teto |

**Ordem recomendada:** 2 → 3 → 4 → 5. A Fase 6 só se a medição pedir.

---

## 9. Custo

| Item | Onde roda | Custo |
|---|---|---|
| Fases 1 a 5 | VM-1 e VM-2, software livre já instalado (Postgres 16, pgvector, SQLite FTS5, fastembed) | **R$ 0,00** de API |
| Memória da VM-2 | liberada pela aposentadoria do Khoj | −1,1 a −1,8 GB |
| Propostas de consolidação (Fase 5) | assinatura do Claude, janela 23h–06h já existente | sem custo adicional; teto de chamadas a definir pelo dono |
| **Fase 6** — contexto por trecho | API da Anthropic (modelo pequeno, com cache de prompt) | Volume estimado: 10.069 trechos × ~2.500 tokens de entrada ≈ **25 milhões de tokens de entrada** (a maior parte em cache, por nota) + ≈ 0,8 milhão de saída, uma vez; depois só o que mudar. **Preço não citado de memória** — conferir a tabela oficial no dia. Proposta de teto: **US$ 5,00**, dentro dos US$ 100,00 já liberados, com interruptor e contagem antes de ligar |
| Graphiti / mem0 / GraphRAG | — | **não adotados** (LLM por documento + servidor de grafo) |

---

## 10. O que fica para o dono decidir

| # | Decisão | Recomendação | Se não decidir |
|---|---|---|---|
| D1 | Confirmar a aposentadoria do Khoj (revê a decisão de 14/11) | Confirmar | Fica parado, reversível |
| D2 | Apagar `vm2:~/khoj-piloto` (2,2 GB) | Só depois da Fase 3 (a régua do vetor é dele) | Dados ficam |
| D3 | Autorizar a Fase 2 (escrita no serviço do cérebro, VM-2) | Autorizar — é o que leva o ganho ao Yoda e às outras sessões | Ganho fica só na VM-1 |
| D4 | Autorizar a Fase 4 (esquema de entidades e tempo) | Autorizar depois da 2 | — |
| D5 | Teto de chamadas da assinatura para as propostas de consolidação | 50 por noite | Fase 5 roda só a parte determinística |
| D6 | Fase 6 paga (teto US$ 5,00) | **Não ligar agora** — só se a medição pedir | Não liga |
| D7 | Revisar o gabarito da bateria (15 min) | Recomendado: hoje o gabarito é de um avaliador só | Bateria segue como está |

---

## 11. Riscos

| Risco | Probabilidade | Efeito | Mitigação |
|---|---|---|---|
| A bateria superestima a busca por palavra (viés do grupo `casos`) | média | Fase 2 otimiza para o que não é o uso real | grupo `dono` separado em toda tabela; D7; crescer o grupo `dono` com perguntas novas do histórico |
| Pergunta sem nenhuma palavra em comum com a nota | baixa | BM25 não acha | resgate por vetor (2 lugares) — e a Fase 3 |
| Índice local defasado | baixa | nota nova não aparece | conferência por mtime a cada 10 min; a bateria reindexa antes de medir |
| VM-2 fora do ar | baixa | sem memórias e sem resgate | a busca por nota continua na VM-1 e o `caso` **diz** que parte não respondeu |
| Nota que transcreve perguntas contamina a medida | ocorreu | recall inflado | lista `ignorar:` no yaml; a decisão no vault não transcreve perguntas |
| Catraca alarma por nota de caso renomeada | média | derivado `cerebro_bateria` em falha | `validar` aponta a pergunta; corrige-se o gabarito, não o limiar |

---

## 12. Implantado em 19/11/2026

| Item | Onde | Prova |
|---|---|---|
| Busca por nota (entidade → BM25 → resgate) | `compliance_agent/cerebro_busca.py` | `tests/test_cerebro_busca.py` — 10 testes (controle positivo e negativo; perna fora do ar é dita) |
| `caso` usa a busca nova | `compliance_agent/cerebro_compartilhado.py` (`JFN_CEREBRO_FUNDIDO=0` desliga) | `tests/test_cerebro_compartilhado.py` — 21 testes passam |
| Bateria e medidor | `config/cerebro_bateria.yaml` · `tools/cerebro_bateria.py` | `validar`: 56 de 56 com gabarito no vault |
| Medições guardadas | `data/cerebro_bateria/base-2026-11-19.json` · `fase1-2026-11-19.json` | — |
| Avaliação contínua | derivado `cerebro_bateria` em `config/propagacao.yaml` (catraca 53/56) | Sistema › Propagação |
| Khoj | parado e fora do boot; anotado em `vm2:~/khoj-piloto/LEIAME.txt` | `is-active` = inactive ×4 · `is-enabled` = disabled ×4 |
| Decisão registrada | `~/vault/decisoes/2026-11-19-segundo-cerebro-arquitetura-alvo.md` · memória `decisoria` no jfn-brain | — |

## 13. Fontes

Medição própria: `data/cerebro_bateria/*.json`; `journalctl --user -u brain-api` e `-u khoj-piloto` (VM-2);
`vm2:~/khoj-piloto/logs/{reindex,vigia,khoj}.log`; `data/propagacao.db` (tabelas `cerebro`, `ponte_entidade`);
`/api/stats` do jfn-brain. Rodada anterior: `~/vault/decisoes/2026-11-14-khoj-rodada-cega-perguntas-reais.md`.
Literatura: URLs e datas na tabela do §3 (pesquisa de 19/11/2026; itens "n.c." não foram confirmados na fonte).
