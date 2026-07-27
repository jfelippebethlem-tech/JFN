# Bases de Dados Jurídicas Nacionais — Direito Administrativo
## Prospecção, verificação de campo e novas funções para o JFN

| | |
|---|---|
| **Emissão** | 27 de julho de 2026 |
| **Escopo** | Bases nacionais de direito administrativo / controle externo com acesso programático |
| **Método** | Prospecção documental + **probe HTTP real a partir da VM `jfn-core`** (não se afirma disponibilidade sem medir) |
| **Documento correlato** | `docs/CONTROLES-FONTES-DADOS.md` (catálogo de 40 fontes, ondas 0–4) — este documento **acrescenta** e **corrige** |
| **Classificação** | Interno — subsídio a controle externo |

---

## 1. Sumário executivo

Foram prospectadas **11 bases jurídicas nacionais** ausentes do catálogo vigente e todas foram
submetidas a probe HTTP a partir da VM de produção. **Cinco entraram em operação hoje**, três estão
disponíveis mas dependem de trabalho adicional, e três estão **bloqueadas por WAF** ou não oferecem
o que a documentação de terceiros promete — registrado aqui para não se gastar esforço de novo.

A prospecção produziu três achados sobre o **próprio sistema**:

> **Achado 1 — Coletor morto em silêncio.** O `collectors/querido_diario.py` apontava para
> `queridodiario.ok.org.br/api/*`, que é a SPA do site e devolve **HTTP 200 com HTML**. O
> `r.json()` estourava, o `except Exception: pass` engolia, e a função retornava `[]` **sempre**.
> Além do host, os três parâmetros de filtro estavam com nome errado — a API os **ignora sem
> erro**, de modo que, se o host estivesse certo, a busca varreria o Brasil inteiro em vez do RJ.
> O agravante: `providers/gazettes_providers.py` **já usava o host e os parâmetros corretos** —
> havia um gêmeo certo e um gêmeo morto para a mesma fonte. **Corrigido e coberto por teste.**

> **Achado 2 — Citações de jurisprudência fabricadas na base curada.** Construído o índice do
> acervo **oficial** do TCU (17.510 enunciados, 292 súmulas), o novo verificador foi rodado contra
> `knowledge/jurisprudencia.py` — que alimenta os prompts do Lex, do Hermes e do Groq. Resultado:
> **4 acórdãos declarados como TCU-Plenário são numericamente impossíveis** e 1 está atribuído ao
> colegiado errado. Detalhamento na seção 4.

> **Achado 3 — O DataJud não faz o que dizem que faz.** A literatura de terceiros vende a API do
> CNJ como caminho para "achar processos de um CNPJ". Medido no acervo real: **não há nome de
> parte, nem CPF/CNPJ, nem teor de decisão** (Portaria CNJ 160/2020). O que a base entrega de
> fato está na seção 3.2 — e é útil, mas é outra coisa.

---

## 2. Estado das fontes prospectadas

Probe executado em 27/07/2026 a partir da VM `jfn-core` (Oracle Cloud ARM), sem proxy.

| # | Base | Órgão | Endpoint verificado | Auth | Probe | Veredito |
|---|---|---|---|---|---|---|
| 41 | **DataJud — Base Nacional de Processos** | CNJ | `api-publica.datajud.cnj.jus.br/api_publica_{trib}/_search` | chave pública do CNJ | **HTTP 200** · 25–35 s/consulta | ✅ **Em operação** |
| 42 | **Jurisprudência Selecionada (bulk)** | TCU | `sites.tcu.gov.br/.../jurisprudencia-selecionada.csv` | nenhuma | **HTTP 200** · 116,6 MB | ✅ **Indexada** — 17.510 enunciados, 2003–2026 |
| 43 | **Súmulas (bulk)** | TCU | `sites.tcu.gov.br/.../sumula/sumula.csv` | nenhuma | **HTTP 200** · 819 KB | ✅ **Indexada** — 292 súmulas |
| 44 | **Querido Diário (back-end real)** | OKBR | `api.queridodiario.ok.org.br/gazettes` | nenhuma | **HTTP 200** · 0,3 s | ✅ **Corrigido** (ver Achado 1) |
| 45 | **Resposta a Consultas** | TCU | `sites.tcu.gov.br/.../resposta-consulta.csv` | nenhuma | **HTTP 200** · 7,2 MB | 🟡 Disponível — indexar junto ao #42 |
| 46 | **Acórdão Completo 2026 (texto integral)** | TCU | `sites.tcu.gov.br/.../acordao-completo-2026.csv` | nenhuma | **HTTP 200** · 244,9 MB | 🟡 Disponível — **pesado**, só em janela off-hours |
| 47 | **Boletim de Jurisprudência** | TCU | `sites.tcu.gov.br/.../boletim-jurisprudencia.csv` | nenhuma | **HTTP 200** · 4,2 MB | 🟡 Disponível — síntese temática barata |
| 48 | **Dados Abertos STJ (CKAN)** | STJ | `dadosabertos.web.stj.jus.br/api/3/action/package_list` | nenhuma | **HTTP 200** · 13,8 s | 🟡 13 datasets, inclui espelhos de acórdãos; **sem busca textual** |
| 49 | **API Câmara dos Deputados** | Câmara | `dadosabertos.camara.leg.br/api/v2/proposicoes` | nenhuma | **HTTP 200** · rápido | 🟡 Rastreio legislativo de emendas/PLs |
| 50 | **API Legislação Senado** | Senado | `legis.senado.leg.br/dadosabertos/materia/pesquisa/lista` | nenhuma | **HTTP 200** · XML | 🟡 Idem, em XML |
| 51 | **LexML (SRU / SolrService)** | Senado | `www.lexml.gov.br/busca/{SRU,SolrService}` | nenhuma | **HTTP 200 com página "Verificação de segurança"** | 🔴 **WAF bloqueia a VM** — o `collectors/lexml_fetcher.py` está nessa condição |
| 52 | **STF / STJ — busca de acórdãos por texto** | STF/STJ | — | — | inexistente | 🔴 **Não existe API pública de busca textual**; só bulk sem índice |
| 53 | **Pesquisa Textual TCU (SPA)** | TCU | `pesquisa.apps.tcu.gov.br/doc/...` | nenhuma | 200, **mesmos 22.104 B para acórdão real e inventado** | 🔴 Imprestável para verificação — usar o bulk (#42) |
| 54 | **CNCIAI — Condenações por improbidade** | CNJ | `cnj.jus.br/improbidade_adm/consultar_requerido.php` | formulário HTML | 200 (HTML) | 🟠 API existe por convênio (Portaria CNJ 94); **pedir credencial pelo gabinete** |
| 55 | **TCM-RJ** | TCM-RJ | `tcmrj.tc.br` | — | **connection reset** | 🔴 Recusa conexão da VM |

**Nota de honestidade sobre o #51.** O `lexml_fetcher.py` continua no repositório apontando para
`www.lexml.gov.br/busca/SolrService`. Da VM, essa rota devolve HTTP 200 com a página de verificação
do Senado — ou seja, **o coletor de legislação está na mesma condição do Querido Diário antes da
correção**. Não foi mexido nele nesta entrega porque a correção não é de código (é de rota de rede:
exige proxy residencial ou o mirror do acervo). Fica registrado como pendência, não como conserto.

---

## 3. Novas funções entregues

### 3.1 Verificador anti-alucinação de jurisprudência
`compliance_agent/knowledge/tcu_juris_index.py`

O sistema cita acórdãos em pareceres que vão ao TCE-RJ e ao MP-RJ. Até hoje, a fundamentação vinha
de uma base escrita à mão e do que a LLM lembrasse. Agora existe um **acervo oficial local** e uma
**guarda de saída**:

| Função | Papel |
|---|---|
| `verificar_citacao(texto)` | Extrai toda citação de acórdão/súmula do TCU num parecer e a confronta com o acervo real |
| `citacoes_suspeitas(texto)` | Só o que não fechou — o que **não pode ir ao papel** sem conferência |
| `buscar_enunciados(termo, area)` | Enunciado **real**, por busca FTS5, com número/ano/colegiado |
| `fundamentar(achado, area)` | Bloco de fundamentação pronto, montado só com acórdão existente |
| `implausivel(num, colegiado, ano)` | Teste de faixa — **não depende de o índice estar completo** |

Os quatro estados possíveis foram desenhados sob a regra de honestidade do projeto
(*INDISPONÍVEL ≠ 0*):

| Estado | Significado | Consequência |
|---|---|---|
| `confirmado` | Existe no acervo, colegiado bate | Pode citar |
| `colegiado_diverge` | O acórdão existe, mas em outro colegiado | Corrigir a referência |
| **`numero_impossivel`** | O número **extrapola a série anual** daquele colegiado | **Não existe. Barra o parecer.** |
| `nao_confirmado` | Ausente do recorte curado — **não é prova de inexistência** | Conferir à mão antes de citar |
| `fora_do_escopo` | Citação de TCE-RJ/TCM — este índice é do TCU | Não julgado aqui |

O estado `numero_impossivel` é a peça inventiva. O TCU numera os acórdãos em **série anual por
colegiado**; medido no acervo, o Plenário fecha o ano entre 2.630 e 4.551 (2019–2025; 2026 ainda
corre), enquanto as
Câmaras chegam a dezenas de milhares. Um "Acórdão 9.244/2024-Plenário" é, portanto, **aritmeticamente
impossível** — e essa conclusão vale mesmo com um índice incompleto, que é justamente onde o
`nao_confirmado` é fraco.

O estado `fora_do_escopo` nasceu de um falso positivo real durante o desenvolvimento: o TCE-RJ
numera na casa das dezenas de milhares e chama o colegiado de *Pleno*/*PLENV*, enquanto o TCU
escreve *Plenário*. Sem esse recorte, **toda** citação do TCE-RJ seria acusada de fabricação.

### 3.2 Cliente DataJud/CNJ
`compliance_agent/collectors/datajud.py`

Metadados processuais dos 182 tribunais. O que a base **tem**: número, classe, assuntos, órgão
julgador, município IBGE, data de ajuizamento e a **cadeia completa de movimentos** da Tabela
Processual Unificada. O que **não tem**: partes, CPF/CNPJ, teor de decisão.

| Função | Papel |
|---|---|
| `resumo_processo(numero)` | Classe, vara, idade, último movimento e **desfecho** (procedência, liminar, acordo…) |
| `extrair_numeros_cnj(texto)` | Todo número CNJ citado num processo SEI, edital ou parecer |
| `judicializacao_de_documento(texto)` | Encadeia os dois: o documento entra, a situação judicial de cada processo citado sai |
| `contar_por_classe(trib, classe)` | Volume por classe/comarca — contexto, não achado |
| `tribunal_do_numero(numero)` | Deduz o tribunal do próprio número; **devolve `None` em vez de chutar** fora da Justiça Estadual |

**Por que isso muda um parecer.** Achado sobre objeto **já sub judice** não é representação nova —
é subsídio ao juízo ou ao MP que já atua. `judicializacao_de_documento` é o gancho: o Lex lê o
processo SEI, encontra os números CNJ citados e descobre sozinho se a matéria já está em ação de
improbidade, ACP ou mandado de segurança, e em que pé.

*Medições de campo:* a API é **lenta por natureza** (25–35 s por consulta ao índice do TJRJ, medido)
— daí o timeout folgado de 90 s e o uso de `term` em vez de `match`. Consulta de amostra: o TJRJ
registra **702 ações civis de improbidade administrativa ajuizadas desde 2020**.

### 3.3 Correção do Querido Diário
`compliance_agent/collectors/querido_diario.py`

Host corrigido, três parâmetros corrigidos e — o mais importante — **a falha deixou de ser
silenciosa**: resposta 200 com content-type não-JSON agora gera `WARNING` em vez de virar lista
vazia. Voltou a funcionar contra a base real (4.557 publicações do município do RJ mencionando
"inexigibilidade"; 283 desde 2025).

---

## 4. Achado 2 detalhado — citações fabricadas na base curada

Universo: 66 citações extraídas de `compliance_agent/knowledge/jurisprudencia.py`.

| Estado | Qtd. | Leitura |
|---|---:|---|
| `confirmado` | 40 | Conferem com o acervo oficial |
| `fora_do_escopo` | 12 | TCE-RJ — fora do alcance deste índice |
| `nao_confirmado` | 9 | Plausíveis, ausentes do recorte — **conferir antes de citar** |
| **`numero_impossivel`** | **4** | **Não existem** |
| `colegiado_diverge` | 1 | Existe, colegiado errado |

**As quatro que não podem existir** — todas declaradas no código como `orgao="TCU"`, Plenário:

| Citação no código | Teto medido do Plenário no ano | Tema atribuído |
|---|---:|---|
| Acórdão 4.021/2022-Plenário | 3.637 | Dispensa reiterada / simulação de emergência |
| Acórdão 6.100/2022-Plenário | 3.637 | Empresa de fachada — indícios de "laranja" |
| Acórdão 5.782/2023-Plenário | 3.556 | Contrato sem publicação no PNCP — nulidade |
| Acórdão 7.002/2023-Plenário | 3.556 | Despesas sem licitação acima do limite |

E ainda: **Acórdão 1.273/2020** é citado como Plenário, mas no acervo oficial é de **Primeira Câmara**.

**Gravidade.** Esses registros não são exemplo de docstring: são dados de produção, consumidos por
`llm/hermes_agent.py`, `llm/groq_agent.py`, `llm/orquestrador.py`, `scheduler.py`,
`editais/peer_diff.py` e `reporting/relatorio_direcionamento.py` — isto é, entram no prompt e podem
sair impressos num parecer endereçado a tribunal. **A tese jurídica de cada um pode estar correta;
o número que a sustenta, não.** Uma citação inexistente num documento de controle externo
desqualifica a peça inteira.

**Recomendação.** Não apagar as ementas: substituir o número por acórdão real de mesmo tema, o que
`buscar_enunciados()` já entrega. As 9 `nao_confirmado` pedem conferência manual, sem presunção de
erro. *Esta correção não foi executada nesta entrega* — mexer no conteúdo jurídico da base curada é
decisão do titular, não do desenvolvedor.

---

## 5. Próximos passos sugeridos

| Prioridade | Ação | Custo |
|---|---|---|
| **1** | Ligar `citacoes_suspeitas()` como **gate de saída** do Lex, ao lado de `reporting/neutralidade.garantir_neutro` — parecer com citação impossível não é emitido | Baixo |
| **2** | Corrigir as 5 citações da seção 4 e conferir as 9 pendentes | Baixo, manual |
| **3** | Indexar `resposta-consulta.csv` (#45) e `boletim-jurisprudencia.csv` (#47) no mesmo índice | Baixo |
| 4 | Cruzar `extrair_numeros_cnj` sobre o acervo SEI já capturado → mapa do que já está judicializado | Médio |
| 5 | Pedir credencial da API do CNCIAI (#54) pelo gabinete — condenação por improbidade transitada em julgado é achado de peso máximo | Institucional |
| 6 | Decidir o destino do `lexml_fetcher.py` (#51): proxy, mirror ou aposentadoria declarada | Médio |
| 7 | `acordao-completo-2026.csv` (#46, 245 MB) só em janela off-hours — a VM tem 2 vCPU | Alto |

---

## 6. Verificação

| Item | Evidência |
|---|---|
| Testes novos | `tests/test_tcu_juris_index.py`, `tests/test_datajud.py`, `tests/test_querido_diario.py` — **36 passaram, 0 falharam** |
| Índice TCU | `data/tcu_juris.db` · 15,5 MB · 17.510 acórdãos (2003–2026) · 292 súmulas |
| DataJud | Consulta real ao TJRJ retornando processo com 337 movimentos |
| Querido Diário | Consulta real retornando publicações do município do RJ |
| **Não verificado** | A suíte completa de testes do projeto **não** foi executada (regra de não derrubar a VM — pytest completo já a derrubou antes). Rodaram apenas os três arquivos novos. |

### Fontes consultadas
TCU Dados Abertos · CNJ DataJud Wiki · CNJ CNCIAI · STJ Dados Abertos (CKAN) · Open Knowledge
Brasil / Querido Diário · LexML Brasil · Câmara dos Deputados Dados Abertos · Senado Federal
Dados Abertos · Portal da Transparência CGU.
