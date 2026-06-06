# Controles Externos e Fontes de Dados Abertas — Catálogo para Ingestão pelo JFN

> Arquiteto de Dados do ecossistema do Deputado Estadual RJ Jorge Felippe.
> Agente **JFN** audita 1,1 milhão de Ordens Bancárias (OBs) do RJ (2019–2026, SQLite);
> agente **Lex** emite parecer jurídico de controle externo (TCU / TCE-RJ).
> Documento consolidado em 2026-06-06. Probes HTTP realizados de VM **GCP** (IP de datacenter).

---

## 1. Sumário executivo

O JFN já possui o lado do **pagamento** (1,1M OBs: favorecido, valor, UG/órgão, data). O que falta para fechar o ciclo de auditoria de controle externo é o lado do **dever-ser** (norma, contrato, edital, preço de referência, jurisprudência) e o lado da **sanção** (quem já está impedido ou condenado). Este documento mapeia as duas peças:

1. **Metodologia** do TCU e do TCE-RJ — como esses tribunais apontam e tipificam achados. O Lex deve imitar o formato **Critério → Condição/Situação → Evidência → Causa → Efeito → Encaminhamento**, sustentado em jurisprudência **real** (citada por número de acórdão/súmula), nunca alucinada.

2. **Catálogo de fontes abertas ingeríveis por HTTP** (seção 3) — priorizando o que é alcançável sem login de uma VM GCP. Os grandes ganhadores são:
   - **TCE-RJ Dados Abertos** (`dados.tcerj.tc.br`): 41 endpoints REST sem auth, com `contratos_estado` e `compras_diretas_estado` trazendo **nº de Processo SEI + CPF/CNPJ + Unidade + Valor** — chave de JOIN direta com as OBs; e `penalidades_ressarcimento_estado` (atualização diária) para flag de fornecedor/órgão já condenado.
   - **PNCP** (`pncp.gov.br/api/consulta`): registro nacional de editais/contratos/atas da Lei 14.133, **sem auth**, vincula cada OB ao contrato/edital de origem.
   - **Portal da Transparência (CGU)**: cadastros de sanção **CEIS/CNEP/CEPIM** — cruzamento "OB paga a fornecedor sancionado" é achado de alto peso. Bulk CSV sem token; API com token gratuito.
   - **TCU Dados Abertos** (`dados-abertos.apps.tcu.gov.br` + `sites.tcu.gov.br`): API de acórdãos, CSVs de jurisprudência completa (RAG do Lex), e APIs de **inidôneos / contas irregulares / certidões por CNPJ**.

**Risco operacional registrado:** vários portais gov bloqueiam IP de datacenter por WAF. Confirmado **HTTP 403 em `sei.rj.gov.br`** da VM GCP — o nº SEI deve ser usado como **chave** (já vem nos datasets do TCE-RJ), nunca por scraping direto do SEI a partir da VM. Detalhes por fonte na seção 5.

---

## 2. Metodologia do controle externo — o que o Lex deve imitar

### 2.1 TCU (controle externo federal)

**Estrutura do achado (Matriz de Achados → Relatório de Auditoria).** Todo achado tem 4 elementos:

| Elemento | O que é |
|---|---|
| **CRITÉRIO** | Norma / lei / contrato / cláusula violada (o dever-ser) |
| **CONDIÇÃO** | A situação efetivamente encontrada |
| **CAUSA** | Por que ocorreu |
| **EFEITO** | Consequência / dano ao erário |

**Tipificação de irregularidade:**

- **Sobrepreço / superfaturamento em obras:** comparação com preços de referência **SINAPI / SICRO**; **BDI** fora das faixas do **Acórdão 2622/2013-Plenário** (faixas de BDI por tipo de obra; valor acima do limite superior / 1º quartil = indício de sobrepreço).
- **Pesquisa de preços em compras/serviços:** **Acórdão 1875/2021-Plenário** exige "cesta de preços" priorizando contratações públicas anteriores; ≥3 preços; **se coeficiente de variação > 25%, usar MEDIANA** (não a média); cotação só com fornecedores é exceção/último recurso.

**Hierarquia jurisprudencial (ordem de força que o Lex deve respeitar ao citar):**
`Súmulas` (vinculantes internamente) > `Acórdãos paradigma` (ex.: 2622/2013 BDI; 1875/2021 cesta de preços) > `Jurisprudência Selecionada` (enunciados temáticos).

**Deliberações tipificadas (o que o achado vira):** determinação, recomendação, ciência, audiência (defesa), citação (débito/imputação), declaração de irregularidade das contas com inabilitação / declaração de inidoneidade.

**Referência de pipeline de IA (modelo de auditoria contínua e preventiva replicável no JFN):** ALICE (varre editais/Comprasnet por indícios de restrição à competição), MONICA (monitoramento de aquisições), SOFIA (sugere achados e fundamentação), ADELE (inconsistências em pregões), ÁGATA (análise textual) — todos sobre o LabContas.

### 2.2 TCE-RJ (controle externo estadual)

**Estrutura do achado (padrão MAG/TCE-RJ, alinhado a ISSAI/TCU) — 5 elementos:**
`Situação encontrada → Critério (norma violada) → Evidência → Causa → Efeito`, deságuando em **proposta de encaminhamento**.

**Tipificação de sobrepreço (regra-chave para o Lex):** sobrepreço **NÃO** se prova por mera divergência entre valor orçado e adjudicado/pago — exige **comparação com preços de mercado vigentes à época da licitação** (jurisprudência consolidada TCE-RJ). Sobrepreço **quantitativo** apura-se por confronto de quantitativos estimados (índices de produtividade) vs. efetivamente utilizados (ex.: retenção de R$ 3,02M em contrato do INEA por superestimativa de mão de obra, 2025).

**Encaminhamentos típicos:** conversão em Tomada de Contas Especial (TCE), citação/audiência dos responsáveis, ressarcimento ao erário, multa, determinação/recomendação, **retenção cautelar** de parcelas.

**Fiscalização digital:** baseada nos dados que jurisdicionados são obrigados a declarar via **SIGFIS** (Deliberação 281/17), insumo do planejamento de fiscalizações. Os dados públicos resultantes saem pela **API de Dados Abertos**, não pelo SIGFIS transacional.

### 2.3 Template que o Lex deve emitir

Para que o parecer seja diretamente aproveitável em representação ao TCE-RJ/TCU, o Lex estrutura cada achado como:

```
SITUAÇÃO: <o que a OB/contrato revela>
CRITÉRIO: <norma + jurisprudência citada por nº real>
EVIDÊNCIA: <OBs, valores, CPF/CNPJ, nº SEI/contrato>
CAUSA: <hipótese de causa>
EFEITO: <dano estimado, atualizado pela Calculadora de Débito do TCU>
ENCAMINHAMENTO: <determinação / TCE / ressarcimento / multa>
```

---

## 3. Catálogo de fontes (ordenado por prioridade de ingestão)

`ingerivel_http`: **sim** = HTTP direto sem auth · **sim-com-token** = exige chave/token ou back-end HTML · **dificil-WAF** = bloqueio de IP datacenter / instável · **nao** = login transacional.

| # | Nome / dataset | Órgão | URL / endpoint | Auth | ingerivel_http | O que agrega ao JFN |
|---|---|---|---|---|---|---|
| 1 | **OpenAPI Dados Abertos (41 endpoints)** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/openapi.json` | nenhuma | **sim** | Índice de todas as rotas; FastAPI paginado `inicio/limite`, `jsonfull=true`/`csv` |
| 2 | **contratos_estado (SIGFIS)** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/contratos_estado?inicio=0&limite=1000&jsonfull=true` | nenhuma | **sim** | Processo SEI + CPFCNPJ + Fornecedor + Unidade + ValorTotal/Empenhado/Pago + CriterioJulgamento → **JOIN direto com as OBs** |
| 3 | **compras_diretas_estado** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/compras_diretas_estado?inicio=0&limite=1000&jsonfull=true` | nenhuma | **sim** | Dispensa/inexigibilidade/adesão: Processo SEI, ValorProcesso, Objeto, Afastamento, Enquadramento → detecção de **fracionamento de despesa** |
| 4 | **penalidades_ressarcimento_estado** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/penalidades_ressarcimento_estado?jsonfull=true` | nenhuma | **sim** | MULTA/RESSARCIMENTO por Processo, Órgão, GrupoNatureza, DataSessao — **DataUltimaAtualizacao diária**; flag de fornecedor/órgão já condenado |
| 5 | **PNCP — Contratos** | PNCP/Gov Federal | `https://pncp.gov.br/api/consulta/v1/contratos` (params `dataInicial dataFinal pagina`, datas AAAAMMDD) | nenhuma | **sim** | Registro nacional (Lei 14.133): vincula cada OB ao contrato de origem; aditivos, modalidade |
| 6 | **PNCP — Contratações/Publicação** | PNCP | `https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao` (`codigoModalidadeContratacao`) | nenhuma | **sim** | Editais por modalidade → dispensa/fracionamento por CNPJ do órgão (ex.: ITERJ) |
| 7 | **PNCP — Atas** | PNCP | `https://pncp.gov.br/api/consulta/v1/atas` | nenhuma | **sim** | Atas de registro de preço → referência de preço por item |
| 8 | **Portal Transparência — bulk CSV sanções** | CGU | `https://portaldatransparencia.gov.br/download-de-dados/ceis` (e `/cnep`, `/cepim`) | nenhuma | **sim** | CSV/ZIP completos sem limite de 20k → tabela local `sancionados` no SQLite |
| 9 | **Portal Transparência — API de Dados** | CGU | `https://api.portaldatransparencia.gov.br/api-de-dados` (`/ceis /cnep /cepim /ceaf /peps /contratos /contratos/cpf-cnpj /licitacoes /despesas/documentos-por-favorecido /convenios`) | token gratuito header `chave-api-dados` | **sim-com-token** | Cruzamento favorecido×sanção em tempo real; ~90 req/min (06–24h), 300 (00–06h) |
| 10 | **API Acórdãos (recupera-acordaos)** | TCU | `https://dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos?inicio=0&quantidade=N` | nenhuma | **sim** | JSON paginado: chave, número, ano, colegiado, relator, sumário, URLs DOC/PDF |
| 11 | **CSV Jurisprudência Selecionada** | TCU | `https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/jurisprudencia-selecionada/jurisprudencia-selecionada.csv` | nenhuma | **sim** | ~115 MB; enunciados temáticos → índice RAG do Lex |
| 12 | **CSV Acórdão Completo por ano** | TCU | `https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/acordao-completo/acordao-completo-2021.csv` (trocar ano 2019..2026) | nenhuma | **sim** | ~525 MB/ano; texto integral → RAG, evita alucinação de jurisprudência |
| 13 | **API Responsáveis Inidôneos (CEIS/TCU)** | TCU | `https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-inidoneos` (POST) | nenhuma | **sim** | Cruzar CNPJ fornecedor das OBs → achado de alta severidade |
| 14 | **API Inabilitados + Contas Irregulares (CADIRREG)** | TCU | `https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-contas-irregulares` (POST) | nenhuma | **sim** | Responsáveis com contas irregulares no TCU |
| 15 | **API Certidões PF/PJ por CNPJ** | TCU | `https://certidoes-apf.apps.tcu.gov.br/api/rest/publico/certidoes/{cnpj}` | nenhuma | **sim** | Situação do CNPJ no TCU (JSON e PDF) |
| 16 | **Calculadora de Débito/Atualização** | TCU | `https://divida.apps.tcu.gov.br/api/publico/calculadora/calcular-saldos-debito` (POST) | nenhuma | **sim** | Atualização monetária do dano apurado → valor de ressarcimento no parecer |
| 17 | **Compras.gov.br — Dados Abertos (CATMAT/CATSER)** | Gov Federal | `https://dadosabertos.compras.gov.br` (`/swagger-ui/index.html`) | nenhuma | **sim** | Catálogos e preços praticados → referência de sobrepreço por item |
| 18 | **Comprasnet Contratos — API** | Gov Federal | `https://contratos.comprasnet.gov.br/api/docs` | nenhuma | **sim** | Contratos, empenhos, faturas, garantias do SIASG |
| 19 | **Compras.dados.gov.br (legado SIASG)** | Gov Federal | `https://compras.dados.gov.br/docs/home.html` | nenhuma | **sim** | HATEOAS JSON/XML/CSV `/{modulo}/v1/{metodo}.{formato}` |
| 20 | **licitante_vencedor/perdedor_municipio** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/licitante_vencedor_municipio?ano=2024&inicio=0&limite=1000&jsonfull=true` | nenhuma | **sim** | Participantes por processo → rede de conluio / taxa de vitória anômala |
| 21 | **empenho/dotacao/receitas_estado** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/empenho_estado?ano=2024&inicio=0&limite=1000&jsonfull=true` | nenhuma | **sim** | Reconciliar empenho↔OB; orçamento e execução por ano |
| 22 | **obras_paralisadas_estado** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/obras_paralisadas_estado?inicio=0&limite=1000&jsonfull=true` | nenhuma | **sim** | Obra parada + OB paga = flag de dano por obra inacabada |
| 23 | **concessoes_publicas (PPPs)** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/concessoes_publicas?jsonfull=true` | nenhuma | **sim** | Concessões e PPPs do Estado-RJ |
| 24 | **convenios_estado** | TCE-RJ | `https://dados.tcerj.tc.br/api/v1/convenios_estado?jsonfull=true` | nenhuma | **sim** | Convênios e pagamento de convênios |
| 25 | **MAG — Manual de Auditoria Governamental** | TCE-RJ | `https://www.tcerj.tc.br/portal-tce-webapi/api/arquivos/2221a85b-f00f-490c-ad61-08d9302d99d2/download` | nenhuma | **sim** | PDF da metodologia (matriz de achados) → template do Lex |
| 26 | **API Atos Normativos** | TCU | `https://dados-abertos.apps.tcu.gov.br/api/atonormativo/recupera-atos-normativos` | nenhuma | **sim** | Atos normativos do TCU |
| 27 | **CSV Boletim de Jurisprudência** | TCU | `https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/boletim-jurisprudencia/boletim-jurisprudencia.csv` | nenhuma | **sim** | ~4 MB; síntese temática |
| 28 | **Espelho Acórdãos TCU (BNDES)** | BNDES | `https://dadosabertos.bndes.gov.br/dataset/acordaos-tcu` | nenhuma | **sim** | Mirror CSV alternativo dos acórdãos |
| 29 | **TransfereGov / Siconv — API** | Gov Federal | `https://api.transferegov.gestao.gov.br` (legado `https://api.convenios.gov.br/siconv/v1/consulta`) | nenhuma | **dificil-WAF** | Convênios/repasses/prestação de contas — **retornou 502/instável** |
| 30 | **dados.gov.br — CKAN (catálogo)** | CGU | `https://dados.gov.br/api/3/action/` (`package_search`, `package_show`); bulk `https://repositorio.dados.gov.br` | `/action/*` exige token; repositório aberto | **sim-com-token** | Descoberta de datasets; arquivos via repositório aberto |
| 31 | **Pesquisa Textual de Jurisprudência** | TCU | `https://pesquisa.apps.tcu.gov.br/` (ex.: `/doc/acordao-completo/2622/2013/Plenário`) | nenhuma | **sim-com-token** | Back-end retorna HTML (não JSON limpo) |
| 32 | **Portal de Jurisprudência (consultas)** | TCE-RJ | `https://www.tcerj.tc.br/sistema-jurisprudencia/public/consultas` | nenhuma | **sim-com-token** | Busca textual de decisões/súmulas/enunciados; sem API documentada (HTML) |
| 33 | **BNPortal — busca de deliberações** | TCE-RJ | `https://www.tce.rj.gov.br/bnportal/m/pt-BR/` (`?exp=...`) | nenhuma | **sim-com-token** | Busca textual (HTML) |
| 34 | **Boletim de Jurisprudência** | TCE-RJ | `https://www.tcerj.tc.br/cadastro-publicacoes/public/boletim-jurisprudencia` | nenhuma | **sim-com-token** | PDFs periódicos por tema |
| 35 | **Deliberações (Plenário/Virtual)** | TCE-RJ | `https://www.tce.rj.gov.br/cadastro-publicacoes/public/deliberacoes` | nenhuma | **sim-com-token** | Pautas e PDFs |
| 36 | **Consulta de Processos / Decisões** | TCE-RJ | `https://www.tcerj.tc.br/consulta-processo/Processo` | nenhuma | **sim-com-token** | Andamento e decisões por nº de processo (HTML) |
| 37 | **CGU — relatórios de fiscalização** | CGU | `https://www.gov.br/cgu/pt-br` | nenhuma | **sim-com-token** | HTML/PDF de auditorias em entes federativos |
| 38 | **Licitações/Compras do próprio TCU (lumis)** | TCU | `https://portal.tcu.gov.br/lumis/api/rest/licitacoestcu/lumgetdata/list.xml` | nenhuma | **dificil-WAF** | XML — probe retornou 404/WAF |
| 39 | **SIGFIS — envio de declarações** | TCE-RJ | `https://www.tcerj.tc.br/sigfismun/` | login (jurisdicionado) | **nao** | Transacional; dados públicos saem pela API de Dados Abertos (#1–4) |
| 40 | **SEI-RJ — processo eletrônico** | Gov RJ | `https://sei.rj.gov.br/` | pública p/ consulta, **mas WAF** | **dificil-WAF** | **HTTP 403 da VM GCP**; usar nº SEI já presente nos datasets como chave |

---

## 4. Plano de ingestão priorizado

### Onda 0 — fechar o ciclo contrato↔OB (impacto imediato, tudo sem auth)
1. **TCE-RJ `contratos_estado` (#2)** e **`compras_diretas_estado` (#3)** — paginar `inicio/limite=1000`, `jsonfull=true`. Carregar em tabelas locais.
   - **Cruzamento:** `JOIN` com as 1,1M OBs por **CPF/CNPJ do favorecido** e por **UG/órgão**. Reconciliar contrato → empenho → OB. Detectar: pagamento **sem contrato vigente**, OB **acima do valor contratado**, **fracionamento** (somatório de dispensas ao mesmo CNPJ acima do limite legal).
2. **TCE-RJ `penalidades_ressarcimento_estado` (#4)** — refresh **diário** (campo `DataUltimaAtualizacao`). Flag automática quando um CPF/CNPJ das OBs ou um órgão aparece como MULTA/RESSARCIMENTO.
3. **TCE-RJ `empenho_estado` (#21)** — reconciliar empenho↔OB por ano.

### Onda 1 — sanções federais (achado de alto peso)
4. **Portal Transparência bulk CSV (#8)** — baixar `ceis`, `cnep`, `cepim` (sem token, sem limite). Tabela `sancionados` no SQLite.
   - **Cruzamento:** CNPJ favorecido das OBs × CEIS/CNEP/CEPIM → "**pagamento a fornecedor sancionado**".
   - Base legal por cadastro (o Lex referencia): CEIS → art. 156 Lei 14.133 / art. 87 Lei 8.666; CNEP → Lei 12.846/2013; CEPIM → repasse a entidade impedida.
5. **TCU Inidôneos (#13)** e **Contas Irregulares (#14)** (POST) + **Certidões por CNPJ (#15)** — cruzar CNPJ das OBs; OB a empresa declarada inidônea pelo TCU = achado de alta severidade.

### Onda 2 — vincular OB ao edital/contrato de origem e preço de referência
6. **PNCP Contratos (#5)** e **Contratações/Publicação (#6)** — ingerir por período (AAAAMMDD), filtrando CNPJ dos órgãos RJ (ex.: **ITERJ UG 133100**). Vincular cada OB ao contrato/edital; detectar aditivos e dispensa indevida.
7. **PNCP Atas (#7)** + **Compras.gov.br CATMAT/CATSER (#17)** — referência de preço por item → indício de **sobrepreço**.

### Onda 3 — base jurisprudencial do Lex (RAG) e régua determinística
8. **TCU `acordao-completo-{ano}.csv` (#12)** 2019–2026 + **`jurisprudencia-selecionada.csv` (#11)** + **Boletim (#27)** → índice local RAG. Lex cita acórdão/súmula **real** (chave + número) ao tipificar.
9. **Régua determinística sobre OBs de obras/serviços:** aplicar **Acórdão 2622/2013** (faixas de BDI) e **Acórdão 1875/2021** (cesta de preços, mediana se CV>25%) como regras antes de escalar ao parecer.
10. **Calculadora de Débito TCU (#16)** — atualizar monetariamente o dano das OBs suspeitas → valor de ressarcimento.

### Onda 4 — sinais de conluio e obras paradas
11. **TCE-RJ `licitante_vencedor/perdedor_municipio` (#20)** — montar grafo de coparticipação e taxa de vitória anômala.
12. **TCE-RJ `obras_paralisadas_estado` (#22)** × OBs — obra parada com pagamento = dano por obra inacabada.

> **Querido Diário** (diários oficiais municipais, `queridodiario.ok.org.br/api`) entra como camada complementar de texto livre para correlacionar atos de homologação/aditivo aos contratos — ingerível por HTTP sem auth; recomendado avaliar na Onda 2.

### Padrão operacional de ingestão
- Agendar via **cron** na VM. TCE-RJ Dados Abertos: paginar `inicio/limite`, baixar `jsonfull=true`; bases com `DataUltimaAtualizacao` (penalidades) = refresh diário.
- **Token Portal da Transparência** (`chave-api-dados`): cadastrar via conta gov.br, armazenar como **secret** na VM, respeitar 90 req/min com backoff.
- Estruturar todo output do JFN no formato de achado (Critério/Condição/Causa/Efeito) para aproveitamento direto em representação.

---

## 5. Notas de WAF / limitação por fonte (o que NÃO funciona da VM GCP)

| Fonte | Status do probe (jun/2026) | Implicação operacional |
|---|---|---|
| **`sei.rj.gov.br` (#40)** | **HTTP 403** — WAF bloqueia IP de datacenter (confirmado) | **NÃO** depender de scraping direto do SEI a partir da VM. Usar o nº SEI já presente em `contratos_estado`/`compras_diretas_estado` como chave. Para casos pontuais, proxy residencial / Camoufox. |
| **`api.transferegov.gestao.gov.br` (#29)** | **502 / instável** | Não confiável para cron; tentar legado `api.convenios.gov.br/siconv` ou repositório de arquivos. |
| **`portal.tcu.gov.br/lumis/...list.xml` (#38)** | **404 / WAF** | Licitações do próprio TCU não acessíveis por essa rota da VM. |
| **`dados.gov.br/api/3/action/*` (#30)** | `/action/*` exige **token** (perfil consumidor) | Usar `repositorio.dados.gov.br` (arquivos abertos) para bulk. |
| **`api.portaldatransparencia.gov.br/api-de-dados/*` (#9)** | **401 sem token** | Token gratuito obrigatório no header `chave-api-dados`. Para sanções, preferir bulk CSV (#8) sem token. |
| **Portais HTML TCE-RJ (#31–37)** | HTTP 200, mas **sem JSON** (HTML / busca textual) | "sim-com-token" = exige parser/token de sessão; não há API limpa. Para jurisprudência, preferir os CSVs do TCU (#11/#12) como base estruturada. |
| **`pesquisa.apps.tcu.gov.br` (#31)** | HTTP 200, back-end **HTML** | Para texto integral estruturado usar os CSVs `acordao-completo` (#12), não o scraping do portal. |

**Confirmados HTTP 200 sem auth da VM GCP (jun/2026):** API Acórdãos TCU (#10); `jurisprudencia-selecionada.csv` 115MB (#11); `acordao-completo-2021.csv` 525MB (#12); certidões `/{cnpj}` (#15); inidôneos POST (#13); TCE-RJ `openapi.json` 41 endpoints (#1); `contratos_estado` com SEI+CPFCNPJ (#2); `compras_diretas_estado` (#3); `penalidades_ressarcimento_estado` com `DataUltimaAtualizacao` 2026-06-06 (#4); `licitante_vencedor_municipio` (#20); PNCP `/contratos` (#5) e `/atas` (#7); `dadosabertos.compras.gov.br` swagger (#17); `api.portaldatransparencia.gov.br/v3/api-docs` (#9, docs).

---

## Fontes consultadas (URLs dos insumos)

**TCU:** `https://sites.tcu.gov.br/dados-abertos/webservices-tcu/` · `https://sites.tcu.gov.br/dados-abertos/jurisprudencia/` · `https://pesquisa.apps.tcu.gov.br/dados-abertos` · `https://portal.tcu.gov.br/imprensa/noticias/uso-de-inteligencia-artificial-aprimora-processos-internos-no-tribunal-de-contas-da-uniao` · `https://pesquisa.apps.tcu.gov.br/doc/acordao-completo/2622/2013/Plenário` · `https://www.conjur.com.br/2021-set-30/interesse-publico-acordao-187521-tcu-pesquisas-precos-lei-1413321/` · `https://dadosabertos.bndes.gov.br/dataset/acordaos-tcu`

**TCE-RJ:** `https://dados.tcerj.tc.br/api/v1/openapi.json` · `https://dados.tcerj.tc.br/api/v1/contratos_estado` · `https://dados.tcerj.tc.br/api/v1/penalidades_ressarcimento_estado` · `https://dados.tcerj.tc.br/api/v1/licitante_vencedor_municipio` · `https://dados.tcerj.tc.br/api/v1/compras_diretas_estado` · `https://www.tcerj.tc.br/sistema-jurisprudencia/public/consultas` · `https://www.tcerj.tc.br/portalnovo/` · `https://www.tce.rj.gov.br/` · `https://sei.rj.gov.br/` (403) · `https://www.tcerj.tc.br/cadastro-publicacoes/public/boletim-jurisprudencia` · `https://www.tce.rj.gov.br/bnportal/m/pt-BR/` · `https://www.tce.rj.gov.br/cadastro-publicacoes/public/deliberacoes` · `https://www.tcerj.tc.br/sigfismun/` · `https://www.mprj.mp.br/documents/20184/171752/manual_de_auditoria_governamental_tce_rj.pdf`

**Federais:** `https://portaldatransparencia.gov.br/api-de-dados` · `https://www.gov.br/conecta/catalogo/apis/portal-da-transparencia-do-governo-federal` · `https://api.portaldatransparencia.gov.br/v3/api-docs` · `https://api.portaldatransparencia.gov.br/api-de-dados/ceis` · `https://portaldatransparencia.gov.br/download-de-dados/ceis` · `https://pncp.gov.br/api/consulta/swagger-ui/index.html` · `https://pncp.gov.br/api/consulta/v1/contratos` · `https://pncp.gov.br/api/consulta/v1/atas` · `https://dadosabertos.compras.gov.br/swagger-ui/index.html` · `https://contratos.comprasnet.gov.br/api/docs` · `https://compras.dados.gov.br/docs/home.html`
