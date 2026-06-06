# Benchmark das IAs do ecossistema — modelo × função (2026-06-06)

Baseline = **Claude Opus 4.8** (gold em `data/benchmark_ias_gold.json`). Score 0–3 (juiz-LLM Gemini-2.5-Flash-Lite;
T5 determinístico). Modelos via **Gemini API direta** + **Mistral** (a OpenRouter ficou sem crédito). Run
interrompido a pedido (não forçar mais tokens das IAs) após T1/T2 — base sólida de 6 modelos distintos.

## T1 — Yoda: roteamento "linguagem natural → rota do barramento"
*Entrada:* "quanto a MGS recebeu da saúde?" — gold: `POST /api/relatorio/inteligencia {empresa:MGS}`, sem inventar ferramenta.

| Modelo | Score | vs Claude |
|---|---:|---|
| Gemini-2.5-Pro | 3 | = (igualou) |
| Gemini-2.5-Flash | 3 | = |
| Mistral-Small | 3 | = |
| Gemini-2.5-Flash-Lite | 2–3 | ≈ |
| Mistral-Nemo | 2 | ≈ |
| Mistral-Large | 1 | abaixo |
| Qwen-2.5-72B | 1 | abaixo |
| Llama-3.3-70B | 0 | falhou |
| Gemini-2.0-Flash | — | quota 429 |

## T2 — interpretar JSON de `/api/anomalias` (resumo + cláusula de honestidade)
| Modelo | Score | vs Claude |
|---|---:|---|
| Mistral-Large | 3 | = |
| Mistral-Small | 2 | ≈ |
| Gemini-2.5-Flash-Lite | 1 | abaixo (faltou clareza/cláusula) |
| Gemini-2.5-Flash | 1 | abaixo |
| Mistral-Nemo | 1 | abaixo |
| Gemini-2.0-Flash | — | quota 429 |

## Aprendizados ponto-a-ponto (o que corrigir no ecossistema)
1. **Não há um "melhor modelo" único — é por função:** roteamento favorece **Gemini-2.5-Flash/Pro e Mistral-Small**;
   interpretação de JSON favorece **Mistral-Large**. → O orquestrador deve **escolher o modelo pela tarefa**
   (já recomendado em `docs/IAS-FRACAS-GUIA.md`).
2. **Maior ≠ melhor:** no roteamento, **Mistral-Small (3) superou Mistral-Large (1)** — a tarefa é de seguir regra
   estrita, não de "potência". Para roteamento, instrução estrita + exemplos importam mais que o tamanho do modelo.
3. **Gemini-flash interpretam mal o JSON sem reforço** (score 1): precisam do lembrete explícito de formato curto
   + **cláusula de honestidade obrigatória**. Aplicado no guia.
4. **Llama-3.3 reprova no roteamento** (0) — não usar para decisão de rota; serve para texto longo.
5. **Higiene de tokens/chaves (debug):** as chaves LLM do `JFN/.env` estavam **inválidas** (401); sincronizadas as
   válidas do `~/.hermes/.env`. **OpenRouter sem crédito** (402/429) e **Gemini-2.0-Flash** com quota diária estourada
   → usar Gemini-2.5-Flash-Lite (barato/estável) como juiz e Mistral como fallback paralelo.

## Pendente (precisa de orçamento de tokens — NÃO forçado por decisão do Mestre)
T5 (gerar SQL de red flag — determinístico) e T6 (parecer Lex) ficaram sem rodar. O harness
(`tools/benchmark_runner.py`) está pronto: com crédito/quota, completa T1–T6 automaticamente.
