# Playbook de Método Pericial — JFN (Hermes · Yoda · Lex)

> Lições de método consolidadas (perícia ITERJ×MGS 005/2021, 2026-06). Conhecimento COMPARTILHADO: o
> Hermes carrega isto na memória `metodo`; o RAG indexa este doc; Lex e Yoda consultam pela mesma cadeia.
> Regra de ouro: **fonte primária acima de tudo; conclusão + memória de cálculo sempre.**

## 1. Hierarquia de prova
- **Documento de parte interessada é ALEGAÇÃO, não prova.** Relatório contábil do próprio órgão (ex.: ASSCONT) deve ser **testado e, se for o caso, refutado** com fonte primária (SIAFE, registro de reajustes, NF, contrato). Nunca adotar o número do órgão como veredito.
- **Empenho ≠ Liquidação ≠ OB.** Só a Ordem Bancária é pagamento. Nunca citar empenho como total pago.
- **Bruto ≠ Líquido.** A OB é líquida; retenção (INSS+IRRF ~9%) **não é glosa**. Nunca tratar diferença bruto×líquido como crédito/débito (gera crédito-fantasma).

## 2. Reajuste / repactuação (contrato de mão-de-obra)
- É **repactuação componente-a-componente (IN 05/2017)**: CCT na mão-de-obra + IPCA nos insumos — **não** % flat sobre o total.
- O índice CCT (ex.: 9,91%) incide **só na mão-de-obra** → o aumento **efetivo na tarifa cheia é menor** (ex.: 8,69%). Validar reajuste por % flat dá falso desvio.
- **Prova ao centavo pelo apostilamento:** `Δ mensal = valor apostilado ÷ 9`; tarifa nova = tarifa anterior + Δ. Confirma o valor oficial sem depender do órgão. Conferir a **data-base real** (no caso ITERJ era JULHO em 2022-23, migrou p/ março só em 2024).

## 3. Duplicidade de pagamento (contrato contínuo)
- Checar por **COMPETÊNCIA**, não por valor. **Valores iguais NÃO provam duplicidade** (tarifa flat).
- **Reconciliação de cobertura:** contar os meses do contrato e confrontar com as OBs. Competência com 2 OBs costuma ser: (a) **recuperação de mês atrasado** (rótulo de competência mal-digitado), (b) **split** sob o mesmo empenho/RE (1 liquidação em 2 OBs), ou (c) **complemento de reajuste** (parcela pequena). Só a **NF** fecha em definitivo.
- Cada mês deve aparecer pago **uma vez**; mês "dobrado" pareia com um mês "ausente" vizinho.

## 4. Dados e tooling (não re-errar)
- **A base SIAFE perde OBs (2022/2023) intermitentemente.** Antes de qualquer total, **verificar a contagem esperada** (ITERJ×MGS = 55 OBs) e **reingerir do cache** (`siafe1_iterj_*.json`) se vier abaixo. Laudo nunca calcula sobre base degradada.
- **OB/pagamento = sempre SIAFE direto**, nunca o espelho TFE (o TFE subcontava).
- **SEI:** enumerar processos de um fornecedor por **INTERESSADO** (CNPJ+full-text é largo demais → pega quem só MENCIONA o CNPJ). Os processos **RELACIONADOS de um pagamento NÃO são todos do mesmo fornecedor** — verificar o favorecido/CNPJ de cada um (relacionados do pagamento MGS incluíam Mobiliza e obras BNDES).
- **NF escaneada com ERR_ABORTED** no visualizador SEI: contornar **baixando a íntegra** (`sei_integra_completa`) — muitas NFs têm camada de texto (pdftotext, sem OCR).

## 5. Entrega
- **Todo laudo tem CONCLUSÃO explícita (bottom-line) + MEMÓRIA DE CÁLCULO** (cada conta mostrada). Tabela sem conclusão não é perícia.
- Ao **retificar um veredito**, detalhar a razão e a nova base de evidência (rastreabilidade).
- **Manter o veredito provisório** até reconciliar todas as fontes primárias relevantes — evita retratação.
- Honestidade: indício ≠ acusação; INDISPONÍVEL ≠ irregular; presunção de legitimidade; nunca inventar número.

## 6. Caso-referência (aplicação)
ITERJ×MGS 005/2021: 55 OBs = R$ 5.038.369,24 cobrem os 52 meses (Dez/2021–Mar/2026), cada mês 1×; reajustes provados ao centavo (90.419,34→98.276,62→103.988,53→109.687,73); saldo R$ 56.044,28 da ASSCONT **refutado** (erro aritmético "4×" + bruto×líquido). Veredito: 🟢 conforme, sem dano ao erário.
