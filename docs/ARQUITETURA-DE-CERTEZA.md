# JFN — Arquitetura de Certeza

| | |
|---|---|
| **Documento** | Desenho, origem de cada ideia, medições e limites |
| **Versão** | 1.0 — 18/11/2026 |
| **Pedido do dono** | "Nessa arquitetura monte o caminho para que tudo seja atualizado simultaneamente, ou seja, temos um super controle de qualidade e certeza em cima de tudo." |
| **Escopo** | Todo número que a casa afirma: derivados, detectores, laudos, notas do vault, memórias do cérebro, painel |
| **Código** | `compliance_agent/certeza/` · testes `tests/test_certeza_*.py` · mapa `config/propagacao.yaml` |
| **Comando** | `python -m compliance_agent.certeza ciclo` (rodado pelo despachante de propagação) |
| **Estado** | Implementado e medido nos dados reais. O que muda algo fora de `data/certeza/` nasce **desligado** (§8) |

> **Regra de ouro, herdada do autoaprimoramento:** quem aprova é código determinístico, com o motivo escrito.
> Aqui o que se julga não é uma mudança de prompt — é **toda escrita de número**. O ciclo não chama modelo, não
> grava no `compliance.db` e não se reagenda.

---

## 1. Sumário executivo

A arquitetura de autoaprimoramento (`docs/AUTOAPRIMORAMENTO-JFN.md`) deu à perícia de execução um ledger com
nível de prova, calibração e portão. A propagação (`config/propagacao.yaml`) deu aos derivados um mapa e um
despachante. Faltava a peça que une os dois e vale para tudo: **o número em si não tinha identidade**. O mesmo fato
vivia no JSON do detector, na nota do vault, na memória do cérebro e no painel, e ninguém conferia um contra o
outro. Esta arquitetura dá identidade ao fato, um portão a cada escrita, um grafo único auditado e um verificador
que acusa onde um texto repete número diferente.

**Medições do primeiro ciclo real (18/11/2026, 19:20–19:30, `data/certeza/estado.json`):**

| Medida | Valor | Estado |
|---|---:|---|
| Fatos registrados com identidade, proveniência e nível de prova | 33 | VERIFICADO |
| — por estado | 16 VERIFICADO · 15 PENDENTE · 2 A CONFERIR | VERIFICADO |
| — por nível de prova | 26 de nível 2 · 7 de nível 1 | VERIFICADO |
| Textos lidos pelo verificador (vault, `docs/`, memória dos agentes) | 1.343 arquivos | VERIFICADO |
| Divergência aberta no vault (nota da AGILE, linha 936: "35 processos"; vigente 38) | 1 | A CONFERIR (§6.1) |
| Índice do cérebro servindo o valor antigo depois de a nota ser corrigida | 1, por pelo menos 32 min | VERIFICADO (§6.1) |
| OB contabilizadas cujo envio **não** está confirmado e que a regra da casa conta como pagas | 34.759 OB · R$ 5.747.413.028,45 | VERIFICADO (§6.4) |
| OB com `status_envio` fora do domínio (colunas deslocadas na coleta) | 45 de 1.363.027 | VERIFICADO |
| Valor-sentinela em `sei_fila_captura.total_pago` | 0 de 14.188 | VERIFICADO |
| Linhas de achado sob fotografia de nível de prova | 14.788 (8.468 laudos + 6.320 triagens) | VERIFICADO |
| Laudos de risco alto de modelo de volume → esperados confirmar na fonte | 665 → 12,6 | ESTIMADO (taxa calibrada) |
| Risco alto exibido como VERIFICADO sem prova primária | 0 | VERIFICADO |
| Laudos dados antes da última captura do processo (fila da re-perícia) | 660 | VERIFICADO |
| Grafo: fontes · derivados · externos | 29 · 21 · 4 | VERIFICADO |
| Grafo: defeitos listados (§6.5) | 2 fontes sem consumidor · 4 sondas que nunca viram mudança · 6 derivados sem efeito verificável · 1 derivado que nunca rodou · 15 arquivos do painel fora do grafo | VERIFICADO |

---

## 2. Desenho em uma página

```
 FONTES (SIAFE, SEI, DOERJ, TCE, commits de regra…)            config/propagacao.yaml  ← o GRAFO ÚNICO
     │ sonda (de fora) → evento                                   fontes · derivados · externos · fatos
     ▼                                                            contratos · superfícies
 DERIVADOS (despachante */5)        EXTERNOS (cron próprio, LLM)
 perícia contábil, ISS, CGE…        perícia de execução, triagem, fichas ──publica──► fonte (sei_lex, triagem…)
     │ declaram `fatos:`                    │ declaram `atraso` (o que ficou velho)
     ▼                                      ▼
 ┌────────────────── CICLO DA CERTEZA (derivado `certeza`, folha do grafo, sem LLM) ──────────────────┐
 │ 1 EXTRAIR  o valor de cada fato declarado (JSON do derivado ou SQL só-leitura)                      │
 │ 2 PORTÃO   P1 identidade · P2 tipo/faixa · P3 proveniência · P4 estado · P5 prova primária ·        │
 │            P6 pagamento · P7 não regride · P8 leu antes de escrever                                 │
 │ 3 REGISTRO fato_versao — só acréscimo (gatilho do banco recusa UPDATE/DELETE); recusa fica gravada  │
 │ 4 CONTRATOS das tabelas de achado: faixa, domínio, proveniência (auditoria) + fotografia do nível   │
 │            de prova de cada linha (acusa a que regrediu, guarda o conteúdo anterior)                │
 │ 5 GRAFO    órfãos, ciclos, sonda cega, derivado atrasado, externo cuja fila não drena               │
 │ 6 TEXTO    citação `número<!--fato:ID-->` × valor vigente; menção livre a valor SUPERADO;           │
 │            agregado × linhas de detalhe; índice e registro do cérebro                               │
 │ 7 DIVERGÊNCIAS  aberta → curada → REINCIDIU (só cura o que foi lido inteiro)                        │
 └───────────────┬───────────────────────────────┬──────────────────────────────┬────────────────────┘
                 ▼                               ▼                              ▼
   /api/sistema/certeza                 sensor `certeza`                 com a chave ligada:
   data/certeza/relatorio.md            (fila da automelhoria)           reescreve a citação no vault ·
   por fato: valor, estado, prova,                                       registra o fato no cérebro ·
   confiança, frescor, divergências                                      gatilho de faixa no banco
```

### 2.1 O fato

`familia:chave[:chave…]:medida` — por exemplo `iss_nao_retido:00801512000157:180100:valor` (família, CNPJ do
credor, UG, medida). O nome legível fica no rótulo; a identidade usa o que não muda.

| Campo | Conteúdo |
|---|---|
| `valor`, `unidade` | BRL · contagem · percentual · índice. INDISPONÍVEL não carrega valor (INDISPONÍVEL ≠ 0) |
| `estado` | VERIFICADO · A CONFERIR · PENDENTE · INDISPONIVEL · REFUTADO |
| `nivel_prova` | 2 = fonte primária, conta fechada registro a registro ou soma direta sobre ela · 1 = agregado que depende de regra de vínculo, ou juízo sobre resumo · 0 = estimativa ou modelo de volume |
| `natureza`, `base` | O **status ao lado do valor**: "pago" só é VERIFICADO com base `ob_contabilizada_confirmada` |
| `confianca` | Probabilidade calibrada quando o fato é juízo de modelo (taxa do autoaprimoramento); para soma e contagem, "determinístico: consulta reproduzível" |
| proveniência | `fonte`, `consulta` (arquivo › lista › campo, ou o SQL), `data_ref`, `hash_fonte`, `produtor` |
| tempo | `registrado_em` (desde quando o valor vale) e `confirmado_em` (última vez que a fonte o reproduziu) |

Uma medição nova é uma **versão** nova; a anterior permanece. É isso que permite acusar o texto que ainda repete
o número antigo.

### 2.2 Como um texto carrega um fato

1. **Citação por id:** `R$ 2.437.189,45<!--fato:iss_nao_retido:00801512000157:180100:valor-->`. O comentário é
   invisível na leitura do Obsidian e é indexado pelo cérebro com o texto. `python -m compliance_agent.certeza
   citar <trecho>` entrega a citação pronta.
2. **Menção livre:** sem âncora. O verificador procura o valor de versões **superadas** — o monetário ao centavo;
   a contagem como "35 processos", no parágrafo que cita o fornecedor e o assunto. Parágrafo com
   `<!--fato-historico-->` é narrativa de histórico.

### 2.3 Níveis de controle

| Controle | Onde age | Vale para |
|---|---|---|
| **Preventivo** — `fatos.registrar`, `portoes.escrever` | Antes de gravar, na mesma transação da leitura | Todo fato; código novo que grava em tabela de achado |
| **Preventivo no banco** — gatilho de faixa (`ddl_gatilhos`) | Dentro do SQLite: qualquer processo | Tabelas com contrato; instalação depende do dono (§8) |
| **Detectivo** — `auditar`, `fotografar`, `varrer`, `grafo.auditar` | A cada ciclo, só leitura | Tudo o que já existe, sem tocar em quem escreve |
| **Já existente, mantido** — `lex_execucao._antes_de_regravar` | No único ponto de regravação do laudo | Perícia de execução |

---

## 3. De onde veio cada ideia

### 3.1 Da casa (esqueleto — nada foi reinventado)

| Peça existente | Papel aqui |
|---|---|
| `config/propagacao.yaml` + `compliance_agent/propagacao.py` | O grafo. Ganhou `fatos:`, `externos:`, `contratos:`, `certeza:` e `frescor_max_s`; o despachante não foi alterado e executa o derivado `certeza` como qualquer outro |
| `autoaprimoramento/portao.py` | O formato do veredito (regra, ok, detalhe) e a regra de ouro |
| `autoaprimoramento/ledger.py` (`nivel_gravado`, `antes_de_regravar`) | O nível de prova do laudo; a regra "prova primária não é regravada por juízo mais fraco", generalizada em P7 |
| `autoaprimoramento/calibracao.py` (`confianca`) | A probabilidade de confirmação exibida com o laudo de risco alto |
| `correlacao_sei.estado_do_laudo` | Conferido a cada ciclo: nenhum risco alto VERIFICADO sem prova primária |
| `siafe_status_ob.INTERMEDIARIOS` | Quais status de envio não confirmam pagamento |
| `config/qualidade_inventario.yaml`, `qualidade_detectores.yaml` | Cruzados com o grafo: o que o painel serve e o que os detectores gravam fora dele |
| `tools/automelhoria_geral.py` | Sensor `certeza` na fila única (aberto, curado, REINCIDIU) — o mesmo ciclo de vida das divergências |
| `cerebro_compartilhado` (`buscar`, `registrar`) | Superfície conferida e, com a chave ligada, destino dos fatos |
| Regras de qualidade PAD-01, PAD-02, CST-11, COR-03 | Proveniência na rota, estados, superfície inventariada, controle positivo e negativo |

### 3.2 Estado da arte — o que entrou e o que ficou de fora

| Técnica (fonte) | Ideia | O que entrou | O que ficou de fora e por quê |
|---|---|---|---|
| OpenLineage, *Object Model* — https://openlineage.io/docs/spec/object-model · Marquez — https://marquezproject.ai/ | Job, Run e Dataset com facetas de metadado | Cada versão de fato grava produtor (job), fonte e hash (dataset) e data de referência (run); o grafo é declarado num arquivo só | Servidor de linhagem e emissão por execução: serviço novo, sem ganho sobre o YAML numa VM |
| Dagster, *Assets* e *Declarative Automation* — https://dagster.io/docs/guides/build/assets · https://dagster.io/docs/guides/automate/declarative-automation | Grafo de ativos; materializar pelo estado das dependências | Já era o desenho do despachante; aqui entram o nó "externo" e o frescor por nó | Orquestrador próprio: o despachante existe |
| Dagster, *Data freshness checks* — https://docs.dagster.io/guides/test/data-freshness-testing (página vista na busca, não aberta) · dbt, *freshness* — https://docs.getdbt.com/reference/resource-properties/freshness | Ativo "fresco" ou "atrasado" por idade máxima declarada | `frescor_max_s`; "atrasado" é sujo além do teto; fila de externo que não diminui em 24 h | Limiar por coluna de carga |
| dbt, *data tests* — https://docs.getdbt.com/docs/build/data-tests | Asserção em SQL: passa quando zero linhas violam; `accepted_values` | `portoes.auditar`: faixa, nulo e `dominio` contados por SQL, com exemplos | Testes de relacionamento entre tabelas |
| dbt, *Model contracts* — https://docs.getdbt.com/docs/mesh/govern/model-contracts · Open Data Contract Standard (Bitol) — https://bitol-io.github.io/open-data-contract-standard/latest/ | Contrato declarado: forma e qualidade da saída | Bloco `contratos:` em YAML: chave, faixa, domínio, proveniência, nível de prova | A especificação inteira (SLA, preço, papéis): não se aplica |
| Great Expectations, *Checkpoint* — https://docs.greatexpectations.io/docs/reference/learn/terms/checkpoint | Validar em produção e agir sobre o resultado | O ciclo é o checkpoint; a ação é o sensor | A biblioteca: peso e dependências para o que são seis consultas |
| Soda, *Reconciliation checks* — https://docs.soda.io/soda-documentation/soda-v3/sodacl-reference/recon (conteúdo visto na busca) · Datafold `data-diff` — https://github.com/datafold/data-diff (arquivado) | Conferir destino contra origem | `reconcilia`: o agregado publicado tem de bater com a soma das linhas de detalhe; citação × fato; índice do cérebro × fato | Comparação linha a linha entre bancos |
| Monte Carlo, *5 pillars of data observability* — https://montecarlo.ai/blog-what-is-data-observability | Frescor, volume, schema, distribuição, linhagem | Frescor (nó), distribuição (faixa e domínio), linhagem (grafo), schema (coluna do contrato que sumiu é erro declarado) | Detecção estatística de anomalia de volume: sem série histórica ainda |
| Fowler, *Event Sourcing* (2005) — https://martinfowler.com/eaaDev/EventSourcing.html | Guardar cada mudança num log e reconstruir o passado | `fato_versao` só acréscimo, imposto por gatilho do banco | Reconstruir o estado por replay: a versão vigente é uma consulta |
| Fowler, *Bitemporal History* (2021) — https://martinfowler.com/articles/bitemporal-history.html | Quando valeu no mundo × quando o sistema soube | `data_ref` (a fonte) × `registrado_em` e `confirmado_em` (o registro) | Correção retroativa de validade |
| W3C, *PROV-O* (2013) — https://www.w3.org/TR/prov-o/ | Entidade, atividade, agente | fato (entidade), consulta (atividade), produtor (agente) | A ontologia em RDF |
| Apache Iceberg, *Audit Branch* (Write-Audit-Publish) — https://iceberg.apache.org/docs/latest/branching/ | Escrever, auditar, só então publicar | O valor proposto é julgado antes de virar a versão vigente; o recusado fica à parte | Branch de tabela |
| IETF RFC 9110, §13.1.1 *If-Match* — https://www.rfc-editor.org/rfc/rfc9110.html#name-if-match | Escrita condicional à versão lida | P8: `lido` tem de ser a versão vigente, conferida dentro da transação de escrita | — |
| Budiu et al., *DBSP: Automatic Incremental View Maintenance*, PVLDB 16(7), 2023 — https://arxiv.org/abs/2203.16684 | Atualizar a visão processando só o delta | A propagação recalcula só o derivado sujo; a certeza só cria versão quando o valor muda | Manutenção incremental dentro do cálculo: os derivados são rotinas inteiras e idempotentes |
| dbt Semantic Layer (MetricFlow) — https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl | Métrica definida uma vez, consumida por todos | O fato definido uma vez no mapa e citado pelo id | Camada de consulta |
| Angelopoulos e Bates, *A Gentle Introduction to Conformal Prediction*, arXiv 2107.07511 — https://arxiv.org/abs/2107.07511 | Garantia de cobertura sem supor distribuição | Nada novo: a confiança exibida é a taxa calibrada que o autoaprimoramento já mede | Conjunto conformal: exige rótulos aleatórios que a casa ainda não tem (mesma razão do §7 do autoaprimoramento) |

As duas fontes marcadas "vista na busca" não sustentam decisão sozinhas: a ideia de frescor está na página do dbt,
aberta, e a de reconciliação está implementada e testada aqui.

---

## 4. Componentes

| Módulo | Função | Estado que mantém (`data/certeza/certeza.db`) |
|---|---|---|
| `config.py` | Caminhos, chaves (`JFN_CERTEZA_SINCRONIZAR`, `…_CEREBRO`, `…_GATILHOS`, `…_KILL`), tetos | — |
| `portoes.py` | `julgar_fato` (P1–P8), `julgar_linha`, `ler`/`escrever` (upsert guardado), `auditar`, `fotografar`, `ddl_gatilhos` | `linha_vista`, `regressao` |
| `fatos.py` | Registro só acréscimo, `registrar`, `extrair` (declaração `fatos:`), reconciliação, formatação única | `fato_versao`, `recusa`, `extracao`, `medida` |
| `grafo.py` | Auditoria do grafo e frescor por nó | — |
| `citacoes.py` | Citação, sincronização, menção a valor superado, cérebro, ciclo de vida da divergência | `divergencia` |
| `orquestrador.py` | Ciclo, painel, relatório, certeza dos laudos, publicação no cérebro | `estado.json`, `relatorio.md` |
| `rotas/propagacao.py` | `/api/sistema/certeza` (`?fato=` filtra) | — |
| `tools/automelhoria_geral.sensor_certeza` | Itens na fila única | — |

### 4.1 O portão

| Regra | Exigência | Falha de 18/11 que barra |
|---|---|---|
| P1 identidade | Id no formato `familia:chave:medida` | 1 |
| P2 tipo e faixa | Valor finito, unidade conhecida, dentro da faixa; monetário nunca é sentinela (acima de R$ 9e11 ou potência de dez ≥ R$ 1 bi) | 3 |
| P3 proveniência | Fonte, consulta, data de referência, hash da fonte e produtor preenchidos | 3 |
| P4 estado | Estado da casa; INDISPONÍVEL sem valor | 4 |
| P5 prova primária | VERIFICADO e toda graduação exigem nível 2 | 6 |
| P6 pagamento | "Pago" VERIFICADO exige envio confirmado | 4 |
| P7 não regride | Nível menor não substitui nível maior | 2 |
| P8 leu antes | A versão lida é a vigente no instante da escrita | 2 |

---

## 5. As seis falhas de 18/11/2026 — o que agora as barra

| # | Falha | Barreira | Teste de aceite (`tests/test_certeza_aceite.py`) |
|---:|---|---|---|
| 1 | Nota dizia 35 / R$ 2.270.009,39; o detector mediu 38 / R$ 2.437.189,45 | Fato com id; citação conferida; menção a valor superado acusada com arquivo e linha; agregado × detalhe; índice do cérebro | `test_f1_*` (9 testes: nota antiga acusada; nota atualizada, histórico e número alheio passam; parágrafo com quebra de linha; sincronização só com a chave; KILL; cérebro; ciclo de vida; ponta a ponta) |
| 2 | Lote montou a lista no início e regravou 51 laudos de prova primária | P8 e P7 em `portoes.escrever` e `fatos.registrar`; `fotografar` acusa regressão de qualquer escritor e guarda o conteúdo | `test_f2_*` (4 testes) |
| 3 | `total_pago = 1e12` gravado para priorizar | P2 e P3; auditoria da fila; gatilho de faixa barra INSERT, INSERT OR IGNORE, INSERT OR REPLACE e UPDATE | `test_f3_*` (13 casos) |
| 4 | OB "Enviado ao Banco" contada como paga | Cada status é um fato com o seu estado; P6; fonte ausente é erro declarado | `test_f4_*` (3 testes) |
| 5 | Recaptura do SEI não refazia o laudo | `externos:` fecham a cadeia; `atraso` conta os laudos anteriores à captura; auditoria do grafo | `test_f5_*` (3 testes, um deles sobre o mapa real) |
| 6 | 1,8% dos riscos altos de volume sobrevivem à fonte | P5; `laudos()` conta o que escaparia e exibe os esperados pela taxa calibrada | `test_f6_*` (8 casos) |

**Teste de mutação:** cada uma das regras P2 (sentinela), P5, P6, P7 e P8 (nas duas formas) foi desligada à mão,
uma por vez; em todas o aceite quebrou (de 1 a 4 testes). Com o código íntegro, 47 testes passam.

**Alcance honesto de cada barreira:**

| Falha | Hoje é impossível… | …e hoje é só detectado (até o próximo ciclo) |
|---|---|---|
| 1 | Divergir entre registro e texto que cita por id com a chave de sincronização ligada | Texto livre sem âncora; texto fora das superfícies declaradas (docstrings de código) |
| 2 | Em `lex_execucao` (gancho existente) e em qualquer escrita por `portoes.escrever` | Escritor antigo de outra tabela de achado: a fotografia acusa no ciclo seguinte e guarda o conteúdo anterior só das linhas de nível 2 |
| 3 | No registro de fatos e por `portoes.escrever` | Escritor antigo da fila: a auditoria acusa no ciclo seguinte. O gatilho que tornaria impossível está pronto e testado, **não instalado** |
| 4 | Um fato "pago" sair VERIFICADO sem envio confirmado | As somas antigas que usam `_ob_paga` (§6.4) |
| 5 | — | Sempre detectivo: fila que não diminui em 24 h vira item |
| 6 | Em fato registrado e em `estado_do_laudo` | — |

---

## 6. Medições nos dados reais

### 6.1 Divergências

> **Achado 1 — o cérebro serviu o número antigo depois de a nota ser corrigida.** A nota da AGILE foi corrigida
> às 18:40. Às 19:05 e às 19:12 a busca do cérebro por "2.270.009,39" ainda devolvia o trecho "35 de 35
> processos… R$ 2.270.009,39 de ISS" e não devolvia nenhum trecho com o valor novo. Às 19:20 já estava
> atualizado. Defasagem medida: pelo menos 32 minutos. A divergência só foi registrada no ensaio (banco
> temporário); no banco real o primeiro ciclo já encontrou o índice em dia.

> **Achado 2 — resto do número antigo na própria nota corrigida.** `~/vault/casos/agile-corp-seeduc-emergencia-do-incumbente.md`,
> linha 936: "Em 35 processos (2023–2025), a OB = bruto − INSS − IRRF, exatamente", no mesmo parágrafo que já
> diz 38. Pode ser deliberado (35 fecham no total; os outros 3 fecham NF a NF) ou resto da versão anterior. **Não
> foi alterado:** quem escreveu decide entre corrigir e marcar `<!--fato-historico-->`. Está aberto no painel e no
> sensor.

| Superfície | Lido | Resultado |
|---|---:|---|
| Vault, `docs/`, memória dos agentes | 1.343 arquivos | 1 menção a valor superado (achado 2); 2 citações por id, as duas conferem |
| Registro local do cérebro (`propagacao.db`) | 347 memórias | Nenhuma menção a valor superado |
| Índice do cérebro (busca pelo valor superado) | 1 consulta | Em dia às 19:20 (achado 1) |
| Agregado × linhas de detalhe (`iss_nao_retido.json`) | 5 fornecedores × UG | Bate: 38, 22, 1, 1, 1 processos; soma de 63 = total publicado |
| Fora das superfícies | — | O docstring de `compliance_agent/detector_iss_retido.py` ainda cita "35 processos, R$ 2.270.009,39" como caso-índice. Código não é superfície varrida; o arquivo é de outra sessão |

Nas duas citações incluídas na nota da AGILE (linhas 935 e 938) o número passou a carregar o id do fato.

### 6.2 Fatos registrados

| Família | Fatos | Estado | Nível | Origem |
|---|---:|---|---:|---|
| `iss_nao_retido:<cnpj>:<ug>` (valor, processos) | 10 | VERIFICADO | 2 | `data/iss_nao_retido.json › por_fornecedor` |
| `iss_nao_retido:total` | 2 | VERIFICADO | 2 | idem, `totais` |
| `siafe_ob:contabilizada:<status de envio>` (valor, n) | 14 | conforme o status (§6.4) | 2 | SQL sobre `ob_orcamentaria_siafe` |
| `pericia_contabil:estado` | 4 | PENDENTE | 1 | `data/pericia_contabil_resumo.json` |
| `cge_confronto:todas` | 3 | PENDENTE | 1 | `data/cge_confronto.json` |

Os agregados da perícia contábil e do CGE × JFN ficaram em nível 1 e PENDENTE de propósito: dependem da regra de
vínculo OB↔contrato e não são conferidos registro a registro.

### 6.3 Contratos de dados

| Contrato | Linhas | Violações |
|---|---:|---|
| `sei_fila_captura` (`total_pago` de 0 a R$ 2e10; `motivo`, `visto_em`) | 14.188 | 0. Maior valor: R$ 385.799.673,52 |
| `lex_execucao` (`nota_risco` de 0 a 10; `modelo`, `em`; nível de prova) | 8.468 | 0. Níveis: 93 fonte primária · 816 Opus sobre o resumo · 5.507 volume · 2.052 regra |
| `alertas_triagem` (`nota`, `valor`; `motor`, `em`; nível de prova) | 6.320 | 0. 215 VERIFICADO |
| `ob_orcamentaria_siafe` (`valor` até R$ 5e9; domínio de `status_envio`) | 1.363.027 | **45** linhas com `status_envio` = número de PD ("2020PD03069"…): colunas deslocadas. Maior OB: R$ 1.500.000.000,00 |

Regressões de nível de prova desde a primeira fotografia: 0 (a fotografia começou hoje; os 51 laudos regravados
antes dela continuam listados pelo sensor `autoaprimoramento:fonte_perdida`).

### 6.4 O status ao lado do valor

Consulta: `status='Contabilizado'`, sem "Erro no Pagamento", com número de OB — o filtro de
`cruzamentos_intel._ob_paga` —, agrupada por status de envio. Todos os exercícios coletados.

| Status de envio | OB | Valor | Estado do fato |
|---|---:|---:|---|
| Processado e Pago | 1.053.548 | R$ 314.960.832.448,85 | VERIFICADO |
| Enviado Manualmente | 226.504 | R$ 95.238.349.712,56 | VERIFICADO (meio de envio estável — `siafe_status_ob`) |
| Parcialmente Pago | 6.166 | R$ 9.595.591.629,04 | A CONFERIR (o valor da OB não é o valor pago) |
| Enviado ao Banco | 33.920 | R$ 5.326.062.590,71 | PENDENTE |
| Aguardando Envio | 636 | R$ 287.869.503,94 | PENDENTE |
| Aguardando Geração RE | 203 | R$ 133.480.933,80 | PENDENTE |
| Fora do domínio | 44 | R$ 0,00 | PENDENTE |

> **Alerta.** `_ob_paga` ainda aceita os três status intermediários: **34.759 OB, R$ 5.747.413.028,45** entram
> como pagas nas somas que usam esse filtro. O número difere do citado no pedido (27.162 OB / R$ 4,51 bi), que
> deve ter outro recorte. A regra não foi alterada: tem dezenas de chamadores e mudar o que é "pago" é decisão do
> dono (§9). O que mudou é que o valor agora existe separado, com o seu estado.

### 6.5 Grafo

| Achado | Quais |
|---|---|
| Erro de mapa, ciclo | Nenhum |
| Fonte que ninguém consome | `sei_leitura_dupla` (sonda ativa, nenhum derivado depende) · `decisao_dono` (manual, sem dependente) |
| Sonda que nunca viu mudança desde 14/11 | `sancoes` · `emendas_base` · `regra_emendas` · `regra_pcrj` — ou a fonte está parada, ou a sonda não a enxerga |
| Derivado sem efeito verificável (roda e ninguém confere se gravou) | `pericia_emendas` · `pericia_pcrj` · `sei_ocr_gpu` · `territorio` · `vault_casos` · `vinculo_ob_contrato` |
| Derivado que nunca rodou | `pericia_emendas` (criado em 18/11; intervalo de 12 h) |
| Arquivo servido pelo painel sem nó no grafo | 15. O mais velho: **`data/flags_graves.json` (rota `/api/flags`), 3.050 h — 127 dias**. Também `tac_ranking_ugs.json` (33 h), `pulos_do_gato.json` (36 h), 8 caches de `cruzamentos_intel` (12 h), `achados.db` |
| Destino de achado sem nó no grafo | 19 destinos (`alertas`: 17 regras · `processo_avaliacao`: 13 detectores · `achado_certame`: 8 · `achado_detector`: 7 · …). Casamento por nome de módulo: **a conferir** caso a caso |
| Fila da re-perícia | 660 laudos de risco alto ou sem execução comprovada dados antes da última captura do processo. Vira item se não diminuir em 24 h |
| Externos | 4 declarados (`lex_execucao`, `sei_fichas`, `triagem_alertas`, `conferencia_opus`), todos agendados |

### 6.6 Certeza dos laudos

| Nível | Quem | Laudos | Risco alto | Esperados confirmar na fonte |
|---:|---|---:|---:|---:|
| — | Regra determinística | 2.052 | 0 | — |
| 0 | Modelo de volume | 5.507 | 665 | 12,6 |
| 1 | Opus sobre o resumo | 816 | 0 | — |
| 2 | Fonte primária | 93 | 19 | 19 |

De 684 riscos altos vigentes, 19 têm prova primária. Os outros 665 saem PENDENTE com a taxa medida do motor.

---

## 7. Riscos e limites

| Risco | Como aparece | Mitigação | Resíduo |
|---|---|---|---|
| Cobertura | Só é fato o que foi declarado em `fatos:` — 33 hoje | O painel declara a cobertura na proveniência | A maior parte dos números do painel ainda não tem id |
| Falso positivo de menção | "Passou de 35 processos para 38 processos" casa como antigo | Monetário ao centavo; contagem exige apelido, termo e "<n> <medida>"; marcador de histórico | Quem escreve narrativa de mudança precisa do marcador |
| Falso negativo de menção | Valor antigo escrito de outro jeito ("2,27 mi") | — | Não coberto; a citação por id é o caminho seguro |
| Controle detectivo tem janela | Entre a escrita ruim e o ciclo (até 1 h mais a espera do despachante) | Gatilho de faixa pronto para instalar | Regressão de nível 0 → menor ou de linha de nível 1 perde o conteúdo anterior |
| Nível de prova por texto | `lex_execucao.modelo` é proveniência escrita à mão | Mesmo classificador do autoaprimoramento | Grafia nova cai em nível menor (lado seguro) |
| Sincronização escreve no vault | Reescreve o número antes da âncora | Desligada por padrão; só o número; idempotente; KILL | Conflito com edição simultânea no Obsidian |
| Heurística do grafo | "Fora do grafo" casa por nome de módulo | Lista, não contagem | Falsos positivos (ex.: a perícia contábil grava pelo `…_rotina`) |
| Loop | A certeza é folha: nada depende dela | Teste sobre o mapa real | — |
| Custo | 14 s por ciclo, quatro consultas sobre a tabela de OB | Intervalo mínimo de 1 h, peso leve | — |

---

## 8. Operação

```bash
python -m compliance_agent.certeza ciclo                # o que o despachante roda
python -m compliance_agent.certeza estado               # resumo do último ciclo
python -m compliance_agent.certeza fato <id>            # versões de um fato e como citar
python -m compliance_agent.certeza citar <trecho>       # citações prontas para colar
python -m compliance_agent.certeza grafo                # auditoria do grafo agora
python -m compliance_agent.certeza gatilhos             # DDL dos gatilhos de faixa (só imprime)
```

Declarar um fato novo: acrescentar um bloco `fatos:` ao nó em `config/propagacao.yaml` (o cabeçalho do arquivo
descreve os campos). Nada mais: o próximo ciclo extrai, julga e registra.

| Chave (desligada por padrão) | O que liga | Por que é decisão do dono |
|---|---|---|
| `JFN_CERTEZA_SINCRONIZAR=1` | Reescreve no vault o número de citação divergente | Escreve em nota humana |
| `JFN_CERTEZA_CEREBRO=1` | Registra fato novo ou alterado no cérebro (até 20 por ciclo) | Escreve na memória comum de todos os agentes |
| `JFN_CERTEZA_GATILHOS=1` + `gatilhos --aplicar` | Instala os gatilhos de faixa no `compliance.db` | Escritor fora do contrato passa a falhar na hora |
| `data/certeza/KILL` | Desliga as três | — |

A rota `/api/sistema/certeza` entra no ar no próximo reinício do `jfn.service` (o serviço não foi reiniciado).
Até lá, `data/certeza/estado.json` e `relatorio.md`.

---

## 9. O que ficou para depois

| Item | Por que não agora |
|---|---|
| Mudar `_ob_paga` para excluir os status intermediários | Muda o "total pago" de toda a casa; dezenas de chamadores; decisão do dono com o número do §6.4 em mãos |
| Instalar os gatilhos de faixa | Mudam o comportamento de escritores vivos; pedir o ok com a lista de tabelas |
| Ligar a sincronização do vault e a publicação no cérebro | Escrevem fora de `data/certeza/`; melhor depois de alguns dias de ciclos só-leitura |
| Declarar fatos das demais manchetes (Governo Couto, sobrepreço, território, orçamento, TAC) | Cada uma exige definir estado e nível de prova com quem conhece a régua; o mecanismo está pronto |
| Usar `portoes.escrever` nos escritores de `alertas_triagem` e das tabelas `achado_*` | 86 ocorrências de escrita só em `alertas_triagem`; troca gradual, com teste por escritor |
| Nós no grafo para os 15 arquivos do painel e para os destinos de achado sem propagação | Cada um precisa do comando idempotente e do efeito; `flags_graves.json` (127 dias) é o primeiro |
| Painel visual | `static/` pertence a outra sessão; a rota e o relatório cobrem |
| Varredura de docstrings de código | Acusaria o docstring do detector de ISS, que é de outra sessão |
| Investigar a defasagem do índice do cérebro (≥ 32 min) | O indexador mora na VM-2, fora deste escopo |
| Conferir a linha 936 da nota da AGILE | Decisão de quem escreveu a nota |

---

## 10. Fontes

**Dados:** `data/compliance.db` (só leitura: `ob_orcamentaria_siafe`, `lex_execucao`, `alertas_triagem`,
`sei_fila_captura`), `data/iss_nao_retido.json`, `data/pericia_contabil_resumo.json`, `data/cge_confronto.json`,
`data/propagacao.db`, `~/vault`, memória dos agentes, busca do cérebro (`jfn-brain`).
**Casa:** `docs/AUTOAPRIMORAMENTO-JFN.md`, `docs/REGRAS-DE-QUALIDADE.md`, `config/propagacao.yaml`,
`config/qualidade_inventario.yaml`, `config/qualidade_detectores.yaml`, `compliance_agent/siafe_status_ob.py`.
**Literatura e documentação:** as referências do §3.2, com a URL em cada linha; consultadas em 18/11/2026.
