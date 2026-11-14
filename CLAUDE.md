# CLAUDE.md — JFN (ENXUTO · injetado a cada turno)

**JFN** = motor de auditoria/compliance do Estado do RJ (TCE-RJ/controle externo). Owner:
jfelippebethlem-tech · VM Oracle ARM `jfn-core` (2 vCPU · 11,6 GB · 4 GB swap), `~/JFN`.
**A branch de trabalho é a que `git branch --show-current` disser** — não fixar aqui: já esteve
obsoleta por semanas (dizia `feat/fiscalizacao-emendas-pcrj` enquanto a real era `feat/painel-v15-holo`).

> **Detalhe vive fora daqui** (leveza — não duplicar): hub **`docs/REFERENCIA-PROJETO.md`**
> (estado/roadmap/lições/§10 log/§11 retomada) · jurídico/orçamentário **`docs/CLAUDE-REFERENCIA-COMPLETA.md`**
> · índice de temas **`docs/INDEX.md`** · ambiente **`AMBIENTE.md`** · falhas conhecidas
> **`~/vault/aprendizados/CATALOGO-DE-FALHAS.md`** · como o sistema funciona **`~/vault/COMO-O-SISTEMA-FUNCIONA.md`**.

## REGRAS ABSOLUTAS
1. **Estética Kroll/Deloitte:** capa, seções numeradas, tabelas alinhadas, rating 🔴🟡🟢+score, R$ milhar+2 casas, fontes citadas.
2. **OB (Ordem Bancária) = pagamento = verdade.** Empenho ≠ pagamento — nunca citar empenho como "total pago".
3. **Credenciais só em `.env`/secrets** (gitignored), nunca em código/log/git; `auth.json` nunca versionar.
4. **Git:** sem force-push sem ok; commit por unidade; msg semântica. Nunca `&&` depois de comando git com pipe (o pipe mascara o exit code — já acertou a branch errada).
5. **Contexto/cota:** cortar DESPERDÍCIO, nunca profundidade. Ler grande em PARTES; grep/tail > dump. Pesado → background. Salvar cedo.
6. **Honestidade:** indício ≠ acusação; **INDISPONÍVEL ≠ 0**; nunca inventar número; presunção de regularidade; score = indício interno; CPF de sócio mascarado (LGPD). Onde a casa corta lista, perguntar **quais** N, nunca só **quantos**.
7. **Portão de pre-push:** `tools/pre_push_gate.sh` roda catracas + testes casados com o que muda ANTES do push (1,4 s no mínimo). CI vermelho vira e-mail para o dono — consertar depois do e-mail é tarde. Acima de load 6 ele DECLARA que não mediu; `--no-verify` só com motivo escrito no commit seguinte.
8. **Não crashar a VM:** 1 pesado por vez; suíte SEMPRE em lotes (`tools/ci_lote.py`, nunca monolítica — já caiu 4×); `pgrep`+`kill` por PID, **nunca `pkill -f`**.
9. **Regras de qualidade (projeto de governo, sem margem para erro):** antes de criar/mudar card, rota, detector, perícia, relatório, resposta do Yoda ou peça do Lex, seguir **`docs/REGRAS-DE-QUALIDADE.md`** (70 regras: padrão, conformidade, correção, constância, subjetivas; fonte `config/qualidade_regras.yaml`). Mínimo: proveniência + estado (VERIFICADO/PENDENTE/INDISPONÍVEL) em todo número; 🔴/🟡 só com prova primária citada e conferida por código; detector com controle positivo **e** negativo; superfície nova entra em `config/qualidade_inventario.yaml`. Catracas `tests/test_regra_*.py` barram; estado em `/api/qualidade/conformidade`; juiz só pela assinatura (`backend="cli"`).

## ECOSSISTEMA
**Yoda** (Telegram) → aciona o JFN pela API `127.0.0.1:8000` (`server.py` + `rotas/`).
**Produtos** (md+pdf+xlsx): `/relatorio` fornecedor · `/orgao` · **Dossiê** · **Lex** (parecer 🟢🟡🔴).
Resolvem por nome/CNPJ/UG (ambíguo → `{ambiguo,pergunta,candidatos}`); são **assíncronos** (empurram no Telegram).
Fonte única de capacidades: **`capabilities.yaml`** — derivados (`data/jfn_tools.json`, `docs/CAPACIDADES.md`,
`static/js/caps.js`) são REGENERADOS pelo pre-commit; nunca editar à mão.
> Caminho/callers de qualquer símbolo → `gitnexus_context({name})`. Mecânica do barramento → `docs/REFERENCIA-PROJETO.md` §4.

## LLM (isolamento de qualidade · remontado 09/11/2026 por bench medido)
- **Sweep SEI** (volume) → **nous `MODELOS_SWEEP`** (`sei_ficha`: beam-1.0:free → longcat-2.5:free, troca sozinha se um morrer).
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** 3-flash-preview→3.6→3.5→2.5 (flash-lite fora do parecer) → groq → openrouter:free → nvidia → cohere.
- **Pool free_llm** → gemini → groq qwen3.8 (só curto, 413 >8k) → openrouter:free → nvidia (reserva) → cloudflare → cohere → zai.
- **Mortos/pagos fora** (`FREE_LLM_DESLIGADOS`): cerebras, github_models, sambanova, siliconflow, wisdomgate, mistral. Chaves em `.env`/`auth.json`.

## FATOS-CHAVE (invariantes; resto sob demanda)
- **DB principal = `data/compliance.db`** (`ordens_bancarias`=OB TFE; `ob_orcamentaria_siafe`=OB SIAFE rica). **ITERJ = UG `133100`**.
- 🧭 **NÃO REINVENTAR** (gatilhos; detalhe no vault):
  1. **OB/pagamento → SEMPRE SIAFE direto, nunca o espelho TFE** (`siafe_ob_orcamentaria --por-ug`).
  2. **Relatório/dossiê = produto da casa** `reporting/inteligencia.py` + `render_html`/`html_to_pdf` — nunca .txt à mão.
  3. **Processo SEI = ARQUIVO primeiro** — `tools/sei_consultar.py` (texto+fases+fotos em `data/sei_arquivo/`) antes de browser/IA; caminho único `docs/PLAYBOOK-SEI.md`.
  4. **Duplicidade de contrato contínuo = lente de COMPETÊNCIA** (não valor): `duplicidade_competencia.py` — só a NF fecha.
  5. **Vício de licitação → catálogo canônico primeiro** `knowledge/catalogo_vicios.py` + `editais/flags.grau_flag` + `editais/escalada.recomendar()`.
  6. **Pacote completo por CNPJ = `/api/dossie/completo`**. TODO entregável passa pelo gate `reporting/neutralidade.garantir_neutro`.
  7. **Limite de fonte → `compliance_agent/limites_de_fonte.py`** ANTES de reprogramar coleta: diz o que a fonte não tem e o que já falhou (LexML/TCU respondem **200 com HTML de WAF**; PNCP não publica ata nem proposta de perdedor; DataJud só tem metadado).
  8. **Detector novo → conferir se já existe e tem caller.** `grep` por callers + `COUNT(*)` na tabela que ele consome: já houve 6 casos de "construído, testado, nunca rodado".
- **Enxame** (`editais_direcionamento --so-rj`) **só OFF-HOURS** — escrever no compliance.db TRAVA as rotas de leitura do painel.
- Schema/colunas · dupla numeração de UG · SIAFE-Rio 2/WAF · sweep SEI → `docs/INDEX.md` e `docs/CLAUDE-REFERENCIA-COMPLETA.md` sob demanda.

<!-- O bloco abaixo é GERADO por `npx gitnexus analyze` e regravado a cada índice novo.
     Eu havia escrito uma versão condensada aqui; o analyze acrescentou a dele por baixo e o
     custo DOBROU no arquivo que entra em todo turno. Lição: não competir com bloco gerado —
     `tools/gitnexus_enxugar.sh` (chamado pelo pre-commit) mantém o AGENTS.md como ponteiro. -->
<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **JFN** (29042 symbols, 66506 relationships, 664 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/JFN/context` | Codebase overview, check index freshness |
| `gitnexus://repo/JFN/clusters` | All functional areas |
| `gitnexus://repo/JFN/processes` | All execution flows |
| `gitnexus://repo/JFN/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
