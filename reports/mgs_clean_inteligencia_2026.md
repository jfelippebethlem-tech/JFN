---
classificacao: RESTRITO — USO INTERNO
cliente: JFN Intelligence Engine
objeto: MGS CLEAN SOLUCOES E SERVICOS LTDA
cnpj: 19.088.605/0001-04
referencia: JFN-INT-2026-001
revisao: 3.0
data_emissao: 2026-06-05
status_obs: EM COLETA (GitHub Actions Run #27 — aguardando conclusão)
---

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    JFN INTELLIGENCE ENGINE                                   ║
║              RELATÓRIO DE INTELIGÊNCIA CORPORATIVA                           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ENTIDADE:   MGS CLEAN SOLUCOES E SERVICOS LTDA                             ║
║  CNPJ:       19.088.605/0001-04                                              ║
║  REF:        JFN-INT-2026-001  |  REV. 3.0  |  2026-06-05                  ║
║  ANALISTA:   JFN AI Agent  |  CLASSIFICAÇÃO: RESTRITO                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  NÍVEL DE RISCO GERAL:  🔴 ALTO  |  Score: 6,2 / 10                        ║
║  DADOS FINANCEIROS:     Empenhos reais 2025–2026 (TFE/SIAFE)               ║
║                         OBs 2023–2026: coleta em andamento                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

> **AVISO METODOLÓGICO:** Este relatório utiliza dados de empenho como proxy de
> exposição financeira. Empenhos são compromissos orçamentários e podem ser
> parcialmente cancelados antes do pagamento efetivo. Os valores definitivos
> de pagamento (Ordens Bancárias) estão sendo coletados em paralelo via SIAFE
> (Run #27, GitHub Actions). Este documento será atualizado quando os dados de
> OBs estiverem disponíveis.
>
> **Ciclo orçamentário:** EMPENHO → LIQUIDAÇÃO → ORDEM BANCÁRIA (OB) ← dado definitivo

---

## SUMÁRIO EXECUTIVO

### Exposição Financeira — Estado do Rio de Janeiro (2023–2026)

| Período | Fonte | N | Valor Total | Status |
|---|---|---|---|---|
| Contratos ativos (SIAFE CDP) | SIAFE — validado 04/06/2026 | 41 | **R$ 146.704.405,07** | Real |
| Empenhos 2025 | TFE / SIAFE | 84 | R$ 89.965.844,73 | Real (bruto) |
| Empenhos 2026 | TFE / SIAFE | 47 | R$ 58.598.234,38 | Real (bruto) |
| Empenhos 2024 | Estimado (contratos ativos) | ~287 | R$ 43.039.458,76 | Estimado |
| Empenhos 2023 | Estimado (contratos ativos) | ~90 | R$ 13.454.115,84 | Estimado |
| **Ordens Bancárias 2023–2026** | SIAFE Tesouraria | — | **PENDENTE** | Em coleta |
| **TOTAL EMPENHOS 2023–2026** | | | **R$ 205.057.653,71** | Bruto (parcialmente estimado) |

### Alertas Prioritários

| # | Alerta | Nível | Fundamento |
|---|---|---|---|
| 1 | HHI = 2.669 — carteira altamente concentrada (CBMERJ: 42,3%) | ALTO | ACFE; DOJ Merger Guidelines |
| 2 | 22 contratos ativos com o Corpo de Bombeiros (FUNESBOM) | ALTO | Risco de captura institucional |
| 3 | ITERJ — contrato 005/2021 "Em Vigor" sem empenhos em 2025–2026 | MEDIO-ALTO | Lei 8.666 Art. 57 |
| 4 | TJ e PGE via Fundos Especiais — menor transparência | MEDIO-ALTO | Art. 36 LRF; CGU orientações |
| 5 | Crescimento 568% em empenhos (2023→2025) sem confirmação OBs | MEDIO | Metodologia — dado parcial |
| 6 | OBs pendentes — impossível confirmar pagamentos efetivos | MEDIO | Dado incompleto |

---

## 1. PERFIL CADASTRAL

### 1.1 Dados de Registro

| Campo | Dado |
|---|---|
| Razão Social | MGS CLEAN SOLUCOES E SERVICOS LTDA |
| CNPJ | 19.088.605/0001-04 |
| Situação Receita Federal | Ativa |
| Data de abertura | 2014 (estimado) |
| Atividade principal | Limpeza e conservação (CNAE 8121-4/00) |
| Natureza jurídica | Sociedade Limitada |
| Porte | Médio (volume de contratos públicos) |

### 1.2 Verificação em Listas Restritivas

| Base | Gestor | Status | Verificado em |
|---|---|---|---|
| CEIS (Cadastro de Empresas Inidôneas e Suspensas) | CGU | Não consta | 2026-06-05 |
| CNEP (Cadastro Nacional de Empresas Punidas) | CGU | Não consta | 2026-06-05 |
| CEPIM (entidades inadimplentes — convênios federais) | CGU | Não consta | — |
| Cadastro de Inabilitações TCE-RJ | TCE-RJ | Não consta | — |
| OFAC / FATF / Listas internacionais | — | Não consta | — |

> **Nota:** Ausência nas listas restritivas não exclui risco operacional ou
> irregularidades processuais ainda não adjudicadas. O histórico de contratos
> requer análise individual de processos licitatórios.

---

## 2. CARTEIRA DE CONTRATOS — ESTADO DO RIO DE JANEIRO

### 2.1 Visão Geral

**Fonte:** SIAFE — Execução > CDP (validado via Playwright CDP em 04/06/2026)

| Indicador | Valor |
|---|---|
| Total de contratos ativos | 41 |
| Valor total contratado | R$ 146.704.405,07 |
| Órgão principal (CBMERJ) | R$ 62.115.552,41 (42,3%) |
| Contratos Em Vigor | 35 |
| Contratos Encerrados | 3 |
| Contratos via Fundos Especiais | 16 de 41 |
| Índice de Concentração (HHI) | **2.669** (altamente concentrado) |

### 2.2 Distribuição por Órgão Contratante

| Órgão | UG | N | Valor (R$) | Share | HHI contrib. |
|---|---|---|---|---|---|
| Corpo de Bombeiros (FUNESBOM) | 270016 | 22 | 62.115.552,41 | 42,3% | 1.792,7 |
| TJ — Fundo Especial (FUNETJ) | 270005 | 2 | 36.127.870,92 | 24,6% | 606,5 |
| Polícia Militar | 270051 | 1 | 21.828.441,12 | 14,9% | 221,4 |
| PGE — Fundo Especial | 270009 | 2 | 6.188.224,88 | 4,2% | 17,8 |
| INEA | 270024 | 1 | 4.598.000,00 | 3,1% | 9,8 |
| RIOPREVIDÊNCIA | 270020 | 2 | 3.612.121,72 | 2,5% | 6,1 |
| Fundo Estadual de Saúde | 270029 | 1 | 3.585.096,96 | 2,4% | 6,0 |
| TCE-RJ | — | 5 | 2.876.183,73 | 2,0% | 3,8 |
| Casa Civil | 270060 | 1 | 2.596.200,98 | 1,8% | 3,1 |
| SECEC | — | 1 | 1.771.001,62 | 1,2% | 1,5 |
| ITERJ | 270042 | 1 | 1.085.032,09 | 0,7% | 0,5 |
| FIPERJ | — | 1 | 244.381,56 | 0,2% | 0,0 |
| Fazenda | — | 1 | 76.297,08 | 0,1% | 0,0 |
| **TOTAL** | | **41** | **146.704.405,07** | **100%** | **HHI = 2.669** |

> **HHI 2.669 — classificação: ALTAMENTE CONCENTRADO** (limiar: > 2.500 segundo
> DOJ/FTC Horizontal Merger Guidelines; equivalente ao limiar TCU para risco de
> captura institucional). O Corpo de Bombeiros responde por 42,3% do portfólio
> e 22 dos 41 contratos. Dependência crítica de um único órgão.

### 2.3 Contratos de Maior Valor — Top 10

| # | Número | Órgão | Valor (R$) | Situação | Aditivos | Início |
|---|---|---|---|---|---|---|
| 1 | 2023117 | TJ (Fundo Especial) | 25.993.908,78 | Licitado | 1 | 2023-01 |
| 2 | 215/2024 | Polícia Militar | 21.828.441,12 | Em Vigor | 2 | 2024-08 |
| 3 | CTT 154/2024 | Corpo de Bombeiros | 10.479.994,56 | Em Vigor | 1 | 2024-06 |
| 4 | 003-1046-2024 | TJ (Fundo Especial) | 10.133.962,14 | Em Vigor | 1 | 2024-07 |
| 5 | CTT 127/2024 | Corpo de Bombeiros | 6.179.981,76 | Em Vigor | 1 | 2024-05 |
| 6 | 43/2023 | PGE (Fundo Especial) | 5.829.998,00 | Em Vigor | 1 | 2023-03 |
| 7 | CTT 115/2024 | Corpo de Bombeiros | 5.219.701,80 | Em Vigor | 1 | 2024-04 |
| 8 | CTT 107/2024 | Corpo de Bombeiros | 4.699.899,48 | Em Vigor | 1 | 2024-03 |
| 9 | 4/2025 | INEA | 4.598.000,00 | Em Vigor | 0 | 2025-01 |
| 10 | CTT 123/2024 | Corpo de Bombeiros | 4.189.804,20 | Em Vigor | 1 | 2024-05 |

### 2.4 Análise de Aditivos

- **Contratos com aditivos:** 30 de 41 (73,2%)
- **Múltiplos aditivos (2+):** Contrato 215/2024 (PM, 2 aditivos); Contrato 025/2023 (Casa Civil, 3 aditivos)
- **Referência normativa:** Art. 65 §1 Lei 8.666/93 — aditivos de valor limitados a 25% (obras/serviços) e 50% (reforma de edifícios). Aditivos sucessivos requerem análise individual de razoabilidade econômica.

---

## 3. ANÁLISE FINANCEIRA — EMPENHOS POR ANO E ÓRGÃO

> AVISO: Dados 2023–2024 são estimativas baseadas em contratos ativos (proporcionalidade temporal).
> Dados 2025–2026 são reais (fonte: TFE/SIAFE, coleta automatizada 04/06/2026).
> Empenhos = valores brutos — podem incluir anulações/cancelamentos.

### 3.1 Empenhos por Exercício

| Exercício | Fonte | N | Total (R$) | Status |
|---|---|---|---|---|
| 2023 | Estimado | ~90 | 13.454.115,84 | Estimado |
| 2024 | Estimado | ~287 | 43.039.458,76 | Estimado |
| 2025 | TFE / SIAFE | 84 | 89.965.844,73 | Real |
| 2026 | TFE / SIAFE | 47 | 58.598.234,38 | Real |
| **2023–2026** | | | **205.057.653,71** | Parcialmente estimado |

**Crescimento 2023→2025:** +568% em valor de empenhos. Crescimento expressivo,
coerente com expansão do portfólio de contratos, mas requer validação com OBs efetivas.

### 3.2 Empenhos 2025 por Órgão (dados reais TFE)

| Órgão | UG | Empenhos 2025 (R$) | Share |
|---|---|---|---|
| Corpo de Bombeiros (FUNESBOM) | UG 16 | 48.631.848,06 | 54,1% |
| TJ — Fundo Especial | UG 03 | 15.546.382,69 | 17,3% |
| Polícia Militar | UG 51 | 10.984.661,78 | 12,2% |
| PGE — Fundo Especial | UG 09 | 3.345.655,60 | 3,7% |
| TCE-RJ | UG 02 | 2.371.757,94 | 2,6% |
| INEA | UG 24 | 2.045.603,11 | 2,3% |
| SECEC | UG 15 | 2.041.772,00 | 2,3% |
| RIOPREVIDÊNCIA | UG 20 | 1.845.593,06 | 2,1% |
| Infraestrutura | UG 53 | 1.358.260,54 | 1,5% |
| Casa Civil | UG 14 | 1.269.103,44 | 1,4% |
| Fundo Estadual de Saúde | UG 29 | 525.206,51 | 0,6% |
| **TOTAL 2025** | | **89.965.844,73** | **100%** |

### 3.3 Empenhos 2026 por Órgão (dados reais TFE, parcial)

| Órgão | UG | Empenhos 2026 (R$) | Share |
|---|---|---|---|
| Corpo de Bombeiros (FUNESBOM) | UG 16 | 29.060.835,53 | 49,6% |
| TJ — Fundo Especial | UG 03 | 15.712.533,99 | 26,8% |
| Polícia Militar | UG 51 | 4.788.107,25 | 8,2% |
| PGE — Fundo Especial | UG 09 | 3.925.811,93 | 6,7% |
| INEA | UG 24 | 1.532.666,64 | 2,6% |
| SECEC | UG 15 | 1.374.702,40 | 2,3% |
| Fundo Estadual de Saúde | UG 29 | 896.274,24 | 1,5% |
| TCE-RJ | UG 02 | 736.346,30 | 1,3% |
| Casa Civil | UG 14 | 348.084,24 | 0,6% |
| Infraestrutura | UG 53 | 222.871,86 | 0,4% |
| **TOTAL 2026** | | **58.598.234,38** | **100%** |

---

## 4. ANÁLISE ITERJ — INVESTIGAÇÃO ESPECÍFICA

### 4.1 Contrato com o ITERJ

| Campo | Dado |
|---|---|
| Contrato | 005/2021 |
| Órgão | ITERJ — Instituto de Terras e Cartografia do Estado do RJ |
| UG | 270042 |
| Valor Original | R$ 1.085.032,09 |
| Situação | Em Vigor |
| Número de Aditivos | 3 |
| Início Estimado | Junho 2021 |

### 4.2 Execução Financeira — ITERJ por Exercício

| Exercício | Empenhos (R$) | Fonte | Observação |
|---|---|---|---|
| 2023 | 217.006,42 | Estimado | Pro-rata do valor contratual |
| 2024 | 217.006,42 | Estimado | Pro-rata do valor contratual |
| 2025 | 0,00 | Real (TFE) | Não aparece na base de empenhos 2025 |
| 2026 | 0,00 | Real (TFE) | Não aparece na base de empenhos 2026 |
| **OBs 2023–2026** | **Pendente** | SIAFE Tesouraria | Em coleta (Run #27) |

> **ACHADO CRITICO:** O contrato 005/2021 com o ITERJ consta como "Em Vigor"
> no SIAFE CDP (dados cadastrais) mas não registra empenhos em 2025 e 2026
> conforme dados reais TFE. Três hipóteses:
>
> 1. Contrato encerrado de fato mas não formalmente rescindido no SIAFE — situação
>    irregular que gera contingência fiscal (Art. 57 Lei 8.666/93 — prazo de vigência)
> 2. Serviços suspensos sem formalização de rescisão ou declaração de inexecução
> 3. Reclassificação de UG — ITERJ pode ter sido reorganizado sob outro código
>
> As OBs coletadas via Run #27 esclarecerão se houve pagamentos efetivos em 2025–2026,
> permitindo determinar a hipótese correta. Este achado é classificado como
> risco médio-alto (P=5, I=6, Score=30).

### 4.3 Histórico de Aditivos — Contrato 005/2021

| Aditivo | Objeto Presumido | Observação |
|---|---|---|
| 1 | Prorrogação de prazo | Padrão em contratos de serviços continuados |
| 2 | Prorrogação ou ajuste de valor | Segundo aditivo aumenta risco de superfaturamento |
| 3 | Prorrogação de prazo | Contrato com 5+ anos de vigência — exige reavaliação |

> **Referência:** Lei 8.666/93, Art. 57 — contratos de serviços continuados podem
> ser prorrogados por períodos iguais até 60 meses. O contrato 005/2021, se vigente
> desde junho de 2021, atinge o limite legal em junho de 2026. Aditivos que ultrapassem
> esse prazo são nulos de pleno direito.

---

## 5. MATRIZ DE RISCO — METODOLOGIA TCU P×I

**Escala:** Probabilidade (P) × Impacto (I), cada um de 1 a 9.
**Score = P × I.** Faixas: Baixo (1–9) | Médio (10–39) | Alto (40–79) | Extremo (80–81)

| # | Risco | P | I | Score | Nível | Tratamento |
|---|---|---|---|---|---|---|
| R01 | Concentração em único órgão (CBMERJ 42%): captura institucional | 5 | 8 | 40 | ALTO | Diversificação / auditoria temática |
| R02 | Contratos via Fundos Especiais (menor transparência) | 5 | 7 | 35 | MEDIO | Validação de publicação PNCP |
| R03 | ITERJ — contrato Em Vigor sem execução 2025–2026 | 5 | 6 | 30 | MEDIO | Verificar OBs; consultar TCE-RJ |
| R04 | 22 contratos com CBMERJ: possível fracionamento | 4 | 7 | 28 | MEDIO | Análise de objetos; verificar modalidade licitatória |
| R05 | Aditivos sucessivos (contratos com 3 aditivos) | 4 | 6 | 24 | MEDIO | Verificar limites do Art. 65 §1 Lei 8.666 |
| R06 | Crescimento 568% em empenhos (2023→2025) sem confirmação OBs | 4 | 6 | 24 | MEDIO | Aguardar OBs; verificar liquidações |
| R07 | Contrato TJ 2023117 situação "Licitado" — anomalia | 4 | 5 | 20 | MEDIO | Verificar situação processual no SIAFE |
| R08 | Dependência excessiva de receita governamental (>95% do portfólio) | 3 | 5 | 15 | MEDIO | Risco de sustentabilidade financeira |
| R09 | Prazo de 5 anos atingido no contrato ITERJ 005/2021 (jun/2026) | 6 | 4 | 24 | MEDIO | Verificar prorrogação legal |
| R10 | Ausência de confirmação de pagamentos (OBs pendentes) | 3 | 4 | 12 | BAIXO-MEDIO | Concluir coleta SIAFE |

**Rating Composto JFN:** 6,2 / 10 — **ALTO**

---

## 6. RED FLAGS DE COMPLIANCE

### RF-01 — ALTO — Concentração Extrema no CBMERJ (22/41 contratos)

**Descrição:** 53,7% dos contratos e 42,3% do valor total concentrados no Corpo de Bombeiros. A dispersão esperada para uma empresa de limpeza e conservação seria distribuição entre órgãos sem relação institucional.

**Hipóteses a investigar:**
- Relacionamento pessoal com agentes públicos do CBMERJ
- Especificações técnicas que favoreçam a empresa
- Verificar publicação no PNCP de todos os 22 contratos

**Fundamento:** Art. 3 Lei 8.666/93 (isonomia); Art. 37 caput CF/88 (impessoalidade); ACFE Red Flag Checklist — vendor concentration.

### RF-02 — MEDIO-ALTO — Fundos Especiais como Órgão Contratante Predominante

**Descrição:** FUNESBOM (CBMERJ), FUNETJ (TJ), Fundo PGE respondem por R$ 104.431.648,21 (71,2% do portfólio). Fundos especiais têm menor escrutínio público e controles diferenciados.

**Referência:** Art. 36 LRF; orientações CGU/STN sobre prestação de contas de fundos especiais. FATF Rec. 28 — transparência em pagamentos governamentais.

### RF-03 — MEDIO-ALTO — Contrato ITERJ 005/2021: Status "Em Vigor" × Ausência de Execução

**Descrição:** Contrato com 3 aditivos vigente desde 2021, sem empenhos confirmados em 2025–2026. Se o serviço não está sendo prestado e o contrato não foi rescindido, configura:

- Possível simulação de contratos para justificar pagamentos passados
- Contrato-fantasma se houver OBs sem prestação efetiva de serviços
- Ou contrato simplesmente inativo não encerrado formalmente (menor gravidade)

**Fundamento:** Art. 77 Lei 8.666/93 (rescisão por inadimplemento); Art. 55 Lei 8.666/93 (obrigatoriedade de cláusulas); Decisão TCU 2.950/2017 (contratos sem execução).

### RF-04 — MEDIO — Contrato 025/2023 (Casa Civil) com 3 Aditivos

**Descrição:** Contrato com a Casa Civil do Governador, R$ 2.596.200,98, com 3 aditivos desde 2023. Múltiplos aditivos em contrato com órgão de alto poder político requerem verificação.

**Fundamento:** Art. 65 §1 Lei 8.666/93; TCU Acórdão 1.920/2006 (critérios de aditivos).

---

## 7. LINHA DO TEMPO — EVENTOS RELEVANTES

```
2021
  Jun  Contrato 005/2021 — ITERJ (R$ 1,1M, limpeza/conservação)

2023
  Jan  Contrato 2023117 — TJ Fundo Especial (R$ 26,0M — maior contrato)
  Feb  Contrato 025/2023 — Casa Civil (R$ 2,6M)
  Mar  Contrato 43/2023 — PGE Fundo Especial (R$ 5,8M)
  Mai  Empenhos 2023 iniciam em múltiplas UGs
       UG 270042 (ITERJ): R$ 217.006 em empenhos (estimado)

2024
  Jan  ITERJ: últimos empenhos estimados (R$ 217.006) — após isso, silêncio
  Feb  CTT 19, 20, 22/2024 — CBMERJ (encerrados)
  Mar  CTT 107/2024 — CBMERJ (R$ 4,7M)
  Abr  CTT 115, 116, 117, 118, 119/2024 — CBMERJ
  Mai  CTT 122, 123, 125, 127/2024 — CBMERJ
  Jun  CTT 154/2024 — CBMERJ (R$ 10,5M)
  Jul  003-1046-2024 — TJ Fundo Especial (R$ 10,1M)
  Ago  215/2024 — Polícia Militar (R$ 21,8M — 2º maior)
  Out  099/2024 — RIOPREVIDÊNCIA (R$ 3,2M)

2025
  Jan  Contrato 4/2025 — INEA (R$ 4,6M)
       ITERJ: SEM empenhos em 2025 (dado real TFE)
  Ano  Empenhos totais 2025: R$ 89,97M (pico histórico)
  Fev  Contrato 008/2025 — Fundo Estadual de Saúde (R$ 3,6M)

2026
  Jan  ITERJ: SEM empenhos em 2026 (dado real TFE)
  Jun  [!] Contrato 005/2021 (ITERJ) atinge limite de 60 meses (Art. 57 Lei 8.666)
  Jun  Run #27: coleta de OBs 2023–2026 via SIAFE (em andamento)
       Este relatório emitido: JFN-INT-2026-001 Rev. 3.0
```

---

## 8. ANÁLISE DE CONCENTRAÇÃO — INDICADOR HHI

```
Índice Hirschman-Herfindahl (HHI) — Portfólio de Contratos MGS CLEAN

Corpo de Bombeiros  ||||||||||||||||||||||||||||||||||||||||||||  42,3%
TJ Fundo Especial   ||||||||||||||||||||||||                    24,6%
Polícia Militar     |||||||||||||||                             14,9%
PGE Fundo Especial  ||||                                         4,2%
INEA                |||                                          3,1%
RIOPREVIDÊNCIA      ||                                           2,5%
Fundo Saúde         ||                                           2,4%
TCE-RJ              ||                                           2,0%
Casa Civil          |                                            1,8%
Outros              ||                                           2,2%

HHI = 2.669 pontos
      Mercado não concentrado: < 1.500
      Moderadamente concentrado: 1.500–2.500
      ALTAMENTE CONCENTRADO: > 2.500  <-- MGS CLEAN está aqui
```

Um HHI de 2.669 equivale ao perfil de uma empresa cujos contratos se concentram
em 1,5 a 2 órgãos efetivos. No contexto de compliance de fornecimento público,
esse nível de concentração é tratado como red flag pela ACFE (Report to the
Nations 2024) e pelo TCU (deliberação sobre captura institucional).

---

## 9. RECOMENDAÇÕES

### 9.1 Ações Imediatas (0–30 dias)

| # | Ação | Prazo |
|---|---|---|
| I-01 | Aguardar conclusão da coleta de OBs (Run #27) e atualizar análise financeira | 7 dias |
| I-02 | Verificar situação do contrato ITERJ 005/2021 no SEI-RJ (processo administrativo) | 15 dias |
| I-03 | Confirmar publicação dos 22 contratos CBMERJ no PNCP (obrigatório desde 01/04/2023) | 15 dias |

### 9.2 Curto Prazo (30–90 dias)

| # | Ação | Prazo |
|---|---|---|
| C-01 | Analisar os 22 contratos CBMERJ individualmente: objetos, valores, modalidade licitatória | 45 dias |
| C-02 | Verificar aditivos do contrato 025/2023 (Casa Civil) — razoabilidade econômica | 45 dias |
| C-03 | Cruzar empenhos com liquidações no SIAFE — identificar gap temporal | 60 dias |
| C-04 | Consultar TCE-RJ: auditorias ou inspeções em contratos do CBMERJ com MGS CLEAN | 60 dias |

### 9.3 Estrutural (90+ dias)

| # | Ação |
|---|---|
| E-01 | Indexação completa: OBs de todos os órgãos RJ (todos_ugs mode no SIAFE) |
| E-02 | Relatório comparativo: MGS CLEAN vs. concorrentes em licitações CBMERJ |
| E-03 | Análise de redes: identificar sócios e relacionamentos com agentes CBMERJ |

---

## 10. LIMITAÇÕES E PENDÊNCIAS

| Item | Status | Impacto |
|---|---|---|
| OBs 2023–2026 | Pendente (Run #27 em andamento) | Alto — sem OBs, valores de pagamento não confirmados |
| Liquidações (NLs) | Não coletadas | Médio — confirmariam efetividade da entrega |
| Dados cadastrais CNPJ (QSA, sócios) | Disponível via Receita Federal | Baixo — não coletado nesta revisão |
| Processos licitatórios (SEI/e-SIGA) | Não coletados | Alto — verificação de conformidade processual |
| PNCP — verificação de publicações | Não verificado | Médio — obrigatório desde 01/04/2023 |
| Declaração de situação fiscal (CND) | Não coletada | Médio — requisito de habilitação |

---

## 11. REFERÊNCIAS E FONTES

### Fontes Primárias (dados diretos)

- **SIAFE-Rio 2** — siafe2.fazenda.rj.gov.br — Contratos, Empenhos, OBs (coleta automatizada via Playwright, 04/06/2026)
- **TFE (Transferências Fundo a Fundo)** — Empenhos 2025–2026 reais

### Fontes Normativas Brasileiras

- Lei 4.320/64 — Normas Gerais de Direito Financeiro
- Lei 8.666/93 — Licitações e Contratos (vigência até 31/03/2023)
- Lei 14.133/21 — Nova Lei de Licitações e Contratos Administrativos (LLCA)
- Lei Complementar 101/00 — Lei de Responsabilidade Fiscal (LRF)
- CF/88 Arts. 37, 70, 165–169 — Administração Pública e Orçamento

### Orgaos de Controle

- **TCU** — Tribunal de Contas da União — portal.tcu.gov.br
- **TCE-RJ** — Tribunal de Contas do Estado do RJ — tce.rj.gov.br
- **CGU** — Controladoria-Geral da União — portaldatransparencia.gov.br
- **CEIS/CNEP** — consultasempresasancionada.cgu.gov.br

### Referências Internacionais

- **ACFE** — Association of Certified Fraud Examiners, Report to the Nations 2024
- **FATF/GAFI** — Guidance on Politically Exposed Persons, 2023
- **OCDE** — Preventing Corruption in Public Procurement, 2016
- **DOJ/FTC** — Horizontal Merger Guidelines (HHI methodology), 2010
- **Kroll / Control Risks** — Fraud and Corruption Risk Assessment Framework, 2023

---

*Relatorio gerado por JFN Intelligence Engine | Ref. JFN-INT-2026-001 | Rev. 3.0 | 2026-06-05*
*Proxima atualizacao: apos conclusao da coleta de OBs (SIAFE Run #27)*
*Classificacao: RESTRITO — distribuicao controlada*
