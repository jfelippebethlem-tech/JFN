# Design — Enxame de Avaliação + Direcionamento de Editais (Spec 1)

**Data:** 2026-07-10 · **Status:** aprovado (design) · **Autor:** Claude Fable 5 + JFN
**Escopo:** enxame-núcleo (orquestrador + agentes-lente) + **superfície EDITAIS** (peer-diff de direcionamento). Contratos e processos SEI = Specs 2 e 3, plugam no mesmo núcleo.

## 1. Objetivo

Avaliar **direcionamento** em licitações municipais do Rio comparando editais de **objeto semelhante cláusula-a-cláusula**: identificar as exigências de **habilitação/participação** de cada edital e distinguir a exigência **normal** (que os pares do mesmo objeto também fazem) da exigência que **reduz competitividade** (que só aquele edital impõe — especificidade dirigida ao incumbente).

Princípio-mãe: **direcionamento é anomalia RELATIVA**. O E7 (já existe) mede restritividade *absoluta* de um edital; esta camada mede restritividade *relativa ao grupo de compra*. As duas somadas = "cláusula forte por súmula **E** que só este edital, entre N do mesmo objeto, impôs".

Honestidade dura (regras da casa): indício ≠ acusação; campo ausente ≠ 0 (nao_avaliavel por construção); presunção de legitimidade; proveniência por trecho em todo dado extraído; CPF mascarado; LLM só free-tier; VM 2 vCPU (funil determinístico primeiro, enxame só nas candidatas).

## 2. Fontes — validadas ao vivo (2026-07-10)

| Fonte | O quê | Estado |
|---|---|---|
| `pncp.baixar_documentos(id_pncp)` | Edital em PDF/ZIP/DOCX → texto (já implementado) | ✅ existe |
| `pncp.buscar_itens(id_pncp)` | Itens: descrição (preenchida), `materialOuServico` M/S (preenchido), `ncmNbsCodigo` (~3%), `catalogoCodigoItem`/CATMAT (**~0%**) | ✅ existe |
| `pcrj_licitacoes` (14.015 linhas) | objeto (100% preenchido), modalidade, órgão, valor_estimado, controle PNCP | ✅ coletado |
| RAG Cohere (`hermes_rag`/embeddings) | embeddings do objeto p/ similaridade | ✅ existe |
| `detectores/e7_clausula_restritiva` + `coletor_edital` + `knowledge.jurisprudencia` | classificação finalística cláusula-a-cláusula ancorada em súmula | ✅ existe |
| `direcionamento_cerebro.gerar_sync` (Gemini→Groq→Cerebras) / hermes multi-IA chain | LLM free-tier p/ os agentes | ✅ existe |

**Correção de design ancorada em teste real:** CATMAT/CATSER vem ~0% preenchido na PCRJ (amostra de 33 itens = 0 com catálogo, 1 com NCM). Logo o agrupamento é **semântico-primário** (embedding do objeto + descrições dos itens), NÃO por código de catálogo. M/S e NCM entram só como refino fraco quando presentes.

## 3. Arquitetura

```
[pcrj_licitacoes] ──► A. Corpus ──► edital_documento (texto+itens, cache)
                          │
                          ▼
                 B. Extração de cláusulas ──► edital_clausula (eixo, texto, parâmetro, proveniência)
                          │
                          ▼
                 C. Agrupamento semântico ──► edital_cluster (grupos "mesmo objeto")
                          │
                          ▼
                 D. Peer-diff (raridade × força E7) ──► candidatas
                          │
                          ▼
   ┌──────────────  ENXAME-NÚCLEO (orquestrador)  ──────────────┐
   │  E1 Proporcionalidade  E2 Jurisprudência  E3 Competição    │  (só nas candidatas)
   │  E4 Refutador (adversarial)  E5 Beneficiário  → E6 Síntese │
   └──────────────────────────────┬─────────────────────────────┘
                                   ▼
                          clausula_veredito ──► G. Relatório Kroll + caso vault
```

Unidades isoladas e testáveis, cada uma com uma responsabilidade:

### A. Corpus de editais — `compliance_agent/editais/corpus.py`
Para cada licitação: baixa o edital (texto) e os itens; grava em `edital_documento`. Incremental (pula o que já tem), checkpoint, 1 por vez (VM-safe), sob o `coleta_lock`. Degrada honesto: edital sem documento acessível → `documento_disponivel=0` (fica fora do peer-diff, não vira "sem cláusula").

### B. Extração de cláusulas — `compliance_agent/editais/clausulas.py`
Reusa `coletor_edital._extrair_exigencias`/`_extrair_clausulas_restritivas` (já trazem exigência + proveniência). Adiciona o **rotulador de eixo** (Lei 14.133 arts. 62–70): `habilitacao_juridica | habilitacao_tecnica | habilitacao_econ_financeira | habilitacao_fiscal_trab | condicao_participacao`. Cada cláusula → `{eixo, subtipo, texto, parametro_num, trecho_fonte, controle_pncp}`. Regex determinístico primeiro; LLM-opcional (schema fixo, citação obrigatória) só para o que o regex não pegar. Ausente ≠ 0.

### C. Agrupamento semântico — `compliance_agent/editais/agrupar.py`
Embedding (Cohere) de `objeto + descrições dos itens concatenadas`. Pré-partição barata por `materialOuServico` (M/S) e faixa de valor (ordem de grandeza) para não comparar caneta com hospital. Dentro da partição, clustering por similaridade de cosseno (limiar calibrável; aglomerativo simples — nada de dependência pesada). Grupo com < 3 editais = **não avaliável por peer-diff** (declarado, não silenciado). Grava `edital_cluster`.

### D. Peer-diff — `compliance_agent/editais/peer_diff.py`
Dentro de cada cluster, para cada cláusula (normalizada por assinatura: eixo+subtipo+faixa de parâmetro): calcula **raridade** = 1 − (nº de editais-irmãos que a exigem / tamanho do cluster). Comum (raridade baixa) = norma de mercado. Rara (raridade ≥ limiar, ex. presente em ≤30% do grupo) = **candidata**. Score de candidatura = `raridade × forca_restritiva_E7` (E7 já dá forte/médio/fraco + súmula). Só candidatas sobem ao enxame.

### E. Enxame-núcleo — `compliance_agent/enxame/` (reutilizável pelas 3 superfícies)
- `orquestrador.py`: recebe uma candidata + o dossiê do cluster (a cláusula, o objeto, os **trechos dos editais-irmãos que NÃO a exigem**, a súmula do E7, o vencedor). Dispara os agentes-lente, coleta votos, chama a síntese. Determinístico no controle de fluxo; LLM só nas lentes.
- Agentes-lente (cada um: prompt especializado + schema de saída `{voto: 0-10, justificativa, citacao}`), todos free-tier via `direcionamento_cerebro`:
  1. `lente_proporcionalidade` — pertinência/proporcionalidade ao objeto (teste finalístico art. 37/67).
  2. `lente_jurisprudencia` — casa com súmula/acórdão? (usa `knowledge.jurisprudencia` + RAG).
  3. `lente_competicao` — quantos fornecedores exclui? (heurística determinística + LLM: raridade da exigência no universo de fornecedores do ramo).
  4. `lente_refutador` — **adversarial**: instruído a DERRUBAR a hipótese, buscando justificativa técnica legítima. Default cético.
  5. `lente_beneficiario` — vencedor casa com sinais? Reusa `emendas.pericia` (D3/D4/D5) e `pcrj.pericia_gastos` (D8/D10): favorecido de emenda, doador do autor, fantasma/recém-aberto, rede societária.
  6. `sintese` — agrega: voto final = mediana das lentes, mas **empate/limítrofe pende para o Refutador** (presunção de legitimidade). Saída: score 0–10, narrativa, citações, "o que verificar a seguir".

### F. Cruzamento com beneficiário
É a lente E5 acima; separada aqui só conceitualmente. Direcionamento + vencedor + retroalimentação = caso; direcionamento sozinho = indício. É o plugue no que já foi construído nesta sessão (emendas/PCRJ).

### G. Saída — `tools/editais_direcionamento.py`
Relatório Kroll por cluster: objeto, N editais, a cláusula rara, quem a impôs × quem não, súmula, veredito do enxame (voto + narrativa), vencedor e sinais de beneficiário. PDF (`reporting.render_html`) + XLSX + `~/vault/casos/` para veredito ≥ 8. Registra em `alertas` (tipo `edital_direcionamento`).

## 4. Modelo de dados (aditivo, `compliance_agent/editais/db.py`)
- `edital_documento` (numero_controle_pncp PK, texto, itens_json, materialservico, valor_estimado, documento_disponivel, coletado_em)
- `edital_clausula` (id, numero_controle_pncp FK, eixo, subtipo, texto, parametro_num, assinatura, trecho_fonte)
- `edital_cluster` (id, assinatura_objeto, membros_json, tamanho, avaliavel)
- `clausula_veredito` (id, clausula_id FK, cluster_id FK, raridade, forca_e7, sumula, votos_json, score_final, veredito, verificado_em)

## 5. Testes (teste REAL — meta do dono)
- **Unit** com fixtures: 3 editais reais do MESMO objeto (ex.: extintores/medicamentos) baixados e versionados como fixture → `peer_diff` detecta a cláusula que só 1 impõe; `agrupar` os coloca no mesmo cluster; `clausulas` rotula os eixos certos.
- **Enxame**: orquestrador com lentes mockadas (votos fixos) → síntese determinística; teste separado do desempate pró-refutador.
- **Integração viva** (dado real, não mock): rodar sobre 1 cluster real da PCRJ end-to-end, revisar os achados à mão (anti-falso-positivo) antes de declarar pronto.
- Reuso dos testes E7 existentes (`tests/` do detector).

## 6. Restrições
- LLM só free-tier (Gemini 2.5-flash / cadeia hermes). Nunca pago sem pedido.
- Funil determinístico ANTES do enxame — nº de chamadas LLM ≈ nº de candidatas (dezenas), não 14 mil.
- `coleta_lock` no download do corpus (serializa com os coletores). Embeddings Cohere: lote, cache no DB (não re-embeddar).
- VM: 1 job pesado por vez; corpus e embeddings rodam fora de horário de sweep.

## 7. Critérios de aceite (verificáveis)
1. Corpus: ≥ 1.000 editais com texto baixado e itens (dos que têm documento no PNCP); os sem documento marcados `documento_disponivel=0`.
2. Cláusulas: para 1 edital conhecido, os eixos extraídos conferem com leitura manual do edital.
3. Cluster: 3 editais reais do mesmo objeto caem no mesmo cluster; 1 de objeto distinto não entra.
4. Peer-diff: numa amostra revisada à mão, a cláusula sinalizada como rara realmente só aparece na minoria do grupo.
5. Enxame: veredito reproduzível dado votos fixos; empate → pró-refutador.
6. E2E vivo: ≥ 1 cluster real produz relatório PDF com veredito ranqueado e citação de súmula; achado revisado à mão = plausível (não falso-positivo óbvio).

## 8. Fora de escopo (Specs 2 e 3)
Superfície **contratos** (aditivos art. 125, sobrepreço, execução — detectores X já existem, enxame orquestra) e **processos SEI** (fases, pareceres PGE/CGE, cronologia — reusa `sei_reader`/`coletor_edital`). O enxame-núcleo (E) é construído aqui uma vez e reutilizado.
