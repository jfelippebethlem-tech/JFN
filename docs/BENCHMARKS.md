# BENCHMARKS — índice único das avaliações do ecossistema

> Porta de entrada para TODO benchmark/avaliação de IA e de produto do JFN.
> Regra: benchmark novo → registrar aqui (uma linha) + artefatos em `data/benchmark_*`.
> Referências EXTERNAS de elite (ALICE/ADELE, ARACHNE/OCP/CRI, screens OCDE/CADE, design Palantir/Linear): **`docs/BENCHMARKS-EXTERNOS.md`** (pesquisa 2026-07-19).

## 1. Benchmarks de IA (modelo × função)

| Avaliação | Data | Artefatos | Estado |
|---|---|---|---|
| **Modelo × função (T1 roteamento, T2 JSON)** — 6 modelos vs baseline Claude | 2026-06-06 | `data/benchmark_relatorio.md` (síntese) · `data/benchmark_ias.csv` · `data/benchmark_resultados.json` · gold: `data/benchmark_ias_gold.json` | T1/T2 feitos; **T5 (SQL) e T6 (parecer Lex) pendentes** de cota — harness pronto: `tools/benchmark_runner.py` |
| **Perícia 4-vias (proc. SEI 762/2021 ITERJ×MGS)** — Lex-fraco × Groq-70B × Hermes+RAG × Fable(gabarito), medidos contra veredito-ouro | 2026-06/07 | `data/pericia_762_comparativo.md` · lições: `~/vault/aprendizados/instruir-ias-fracas-licoes.md` | Concluído — 10 lições aplicadas (payload ≤8k, RAG carrega vereditos, armadilha temporal de certidões) |
| **Perícia bombeiros 4-camadas** (scorer calibrado + portão determinístico) | 2026-06-28 | `reports/_pericia_bombeiros_reconciliacao.json` · ledger: `~/vault/aprendizados/jedi-loop-treino-ias.md` | Concluído — 37 achados, 28 confirmados (loop jedi-audit) |
| **IA ingênua × instruída (fachada/fantasma)** | 2026-06 | memória `fachada-fantasma-e-ia-fraca` (84% → 91% com gabarito em código) | Concluído |

## 2. Metodologia e catálogo

- **`docs/IAS-ECOSSISTEMA-BENCHMARK.md`** — quem executa (catálogo de modelos, ATUALIZADO: Gemini OFF), regras de ouro p/ IA fraca, bateria T1–T6, loop de 5 passos.
- **`docs/IAS-FRACAS-GUIA.md`** — como instruir as IAs fracas (aplicação das lições).
- **`compliance_agent/benchmark_ias.py`** — arcabouço (gold/score/painel) · **`tools/benchmark_runner.py`** — runner T1–T6.
- **`compliance_agent/eval_groundtruth.py`** — avaliação contra casos-ouro da memória pericial.

## 3. Benchmarks/qualidade de PRODUTO (documentos gerados)

- Produtos entregáveis e geradores: **`reports/LEIAME.md`** (índice; raiz = versão mais recente, `arquivo/AAAA-MM/` = histórico).
- Padrão de qualidade exigido: estética Kroll/Deloitte (CLAUDE.md REGRA #1) — capa, seções numeradas, R$ com milhar, rating 🔴🟡🟢 com escala explícita.
- Verificação de honestidade dos produtos: `audit_fairness_pericia` (perícia benefícios) · guards de `duplicidade_competencia`.

## 4. Decisões vigentes extraídas dos benchmarks

1. **Não há "melhor modelo" único** — escolher por função (roteamento: instrução estrita > tamanho; JSON: Mistral-Large/força).
2. **Sweep em volume = stepfun:free** (única IA do sweep); **produtos = cadeia de qualidade** (cerebras/groq enquanto Gemini OFF).
3. **Gabarito determinístico em código > prompt** para IA fraca (fases.py; +7pp de acerto).
4. **RAG deve carregar VEREDITOS** (não só hipóteses) — evita re-acusar o que já foi refutado.
5. **Proveniência real do modelo** gravada em `lex_execucao`/`lex_pesquisa` via `direcionamento_cerebro.ultimo_provedor` (fix 2026-07-06; antes gravava "gemini" fixo).
