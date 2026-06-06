# Benchmark das IAs do ecossistema — modelo × tarefa (parcial, 2026-06-06)

Baseline = **Claude Opus 4.8** (gold em `data/benchmark_ias_gold.json`). Score 0–3. Run via OpenRouter com as
chaves válidas (sincronizadas do Hermes; as do `JFN/.env` estavam truncadas/inválidas → 401).

## Resultado VÁLIDO — T1 (Yoda: roteamento "linguagem natural → rota do barramento")
Entrada: *"quanto a MGS recebeu da saúde?"* — gold: chamar `/api/relatorio/inteligencia {empresa:MGS}`, sem inventar ferramenta.

| Modelo | T1 | Veredito |
|---|---:|---|
| **Gemini-2.5-Pro** | **3** | acertou a rota, sem inventar ferramenta |
| **Gemini-2.5-Flash-Lite** | **3** | acertou |
| Qwen-2.5-72B | 1 | parcial (rota imprecisa) |
| Gemini-2.5-Flash | 0 | falhou (rota errada / inventou) |
| Gemini-3-Flash (preview) | 0 | falhou |
| Llama-3.3-70B | 0 | falhou |

## Aprendizado-chave (ponto a ponto vs Claude)
Na função de **roteamento**, os modelos *flash*/baratos e o Llama **falham** (inventam ferramenta ou erram a
rota); só **Pro e Flash-Lite** igualam o Claude. → Correção: guia com instrução estrita + exemplos para as IAs
fracas (`docs/IAS-FRACAS-GUIA.md`) e recomendação de **rotear "decisão de rota" para um modelo forte**
(Pro/Flash-Lite/Claude), deixando tarefas simples (resumo) para os baratos.

## Limitação HONESTA do run
T2/T5/T6 ficaram **incompletos**: a conta OpenRouter esgotou crédito no meio (HTTP **402** nos modelos pagos,
**429** nos `:free`), e o juiz-LLM (Gemini-2.5-Pro) passou a falhar. O **harness está pronto e correto**
(`tools/benchmark_runner.py`): com crédito recarregado (ou a chave Gemini direta, que tem quota diária) um run
completo gera este relatório + `benchmark_resultados.json` + `benchmark_ias.csv`. T5 é determinístico (compara o
SQL gerado com o banco) e independe de crédito de juiz.

## Como rodar (quando houver crédito/quota)
```
nohup .venv/bin/python tools/benchmark_runner.py > data/benchmark_run.log 2>&1 &
```
Roster (distintos, sem repetir versão): Gemini 2.5-Flash / 2.5-Flash-Lite / 2.5-Pro / 3-Flash, Qwen-2.5-72B,
Llama-3.3-70B. Juiz: Gemini-2.5-Pro (trocar por Flash-Lite se o orçamento for curto).
