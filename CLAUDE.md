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
7. **Não crashar a VM:** 1 pesado por vez; suíte SEMPRE em lotes (`tools/ci_lote.py`, nunca monolítica — já caiu 4×); `pgrep`+`kill` por PID, **nunca `pkill -f`**.

## ECOSSISTEMA
**Yoda** (Telegram) → aciona o JFN pela API `127.0.0.1:8000` (`server.py` + `rotas/`).
**Produtos** (md+pdf+xlsx): `/relatorio` fornecedor · `/orgao` · **Dossiê** · **Lex** (parecer 🟢🟡🔴).
Resolvem por nome/CNPJ/UG (ambíguo → `{ambiguo,pergunta,candidatos}`); são **assíncronos** (empurram no Telegram).
Fonte única de capacidades: **`capabilities.yaml`** — derivados (`data/jfn_tools.json`, `docs/CAPACIDADES.md`,
`static/js/caps.js`) são REGENERADOS pelo pre-commit; nunca editar à mão.
> Caminho/callers de qualquer símbolo → `gitnexus_context({name})`. Mecânica do barramento → `docs/REFERENCIA-PROJETO.md` §4.

## LLM (isolamento de qualidade)
- **Sweep SEI** (volume) → **nous `stepfun:free`** (única IA do sweep). **Cerebras nunca no volume.**
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** + **cerebras** (rede de segurança).
- **Pool free_llm e Yoda** → cerebras + gemini. Chaves em `.env`/`auth.json`.

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

This project is indexed by GitNexus as **JFN** (41847 symbols, 61806 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

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
