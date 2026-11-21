# PARECER REFERÊNCIA — SNAPSHOT ENGENHARIA E SERVICOS LTDA
### Avaliação jurídica, financeira, contábil e de integridade de contratação e pagamentos

*Instrução preliminar de controle externo (TCE-RJ) — camada determinística + camada subjetiva*

**CNPJ:** 11.222.333/0001-81  |  **Data:** 2026-07-06  |  **Analista:** Controle Externo (automatizado)
**Classificação (modelo CGE-RJ — Decreto 47.408/2020):** Nota Técnica **COM Achado**.
**Grau de atenção:** 🔴 **VERMELHO** · índice 67/100 — convergência de 3+ indícios, ao menos um grave — recomenda-se controle externo.
**Base de pagamentos:** SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · coleta mais recente das OB do alvo: 2026-07-05 10:00:00.

---

## 1. SUMÁRIO EXECUTIVO

- **Grau consolidado:** 🔴 **VERMELHO** · índice de atenção **67/100** — 8 indício(s) em 3 eixo(s) — Financeiro (2), Contábil (3), Compliance / integridade (3); gravidade máxima 4/5. Indício ≠ acusação; vigora a presunção de legitimidade.
- **Fatos mais relevantes (camada determinística):**
  - Total pago (OB SIAFE, valor > 0): **R$ 4.620.000,00** — fonte SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO.
  - Maior UG pagadora: **ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100) — R$ 2.820.000,00 (61,0%)** — fonte SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO.
  - Pago ÷ capital social: **462×** — fonte Receita Federal · cadastro CNPJ (enriquecimento do contexto) × SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO.
  - Indício **R8** (Concentração de fornecedor / risco de captura (bid rigging), grav. 4/5): 61,0% do valor pago concentrado em um único órgão (ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100)) — concentração extrema para um prestador de serviços. Fonte: SIAFE · ob_orcamentaria_siafe (régua _ob_paga)…
  - Indício **F-ESCALADA** (Escalada abrupta do valor pago entre exercícios, grav. 3/5): Crescimento abrupto dos pagamentos de R$ 300.000,00 (2024) para R$ 4.200.000,00 (2025) — +1.300% (primeiro × último exercício completo com pagamento). Fora da comparação, por incompletos: 2023 (ano de início da relação).…
  - Indício **DD/H-CAPITAL** (Capital social ínfimo frente ao recebido, grav. 3/5): Capital social ínfimo frente ao recebido. Capital social declarado de R$ 10.000,00 contra R$ 4.620.000,00 recebidos do Estado (462× o capital). Capital irrisório frente a contratos vultosos é indício de subcapitalização…
- **Não verificado (lacunas declaradas):** liquidação: só 54,5% do pago tem a NL na base (R$ 2.100.000,00 sem NL ingerida); 2 OB(s) (R$ 2.100.000,00) sem nº de processo SEI reconhecível na cadeia OB→NL→NE; íntegra dos processos SEI não lida nesta execução (vícios de planejamento, edital e julgamento não examinados); nenhum contrato do fornecedor na base de Dados Abertos do TCE-RJ (valor contratado e aditivos não confrontados com o pago); due diligence sem fonte para: endereco residencial, geocode, foto sede, porte, pep, beneficio social, site.
- **Diligências prioritárias:**
  - Processo **SEI-330020/000123/2023** (R$ 2.520.000,00 pagos em 2 OB, UG 133100): ler a íntegra (contrato, aditivos, medições/atestos e notas fiscais).
  - Indício **R8** — teste discriminante: atas dos certames: nº de propostas VÁLIDAS, cascata de desclassificações e QSA/endereços dos derrotados (derrotado-fantasma que nunca vence em lugar nenhum = cartel de cobertura).
  - Indício **F-ESCALADA** — teste discriminante: contratos e aditivos vigentes em cada exercício (valor e data) × pago por exercício; inscrição em restos a pagar das OBs do ano do salto.
  - Indício **DD/H-CAPITAL** — teste discriminante: verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED).

## 2. OBJETO, ESCOPO E METODOLOGIA

Avalia-se a relação do fornecedor com a Administração estadual em quatro eixos — **financeiro**, **contábil**, **jurídico** e **compliance/integridade** — instruídos no formato de **tribunal de contas** (seção 8). Cada eixo declara o critério normativo, examina os fatos e conclui com grau próprio; o grau consolidado (seção 10) é derivado dos eixos.

**Duas camadas, separadas:**

- **Determinística** (seções 3 a 8): só o que o código prova contra a fonte primária. Todo número traz fonte e estado — **VERIFICADO** (lido da fonte primária por código), **PENDENTE** (piso ou cobertura parcial, a conferir) ou **INDISPONÍVEL** (fonte não lida — INDISPONÍVEL ≠ 0). Pagamento é só a **OB paga do SIAFE** (régua `_ob_paga`); empenho ≠ liquidação ≠ pagamento; o espelho TFE não é usado como pago.
- **Subjetiva** (seção 9): juízo raciocinado do Claude Opus pela assinatura, marcado como OPINIÃO; não altera fato nem grau — no máximo recomenda diligência.

**Régua do grau:** 🟢 sem indício; 🟡 indício isolado ou pontual; 🔴 convergência de 3+ indícios com ao menos um grave (≥ 4/5); ⚪ sem base para graduar. O índice de atenção (0-100) é a soma dos P×I da matriz de risco (seção 8.4) — escala interna de priorização, não juízo de irregularidade.

## 3. BASE DE FATOS (camada determinística)

### 3.1 Identificação

- **Fornecedor:** SNAPSHOT ENGENHARIA E SERVICOS LTDA — CNPJ 11.222.333/0001-81 (raiz 11222333: matriz e filiais consolidadas)
- **Endereço cadastral:** não informado no cadastro
- **Porte:** não informado · **CNAE:** Comércio varejista de artigos do vestuário e acessórios
- **Quadro societário (QSA):** FULANO SNAPSHOT, entrada 2024-06-01 — documentos de pessoa física não são exibidos (LGPD).

### 3.2 Quadro de fatos (fonte única por fato)

*Cada número do parecer remete a esta tabela; as seções seguintes não consultam outra fonte para o mesmo fato.*

| Fato | Valor | Fonte (tabela/consulta) | Estado |
|---|---|---|---|
| Total pago (OB SIAFE, valor > 0) | R$ 4.620.000,00 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Nº de OBs pagas | 4 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Janela das OBs pagas | 2023-03-10 a 2025-08-20 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Órgãos (UG) pagadores | 2 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Maior UG pagadora | ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100) — R$ 2.820.000,00 (61,0%) | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Concentração por órgão (HHI) | 5243,7 (ALTA) | derivado de SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| OB de valor zero (regularização) | 3 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| OB registradas e NÃO pagas (fora da régua) | 2 — R$ 2.450.000,00 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Pago com NL localizada na base | 54,5% do valor (50,0% das OBs) | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) × SIAFE · nl_siafe (notas de liquidação) — ingestão de NL parcial | **PENDENTE** |
| Liquidado (NL contabilizadas do credor) — piso | R$ 2.420.000,00 em 2 NL | SIAFE · nl_siafe (notas de liquidação) — piso: ingestão parcial | **PENDENTE** |
| Retido na liquidação (NL) — piso | R$ 121.000,00 | SIAFE · nl_siafe (notas de liquidação) — retenções por tipo não ingeridas | **PENDENTE** |
| Empenhado (NE contabilizadas do credor) — piso | R$ 2.650.000,00 em 2 NE | SIAFE · ne_siafe (notas de empenho) — piso: ingestão parcial | **PENDENTE** |
| Processos SEI identificados (nº na OB; na falta, na NL ou NE que ela cita) | 1 — R$ 2.520.000,00 (54,5% do pago) | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) × NL × NE — o restante não traz nº de processo reconhecível | **PENDENTE** |
| Última coleta das OBs do alvo | 2026-07-05 10:00:00 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Abertura do CNPJ | 2022-11-01 | Receita Federal · cadastro CNPJ (enriquecimento do contexto) | **VERIFICADO** |
| Capital social | R$ 10.000,00 | Receita Federal · cadastro CNPJ (enriquecimento do contexto) | **VERIFICADO** |
| Situação cadastral | ATIVA | Receita Federal · cadastro CNPJ (enriquecimento do contexto) | **VERIFICADO** |
| Atividade principal (CNAE) | Comércio varejista de artigos do vestuário e acessórios | Receita Federal · cadastro CNPJ (enriquecimento do contexto) | **VERIFICADO** |
| Sócios/administradores no QSA | 1 | Receita Federal · cadastro CNPJ (enriquecimento do contexto) | **VERIFICADO** |
| Idade do CNPJ na 1ª OB paga | 0,4 ano(s) (2022-11-01 → 2023-03-10) | Receita Federal · cadastro CNPJ (enriquecimento do contexto) × SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |
| Pago ÷ capital social | 462× | Receita Federal · cadastro CNPJ (enriquecimento do contexto) × SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |

### 3.3 Mapa de cobertura (verificado × pendente × indisponível)

| Eixo | Item | Estado | Fonte / observação |
|---|---|---|---|
| Financeiro | OB paga (régua _ob_paga) | **VERIFICADO** | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) |
| Financeiro | Empenho (NE) | **PENDENTE** | piso — ingestão parcial de ne_siafe |
| Financeiro | Liquidação (NL) por OB | **PENDENTE** | 54,5% do pago com NL na base |
| Financeiro | Sazonalidade, cadência e concentração | **VERIFICADO** | derivadas da mesma série de OB paga |
| Contábil | OB não paga (cancelada, devolvida, complementar, reemitida) | **VERIFICADO** | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) |
| Contábil | Pago × liquidado na mesma NL; OB × data da NL | **PENDENTE** | só onde a NL está na base |
| Contábil | Retenções na liquidação | **PENDENTE** | valor retido da NL (piso); tipo de retenção não ingerido |
| Contábil | Benford / valores redondos | **VERIFICADO** | régua descritiva; Benford exige n ≥ 100 |
| Jurídico | Contratos e compras diretas (TCE-RJ Dados Abertos) | **PENDENTE** | 0 contrato(s), 0 compra(s) direta(s) |
| Jurídico | Íntegra dos processos SEI (edital, TR, atas, pareceres) | **INDISPONÍVEL** | leitura não executada |
| Jurídico | Acervo SEI da casa (fases documentadas por processo) | **PENDENTE** | manifesto de data/sei_arquivo dos maiores processos |
| Jurídico | Padrões da casa por processo | **INDISPONÍVEL** | 0 padrão(ões) lido(s) |
| Compliance | Due diligence — endereco residencial | **INDISPONÍVEL** | INDISPONIVEL (endereço não ingerido) |
| Compliance | Due diligence — geocode | **INDISPONÍVEL** | INDISPONIVEL |
| Compliance | Due diligence — foto sede | **INDISPONÍVEL** | INDISPONIVEL (sem foto classificada) |
| Compliance | Due diligence — coendereco | **VERIFICADO** | verificado (nenhum) |
| Compliance | Due diligence — capital | **VERIFICADO** | verificado |
| Compliance | Due diligence — recencia | **VERIFICADO** | verificado |
| Compliance | Due diligence — situacao cadastral | **VERIFICADO** | verificado |
| Compliance | Due diligence — porte | **INDISPONÍVEL** | INDISPONIVEL |
| Compliance | Due diligence — pep | **INDISPONÍVEL** | INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY) |
| Compliance | Due diligence — beneficio social | **INDISPONÍVEL** | INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY) |
| Compliance | Due diligence — site | **INDISPONÍVEL** | INDISPONIVEL (sem e-mail de domínio próprio na Receita) |
| Compliance | Sanções no registro estadual (SIGA) | **VERIFICADO** | consultado |
| Compliance | Cadastro MTE (trabalho escravo) | **VERIFICADO** | consultado |
| Compliance | Sócio na folha pública | **VERIFICADO** | consultado |
| Compliance | Termos de ajuste de contas (D.O.) | **VERIFICADO** | consultado |

## 4. EIXO FINANCEIRO — execução da despesa

### 4.1 Critério normativo

Lei 4.320/64: o **empenho** reserva a dotação e cria a obrigação de pagamento pendente de implemento (art. 58), vedada a despesa sem prévio empenho (art. 60); a **liquidação** verifica o direito do credor à vista dos comprovantes da entrega (art. 63); o **pagamento** só ocorre após a regular liquidação (art. 62), por ordem de pagamento (art. 64). Só a **OB paga** prova o desembolso — empenho ≠ liquidação ≠ pagamento.

### 4.2 Empenhado × liquidado × pago

| Estágio | Valor (R$) | Documentos | Fonte | Estado |
|---|---:|---:|---|---|
| Empenhado (NE contabilizadas) | 2.650.000,00 | 2 | SIAFE · ne_siafe (notas de empenho) | **PENDENTE** (piso) |
| Liquidado (NL contabilizadas) | 2.420.000,00 | 2 | SIAFE · nl_siafe (notas de liquidação) | **PENDENTE** (piso) |
| **Pago (OB SIAFE, régua _ob_paga)** | **4.620.000,00** | 4 | SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | **VERIFICADO** |

> **Leitura honesta:** 54,5% do valor pago (50,0% das OBs) tem a NL citada presente na base; R$ 2.100.000,00 foram pagos por OBs cuja NL não foi ingerida. Por isso empenhado e liquidado são **piso** e não se comparam ao pago como totais — a comparação homogênea (mesma NL nas duas pontas) está no eixo contábil (5.2).

### 4.3 Pagamento por exercício e sazonalidade

*Ano = data da OB. A soma das linhas fecha com o total pago do quadro de fatos.*

| Ano | jan | fev | mar | abr | mai | jun | jul | ago | set | out | nov | dez | OBs | Total (R$) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023 | — | — | **120,00k** | — | — | — | — | — | — | — | — | — | 1 | 120.000,00 |
| 2024 | — | — | — | — | — | **300,00k** | — | — | — | — | — | — | 1 | 300.000,00 |
| 2025 | — | **2.400,00k** | — | — | — | — | — | **1.800,00k** | — | — | — | — | 2 | 4.200.000,00 |
| **Total** |  |  |  |  |  |  |  |  |  |  |  |  | **4** | **4.620.000,00** |

*Células em negrito concentram ≥ 25% do ano. Dezembro responde por 0,0% do pago (concentração de fim de exercício pede conferência do atesto das OBs de dezembro — art. 63 da Lei 4.320/64; aqui é régua descritiva, não indício).*

### 4.4 Cadência e concentração por órgão

| Órgão (UG) | OBs | Total (R$) | % do pago | Meses ativos | Média/mês ativo (R$) | Maior OB (R$) | Janela |
|---|---:|---:|---:|---:|---:|---:|---|
| ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100) | 3 | 2.820.000,00 | 61,0% | 3 | 940.000,00 | 2.400.000,00 | 2023-03→2025-02 |
| DETRAN-RJ — Departamento de Trânsito do Estado do Rio de Jan | 1 | 1.800.000,00 | 39,0% | 1 | 1.800.000,00 | 1.800.000,00 | 2025-08→2025-08 |

*HHI 5243,7 (ALTA); maior órgão com 61,0% do pago. A régua do indício R8 é ≥ 40% num único órgão (≥ 60% = extrema).*

### 4.5 Processos: cadeia empenho → liquidação → pagamento

*Processo identificado pelo SIAFE: o nº gravado na OB ou, na falta, o da NL que ela cita ou o da NE dessa NL. NL e NE «0» = não ingeridas na base, não ausentes no SIAFE. A coluna «Acervo» diz o que o arquivo SEI da casa tem do processo; fase ausente = documento a requisitar (lacuna, não irregularidade).*

| Processo | UG | OBs | Pago (R$) | 1ª/última OB | NL | Liquidado (R$) | NE | Empenhado (R$) | Acervo SEI |
|---|---|---:|---:|---|---:|---:|---:|---:|---|
| SEI-330020/000123/2023 | 133100 | 2 | 2.520.000,00 | 2023-03-10/2025-02-15 | 2 | 2.420.000,00 | 2 | 2.650.000,00 | processo não capturado no acervo SEI da casa |
| (processo não identificado na cadeia OB→NL→NE) | 133100, 263100 | 2 | 2.100.000,00 | 2024-06-12/2025-08-20 | 0 | — | 0 | — | não consultado |

*2 grupo(s) de processo; os 20 maiores somam 100,0% do pago. NL/NE «—» = não ingeridas na base (PENDENTE).*

### 4.6 Indícios do eixo

#### R8 — Concentração de fornecedor / risco de captura (bid rigging) (gravidade 4/5)
- **Condição (fato):** 61,0% do valor pago concentrado em um único órgão (**ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100)**) — concentração extrema para um prestador de serviços. Fonte: SIAFE · ob_orcamentaria_siafe (régua _ob_paga).
- **Critério:** Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE
- **Explicação inocente:** A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um ramo de poucos players (ex.: engenharia/consórcio legítimo), sem qualquer conluio. → os dados a **refutam** (convergência/gravidade): sustenta **requisição de documentos**.

#### F-ESCALADA — Escalada abrupta do valor pago entre exercícios (gravidade 3/5)
- **Condição (fato):** Crescimento abrupto dos pagamentos de R$ 300.000,00 (2024) para R$ 4.200.000,00 (2025) — +1.300% (primeiro × último exercício completo com pagamento). Fora da comparação, por incompletos: 2023 (ano de início da relação). Fonte: SIAFE · ob_orcamentaria_siafe (régua _ob_paga).
- **Critério:** Arts. 5º, 18 e 125 Lei 14.133/2021 (planejamento e limites de acréscimo); arts. 62-63 Lei 4.320/64
- **Explicação inocente:** O salto pode decorrer de contrato novo vencido em licitação regular, de aditivo dentro do limite legal ou do pagamento, num exercício, de serviço prestado em exercício anterior (restos a pagar). → os dados a **refutam** (convergência/gravidade): sustenta **requisição de documentos**.

**Conclusão do eixo financeiro:** 🟡 **AMARELO** — 2 indício(s) (R8, F-ESCALADA); P×I somado 25.

## 5. EIXO CONTÁBIL — conformidade do registro e contabilidade forense

### 5.1 Critério normativo

Lei 4.320/64, arts. 36 (restos a pagar), 58-65 (estágios da despesa) e 101-105 (demonstrações); a OB só é pagamento quando contabilizada e não devolvida pelo banco (régua `_ob_paga`). Retenção na fonte: ISS (LC 116/2003, art. 6º: o tomador responde pela retenção que deixa de fazer) e IR retido na fonte, cujo produto pertence ao Estado (CF/88, art. 157, I).

### 5.2 Estágios e registro

- **OB pagas com valor > 0:** 4 — R$ 4.620.000,00 (SIAFE · ob_orcamentaria_siafe (régua _ob_paga) · VERIFICADO).
- **OB de valor zero (regularização contábil):** 3 — fora da série paga (régua do indício R10: ≥ 3).
- **OB registradas e NÃO pagas** (excluídas do pago pela régua):

| Motivo | OBs | Valor (R$) |
|---|---:|---:|
| devolvida pelo banco (Erro no Pagamento) | 1 | 2.400.000,00 |
| status 'Excluído' | 1 | 50.000,00 |

- **Pago acima do liquidado na mesma NL:** 1 NL; **OB anterior à NL citada:** 1 OB — conferido só onde a NL está na base (50,0% das OBs).
- **NL não contabilizadas (anuladas/excluídas):** 0 — R$ 0,00; **NE não contabilizadas:** 0 — R$ 0,00 (SIAFE · nl_siafe (notas de liquidação) / SIAFE · ne_siafe (notas de empenho)).

### 5.3 Retenções

Valor retido declarado nas NL contabilizadas do credor: **R$ 121.000,00** (SIAFE · nl_siafe (notas de liquidação) · PENDENTE, piso). O **tipo** de cada retenção (ISS, IR, INSS) não está ingerido; a conferência da retenção de ISS nota a nota é feita pelo detector `iss_declarado_retido_nao_retido` sobre o acervo SEI — sem disparo nos processos deste fornecedor presentes no acervo.

### 5.4 Contabilidade forense (régua descritiva)

*Benford e valores redondos são RÉGUA, não prova: não entram no grau (detectores sem taxa de falso positivo medida) e só se leem com amostra suficiente.*

- **Benford:** não aplicado — amostra insuficiente (4 < 100 OBs); afirmar conformidade ou desvio seria fabricar precisão.
- **Valores redondos:** das 4 OBs pagas ≥ R$ 1.000,00 (de 4 OBs pagas), 4 (100,0%) fecham em milhar exato e 100,0% em centena exata — amostra pequena demais para inferência (n < 30) — dado descritivo.

### 5.5 Indícios do eixo

#### C-PAGO>NL — Pagamento acima do valor liquidado na mesma nota de liquidação (gravidade 3/5)
- **Condição (fato):** Em **1** nota(s) de liquidação a soma das OBs pagas que a citam supera o valor liquidado — excedente de **R$ 100.000,00** (maior: 2025NL00010 da UG 133100, pago R$ 2.400.000,00 × liquidado R$ 2.300.000,00; OBs 2025OB00007). Fonte: SIAFE · ob_orcamentaria_siafe (régua _ob_paga) × SIAFE · nl_siafe (notas de liquidação).
- **Critério:** Arts. 62-64 Lei 4.320/64 (pagamento só após a regular liquidação e no valor liquidado)
- **Explicação inocente:** A NL pode ter sido reduzida (anulação parcial) depois do pagamento, com a diferença devolvida por Guia de Devolução não ingerida, ou a OB pode ser reemissão de outra devolvida pelo banco. → os dados a **refutam** (convergência/gravidade): sustenta **requisição de documentos**.

#### R10 — Liquidação irregular / pagamento atípico (estornos) (gravidade 2/5)
- **Condição (fato):** 3 ordens bancárias de valor R$ 0,00 (estornos/regularizações) — verificar a regularidade da liquidação.
- **Critério:** Arts. 62-63 Lei 4.320/64; Decreto 93.872/86 art. 38
- **Explicação inocente:** OBs de R$ 0,00 e estornos são, em regra, regularizações contábeis ordinárias, não pagamento irregular. → os dados **não** a refutam: rebaixado a **monitoramento** (não representação).

#### C-OB<NL — Ordem bancária emitida antes da liquidação que a fundamenta (gravidade 2/5)
- **Condição (fato):** **1** OB(s) emitida(s) em data ANTERIOR à da nota de liquidação que citam (ex.: 2025OB00007 de 2025-02-15 × 2025NL00010 de 2025-02-20, UG 133100). O pagamento pressupõe a liquidação (art. 62 da Lei 4.320/64). Fonte: SIAFE · ob_orcamentaria_siafe (régua _ob_paga) × SIAFE · nl_siafe (notas de liquidação).
- **Critério:** Arts. 62-63 Lei 4.320/64 (a liquidação precede o pagamento)
- **Explicação inocente:** A NL pode ser lançamento de regularização emitido depois para formalizar um pagamento cuja liquidação material (atesto) ocorreu antes — falha de registro, não pagamento sem direito do credor. → os dados **não** a refutam: rebaixado a **monitoramento** (não representação).

**Conclusão do eixo contábil:** 🟡 **AMARELO** — 3 indício(s) (C-PAGO>NL, R10, C-OB<NL); P×I somado 21.

## 6. EIXO JURÍDICO — legalidade da contratação

### 6.1 Critério normativo

Lei 14.133/2021: princípios e vedações (arts. 5º, 9º e 11), planejamento (art. 18), pesquisa de preços (art. 23), habilitação (arts. 62-70), contratação direta instruída (art. 72) e suas hipóteses (arts. 74-75, vedado o fracionamento — art. 75, §1º), fiscalização do contrato (art. 117) e limites de alteração (art. 125). LINDB, arts. 20-22 e 28 (consequências práticas; dificuldades reais do gestor; só o erro grosseiro responsabiliza). Improbidade (Lei 8.429/92 pós-Lei 14.230/2021): exige **dolo** e, no art. 10, **dano efetivo**.

### 6.2 Contratos e contratação direta (TCE-RJ Dados Abertos)

> Nenhum contrato nem compra direta deste CNPJ na base de Dados Abertos do TCE-RJ (PENDENTE: confirmar no PNCP e no próprio processo SEI). Sem o valor contratado, o pago não é confrontado com o teto do contrato nem com os limites de aditivo do art. 125.

### 6.3 Leitura dos processos SEI

> Íntegra não lida nesta execução. Os vícios das fases de planejamento, edital e julgamento **não foram examinados** — é lacuna, não regularidade.

### 6.4 Vícios de licitação pelo catálogo canônico

| Vício (catálogo) | Fase | Achado que o aponta | Dispositivos | Escalada típica |
|---|---|---|---|---|
| Empresa-fachada / laranja | perfil_contratado | DD/H-CAPITAL, DD/H-RECENTE, DD/H-SOCIO-UNICO | Lei 14.133/2021 art. 14; Código Penal art. 337-F | representacao |
| Execução financeira anômala | execucao | R10 | Lei 4.320/1964 arts. 62-63 | diligencia |

> **Não examinados por falta da íntegra do processo:** planejamento (7 vícios); edital (13 vícios); julgamento (11 vícios). O catálogo tem 50 vícios; sem os documentos da contratação, a ausência de achado nessas fases não é afirmação de regularidade.

### 6.5 Triagem: ilegalidade × improbidade (elemento subjetivo)

| Indício | Elemento subjetivo (triagem) | Encaminhamento doutrinário |
|---|---|---|
| R8 Concentração de fornecedor / risco de captura (bid rigging) | irregularidade / erro de gestão | controle de contas (TCE-RJ) — não improbidade |
| F-ESCALADA Escalada abrupta do valor pago entre exercícios | irregularidade / erro de gestão | controle de contas (TCE-RJ) — não improbidade |
| DD/H-CAPITAL Capital social ínfimo frente ao recebido | dolo a apurar | improbidade (MP-RJ) — a apurar dolo + dano efetivo |
| C-PAGO>NL Pagamento acima do valor liquidado na mesma nota de liquidação | irregularidade / erro de gestão | controle de contas (TCE-RJ) — não improbidade |
| R10 Liquidação irregular / pagamento atípico (estornos) | irregularidade / erro de gestão | controle de contas (TCE-RJ) — não improbidade |
| DD/H-RECENTE Empresa recém-aberta antes do 1º recebimento | dolo a apurar | improbidade (MP-RJ) — a apurar dolo + dano efetivo |
| DD/H-SOCIO-UNICO Sócio único com sinais de fachada | dolo a apurar | improbidade (MP-RJ) — a apurar dolo + dano efetivo |
| C-OB<NL Ordem bancária emitida antes da liquidação que a fundamenta | irregularidade / erro de gestão | controle de contas (TCE-RJ) — não improbidade |

> 3 indício(s) com sinal de elemento subjetivo — apurar dolo e dano antes de cogitar improbidade.

### 6.6 Indícios do eixo

> Nenhum indício jurídico disparou nas fontes lidas.

**Conclusão do eixo jurídico:** 🟢 **VERDE** — sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida.

## 7. EIXO COMPLIANCE / INTEGRIDADE — due diligence do fornecedor

### 7.1 Critério normativo

Lei 12.846/2013 (responsabilização objetiva da pessoa jurídica por atos lesivos — art. 5º, IV: fraude a licitação e contrato) e Decreto 11.129/2022 (parâmetros do programa de integridade); Lei 14.133/2021, art. 14 (impedimentos, inclusive vínculo com agente público), art. 156 (sanções) e art. 25, §4º (programa de integridade em contratação de grande vulto). Sanção vale pela **vigência e alcance** na data do ato.

### 7.2 Due diligence — fachada, laranja, sanções e vínculos

*Bateria de hipóteses investigativas (cadastro Receita + base de OBs + OSINT). Base legal: controle externo e fiscalização (CF art. 70-71; LGPD art. 7º,II e 23). **Honesto:** indício merece apuração, nunca acusação; **INDISPONÍVEL ≠ ausência de risco**; CPF de pessoa física mascarado (LGPD).*

**Placar da bateria de due diligence:** 0 fato(s) confirmado(s), 3 indício(s) a apurar.

Investigação de fachada/laranja: 3 indício(s) a apurar. Indício merece apuração — não constitui acusação (presunção de regularidade).

#### H-CAPITAL — Capital social ínfimo frente ao recebido
- **Status:** 🟡 INDÍCIO  ·  **Nível:** ALTO
- **Constatação:** Capital social declarado de R$ 10.000,00 contra R$ 4.620.000,00 recebidos do Estado (462× o capital). Capital irrisório frente a contratos vultosos é indício de subcapitalização típica de empresa de fachada — verificar capacidade econômico-financeira.
- **Fonte:** Receita Federal (cadastro CNPJ)  ·  **Base legal:** art. 11 Lei 8.429/92; Lei 14.133/21 art. 69

#### H-RECENTE — Empresa recém-aberta antes do 1º recebimento
- **Status:** 🟡 INDÍCIO  ·  **Nível:** MEDIO
- **Constatação:** Empresa aberta em 01/11/2022 e já recebendo do Estado 129 dias depois (10/03/2023). Constituição imediatamente anterior à receita pública é indício de empresa criada sob medida para o contrato — verificar histórico operacional prévio.
- **Fonte:** Receita Federal (cadastro CNPJ)  ·  **Base legal:** art. 337-F CP

#### H-SOCIO-UNICO — Sócio único com sinais de fachada
- **Status:** 🟡 INDÍCIO  ·  **Nível:** MEDIO
- **Constatação:** Quadro societário com 1 único sócio, somado a capital R$ 10.000,00. A combinação de sócio único, baixo capital e endereço residencial é o perfil típico de empresa de fachada/laranja — verificar a pessoa do sócio (capacidade econômica, vínculos, interposição).
- **Fonte:** Receita Federal (QSA)  ·  **Base legal:** art. 337-F CP; art. 11 Lei 8.429/92

> **Cobertura da investigação (honestidade):** endereco residencial: INDISPONIVEL (endereço não ingerido); geocode: INDISPONIVEL; foto sede: INDISPONIVEL (sem foto classificada); coendereco: verificado (nenhum); capital: verificado; recencia: verificado; situacao cadastral: verificado; porte: INDISPONIVEL; pep: INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY); beneficio social: INDISPONIVEL (sem chave PORTAL_TRANSPARENCIA_KEY); site: INDISPONIVEL (sem e-mail de domínio próprio na Receita).

> **Veredito raciocinado (IA):** veredito LLM desligado (JFN_VEREDITO_LLM_DISABLED) — os sinais determinísticos acima permanecem válidos por si (degradação honesta).


> Sinais do pacote de fachada (rede de comando, veículos do administrador, sede) que **não** viraram hipótese CONFIRMADA ou INDÍCIO acima são **contexto para diligência** e não entram no grau; o que entra está listado nos indícios do eixo.

### 7.3 Linha do tempo societária × pagamentos

| Data | Evento | Pago até a data (R$) |
|---|---|---:|
| 2022-11-01 | Abertura do CNPJ na Receita Federal | 0,00 |
| 2023-03-10 | Primeira OB estadual observada (R$ 120.000,00) | 0,00 |
| 2024-06-01 | Entrada de sócio/administrador: FULANO SNAPSHOT | 120.000,00 |
| 2025-02-15 | Maior OB do período (R$ 2.400.000,00) | 420.000,00 |
| 2025-08-20 | Última OB observada (R$ 1.800.000,00) | 2.820.000,00 |

> Houve ingresso no QSA depois da 1ª OB (2024-06-01), com R$ 120.000,00 pagos antes (2,6% do total). A régua do indício R6 (troca de controle após receita pública) exige R$ 1.000.000,00 **e** 15% do pago antes do ingresso — **não atingida**: o fato fica registrado, não pesa no grau.

### 7.4 Rede fornecedor–órgão e sócios em comum

> Sem co-ocorrência relevante na base fornecedor–órgão.

### 7.5 Indícios do eixo

*Hipóteses da due diligence que entram no grau (constatação e fonte na subseção da due diligence):*

| Indício | Gravidade | Explicação inocente | Refutada pelos dados? |
|---|---:|---|---|
| DD/H-CAPITAL Capital social ínfimo frente ao recebido | 3/5 | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas… | Sim — requisição |
| DD/H-RECENTE Empresa recém-aberta antes do 1º recebimento | 2/5 | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas… | Não — monitoramento |
| DD/H-SOCIO-UNICO Sócio único com sinais de fachada | 2/5 | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas… | Não — monitoramento |

**Conclusão do eixo compliance / integridade:** 🟡 **AMARELO** — 3 indício(s) (DD/H-CAPITAL, DD/H-RECENTE, DD/H-SOCIO-UNICO); P×I somado 21.

## 8. INSTRUÇÃO NO FORMATO DE TRIBUNAL DE CONTAS

*Anatomia do achado (TCU/ISSAI, adotada pelo TCE-RJ): critério × condição × causa × efeito, com evidência, responsáveis e proposta de encaminhamento.*

### 8.1 Matriz de achados

| # | Eixo | Critério | Condição (fato provado) | Causa provável | Efeito potencial | Evidência |
|---|---|---|---|---|---|---|
| R8 | Financeiro | Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE | 61,0% do valor pago concentrado em um único órgão (ITERJ — Instituto de Terras e Cartografia do ERJ (UG 133100)) — conce… | baixa rotatividade/captura de fornecedor por um órgão | risco de cartel/sobrepreço e dependência do prestador | SIAFE (OB/NL/NE) |
| F-ESCALADA | Financeiro | Arts. 5º, 18 e 125 Lei 14.133/2021 (planejamento e limites de acréscim… | Crescimento abrupto dos pagamentos de R$ 300.000,00 (2024) para R$ 4.200.000,00 (2025) — +1.300% (primeiro × último exer… | novos contratos/aditivos, demanda nova ou pagamento acumulado de exerc… | acréscimo sem lastro contratual ou acima do limite do art. 125 | SIAFE (OB/NL/NE) |
| DD/H-CAPITAL | Compliance / integridade | art. 11 Lei 8.429/92 (exige dolo — Lei 14.230/2021); Art. 69 Lei 14.13… | Capital social ínfimo frente ao recebido. Capital social declarado de R$ 10.000,00 contra R$ 4.620.000,00 recebidos do E… | a apurar | a apurar | fonte citada na condição |
| C-PAGO>NL | Contábil | Arts. 62-64 Lei 4.320/64 (pagamento só após a regular liquidação e no… | Em 1 nota(s) de liquidação a soma das OBs pagas que a citam supera o valor liquidado — excedente de R$ 100.000,00 (maior… | OB emitida sobre NL já esgotada, reemissão sem baixa ou NL corrigida a… | pagamento sem liquidação correspondente (dano potencial no excedente) | SIAFE (OB/NL/NE) |
| R10 | Contábil | Arts. 62-63 Lei 4.320/64; Decreto 93.872/86 art. 38 | 3 ordens bancárias de valor R$ 0,00 (estornos/regularizações) — verificar a regularidade da liquidação. | falha de liquidação/regularização (estornos, OB R$ 0,00) | risco de pagamento sem liquidação regular | SIAFE (OB/NL/NE) |
| DD/H-RECENTE | Compliance / integridade | indício de fachada — não tipifica por si; art. 337-L CP se comprovados… | Empresa recém-aberta antes do 1º recebimento. Empresa aberta em 01/11/2022 e já recebendo do Estado 129 dias depois (10/… | a apurar | a apurar | fonte citada na condição |
| DD/H-SOCIO-UNICO | Compliance / integridade | indício de fachada — tipificação depende de DOLO e resultado (art. 337… | Sócio único com sinais de fachada. Quadro societário com 1 único sócio, somado a capital R$ 10.000,00. A combinação de s… | a apurar | a apurar | fonte citada na condição |
| C-OB<NL | Contábil | Arts. 62-63 Lei 4.320/64 (a liquidação precede o pagamento) | 1 OB(s) emitida(s) em data ANTERIOR à da nota de liquidação que citam (ex.: 2025OB00007 de 2025-02-15 × 2025NL00010 de 2… | lançamento contábil retroativo (regularização) ou pagamento antecipado… | pagamento sem prévia verificação do direito do credor | SIAFE (OB/NL/NE) |

### 8.2 Responsáveis (art. 117 da Lei 14.133/2021)

> Nenhum responsável identificado nos documentos disponíveis — **lacuna de captura ou de instrução**, não afirmação de que o processo corra sem responsável. Diligência: requisitar o ato de designação de gestor e fiscal de cada contrato (art. 117).

### 8.3 Passo exculpatório e cenários discriminantes

| Indício | Explicação inocente mais plausível | Os dados a refutam? | Encaminhamento |
|---|---|---|---|
| R8 Concentração de fornecedor / risco de captura (bid rigging) | A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um ramo de poucos players (ex.: engenharia/consórcio legítimo), sem q… | **Sim** — afastada | **representação** |
| F-ESCALADA Escalada abrupta do valor pago entre exercícios | O salto pode decorrer de contrato novo vencido em licitação regular, de aditivo dentro do limite legal ou do pagamento, num exercício, de serviço prestado em ex… | **Sim** — afastada | **representação** |
| DD/H-CAPITAL Capital social ínfimo frente ao recebido | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas e, sozinhos, não caracterizam fachada/la… | **Sim** — afastada | **representação** |
| C-PAGO>NL Pagamento acima do valor liquidado na mesma nota de liquidação | A NL pode ter sido reduzida (anulação parcial) depois do pagamento, com a diferença devolvida por Guia de Devolução não ingerida, ou a OB pode ser reemissão de… | **Sim** — afastada | **representação** |
| R10 Liquidação irregular / pagamento atípico (estornos) | OBs de R$ 0,00 e estornos são, em regra, regularizações contábeis ordinárias, não pagamento irregular. | Não — plausível | **monitoramento** |
| DD/H-RECENTE Empresa recém-aberta antes do 1º recebimento | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas e, sozinhos, não caracterizam fachada/la… | Não — plausível | **monitoramento** |
| DD/H-SOCIO-UNICO Sócio único com sinais de fachada | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas e, sozinhos, não caracterizam fachada/la… | Não — plausível | **monitoramento** |
| C-OB<NL Ordem bancária emitida antes da liquidação que a fundamenta | A NL pode ser lançamento de regularização emitido depois para formalizar um pagamento cuja liquidação material (atesto) ocorreu antes — falha de registro, não p… | Não — plausível | **monitoramento** |

#### Cenários e testes discriminantes (o documento que decide)

*Método: para cada achado, a hipótese benigna mais plausível, a hipótese de risco e o teste que discrimina entre elas — a diligência deixa de ser genérica e vira pedido de documento específico (arts. 20-21 da LINDB: decidir pelas consequências reais, não pela abstração).*

| Achado | Hipótese benigna | Hipótese de risco | TESTE DISCRIMINANTE |
|---|---|---|---|
| **R8** (grav. 4/5) | A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um ramo de poucos players (ex.: engenharia/consór | captura do órgão/rodízio combinado entre fornecedores | atas dos certames: nº de propostas VÁLIDAS, cascata de desclassificações e QSA/endereços dos derrotados (derrotado-fantasma que nunca vence em lugar nenhum = cartel de cobertura) |
| **F-ESCALADA** (grav. 3/5) | O salto pode decorrer de contrato novo vencido em licitação regular, de aditivo dentro do limite legal ou do pagamento, num exercício, de se | acréscimo sem lastro contratual ou acima do limite do art. 125 da Lei 14.133/2021 | contratos e aditivos vigentes em cada exercício (valor e data) × pago por exercício; inscrição em restos a pagar das OBs do ano do salto |
| **DD/H-CAPITAL** (grav. 3/5) | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas e, sozinhos, não car | fachada sem operação real no endereço declarado | verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED) |
| **C-PAGO>NL** (grav. 3/5) | A NL pode ter sido reduzida (anulação parcial) depois do pagamento, com a diferença devolvida por Guia de Devolução não ingerida, ou a OB po | pagamento acima do direito liquidado do credor | espelhos da NL e das OBs que a citam + Guias de Devolução (gd_siafe) do período |
| **R10** (grav. 2/5, defesa sobrevive) | OBs de R$ 0,00 e estornos são, em regra, regularizações contábeis ordinárias, não pagamento irregular. | ciclo de empenho-estorno para reter dotação ou mascarar liquidação irregular | documentos de anulação no SIAFE (motivo declarado) + cronologia estorno→novo empenho |
| **DD/H-RECENTE** (grav. 2/5, defesa sobrevive) | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas e, sozinhos, não car | fachada sem operação real no endereço declarado | verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED) |
| **DD/H-SOCIO-UNICO** (grav. 2/5, defesa sobrevive) | Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas legítimas e, sozinhos, não car | fachada sem operação real no endereço declarado | verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED) |
| **C-OB<NL** (grav. 2/5, defesa sobrevive) | A NL pode ser lançamento de regularização emitido depois para formalizar um pagamento cuja liquidação material (atesto) ocorreu antes — falh | pagamento antes da verificação do direito do credor | atesto/medição e nota fiscal: data do atesto × data da OB |


### 8.4 Matriz de risco (P × I)

| Indício | Eixo | P (1-5) | I (1-5) | P×I | Faixa |
|---|---|---:|---:|---:|---|
| R8 Concentração de fornecedor / risco de captura (bid rigging) | Financeiro | 4 | 4 | 16 | Extremo |
| F-ESCALADA Escalada abrupta do valor pago entre exercícios | Financeiro | 3 | 3 | 9 | Médio |
| DD/H-CAPITAL Capital social ínfimo frente ao recebido | Compliance / integridade | 3 | 3 | 9 | Médio |
| C-PAGO>NL Pagamento acima do valor liquidado na mesma nota de liquidação | Contábil | 3 | 3 | 9 | Médio |
| R10 Liquidação irregular / pagamento atípico (estornos) | Contábil | 3 | 2 | 6 | Médio |
| DD/H-RECENTE Empresa recém-aberta antes do 1º recebimento | Compliance / integridade | 3 | 2 | 6 | Médio |
| DD/H-SOCIO-UNICO Sócio único com sinais de fachada | Compliance / integridade | 3 | 2 | 6 | Médio |
| C-OB<NL Ordem bancária emitida antes da liquidação que a fundamenta | Contábil | 3 | 2 | 6 | Médio |
| **Índice de atenção (soma, teto 100)** | | | | **67** | |

### 8.5 Triagem por indicadores de risco de fraude

> Metodologia de indicadores de risco em licitações (B. V. Mondo). **Indício para priorização/diligência — nunca prova nem acusação.**

**Risco de triagem:** 🟡 MÉDIO (score 2; 1 indicador(es)). **Tipologias associadas:** Cartel/rodízio (bid rigging) — divisão de mercado entre players, Cláusulas/exigências que restringem indevidamente a competição.

| Indicador | Fase | Escopo | Tipologia | RF |
|---|---|---|---|---|
| Concentração de contratos em um ou poucos fornecedores | — | conjunto | cartel, edital_restritivo | — |

**Técnicas de detecção recomendadas:** Monitoramento de processos com base em indicadores de risco; Análise documental do edital/TR (especificações × restrição); Pesquisa de preços independente (cesta — Acórdão 1875/2021-TCU); Cruzamento societário e de endereços dos licitantes (laranjas/empresas-irmãs); Análise de rede de co-ocorrência entre participantes (cartel/rodízio); Pedidos via Lei de Acesso à Informação (LAI) para suprir lacunas documentais.

### 8.6 Proposta de encaminhamento

| Medida proposta | Fundamento | Achados que a sustentam |
|---|---|---|
| Requisição de documentos ao órgão (diligência) | CF/88 arts. 70-71; Lei 14.133/2021, arts. 169-171 | R8, F-ESCALADA, DD/H-CAPITAL, C-PAGO>NL, R10, DD/H-RECENTE, DD/H-SOCIO-UNICO, C-OB<NL |
| Representação ao TCE-RJ/MP-RJ se a resposta não afastar o indício | Deliberação TCE-RJ 279/2017 (elementos que indiquem) | R8, F-ESCALADA, DD/H-CAPITAL, C-PAGO>NL |
| Ciência a CGU / CGE-RJ | PAR anticorrupção — fachada/laranja/idoneidade (Lei 12.846; controle interno) | DD/H-CAPITAL, DD/H-RECENTE, DD/H-SOCIO-UNICO |
| Ciência a MP-RJ | improbidade/penal — fachada/laranja (Lei 8.429; CP arts. 337-E ss.) | DD/H-CAPITAL, DD/H-RECENTE, DD/H-SOCIO-UNICO |

> Encaminhamento a outro órgão só para achado cuja explicação inocente os dados afastaram; a tipificação (improbidade, crime) é do MP-RJ e do Judiciário, após contraditório (art. 5º, LV, CF/88).

### 8.7 Proposta preliminar de sanção administrativa

> Subsídio técnico ao gestor com base no Manual de Sanções da PGE-RJ e na Lei 14.133/21. **Não é decisão nem acusação** — a sanção exige processo com contraditório, ampla defesa e decisão motivada da Autoridade Competente (presunção de regularidade dos atos administrativos).

**Gravidade ajustada:** 🔴 GRAVE · **Dolo indiciado:** não · **Regime:** Lei 14.133/21
- **Fundamento da dosimetria:** Lei RJ 5.427/09 arts. 70-72; LINDB art. 22 §2º; proporcionalidade (CF art. 37).

**Sanções compatíveis (proporcionalidade — não vinculam a ordem legal):**

| Sanção | Base legal | Prazo/limite | Cumulável c/ multa |
|---|---|---|:---:|
| Advertência | Lei 14.133/21, art. 156, I | — | sim |
| Multa | Lei 14.133/21, art. 156, II e §3º | 30% | sim |
| Impedimento de licitar e contratar | Lei 14.133/21, art. 156, III e §4º | 3 anos | sim |

**Processo:** defesa 5 dias úteis · recurso 5 dias úteis · autoridade: Ordenador de despesa do órgão/entidade.

**Providências pós-decisão:** registro da penalidade no Cadastro de Fornecedores (SIGA); publicação do extrato no Diário Oficial (suspensão/impedimento/inidoneidade); comunicação à CGE para registro no CEIS (Cadastro Nacional de Empresas Inidôneas e Suspensas); cobrança da multa: garantia → retenção de créditos → notificação → dívida ativa/execução fiscal.

> **Valor da multa não estimado:** a base legal é o valor do contrato (art. 156, §3º, da Lei 14.133/2021), não o total pago; sem o contrato e o dano apurado, qualquer número seria fabricado.

## 9. CAMADA SUBJETIVA — juízo raciocinado (OPINIÃO)

*Separada da camada determinística: é opinião do Claude Opus pela assinatura sobre os fatos das seções 3 a 8. Não altera fato nem grau; pode, no máximo, recomendar diligência.*

> **INDISPONÍVEL** — camada subjetiva desligada nesta execução (JFN_LEX_SUBJETIVA=0). Nenhum texto foi gerado no lugar; o parecer vale pela camada determinística.

## 10. CONCLUSÃO — GRAU CONSOLIDADO

| Eixo | Grau | Indícios | P×I | Fundamento |
|---|---|---:|---:|---|
| Financeiro | 🟡 AMARELO | 2 | 25 | indícios pontuais a esclarecer mediante diligência |
| Contábil | 🟡 AMARELO | 3 | 21 | indícios pontuais a esclarecer mediante diligência |
| Jurídico | 🟢 VERDE | 0 | 0 | sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida |
| Compliance / integridade | 🟡 AMARELO | 3 | 21 | indícios pontuais a esclarecer mediante diligência |
| **Consolidado** | **🔴 VERMELHO** | **8** | **67** | convergência de 3+ indícios, ao menos um grave — recomenda-se controle externo |

> O consolidado sobe acima do maior grau de eixo por **convergência entre eixos** (fontes independentes apontando no mesmo sentido — ISSAI 100/300).

## 11. DILIGÊNCIAS, QUESITOS E MINUTA DE REQUISIÇÃO

### 11.1 Diligências (ordem de prioridade)

1. Processo **SEI-330020/000123/2023** (R$ 2.520.000,00 pagos em 2 OB, UG 133100): ler a íntegra (contrato, aditivos, medições/atestos e notas fiscais).
2. Indício **R8** — teste discriminante: atas dos certames: nº de propostas VÁLIDAS, cascata de desclassificações e QSA/endereços dos derrotados (derrotado-fantasma que nunca vence em lugar nenhum = cartel de cobertura).
3. Indício **F-ESCALADA** — teste discriminante: contratos e aditivos vigentes em cada exercício (valor e data) × pago por exercício; inscrição em restos a pagar das OBs do ano do salto.
4. Indício **DD/H-CAPITAL** — teste discriminante: verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED).
5. Indício **C-PAGO>NL** — teste discriminante: espelhos da NL e das OBs que a citam + Guias de Devolução (gd_siafe) do período.
6. Coletar no SIAFE as NL/NE das OBs sem liquidação ingerida (R$ 2.100.000,00) — só então comparar empenhado × liquidado × pago como totais.
7. Identificar o processo SEI da(s) 2 OB sem nº reconhecível (R$ 2.100.000,00) pelo espelho da OB/PD no SIAFE.
8. Obter o(s) contrato(s) e aditivos (PNCP / processo SEI) para confrontar pago × valor contratado e o limite do art. 125 da Lei 14.133/2021.
9. Requisitar o ato de designação de gestor e fiscal de cada contrato (art. 117 da Lei 14.133/2021).

### 11.2 Quesitos

1. Qual o instrumento (contrato/ata/termo) que lastreia cada OB paga listada no Anexo A, e qual o seu valor atualizado com aditivos?
2. Para cada OB, qual a nota fiscal e o atesto/medição que a liquidaram (data e responsável)?
3. Houve retenção de ISS, IR e INSS em cada pagamento? Juntar as guias de recolhimento.
4. Indício R8 (Concentração de fornecedor / risco de captura (bid rigging)): apresentar atas dos certames: nº de propostas VÁLIDAS, cascata de desclassificações e QSA/endereços dos derrotados (derrotado-fantasma que nunca vence em lugar nenhum = cartel de cobertura) — o documento que distingue a hipótese benigna («A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um ramo de poucos p…») da hipótese de risco («captura do órgão/rodízio combinado entre fornecedores»).
5. Indício F-ESCALADA (Escalada abrupta do valor pago entre exercícios): apresentar contratos e aditivos vigentes em cada exercício (valor e data) × pago por exercício; inscrição em restos a pagar das OBs do ano do salto — o documento que distingue a hipótese benigna («O salto pode decorrer de contrato novo vencido em licitação regular, de aditivo dentro do limite legal ou do p…») da hipótese de risco («acréscimo sem lastro contratual ou acima do limite do art. 125 da Lei 14.133/2021»).
6. Indício DD/H-CAPITAL (Capital social ínfimo frente ao recebido): apresentar verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED) — o documento que distingue a hipótese benigna («Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas…») da hipótese de risco («fachada sem operação real no endereço declarado»).
7. Indício C-PAGO>NL (Pagamento acima do valor liquidado na mesma nota de liquidação): apresentar espelhos da NL e das OBs que a citam + Guias de Devolução (gd_siafe) do período — o documento que distingue a hipótese benigna («A NL pode ter sido reduzida (anulação parcial) depois do pagamento, com a diferença devolvida por Guia de Devo…») da hipótese de risco («pagamento acima do direito liquidado do credor»).
8. Indício R10 (Liquidação irregular / pagamento atípico (estornos)): apresentar documentos de anulação no SIAFE (motivo declarado) + cronologia estorno→novo empenho — o documento que distingue a hipótese benigna («OBs de R$ 0,00 e estornos são, em regra, regularizações contábeis ordinárias, não pagamento irregular.») da hipótese de risco («ciclo de empenho-estorno para reter dotação ou mascarar liquidação irregular»).
9. Indício DD/H-RECENTE (Empresa recém-aberta antes do 1º recebimento): apresentar verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED) — o documento que distingue a hipótese benigna («Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas…») da hipótese de risco («fachada sem operação real no endereço declarado»).
10. Indício DD/H-SOCIO-UNICO (Sócio único com sinais de fachada): apresentar verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED) — o documento que distingue a hipótese benigna («Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em microempresas…») da hipótese de risco («fachada sem operação real no endereço declarado»).
11. Indício C-OB<NL (Ordem bancária emitida antes da liquidação que a fundamenta): apresentar atesto/medição e nota fiscal: data do atesto × data da OB — o documento que distingue a hipótese benigna («A NL pode ser lançamento de regularização emitido depois para formalizar um pagamento cuja liquidação material…») da hipótese de risco («pagamento antes da verificação do direito do credor»).

### 11.3 Minuta de ofício de requisição

> **Ofício nº ____/____** — Ao(À) Ordenador(a) de Despesa da(s) UG 133100.
>
> Com fundamento nos arts. 70 e 71 da Constituição Federal, nos arts. 169 a 171 da Lei 14.133/2021 e no dever de prestar contas, requisitam-se, no prazo de 15 (quinze) dias, os documentos abaixo relativos aos pagamentos ao fornecedor SNAPSHOT ENGENHARIA E SERVICOS LTDA (CNPJ 11.222.333/0001-81):
>
> - **SEI-330020/000123/2023** (R$ 2.520.000,00 pagos): íntegra do processo; contrato e aditivos; notas fiscais, atestos e medições; guias de retenção; ato de designação do fiscal.
>
> A requisição não constitui juízo de irregularidade; visa a instruir exame sob presunção de legitimidade dos atos administrativos.

## 12. RESSALVAS

1. Os apontamentos são **indícios**, sujeitos a contraditório e ampla defesa (art. 5º, LV, CF/88).
2. Vigora a **presunção de legitimidade** dos atos administrativos; a dúvida sobre a economicidade favorece o gestor.
3. **Não se afirma crime, improbidade ou dolo** — competência do tribunal de contas, do MP-RJ e do Judiciário.
4. As conclusões se limitam aos dados verificados (seção 3); lacunas geram **diligência**, não condenação.
5. Pagamento é só a OB paga do SIAFE pela régua da casa; empenho e liquidação aparecem como piso quando a ingestão é parcial; o espelho TFE não é usado como pago.
6. A camada subjetiva (seção 9) é opinião e não integra a prova.

_Parecer gerado por sistema de controle externo em 2026-07-06. Não substitui parecer jurídico formal._

## ANEXO A — ORDENS BANCÁRIAS DO ALVO (SIAFE)

*4 OB pagas (valor > 0), em ordem de data — soma R$ 4.620.000,00. Fonte: SIAFE · ob_orcamentaria_siafe (régua _ob_paga).*

| Nº OB | Data | UG | NL | Valor (R$) | Estado |
|---|---|---|---|---:|---|
| 2023OB00101 | 2023-03-10 | 133100 | 2023NL00050 | 120.000,00 | paga |
| 2024OB00410 | 2024-06-12 | 133100 | — | 300.000,00 | paga |
| 2025OB00007 | 2025-02-15 | 133100 | 2025NL00010 | 2.400.000,00 | paga |
| 2025OB00930 | 2025-08-20 | 263100 | 2025NL00200 | 1.800.000,00 | paga |
| **Total** | | | | **4.620.000,00** | |

**OB fora do pago (não somadas):**

| Nº OB | Data | UG | Valor (R$) | Motivo |
|---|---|---|---:|---|
| 2023OB00150 | 2023-05-02 | 133100 | 0,00 | regularização (valor zero) |
| 2023OB00151 | 2023-06-02 | 133100 | 0,00 | regularização (valor zero) |
| 2023OB00152 | 2023-07-02 | 133100 | 0,00 | regularização (valor zero) |
| 2024OB00300 | 2024-04-05 | 133100 | 50.000,00 | status 'Excluído' |
| 2025OB00006 | 2025-02-10 | 133100 | 2.400.000,00 | devolvida pelo banco (Erro no Pagamento) |

## ANEXO B — FONTES CONSULTADAS

| Fonte | O que forneceu | Atualização | Estado |
|---|---|---|---|
| SIAFE · ob_orcamentaria_siafe (régua _ob_paga) | OB do alvo (paga e não paga) | coleta mais recente das OB do alvo: 2026-07-05 10:00:00 | **VERIFICADO** |
| SIAFE · nl_siafe (notas de liquidação) | liquidações do credor | 2026-07-05 10:00:00 | **PENDENTE** |
| SIAFE · ne_siafe (notas de empenho) | empenhos do credor | 2026-07-05 10:00:00 | **PENDENTE** |
| Receita Federal · cadastro CNPJ (enriquecimento do contexto) | cadastro e QSA | — | **VERIFICADO** |
| TCE-RJ Dados Abertos (contratos e compras diretas) | 0 contrato(s), 0 compra(s) | consulta nesta execução | **PENDENTE** |
| Acervo SEI da casa (data/sei_arquivo) | fases documentadas dos maiores processos | manifesto por processo | **PENDENTE** |

## ANEXO C — BASE NORMATIVA CITADA

| Norma | Dispositivos | Uso no parecer |
|---|---|---|
| CF/88 | arts. 5º, LV; 37; 70-71 | contraditório; princípios; controle externo |
| Lei 4.320/64 | arts. 36, 58-65 | restos a pagar; estágios da despesa |
| Lei 14.133/2021 | arts. 5º, 9º, 11, 14, 18, 23, 25 §4º, 62-70, 72-75, 117, 125, 156, 169-171 | licitação, contratação direta, fiscalização, aditivos, sanções, controle |
| Decreto-Lei 4.657/42 (LINDB) | arts. 20-22 e 28 | consequências práticas; erro grosseiro |
| Lei 8.429/92 (red. Lei 14.230/2021) | arts. 9º-11 | improbidade só com dolo; art. 10 com dano efetivo |
| Lei 12.846/2013 e Decreto 11.129/2022 | art. 5º, IV; programa de integridade | responsabilização da PJ |
| LC 116/2003; CF/88 | art. 6º; art. 157, I | retenção de ISS pelo tomador; IR retido pertence ao Estado |
| Deliberação TCE-RJ 279/2017 | — | rito de tomada de contas (limiar: elementos que indiquem) |


_Nota de conferência: 1 citação(ões) verificada(s) contra a Jurisprudência Selecionada do TCU (dados abertos oficiais); 1 confirmada(s)._