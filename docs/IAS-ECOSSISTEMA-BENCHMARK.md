# IAs do ecossistema — quem executa, como instruir e como comparar com o Claude (baseline)

> Diretriz eterna do Mestre Jorge: **a execução do dia a dia é feita por IAs mais fracas que o Claude** —
> elas precisam de instruções explícitas, idempotentes, passo a passo. Este doc (1) cataloga quais são,
> (2) define como escrever para elas, e (3) define um benchmark para comparar o trabalho delas com o do
> Claude Opus 4.8 (baseline), gerando um panorama de capacidades e de onde melhorar.

## 1. Quem executa (apurado em `~/.hermes/config.yaml` + `auth.json`)

> **⚠️ Atualização 2026-06-25:** o **Gemini está DESLIGADO** em todo o ecossistema (`GEMINI_DISABLED=1`
> no `JFN/.env` — billing cobrava fora do free tier; ver `~/vault` e memória `gemini-desligado-billing`).
> Onde a tabela diz "gemini", quem responde hoje é a cadeia **cerebras → groq → nvidia → openrouter:free**
> (14 elos, ver `~/.hermes/config.yaml`). Reverter só quando o billing for reposto.

| Papel no ecossistema | Modelo | Provider | Força relativa | Onde atua |
|---|---|---|---|---|
| **Baseline (referência)** | **Claude Opus 4.8** / Claude Code | Anthropic | ★★★★★ | arquitetura, código, parecer, planejamento (eu) |
| Yoda — default/conversa | ~~gemini-2.5-flash~~ → cadeia cerebras/groq | cerebras/groq | ★★★☆☆ | roteamento Telegram, resposta ao Jorge |
| Visão / OCR | ~~gemini-2.5-flash~~ → OCR local (tesseract/fitz) | local | ★★☆☆☆ | captcha SEI, PDFs/scan DOERJ/SIAFE |
| Principal (código/raciocínio, citado no config) | **Qwen 3.6** | (pool) | ★★★☆☆ | código, compliance, geral |
| Sweep SEI (volume) | stepfun/step-3.7-flash:free | nous | ★★☆☆☆ | triagem em volume (ÚNICA IA do sweep) |
| Fallback 2 | inclusionai/ring-2.6-1t:free | nous | ★★☆☆☆ | quando o principal falha |
| Fallback 3 | tencent/hy3-preview:free | nous | ★★☆☆☆ | idem |

## 2. Como escrever para a IA fraca (regras de ouro — aplicar em TODA skill/doc)
1. **Passos numerados e idempotentes** (rodar 2x sem efeito colateral: `IF NOT EXISTS`, cache por chave).
2. **Comando exato + caminho absoluto** (não "rode o coletor", e sim `curl -s http://127.0.0.1:8000/...`).
3. **Critério de sucesso explícito** ("se vier `ok:true`, faça X; se `ok:false`, diga Y") — não deixar a IA inferir.
4. **Travas de segurança repetidas** ("NUNCA pare o jfn.service"; "isto é indício, não acusação").
5. **Fonte única de verdade** (apontar para `AMBIENTE.md`/`ambiente.json`, não memorizar caminhos).
6. **Saída estruturada** (pedir JSON quando a IA for alimentar outra etapa — reduz erro de parsing).
7. **Um objetivo por skill** (a IA fraca erra mais com tarefas compostas).

## 3. Bateria de testes (tarefas REAIS do ecossistema)
Rodar a MESMA tarefa em cada IA e no Claude (baseline), com a mesma instrução, e comparar:

| # | Tarefa | Entrada | Saída esperada (verificável) |
|---|---|---|---|
| T1 | Roteamento NL → rota | "quanto a MGS recebeu da saúde?" | rota = `/api/relatorio/...` (não inventar ferramenta) |
| T2 | Resumir JSON de `/api/anomalias` | JSON com 10 itens | lista PT-BR com valor/fornecedor/score/red flag |
| T3 | Extrair OBs de uma tabela DOERJ/SIAFE | 1 página HTML/scan | nº de OBs, valores, fornecedores corretos (vs. gabarito) |
| T4 | OCR de captcha SEI | imagem | texto correto (taxa de acerto) |
| T5 | Escrever 1 regra SQL de red flag | enunciado | SQL que roda e bate com a contagem do Claude |
| T6 | Parecer de 1 parágrafo (mérito) | contexto de fornecedor | sem afirmar crime; cita fundamento; linguagem condicional |

## 4. Rubrica de comparação (0–3 por critério)
- **Correção** (bate com o gabarito/baseline do Claude?), **Aderência à instrução** (seguiu os passos?),
  **Segurança** (respeitou as travas? não inventou número/ferramenta?), **Formato** (saída no formato pedido?),
  **Custo/latência** (tokens/tempo). Score = média; o Claude define o teto (3,0) por tarefa.

## 5. Metodologia (loop de 5 passos — definição do Mestre Jorge)
1. **Passo 1 — GABARITO:** o **Claude (Opus 4.8) roda cada função de cada agente UMA vez**, substituindo as IAs
   fracas só nessa rodada. A saída vira o gold (`data/benchmark_ias_gold.json`).
2. **Passo 2 — REAL:** rodar o ecossistema inteiro nas **IAs fracas** (config normal: Gemini/Qwen/nous), capturando
   a saída de cada função (via Hermes/Telegram ou chamada ao provider).
3. **Passo 3 — COMPARAR:** gold × fraca por tarefa, pela rubrica §4 → `data/benchmark_ias.csv`.
4. **Passo 4 — MELHORAR:** onde divergiu, ajustar **instrução/processo** da IA fraca (mais passos, saída JSON,
   critério de sucesso, travas). Re-rodar (volta ao Passo 2) e medir o ganho.
5. **Passo 5 — DIA A DIA:** produção segue nas IAs fracas (custo), mas instruídas direito; roteador manda **tarefa
   crítica → modelo forte**, **tarefa simples → modelo barato**; aprender caso a caso como cada IA reage e iterar.

**Panorama esperado:** tabela modelo × tarefa com o gap vs. Claude; onde o gap é por **ambiguidade** → resolve com
instrução melhor; onde é por **capacidade** → roteia pro modelo forte. Harness: `compliance_agent/benchmark_ias.py`.

## 6. Hipóteses a confirmar com dados (não assumir)
- Gemini 2.5 Flash: bom em visão/OCR e resumo; fraco em raciocínio jurídico longo.
- Qwen 3.6: bom em código/SQL; precisa de instrução explícita p/ travas de honestidade.
- Fallbacks free: úteis só para tarefas simples; validar T1/T2 antes de confiar.
- **Conclusão de melhoria:** quanto mais estruturada e verificável a instrução (saída JSON + critério de sucesso),
  menor a diferença entre o Claude e a IA fraca. Onde a diferença persistir, é tarefa para o modelo forte.

> Atualizar `data/benchmark_ias.csv` a cada rodada. Relacionado: diretriz `diretriz-workflows-para-ias` (memória),
> `docs/ECOSSISTEMA-EVOLUCAO.md` (§Yoda: roteamento por regra antes do LLM, log de interação).
