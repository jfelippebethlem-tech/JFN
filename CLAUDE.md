# CLAUDE.md — JFN (ENXUTO · injetado a cada turno)

**JFN** = motor de auditoria/compliance do Estado do RJ (TCE-RJ/controle externo). Owner: jfelippebethlem-tech ·
branch **`feat/lista-limpa`** · VM Linux Oracle Cloud ARM (`jfn-core`, 2 vCPU · 11,6GB · 4GB swap), `~/JFN`.

> **Detalhe vive fora daqui** (leveza — não duplicar): hub **`docs/REFERENCIA-PROJETO.md`** (estado/roadmap/lições/§10
> log/§11 retomada — *"continue pelo docs/REFERENCIA-PROJETO.md"*) · jurídico/orçamentário completo
> **`docs/CLAUDE-REFERENCIA-COMPLETA.md`** · índice de temas **`docs/INDEX.md`** · ambiente **`AMBIENTE.md`**/`ambiente.json`.

## REGRAS ABSOLUTAS
1. **Estética Kroll/Deloitte:** capa, seções numeradas, tabelas alinhadas, rating 🔴🟡🟢+score, R$ milhar+2 casas, fontes citadas. Nada feio.
2. **OB (Ordem Bancária) = pagamento = verdade.** Empenho ≠ pagamento — nunca citar empenho como "total pago".
3. **Credenciais só em `.env`/secrets** (gitignored), nunca em código/log/git (`os.environ.get`); `auth.json` nunca versionar.
4. **Git:** sem force-push sem ok; commit por unidade (sem spam); msg semântica; `Co-Authored-By: Claude Opus 4.8`.
5. **Contexto/cota:** cortar só DESPERDÍCIO (reler o que já está no contexto, pollar subprocesso, dump grande), nunca profundidade. Ler grande em PARTES (offset/limit); grep/tail > dump. Pesado → background. Salvar cedo; nunca despachar pela metade.
6. **Honestidade:** indício ≠ acusação; INDISPONÍVEL ≠ 0; nunca inventar número; presunção de regularidade; score = indício interno; CPF de sócio mascarado (LGPD).

## ECOSSISTEMA
**Yoda** (Telegram, `~/hermes-agent`, `hermes-gateway.service`) = maestro → aciona o JFN pela **API `127.0.0.1:8000`**
(`server.py`, `jfn.service`). Capacidades = **`capabilities.yaml`** (fonte única) → `/api/lista`.
**Produtos** (md+pdf+xlsx): `/relatorio` fornecedor (`reporting/inteligencia.py`) + **Lex** (`lex.py`, 🟢🟡🔴) ·
`/orgao` (`reporting/inteligencia_orgao.py`) + Lex de órgão · **Dossiê** · **Massare**. Resolvem por nome/CNPJ/UG
(ambíguo → `{ambiguo,pergunta,candidatos}`); `/relatorio` e `/orgao` são ASSÍNCRONOS (empurram os docs no Telegram).

## LLM (isolamento de qualidade)
- **Sweep SEI** (triagem + raciocínio de fraude, em volume) → **nous `stepfun:free`** (ilimitado/grátis; ÚNICA IA do sweep). **Cerebras nunca no volume do sweep.**
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** (qualidade) + **cerebras** (rede de segurança).
- **Pool free_llm e Yoda** → cerebras + gemini (redundância). Chaves em `.env`/`auth.json`.

## FATOS-CHAVE
- **DB** `data/compliance.db`: `ordens_bancarias` (OB 2019-2026, ~1,12M, 77% c/ CNPJ); `favorecido_cpf` = CNPJ(14)/CPF(11).
- **UG tem 2 numerações** (TFE 6díg vs SIAFE-Rio 2); **ITERJ=`133100`**. Órgão resolve pelo CÓDIGO (`compliance_agent/ugs.py` + `data/ug_canonico.json`), não pelo texto da OB.
- **SIAFE-Rio 2:** WAF bloqueia IP não-gov (acessa por login). `siafe_runner diario` (cron 05:00, incremental) + backfill. Exercícios 2024=3/2025=2/2026=1.
- **SEI sweep** (`tools/sei_sweep.py` + `sei_supervisor.sh`, resumível, login itkava): ficha (`sei_ficha.py`, nous) inventaria docs (edital/contrato/parecer) + red flags. Correlação OB↔SEI: `correlacao_sei.py`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **JFN** (8700 symbols, 21118 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/JFN/context` | Codebase overview, check index freshness |
| `gitnexus://repo/JFN/clusters` | All functional areas |
| `gitnexus://repo/JFN/processes` | All execution flows |
| `gitnexus://repo/JFN/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
