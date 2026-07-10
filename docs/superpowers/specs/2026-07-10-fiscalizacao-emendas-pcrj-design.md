# Design — Fiscalização de Emendas Federais RJ + Contratos e Gastos da Prefeitura do Rio

**Data:** 2026-07-10 · **Status:** aprovado pelo dono (escopo ampliado via /goal) · **Autor:** Claude + JFN

## 1. Objetivo

Construir o melhor sistema possível de fiscalização de contratos e gastos, somando duas frentes novas ao ecossistema JFN (hoje forte no nível estadual — SIAFE/SEI/DOERJ/TCE-RJ):

1. **Emendas parlamentares federais** — dois recortes: (a) tudo dos 46 deputados federais do RJ, qualquer destino; (b) toda emenda com gasto em município do RJ, qualquer autor. Inclui emendas PIX (transferências especiais, art. 166-A).
2. **Prefeitura do Rio (PCRJ)** — seguir o dinheiro: despesa por credor (empenho/liquidação/pagamento) **e** processos de licitação/contratação (editais, dispensas, atas, contratos, aditivos).
3. **Cruzamento de sócios** — QSA dos destinatários de emendas e credores da PCRJ contra doações eleitorais, sanções, folhas de pagamento e rede societária (inspiração: br-acc/World Transparency Graph).

Princípios permanentes do projeto se aplicam integralmente: **Empenho ≠ Liquidação ≠ OB/pago**; **indício ≠ acusação**; **INDISPONÍVEL ≠ 0**; CPF sempre mascarado; detectores em código determinístico (não prompt); VM 2 vCPU — sem browser em sweep, 1 processo pesado por vez; só fontes gratuitas e sustentáveis (nunca assumir free tier em nada que tenha billing).

## 2. Fontes — validadas ao vivo em 2026-07-10

### 2.1 Emendas federais (todas testadas com resposta real)

| Fonte | O que dá | Acesso | Status |
|---|---|---|---|
| API Portal da Transparência `/api-de-dados/emendas` | Emenda por ano: autor, tipo (individual/bancada/comissão/**PIX**), função, `localidadeDoGasto`, valores **empenhado/liquidado/pago/restos** separados | `PORTAL_TRANSPARENCIA_KEY` (já no `.env`), ~90 req/min | ✅ testado |
| API Portal `/api-de-dados/emendas/documentos/{codigoEmenda}` | Documentos de empenho → **CNPJ/nome do favorecido final** | idem | endpoint documentado (Brazil Visible/CGU) |
| API Câmara `dadosabertos.camara.leg.br/api/v2/deputados?siglaUf=RJ` | Roster: 46 deputados RJ, id, partido, situação | pública, sem chave | ✅ testado (46 retornados) |
| API Transferegov `api.transferegov.gestao.gov.br/transferenciasespeciais/plano_acao_especial?uf_beneficiario_plano_acao=eq.RJ` | Planos de ação das **emendas PIX**: CNPJ do beneficiário, situação (ex.: `IMPEDIDO`), banco/conta, execução | PostgREST público, sem chave | ✅ testado |
| Tesouro Transparente CKAN — dataset "Emendas Parlamentares Individuais e de bancada" | Bulk CSV histórico (fallback/conferência) | público | referência |

### 2.2 Prefeitura do Rio

| Fonte | O que dá | Acesso | Status |
|---|---|---|---|
| **PNCP** `pncp.gov.br/api/consulta/v1/*` com `cnpjOrgao=42498733000148` | Contratos, empenhos-contrato, licitações e atas do MUNICIPIO DE RIO DE JANEIRO (esfera M) + secretarias/empresas municipais (CNPJs próprios, ex.: 42498600000171 visto em contrato real) | público, sem chave; `tamanhoPagina` mín. 10 | ✅ testado (contrato real retornado) |
| **ContasRio — Dados Abertos** `rio.rj.gov.br/web/contasrio/dados-abertos` | Arquivos abertos da CGM: despesa por órgão/ação/programa/fundamento, **liquidação orçamentária e de restos**, **contratos por favorecido**/órgão/modalidade/objeto, despesa com pessoal e diárias | páginas Liferay por tema; arquivos servidos via document library (`/web/arquivogeral`) — descoberta do link direto é o passo 1 da implementação | ✅ páginas mapeadas |
| ContasRio app `contasrio.rio.rj.gov.br/ContasRio/` (FINCON) | Consulta interativa | **Vaadin 8 (estado server-side) — inviável por HTTP puro; NÃO scraper** | ✅ diagnosticado |
| BigQuery `datario` (Escritório de Dados PCRJ) | Dump do **SIGMA** (compras/materiais, `rj_smfp.dump_db_sigma*` no repo `prefeitura-rio/pipelines`) e datalake geral | exige projeto GCP → **billing: só com autorização explícita do dono** | fallback |
| `doweb.rio.rj.gov.br` | Diário Oficial do município (extratos de contrato, dispensas, nomeações) | público; Querido Diário cobre o Rio (coletor já existe) | camada 2 |
| `ecomprasrio.rio.rj.gov.br` | Portal de compras PCRJ (editais/sessões) | ✅ responde 200; complemento ao PNCP | camada 2 |
| TCM-RJ `tcmrio.tc.br` | Julgados, inspeções e contas do município | ✅ responde 200 | camada 2 |

### 2.3 Sócios / QSA (o cruzamento pedido)

| Fonte | O que dá | Status |
|---|---|---|
| `socios_receita` local (compliance.db) | 27.027 sócios já carregados | ✅ existe |
| `tools/baixar_receita_dump.sh` | Dump completo Socios+Empresas da RFB (mirror Nextcloud oficial, resumível, VM-safe) — **ampliar carga é pré-requisito do cruzamento em escala** | ✅ existe |
| `minhareceita.org/{cnpj}` | QSA on-demand por CNPJ, grátis, sem chave | ✅ testado |
| `doacoes_eleitorais` local | 542.244 doações TSE | ✅ existe |
| `sancoes_federais` local + CEIS/CNEP | 24.747 sanções | ✅ existe |

### 2.4 Ferramenta de referência: br-acc (o que o dono citou)

- Original `brunoclz/br-acc` ("World Transparency Graph", viralizou em 2026): **removido do GitHub**. Fork vivo: **`enioxt/br-acc`** (EGOS Inteligência, Python, AGPLv3, atualizado 2026-07-01), clonado e inspecionado.
- Traz **45+ pipelines ETL** (SIOP, Transferegov, Portal Transparência, PNCP, CNPJ/RFB, TSE + bens + filiados, PGFN, TCU, DOU, CEAF/CEPIM/leniência, OFAC/ONU/UE/OpenSanctions, RAIS, CAGED, DataJud, ICIJ…), grafo Neo4j de 83,7M nós e postura LGPD idêntica à nossa (CPF bloqueado/mascarado; "sinais, não prova").
- **Decisão:** NÃO instalar a plataforma (Neo4j 83M nós não cabe na VM 2 vCPU; padrão do projeto é cherry-pick, não pacote). Usamos como **catálogo de fontes e de modelagem**; qualquer código aproveitado é **reimplementado** no padrão da casa (evita contaminação AGPL no repo JFN e mantém mudanças cirúrgicas). O equivalente local do grafo já existe em embrião: `rede_socios_fornecedores`, `socios_reverso`, `relacionamentos`.
- Fontes do br-acc adotadas como camada 2 nossa: **PGFN dívida ativa, CEPIM, CEAF, acordos de leniência, TSE bens de candidatos**.

## 3. Arquitetura

Padrão da casa, sem novidade estrutural: coletores em `compliance_agent/collectors/`, tabelas aditivas no `compliance.db`, detectores determinísticos em módulo de perícia, runners em `tools/`, relatório PDF via `render_html`/`html_to_pdf` (padrão Kroll), casos com sinal forte viram nota em `~/vault/casos/`.

```
[APIs federais]──┐
  emendas ────────► collectors/emendas_federais.py ──► emendas, emenda_favorecidos,
  transferegov ──► (PIX)                               emendas_pix_planos, deputados_federais_rj
[PCRJ]
  ContasRio CSV ─► collectors/contasrio.py ──────────► pcrj_despesa
  PNCP ──────────► pncp.py (+filtro PCRJ) ───────────► pcrj_contratos, pcrj_licitacoes
[Cruzamento]
  QSA (dump RFB ampliado + minhareceita) × doacoes_eleitorais × sancoes × folhas
        └────► compliance_agent/pericia_emendas.py (detectores 1–10) ──► alertas + PDF + vault
```

## 4. Schema (aditivo — nada existente muda)

- `deputados_federais_rj` — id_camara, nome, nome_civil, cpf_mascarado, partido, uf, legislaturas, situacao.
- `emendas` — codigo (PK), ano, autor_raw, autor_norm, autor_id_camara (nullable — só se casar com roster), tipo, e_pix (bool), funcao, subfuncao, localidade_gasto, uf_destino, municipio_destino_ibge (via resolvedor_municipio existente), valores: empenhado, liquidado, pago, resto_inscrito, resto_cancelado, resto_pago (REAIS, parse pt-BR), fonte, coletado_em.
- `emenda_favorecidos` — codigo_emenda (FK), documento_favorecido (CNPJ/CPF-mascarado), nome, valor, fase (empenho/pagamento), documento_ref, coletado_em.
- `emendas_pix_planos` — id_plano (PK), codigo, ano, cnpj_beneficiario, nome_beneficiario, uf, municipio, situacao, valores, banco/conta (se público), coletado_em.
- `pcrj_despesa` — exercicio, orgao, unidade, credor_documento, credor_nome, natureza, fonte_recurso, empenhado, liquidado, pago, arquivo_origem, coletado_em. Unique(exercicio, orgao, credor_documento, natureza, fonte_recurso).
- `pcrj_contratos` — numero_controle_pncp (PK), ano, orgao_cnpj, unidade, fornecedor_documento, fornecedor_nome, tipo (contrato/empenho), objeto, valor_inicial, valor_global, data_assinatura, vigencia_ini/fim, num_aditivos, fonte.
- `pcrj_licitacoes` — numero_controle_pncp (PK), modalidade, objeto, valor_estimado, situacao, data_abertura, orgao_cnpj, amparo (dispensa/inexigibilidade art.), fonte.

## 5. Perícia — detectores determinísticos (código, não prompt)

Cada detector produz linhas em `alertas` com escala de risco explícita (0–10), fonte citada e texto indício≠acusação.

**Emendas**
1. **PIX sem rastro/impedida** — transferência especial com plano `IMPEDIDO`/sem execução, ou valor alto sem plano de trabalho localizado.
2. **Concentração autor→destino** — % da carteira do deputado num único município/entidade (curral eleitoral); comparar com distribuição dos pares.
3. **Favorecido sancionado** — CNPJ favorecido × `sancoes_federais`/CEIS/CNEP (+CEPIM/CEAF/leniência quando carregados).
4. **Favorecido fantasma** — os 8 sinais do /fantasma sobre favorecidos (idade CNPJ, capital, porte×valor, endereço, CNAE incompatível, QSA circular…).
5. **Retroalimentação eleitoral (o mais forte)** — sócio (QSA) de favorecido de emenda ∈ `doacoes_eleitorais` do autor da emenda. Match por CPF quando disponível; por nome normalizado = indício fraco (homônimo possível — regra de honestidade).
6. **Empenho≠pago / restos cancelados altos** — anúncio político sem execução; nunca apresentar empenhado como pago.

**PCRJ**
7. **Fracionamento** — múltiplas dispensas/empenhos abaixo do teto para mesmo credor/objeto/órgão em janela curta.
8. **Credor recém-aberto ou fantasma** — idade CNPJ < 6 meses ganhando contrato/despesa relevante + 8 sinais.
9. **Sócio de credor ∈ folha** — QSA de credor PCRJ × folha PCRJ/Câmara (módulo pcrj existente) e × folha estadual; benefício×vínculo já tem guard de fairness.
10. **Rede entre concorrentes** — QSA/endereço compartilhado entre participantes da mesma licitação (reuso do motor E7 e de `rede_socios_fornecedores`); aditivos acumulados > 25–50% (Lei 14.133, art. 125).

## 6. Relatórios e saída

- `tools/emendas_pericia.py` e `tools/pcrj_pericia_gastos.py` → PDF padrão Kroll (capa, seções numeradas, valores com milhar e 2 casas, escala de risco explícita, fontes citadas), XLSX de apoio.
- Alertas fortes → nota em `~/vault/casos/` + Telegram (canal já existente).
- Camada 2 (fora deste ciclo): painel no /painel do site, integração no loop do Hermes, CEAP/cota parlamentar, votações×emendas, TCM-RJ julgados, DOU municipal fino.

## 7. Restrições operacionais

- `requests` puro em todos os coletores; nunca browser em sweep. Rate ≤ 60–80 req/min no Portal (limite 90). Checkpoint/resume por (fonte, ano, página) em JSON atômico (tmp+rename — lição do split de rotas).
- Dump RFB: usar o script existente (já tem guarda de load/RAM). Carga do dump completo de sócios é o job pesado conhecido — rodar sozinho, fora de horário de sweep.
- BigQuery `datario`: **não ativar** sem o dono aprovar o projeto GCP (regra: nunca assumir free tier).
- Volumes esperados: emendas ~8–12k/ano nacionais → recorte RJ cabe folgado em SQLite; PNCP PCRJ ~10³–10⁴ contratos; ContasRio CSVs anuais ~10⁵ linhas — ok.

## 8. Critérios de aceite (verificáveis)

1. Roster: 46 deputados RJ no DB, com id_camara e partido.
2. Emendas 2019–2026 dos dois recortes carregadas; total de 1 deputado conhecido confere com a consulta pública do Portal (mesmos valores empenhado/liquidado/pago).
3. ≥ 1 emenda PIX RJ com plano Transferegov linkado (incl. situação).
4. Favorecidos com CNPJ válido para ≥ 80% das emendas com documento disponível; cruzamento com sanções executa e reporta contagem (0 é resultado válido, INDISPONÍVEL ≠ 0).
5. `pcrj_despesa` com exercício 2025 carregado do ContasRio, sanity `empenhado ≥ liquidado ≥ pago` por agregado.
6. `pcrj_contratos`/`pcrj_licitacoes` com dados PNCP do CNPJ 42.498.733/0001-48 e das unidades municipais descobertas.
7. Detectores 1–10 rodam end-to-end e produzem relatório PDF com ≥ 1 achado ranqueado (ou a declaração honesta de zero achados com cobertura declarada).
