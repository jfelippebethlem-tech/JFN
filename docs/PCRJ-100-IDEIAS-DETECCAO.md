# PREFEITURA DA CIDADE DO RIO DE JANEIRO
## Catálogo de 100 Ideias de Detecção de Irregularidades
### Avaliadas contra o acervo de dados existente — `data/compliance.db`

---

| | |
|---|---|
| **Documento** | Catálogo técnico de hipóteses de detecção |
| **Jurisdição** | Município do Rio de Janeiro (CNPJ raiz 42.498.733) |
| **Base de dados** | `~/JFN/data/compliance.db` (aberta em modo somente-leitura) |
| **Período coberto** | Despesa 2019–2023 · Contratos 2021–2026 · Licitações 2025–2026 |
| **Data de apuração** | 30 de agosto de 2026 |
| **Regra metodológica** | Prevalência decide. Empenho ≠ Liquidação ≠ Pago. INDISPONÍVEL ≠ 0. |
| **Classificação** | Uso interno — controle externo |

---

## 1. SUMÁRIO EXECUTIVO

### 1.1 Veredito sobre a testabilidade

Das 100 hipóteses catalogadas, o acervo de hoje sustenta **68**. Destas, **48 foram efetivamente medidas
com SQL executado** para este documento; as outras 20 são executáveis sem nenhuma captura adicional, apenas
não foram rodadas por economia de ciclo. **32 hipóteses dependem de captura nova** e estão marcadas com o
insumo exato que falta — nenhuma delas foi apresentada como "zero casos".

| Situação | Nº de ideias | % |
|---:|---:|---:|
| **MEDIDA** — SQL rodado, prevalência apurada neste documento | 48 | 48,0% |
| **TESTÁVEL HOJE** — dado presente, query ainda não rodada | 20 | 20,0% |
| **PRECISA CAPTURA** — insumo ausente, identificado nominalmente | 32 | 32,0% |
| **Total** | **100** | **100,0%** |

### 1.2 O universo real, medido

`pcrj_despesa` contém **78.595 linhas**, **146 órgãos municipais**, exercícios **2019–2023**, e
**R$ 89.620.000.000,00** pagos (R$ 89,62 bi). O grão é único por
(`exercicio`, `orgao`, `credor_documento`, `natureza`, `fonte_recurso`) — verificado: **zero duplicidades**
nessa chave. São **10.343** documentos de credor distintos, dos quais **9.241** com pagamento maior que zero.

Decomposição do código de natureza de despesa (posições 1=categoria, 2=grupo, 3-4=modalidade de aplicação,
5-6=elemento):

| Grupo de natureza | Linhas | Pago (R$ bi) | % do pago |
|---|---:|---:|---:|
| 3 — Outras Despesas Correntes | 73.493 | 51,60 | 57,6% |
| 1 — Pessoal e Encargos | 895 | 21,18 | 23,6% |
| 4 — Investimentos | 4.074 | 6,82 | 7,6% |
| 6 — Amortização da Dívida | 37 | 5,65 | 6,3% |
| 2 — Juros e Encargos da Dívida | 26 | 3,57 | 4,0% |
| 5 — Inversões Financeiras | 70 | 0,82 | 0,9% |

| Modalidade de aplicação | Linhas | Pago (R$ bi) |
|---|---:|---:|
| 90 — Aplicação direta | 71.410 | 47,49 |
| 91 — Aplicação direta intra-orçamentária | 1.363 | 27,83 |
| 50 — Transferência a instituições privadas sem fins lucrativos | 5.685 | 12,90 |
| Demais (67, 20, 30, 84, 60, 80, 40) | 137 | 1,39 |

> **Correção de denominador — leia antes de citar qualquer percentual sobre "o gasto do Rio".**
> Dos R$ 89,62 bi, **R$ 27,83 bi (31,1%) são modalidade 91 (intra-orçamentária)** e **R$ 21,18 bi (23,6%)
> são grupo 1 (Pessoal)**. O maior credor isolado do acervo é o **Fundo Especial de Previdência do Município
> do Rio de Janeiro (R$ 20.489.600.000,00)**, seguido do **Banco do Brasil S.A. (R$ 12.490.810.000,00)** —
> ambos folha e encargos, não risco contratual. O top-1 credor absorve entre **27,25% (2019)** e
> **20,17% (2023)** do pago anual. Todo ranking por valor bruto ranqueia folha, não irregularidade.

### 1.3 As dez hipóteses mais promissoras (força do sinal × dado disponível)

| # | Ideia | Prevalência medida | Massa financeira | Por que é forte |
|---:|---|---:|---:|---|
| 39 | ME/EPP com recebimento anual acima do teto de R$ 4.800.000,00 | **1,18%** (92 de 7.764 empresa-ano) | R$ 861.000.000,00 | Baixa prevalência, tipicidade direta (LC 123/2006), universo bem definido |
| 29 | Credor com sanção federal vigente no período de pagamento | **0,68%** (52 de 7.698 CNPJ) | R$ 375.030.000,00 | A menor prevalência de todo o catálogo com massa relevante |
| 26 | Sócio comum a 3 ou mais fornecedores do Município | **0,69%** (89 de 12.894 sócios) | a apurar por caso | Sinal de rede, não de volume; discrimina fortemente |
| 62 | Salto de 10× ou mais no pagamento ano a ano (base ≥ R$ 1 mi) | **0,87%** (19 de 2.190 pares) | a apurar por caso | Anomalia temporal pura, imune a viés de tamanho |
| 58 | Valor liquidado sem qualquer pagamento correspondente | **1,03%** (813 de 78.595 linhas) | R$ 146.670.000,00 | Despesa reconhecida como devida e não paga — ou serviço atestado sem quitação |
| 20 | Sócio de fornecedor municipal consta em folha pública estadual | **5,55%** (416 de 7.500 raízes) | R$ 10.522.000.000,00 | Massa enorme; exige refino por CPF completo (ver ressalva §5.2) |
| 42 | Pagamento acumulado superior a 100× o capital social | **4,97%** (304 de 6.115 empresas) | R$ 6.935.000.000,00 | Desproporção entre capacidade declarada e contratação |
| 2 | Fornecedor que absorve 80% ou mais do pago de um órgão-ano | 84 órgão-ano | R$ 34.624.000.000,00 | Quase-exclusividade; o corte de 50% não serve (ver §5.1) |
| 55 | Pagamento a pessoa física em elemento típico de pessoa jurídica | **2,65%** (2.085 linhas) | R$ 436.630.000,00 | Produziu caso concreto imediato (ideia 56) |
| 78 | Outlier de valor estimado em licitação | 1 caso em 2.449 | R$ 347.037.696.000,00 declarados | Dispensa com estimativa de R$ 347 bi — erro grave de dado ou achado grave |

---

## 2. ADVERTÊNCIAS DE LEITURA DO ACERVO

Três limitações estruturais foram medidas e condicionam um terço do catálogo:

**2.1 A coluna `unidade` de `pcrj_despesa` é nula em 78.595 de 78.595 linhas (100,00%).**
Não existe granularidade abaixo do órgão. Toda a família de fracionamento por unidade gestora está
bloqueada na origem.

**2.2 `pcrj_despesa` não possui data, número de empenho nem objeto.** O grão temporal mínimo é o
exercício. Fracionamento por proximidade de datas, sequência de empenhos e análise de objeto são
inviáveis nesta base.

**2.3 Em `pcrj_contratos` filtrado para o Município, `valor_inicial` é idêntico a `valor_global` em
1.987 de 1.987 registros (100,00%).** O campo de valor global espelha o inicial — não é possível medir
aditivo por valor. Resta apenas a contagem `num_aditivos`.

**2.4 As janelas temporais não se sobrepõem bem.** Despesa cobre 2019–2023; contratos do Município,
2021–2026 (1 registro em 2021, 4 em 2022, 18 em 2023, 387 em 2024, 696 em 2025, 881 em 2026);
licitações do Município, apenas 2025–2026. A interseção entre despesa executada e contrato registrado é
de **três exercícios com volume residual (2021–2023, 23 contratos)**.

**2.5 Não há folha de pagamento do Município no acervo.** `registros_folha` (801.827 linhas) tem origem
`gesperj_estado`, `dprj_transparencia`, `tjrj_anexo8` e `camara_csv`; `agente_publico_societario`
(712.534) tem origem `folha_estado` e `alerj`. Portanto, "servidor municipal sócio de fornecedor
municipal" **não é testável hoje**. O que é testável é o cruzamento inter-esferas: servidor estadual ou
da ALERJ sócio de empresa paga pela Prefeitura.

---

## 3. AS 100 IDEIAS, POR FAMÍLIA

Legenda de status: **MEDIDA** (SQL rodado neste documento) · **TESTÁVEL** (dado presente, query não rodada) ·
**CAPTURA** (falta insumo, nomeado).

### 3.1 Família A — Concentração de fornecedor e estrutura de mercado

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 1 | Fornecedor dominante no órgão-ano (≥50%) | Captura de órgão por um único credor | `pcrj_despesa`: exercicio, orgao, credor_documento, pago | MEDIDA | **35,7%** — 174 de 488 órgão-ano com ≥ R$ 5 mi. R$ 45,90 bi. **Prevalência alta: refinar** |
| 2 | Fornecedor quase-exclusivo (≥80%) | Monopólio de fato | idem | MEDIDA | 84 órgão-ano · R$ 34,62 bi |
| 3 | Share do top-1 credor no total municipal | Dependência sistêmica | idem | MEDIDA | 27,25% (2019) · 26,86% · 23,58% · 19,54% · 20,17% (2023) — dominado pela previdência |
| 4 | Fornecedor único por natureza-órgão-ano | Ausência de disputa no elemento | `pcrj_despesa`: natureza | MEDIDA | **48,6%** — 1.724 de 3.547 grupos ≥ R$ 1 mi. **DESCARTADA (§5.1)** |
| 5 | Fornecedor transversal (≥10 órgãos) | Penetração anômala na máquina | `pcrj_despesa`: orgao | MEDIDA | 4,96% — 458 de 9.241 credores · R$ 34,93 bi. Topo é concessionária e banco: **refinar excluindo utilities** |
| 6 | Índice HHI por natureza-órgão | Mede concentração em escala contínua | `pcrj_despesa` | TESTÁVEL | — |
| 7 | Rodízio de vencedores no mesmo objeto | Cartel por alternância | `pncp_resultado` | CAPTURA: histórico de itens PNCP anterior a 2024 | — |
| 8 | Fornecedor mono-cliente de alto valor | Empresa que só existe para um órgão | `pcrj_despesa` | TESTÁVEL | — |
| 9 | Órgão com carteira de fornecedores anormalmente estreita | Mercado fechado | `pcrj_despesa` | TESTÁVEL | — |
| 10 | Migração de dominância entre exercícios | Sucessão de incumbente | `pcrj_despesa` | TESTÁVEL | — |

### 3.2 Família B — Fracionamento e escape de modalidade

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 11 | Soma anual de dispensas por objeto e fornecedor | Fracionamento clássico | `pcrj_licitacoes` | CAPTURA: base cobre só 2025–2026 e não traz fornecedor | — |
| 12 | Empenhos próximos no tempo para o mesmo credor | Fracionamento por data | — | CAPTURA: `pcrj_despesa` não tem data (§2.2) | — |
| 13 | Dispensa acima do teto do art. 75 da Lei 14.133/2021 | Enquadramento indevido | `pcrj_licitacoes`: valor_estimado | CAPTURA: `amparo` é nulo em 100% dos registros | — |
| 14 | Sequência de empenhos logo abaixo do teto | Corte deliberado de valor | — | CAPTURA: sem número de empenho (§2.2) | — |
| 15 | Mesmo objeto dividido entre unidades gestoras | Fracionamento por unidade | — | CAPTURA: `unidade` nula em 100% (§2.1) | — |
| 16 | Participação da dispensa no total de certames | Escape sistêmico da licitação | `pcrj_licitacoes`: modalidade | MEDIDA | Dispensa 1.148 · Pregão-e 886 · Inexigibilidade 254 · Concorrência-e 161 → **46,9% dos certames são dispensa** |
| 17 | Inexigibilidade com mercado competitivo comprovado | Inexigibilidade sem exclusividade | `pcrj_licitacoes` | CAPTURA: prova de exclusividade e mapa de mercado | — |
| 18 | Dispensa emergencial repetida com o mesmo fornecedor | Emergência fabricada | `pcrj_licitacoes`: amparo | CAPTURA: `amparo` nulo em 2.449 de 2.449 | — |

### 3.3 Família C — Vínculo societário e agente público

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 19 | Sócio de fornecedor é servidor **municipal** | Conflito de interesse direto | — | CAPTURA: folha da PCRJ (§2.5) | — |
| 20 | Sócio de fornecedor municipal em folha **estadual/ALERJ** | Conflito inter-esferas | `agente_publico_societario`: cnpj_basico | MEDIDA | **5,55%** — 416 de 7.500 raízes · R$ 10,52 bi |
| 21 | Recorte apenas de cargos comissionados | Vínculo político, não estatutário | `agente_publico_societario`: comissionado | MEDIDA | **0,92%** — 69 raízes |
| 22 | Marcação `socio_servidor` já consolidada | Reaproveita trabalho anterior | `socios_fornecedor`: socio_servidor | MEDIDA | 1,32% — 33 de 2.494 CNPJ cobertos |
| 23 | Controle de homonímia do vínculo | Falso positivo por CPF mascarado | `socios_receita`: doc_socio | MEDIDA | `doc_socio` tem **6 dígitos em 12.936 de 13.792 ocorrências (93,8%)** — colisão material (§5.2) |
| 24 | Parentesco entre sócio e agente público | Interposição familiar | — | CAPTURA: base de parentesco | — |
| 25 | Troca de sócio na véspera da contratação | Empresa preparada para o certame | `socio_historico`: janela | CAPTURA: contratos municipais só a partir de 2021, sem sobreposição útil | — |
| 26 | Sócio comum a 3 ou mais fornecedores | Rede de empresas coordenadas | `socios_receita` × `pcrj_despesa` | MEDIDA | **0,69%** — 89 de 12.894 sócios |
| 27 | Sócio de fornecedor é doador eleitoral | Financiamento e contrapartida | `doacoes_eleitorais` | CAPTURA: doador tem CPF de 11 dígitos, sócio tem 6 mascarados — **não casável** | — |
| 28 | Fornecedor é doador eleitoral direto | Doação de PJ | `doacoes_eleitorais`: cpf_cnpj_doador | MEDIDA | **0,04%** — 3 de 7.698 · R$ 4.661,25. **DESCARTADA (§5.3)** |

### 3.4 Família D — Idoneidade, sanção e vida cadastral

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 29 | Sanção federal vigente durante o período de pagamento | Contratação de inidôneo | `sancoes_federais`: cpf_cnpj, data_inicio, data_fim | MEDIDA | **0,68%** — 52 de 7.698 CNPJ · R$ 375,03 mi. Aferição por exercício, não por data exata |
| 30 | Estratificação por cadastro (CEIS/CNEP/CEPIM) | Grava a natureza da sanção | `sancoes_federais`: cadastro | TESTÁVEL | — |
| 31 | Penalidade aplicada pelo TCE-RJ | Reincidência perante o controle | `penalidades_tcerj` (954 reg.) | CAPTURA: acervo é estadual; confirmar cobertura da capital | — |
| 32 | Fornecedor sem quadro societário conhecido e alto valor | Opacidade de titularidade | `pcrj_despesa` × `socios_receita` | MEDIDA | 5,64% — 26 de 461 empresas com pago ≥ R$ 10 mi |
| 33 | Score de empresa fantasma | Casca sem substância | `fantasma_score`: classificacao | MEDIDA | 7 "alto", 65 "medio", 200 "baixo", 98 sem cadastro (370 avaliadas) |
| 34 | Sede real não confirmada | Endereço de fachada | `verificacao_sede_real`: veredito | MEDIDA | 9 "forte_suspeita" e 336 "suspeita" de 2.521 avaliadas (**13,7% somados**) |
| 35 | Ninho de endereço (3+ fornecedores no mesmo local) | Empresas coabitando | `endereco_fornecedor`: endereco_norm | MEDIDA | **0 ninhos** com ≥3 em 2.518 endereços; com ≥2, **22 (0,87%)**. Ver §5.4 |
| 36 | CNAE incompatível com o objeto contratado | Empresa fora do ramo | — | CAPTURA: CNAE ausente em `empresas_cadastro` | — |
| 37 | Situação cadastral baixada/suspensa na data do pagamento | Pagamento a empresa inexistente | — | CAPTURA: situação cadastral com vigência datada | — |
| 38 | Empresa recém-constituída vencendo contrato vultoso | Empresa criada para o certame | — | CAPTURA: `data_inicio_atividade` ausente | — |

### 3.5 Família E — Porte, capacidade econômica e teto legal

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 39 | ME/EPP com recebimento anual acima de R$ 4.800.000,00 | Fruição indevida do regime | `empresas_cadastro`: porte_cod × `pcrj_despesa` | MEDIDA | **1,18%** — 92 de 7.764 empresa-ano. EPP: 71 casos, R$ 710,00 mi. ME: 21 casos, R$ 151,00 mi |
| 40 | Microempresa acima do teto no acumulado 2019–2023 | Persistência da distorção | idem, porte_cod = '01' | MEDIDA | 30 empresas · R$ 294,87 mi |
| 41 | Porte declarado no certame × valor homologado | Benefício de porte indevido | `pncp_resultado`: porte_fornecedor | TESTÁVEL | Base: porte 1 vence 1.400 itens (R$ 402,45 mi); porte 3, 1.039 itens (R$ 2.060,12 mi) |
| 42 | Pagamento acumulado > 100× o capital social | Desproporção de capacidade | `empresas_cadastro`: capital_social | MEDIDA | **4,97%** — 304 de 6.115 · R$ 6,94 bi |
| 43 | Capital social irrisório (≤ R$ 1.000,00) com contrato relevante | Casca societária | `empresas_cadastro`: capital_social | TESTÁVEL | — |
| 44 | Empate ficto e preferência de ME/EPP em disputa | Manipulação do benefício | `pncp_resultado`: porte_fornecedor, ordem_classificacao | TESTÁVEL | — |
| 45 | Porte declarado divergente do porte na Receita | Declaração falsa no certame | `pncp_resultado` × `empresas_cadastro` | TESTÁVEL | — |
| 46 | Dependência do fornecedor em relação ao erário | Empresa que só vive de contrato público | — | CAPTURA: faturamento total da empresa | — |

### 3.6 Família F — Preço e referência

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 47 | Dispersão bruta de preço unitário por descrição de item | Sobrepreço | `pncp_resultado`: item_descricao, valor_unitario | MEDIDA | **71,1%** dos grupos do Rio (54 de 76) e **81,8%** do município inteiro (962 de 1.176) têm razão máx/mín ≥ 3×. **DESCARTADA (§5.5)** |
| 48 | Dispersão com item normalizado e unidade de medida homogênea | Sobrepreço, versão utilizável | `pncp_resultado`: unidade_medida | CAPTURA: normalizador de descrição de item | — |
| 49 | Preço acima do Painel de Preços federal | Referência externa | — | CAPTURA: painel de preços | — |
| 50 | Item "pacote" — quantidade 1 e valor unitário elevado | Objeto não decomposto, impede comparação | `pncp_resultado`: quantidade, valor_unitario | TESTÁVEL | — |
| 51 | Homologado colado no estimado (≥ 99%) | Ausência de disputa efetiva | `pncp_resultado`: valor_homologado × `pcrj_licitacoes`: valor_estimado | TESTÁVEL | — |
| 52 | Reajuste acima do índice no aditivo | Reequilíbrio indevido | — | CAPTURA: valor de aditivo (§2.3) | — |
| 53 | Proposta vencedora idêntica ao preço-teto | Direcionamento | `pncp_resultado` × `pcrj_licitacoes` | TESTÁVEL | — |
| 54 | Mesmo item e fornecedor com preços distintos entre órgãos | Discriminação de preço contra o erário | `pncp_resultado` | TESTÁVEL | — |

### 3.7 Família G — Execução orçamentária e prova de entrega

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 55 | Pagamento a pessoa física em elemento típico de PJ | Cadastro falso ou pagamento irregular | `pcrj_despesa`: length(credor_documento)=11 | MEDIDA | **2,65%** — 2.085 linhas, 1.543 CPF · R$ 436,63 mi |
| 56 | Pessoa jurídica estrangeira registrada sob CPF | Erro cadastral em compra vultosa | idem + natureza 44905202 | MEDIDA | **3 linhas · R$ 112.291.435,82** — "CHINA MEHECO CORPORATION", Secretaria Municipal de Saúde, 2019–2020, elemento 52 (equipamentos e material permanente), sob documento de 11 dígitos |
| 57 | Empenhado sem qualquer pagamento | Restos a pagar / empenho fantasma | `pcrj_despesa`: empenhado, pago | MEDIDA | **3,47%** — 2.731 linhas · R$ 495,23 mi empenhados |
| 58 | Liquidado sem pagamento | Despesa atestada e não quitada | `pcrj_despesa`: liquidado, pago | MEDIDA | **1,03%** — 813 linhas · R$ 146,67 mi |
| 59 | Diferença empenho→pago acima de 50% em empenhos ≥ R$ 1 mi | Superempenho | `pcrj_despesa` | MEDIDA | **2,12%** — 145 linhas · R$ 671,00 mi de diferença |
| 60 | Consistência da cascata (liquidado ≤ empenhado, pago ≤ liquidado) | Corrupção de dado ou de execução | `pcrj_despesa` | MEDIDA | **0 violações** em 78.595 linhas — a base é internamente consistente |
| 61 | Pagamento sem contrato correspondente | Despesa sem instrumento | `pcrj_despesa` × `pcrj_contratos` | CAPTURA: sem chave comum e sem sobreposição de anos (§2.4) | — |
| 62 | Salto de 10× ou mais no pagamento ano a ano | Ascensão anômala de fornecedor | `pcrj_despesa` | MEDIDA | **0,87%** — 19 de 2.190 pares consecutivos com base ≥ R$ 1 mi |
| 63 | Fornecedor de exercício único com ≥ R$ 10 mi | Empresa de passagem | `pcrj_despesa` | MEDIDA | 22 casos · R$ 670,00 mi. Atenção: **5.225 de 9.241 credores (56,5%) aparecem em um único exercício** — só o corte de valor discrimina |
| 64 | Prova documental de entrega no processo | Pagamento sem execução comprovada | `processos_sei` | CAPTURA: tabela vazia (0 linhas); falta o SEI municipal | — |

### 3.8 Família H — Contratos e aditivos

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 65 | Aditivo acima do limite de 25% | Extrapolação do art. 125 da Lei 14.133/2021 | `pcrj_contratos`: valor_inicial, valor_global | MEDIDA — **NÃO TESTÁVEL** | **0 casos por defeito de campo**: `valor_global` = `valor_inicial` em 1.987 de 1.987 (100,00%). Não é ausência de aditivo, é ausência de dado |
| 66 | Contagem de aditivos elevada | Contrato que virou outro contrato | `pcrj_contratos`: num_aditivos | MEDIDA | ≥1 aditivo: 170 de 1.987 (**8,6%**); ≥3: 7 (0,35%); máximo observado: 6 aditivos em 1 contrato |
| 67 | Assinatura posterior ao início da vigência | Contrato retroativo | `pcrj_contratos`: data_assinatura, vigencia_ini | MEDIDA | **0 casos** — sinal limpo nesta base |
| 68 | Concentração de assinaturas em dezembro | Corrida orçamentária de fim de exercício | `pcrj_contratos`: data_assinatura | MEDIDA | 290 de 1.987 (**14,6%**) — acima do 1/12 esperado (8,3%) |
| 69 | Vigência superior a 5 anos | Extrapolação do prazo máximo | `pcrj_contratos`: vigencia_ini, vigencia_fim | MEDIDA | 9 contratos |
| 70 | Contratação formalizada apenas por empenho | Ausência de termo contratual | `pcrj_contratos`: tipo | TESTÁVEL | Base: tipo "Empenho" em **1.192 de 1.987 (60,0%)**; "Contrato (termo inicial)" em 743 |
| 71 | Prorrogação sucessiva de serviço não continuado | Perpetuação indevida | `pcrj_contratos` | CAPTURA: histórico de termos aditivos com datas | — |
| 72 | Contrato assinado antes da homologação do certame | Inversão da ordem procedimental | `pcrj_contratos` × `pncp_resultado` | CAPTURA: data de homologação do certame municipal | — |

### 3.9 Família I — Licitação e competição

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 73 | Certame com licitante único | Ausência de competição | `tcerj_licitante`: qtd_participantes | CAPTURA: **0 de 126.251 registros são da capital** (91 entes, nenhum é o Rio) | — |
| 74 | Fornecedor vencedor em 5 ou mais certames do Município | Vencedor contumaz | `pncp_resultado`: fornecedor_cnpj, certame | MEDIDA | **3,27%** — 29 de 887 fornecedores · R$ 250,00 mi |
| 75 | Propostas gêmeas entre concorrentes | Conluio | — | CAPTURA: propostas perdedoras (só há o vencedor) | — |
| 76 | Ordem de classificação ausente no resultado | Lacuna de captura, não achado | `pncp_resultado`: ordem_classificacao | MEDIDA | **32,0%** — 788 de 2.461 itens sem classificação. **Classificar como lacuna do processo** |
| 77 | Prazo exíguo entre publicação e abertura | Restrição à competitividade | `pcrj_licitacoes`: data_abertura | CAPTURA: data de publicação do edital | — |
| 78 | Outlier de valor estimado | Erro grave de dado ou superestimativa | `pcrj_licitacoes`: valor_estimado | MEDIDA | **1 caso**: dispensa 42498733000148-1-001029/2025, "serviços técnicos especializados em tecnologia", **R$ 347.037.696.000,00** estimados. Média da dispensa fica em R$ 307.148.883,40 por conta deste único registro |
| 79 | Certame deserto ou fracassado seguido de dispensa | Fabricação do fundamento da dispensa | `pcrj_licitacoes`: situacao | TESTÁVEL | — |
| 80 | Fundamento legal do certame ausente | Impede o teste de enquadramento | `pcrj_licitacoes`: amparo | MEDIDA | **100,0%** — 2.449 de 2.449 nulos. Bloqueia as ideias 13, 17 e 18 |
| 81 | Objeto genérico ou impreciso | Edital que não define o que compra | `pcrj_licitacoes`: objeto | TESTÁVEL | — |
| 82 | Especificação direcionada a marca ou modelo | Direcionamento técnico | — | CAPTURA: texto integral do edital municipal | — |

### 3.10 Família J — Terceiro setor e transferências (modalidade 50)

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 83 | Universo das transferências a entidades privadas sem fins lucrativos | Delimita a superfície do terceiro setor | `pcrj_despesa`: substr(natureza,3,2) = '50' | MEDIDA | **482 entidades · 5.685 linhas · R$ 12,90 bi** (14,4% do pago total) |
| 84 | Entidade que recebe por transferência e também por aplicação direta | Dupla porta de entrada | idem × modalidade '90' | MEDIDA | **58,5%** — 282 de 482 entidades. **Prevalência alta: é a norma, não o desvio** |
| 85 | Concentração do repasse em poucas entidades | Oligopólio do terceiro setor | idem | MEDIDA | Top 3 = **R$ 7,19 bi de R$ 12,90 bi (55,8%)**: APDM R$ 3.155,87 mi · Viva Rio R$ 2.592,48 mi · Instituto Gnosis R$ 1.446,11 mi |
| 86 | Entidade sem prestação de contas aprovada | Repasse sem prova de aplicação | — | CAPTURA: prestações de contas de parcerias (Lei 13.019/2014) | — |
| 87 | Dirigente de entidade também sócio de fornecedora da mesma pasta | Autocontratação em rede | — | CAPTURA: quadro de dirigentes de OSC | — |
| 88 | Entidade sediada fora do Município ou do Estado | Repasse extraterritorial | `pcrj_despesa` × `endereco_fornecedor` | TESTÁVEL | Indício já visível: "Cruz Vermelha Brasileira — Filial do Estado do Rio Grande do Sul", R$ 472,27 mi |

### 3.11 Família K — Natureza de despesa e fonte de recurso

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 89 | Elemento de despesa incompatível com a missão do órgão | Desvio de finalidade | `pcrj_despesa`: natureza, orgao | TESTÁVEL | — |
| 90 | Fonte vinculada aplicada em finalidade estranha | Desvio de recurso carimbado | `pcrj_despesa`: fonte_recurso | CAPTURA: dicionário oficial das fontes municipais (códigos observados: 100, 181, 1500100, 119, 200, 1600181, 142, 196, 300, 208 — sem tradução em casa) | — |
| 91 | Apuração dos mínimos de saúde e educação | Descumprimento constitucional | `pcrj_despesa` | CAPTURA: mesmo dicionário e a base de cálculo da receita | — |
| 92 | Concentração no elemento 39 (serviços de terceiros — PJ) | Terceirização difusa | `pcrj_despesa`: substr(natureza,5,2) | MEDIDA | **27.000 linhas · R$ 31,32 bi (34,9% do pago)**. Prevalência altíssima: serve de estrato, **não de alerta** |
| 93 | Isolamento da modalidade 91 (intra-orçamentária) | Corrige o denominador | `pcrj_despesa` | MEDIDA | 1.363 linhas · **R$ 27,83 bi (31,1% do total)**. Filtro obrigatório antes de qualquer ranking |
| 94 | Migração de elemento no mesmo fornecedor entre exercícios | Reclassificação para escapar de controle | `pcrj_despesa` | TESTÁVEL | — |

### 3.12 Família L — Qualidade cadastral e integridade do dado

| # | Ideia | O que detecta | Tabela · coluna | Status | Prevalência medida |
|---:|---|---|---|---|---|
| 95 | Mesmo documento com razões sociais divergentes | Cadastro corrompido ou troca de titularidade | `pcrj_despesa`: credor_documento, credor_nome | MEDIDA | **0,23%** — 24 de 10.343 documentos |
| 96 | Mesmo nome com documentos divergentes | Duplicidade de cadastro | idem | MEDIDA | **1,05%** — 107 de 10.221 nomes |
| 97 | Razão social de PJ sob documento de 11 dígitos | Erro de tipo de pessoa | idem | MEDIDA | 21 linhas (LTDA, S.A., EIRELI, CORPORATION sob CPF) |
| 98 | Dígito verificador de CNPJ/CPF inválido | Documento inexistente | `pcrj_despesa` | TESTÁVEL | — |
| 99 | Ausência total de granularidade de unidade gestora | Bloqueio estrutural de análise | `pcrj_despesa`: unidade | MEDIDA | **100,00%** — 78.595 de 78.595 nulos. Inviabiliza as ideias 15 e derivadas |
| 100 | Descontinuidade de cobertura entre as bases | Falsa conclusão por janela desalinhada | Todas | MEDIDA | Despesa 2019–2023 · Contratos 2021–2026 (23 registros antes de 2024) · Licitações 2025–2026. **Interseção útil despesa×contrato: praticamente nula** |

---

## 4. RESUMO DAS 26 MEDIÇÕES INDEPENDENTES EXECUTADAS

| Ideia | Filtro | Casos | Universo | Prevalência | Massa (R$) |
|---:|---|---:|---:|---:|---:|
| 1 | Fornecedor ≥50% do órgão-ano | 174 | 488 | 35,66% | 45.903.000.000,00 |
| 2 | Fornecedor ≥80% do órgão-ano | 84 | 488 | 17,21% | 34.624.000.000,00 |
| 4 | Fornecedor único por natureza-órgão-ano | 1.724 | 3.547 | 48,60% | 57.175.000.000,00 |
| 5 | Fornecedor em ≥10 órgãos | 458 | 9.241 | 4,96% | 34.929.000.000,00 |
| 16 | Certame na modalidade Dispensa | 1.148 | 2.449 | 46,88% | — |
| 20 | Sócio em folha pública estadual | 416 | 7.500 | 5,55% | 10.522.000.000,00 |
| 21 | Sócio comissionado | 69 | 7.500 | 0,92% | — |
| 22 | `socio_servidor` marcado | 33 | 2.494 | 1,32% | — |
| 26 | Sócio comum a ≥3 fornecedores | 89 | 12.894 | 0,69% | — |
| 28 | Fornecedor doador eleitoral | 3 | 7.698 | 0,04% | 4.661,25 |
| 29 | Sanção federal vigente | 52 | 7.698 | 0,68% | 375.030.000,00 |
| 32 | Sem sócio conhecido, pago ≥ R$ 10 mi | 26 | 461 | 5,64% | — |
| 34 | Sede suspeita ou fortemente suspeita | 345 | 2.521 | 13,69% | — |
| 35 | Ninho de endereço com ≥3 CNPJ | 0 | 2.518 | 0,00% | — |
| 39 | ME/EPP acima do teto anual | 92 | 7.764 | 1,18% | 861.000.000,00 |
| 42 | Pago > 100× capital social | 304 | 6.115 | 4,97% | 6.935.000.000,00 |
| 47 | Preço unitário com dispersão ≥3× | 54 | 76 | 71,05% | — |
| 55 | Pagamento a pessoa física | 2.085 | 78.595 | 2,65% | 436.630.000,00 |
| 57 | Empenhado sem pagamento | 2.731 | 78.595 | 3,47% | 495.230.000,00 |
| 58 | Liquidado sem pagamento | 813 | 78.595 | 1,03% | 146.670.000,00 |
| 59 | Gap empenho→pago >50% (≥ R$ 1 mi) | 145 | 6.840 | 2,12% | 671.000.000,00 |
| 62 | Salto ≥10× ano a ano | 19 | 2.190 | 0,87% | — |
| 66 | Contrato com ≥1 aditivo | 170 | 1.987 | 8,56% | — |
| 68 | Contrato assinado em dezembro | 290 | 1.987 | 14,60% | — |
| 74 | Vencedor em ≥5 certames | 29 | 887 | 3,27% | 250.000.000,00 |
| 84 | OSC com dupla porta de recebimento | 282 | 482 | 58,51% | — |

---

## 5. SEÇÃO DE DESCARTE — O QUE MORREU, E O NÚMERO QUE MATOU

Esta seção existe porque um catálogo de detecção sem lista de descarte é lista de desejos.

**5.1 — Fornecedor dominante com corte em 50% (ideia 1). Morta pelo número 35,7%.**
O filtro marca 174 de 488 órgão-ano. Um sinal que acende em mais de um terço do acervo não é sinal, é
descrição da máquina municipal — muitos órgãos são de missão única e naturalmente compram de um só
fornecedor. Sobrevive apenas o corte em 80% (84 casos, 17,2%), e ainda assim exige exclusão prévia da
modalidade 91 e do grupo 1.

**5.2 — Fornecedor único por natureza-órgão-ano (ideia 4). Morta pelo número 48,6%.**
1.724 de 3.547 combinações com mais de R$ 1 mi têm um único fornecedor. Ter um só fornecedor por
elemento de despesa dentro de um órgão é o **estado normal** do orçamento. O detector não discrimina nada.

**5.3 — Cruzamento com doação eleitoral (ideia 28). Morta pelo número 3 casos e R$ 4.661,25.**
Doação de pessoa jurídica a campanha é vedada desde 2015 (ADI 4.650), e a base reflete isso. O cruzamento
útil seria pelo sócio pessoa física — que está bloqueado porque `socios_receita.doc_socio` traz apenas
**6 dígitos mascarados em 93,8% dos casos**, enquanto `doacoes_eleitorais` traz CPF completo. Zero
correspondências não é ausência de fato: é ausência de chave.

**5.4 — Ninho de endereço (ideia 35). Morta pelo número 0 em 2.518.**
Nenhum endereço normalizado reúne 3 ou mais fornecedores do Município, e apenas 22 reúnem 2. Isto **não**
significa que não há ninhos: significa que `endereco_norm` preserva complemento e sala, de modo que
empresas no mesmo prédio recebem endereços distintos. O detector precisa ser reescrito sobre logradouro +
número, com o cuidado registrado no acervo de que **ninho é a mesma sala, não o mesmo prédio**.

**5.5 — Dispersão bruta de preço unitário (ideia 47). Morta pelos números 71,1% e 81,8%.**
Agrupando por `item_descricao` livre, 54 de 76 grupos do Município do Rio (71,1%) e 962 de 1.176 grupos da
cidade inteira (81,8%) apresentam razão máximo/mínimo igual ou superior a 3×. O que o filtro está medindo
é a heterogeneidade da descrição textual, não a variação de preço de um mesmo bem. Sem normalizador de
item, o detector produz oitenta por cento de falso positivo.

**5.6 — Concentração no elemento 39 (ideia 92). Morta pelo número 34,9% do pago.**
Serviços de terceiros — pessoa jurídica respondem por R$ 31,32 bi. Serve como estrato de amostragem;
jamais como alerta.

**5.7 — Dupla porta de recebimento das OSC (ideia 84). Morta pelo número 58,5%.**
282 de 482 entidades recebem tanto por transferência quanto por aplicação direta. É o padrão contábil
corrente, não anomalia.

**5.8 — Fornecedor de exercício único (ideia 63), na forma crua. Morta pelo número 56,5%.**
5.225 de 9.241 credores aparecem em um único exercício. Só o corte de valor (≥ R$ 10 mi, que reduz a 22
casos) transforma a hipótese em algo utilizável.

**5.9 — Aditivo acima de 25% (ideia 65). Não morreu por prevalência: morreu por dado.**
Zero casos em 1.987 contratos, porque `valor_global` replica `valor_inicial` em 100,00% dos registros.
Registrar como zero seria ler ausência de dado como fato. Fica pendente de captura do valor efetivo dos
termos aditivos.

**5.10 — Ordem de classificação ausente (ideia 76). Reclassificada.**
Os 788 itens sem `ordem_classificacao` (32,0%) são lacuna de captura do PNCP. Contar isso como achado de
irregularidade inflaria o placar com queixa de captura.

---

## 6. RECOMENDAÇÃO DE CAPTURA — POR ORDEM DE RETORNO

| Prioridade | Insumo a capturar | Quantas ideias destrava |
|---:|---|---:|
| 1 | Folha de pagamento da Prefeitura do Rio (servidores, cargos, CPF) | 19, 24 e o refino de 20–23 |
| 2 | Fundamento legal (`amparo`) e fornecedor nas licitações municipais | 11, 13, 17, 18 |
| 3 | Valor efetivo dos termos aditivos dos contratos municipais | 52, 65, 71 |
| 4 | Data e número do empenho na despesa municipal, com unidade gestora | 12, 14, 15 |
| 5 | CNAE, data de início de atividade e situação cadastral datada | 36, 37, 38 |
| 6 | Processos do SEI municipal (prova de entrega e liquidação) | 61, 64 |
| 7 | Dicionário oficial das fontes de recurso do Município | 90, 91 |
| 8 | Propostas perdedoras e ata de julgamento dos certames municipais | 73, 75, 77, 82 |

---

*Todos os valores deste documento derivam de consultas SQL executadas sobre `data/compliance.db` em
30 de agosto de 2026, em conexão somente-leitura. Nenhum número foi estimado, arredondado por conveniência
ou herdado de documento anterior. Onde o dado não existia, o documento diz que não existe.*
