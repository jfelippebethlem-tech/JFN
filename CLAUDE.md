# CLAUDE.md — JFN (ENXUTO · injetado a cada turno)

**JFN** = motor de auditoria/compliance do Estado do RJ (TCE-RJ/controle externo). Owner: jfelippebethlem-tech ·
branch **`feat/fiscalizacao-emendas-pcrj`** · VM Linux Oracle Cloud ARM (`jfn-core`, 2 vCPU · 11,6GB · 4GB swap), `~/JFN`.

> **Detalhe vive fora daqui** (leveza — não duplicar): hub **`docs/REFERENCIA-PROJETO.md`** (estado/roadmap/lições/§10
> log/§11 retomada — *"continue pelo docs/REFERENCIA-PROJETO.md"*) · jurídico/orçamentário completo
> **`docs/CLAUDE-REFERENCIA-COMPLETA.md`** · índice de temas **`docs/INDEX.md`** · ambiente **`AMBIENTE.md`**/`ambiente.json`.

## REGRAS ABSOLUTAS
1. **Estética Kroll/Deloitte:** capa, seções numeradas, tabelas alinhadas, rating 🔴🟡🟢+score, R$ milhar+2 casas, fontes citadas. Nada feio.
2. **OB (Ordem Bancária) = pagamento = verdade.** Empenho ≠ pagamento — nunca citar empenho como "total pago".
3. **Credenciais só em `.env`/secrets** (gitignored), nunca em código/log/git (`os.environ.get`); `auth.json` nunca versionar.
4. **Git:** sem force-push sem ok; commit por unidade (sem spam); msg semântica; `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
5. **Contexto/cota:** cortar só DESPERDÍCIO (reler o que já está no contexto, pollar subprocesso, dump grande), nunca profundidade. Ler grande em PARTES (offset/limit); grep/tail > dump. Pesado → background. Salvar cedo; nunca despachar pela metade.
6. **Honestidade:** indício ≠ acusação; INDISPONÍVEL ≠ 0; nunca inventar número; presunção de regularidade; score = indício interno; CPF de sócio mascarado (LGPD).

## ECOSSISTEMA
**Yoda** (Telegram, maestro) → aciona o JFN pela **API `127.0.0.1:8000`** (`server.py`). **Produtos** (md+pdf+xlsx):
`/relatorio` fornecedor (`inteligencia`) + **Lex** (`lex`, 🟢🟡🔴) · `/orgao` (`inteligencia_orgao`) + Lex de órgão ·
**Dossiê**. (Massare saiu da VM 2026-07-07 — vive só no GitHub.) Resolvem por **nome/CNPJ/UG** (ambíguo → `{ambiguo,pergunta,candidatos}`); `/relatorio`,
`/orgao`, `/dossie` são ASSÍNCRONOS (empurram os docs no Telegram).
> Caminho/callers de QUALQUER símbolo (`inteligencia`/`inteligencia_orgao`/`lex`/`correlacao_sei`/`ugs`) →
> `gitnexus_context({name})`. Mecânica do barramento (capabilities.yaml→`/api/lista`, fluxo assíncrono Telegram,
> lista de produtos, caminhos canônicos) → `docs/REFERENCIA-PROJETO.md` §4 / `docs/CAPACIDADES.md` sob demanda.

## LLM (isolamento de qualidade)
- **Sweep SEI** (triagem + raciocínio de fraude, em volume) → **nous `stepfun:free`** (ilimitado/grátis; ÚNICA IA do sweep). **Cerebras nunca no volume do sweep.**
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** (qualidade) + **cerebras** (rede de segurança).
- **Pool free_llm e Yoda** → cerebras + gemini (redundância). Chaves em `.env`/`auth.json`.

## FATOS-CHAVE (invariantes sempre-on; resto sob demanda)
- **DB principal = `data/compliance.db`** (`ordens_bancarias`=OB TFE; `ob_orcamentaria_siafe`=OB SIAFE rica c/ NL/RE/PD/processo). **ITERJ = UG `133100`**.
- 🧭 **NÃO REINVENTAR (gatilhos; detalhe no vault):** (1) **OB/pagamento → SEMPRE SIAFE direto, nunca o espelho TFE** (`siafe_ob_orcamentaria --por-ug`/`coletar_obs_sessao`); (2) **relatório/dossiê = produto da casa** `reporting/inteligencia.py` + `render_html`/`html_to_pdf` (Kroll, PDF) — nunca .txt à mão; (3) **processo SEI = ARQUIVO primeiro** — `tools/sei_consultar.py` (texto+fases+fotos de medição em `data/sei_arquivo/`, grátis) antes de browser/IA; caminho único `docs/PLAYBOOK-SEI.md`; (4) **duplicidade de contrato contínuo = lente de COMPETÊNCIA** (não valor): `compliance_agent/duplicidade_competencia.py` (guards: lag, dez lag-0, split=mesmo RE, reajuste-complemento, renovação ≠ ano civil) — só a NF fecha; (5) **vício de licitação → catálogo canônico primeiro** `knowledge/catalogo_vicios.py` (40 vícios, `lacunas()` declaradas) + graus de flag `editais/flags.grau_flag` (LLM nunca produz flag CERTO) + escalada `editais/escalada.recomendar()` — plano-mestre `docs/superpowers/plans/2026-07-20-dossie-mestre.md`. Notas: `~/vault/codigo/relatorio-pipeline.md` · `~/vault/aprendizados/{fonte-ob-sempre-siafe-nunca-tfe,duplicidade-ob-competencia-vs-valor}.md` · `~/vault/casos/iterj-mgs-clean-pagamentos.md`.
- Fatos de dados (DB schema/colunas · dupla numeração de UG · SIAFE-Rio 2/WAF · SEI sweep) → `docs/INDEX.md` /
  `docs/CLAUDE-REFERENCIA-COMPLETA.md` (§"FATOS DE DADOS" e §"UGs Relevantes") sob demanda. Símbolos no código → `gitnexus_context({name})`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **JFN** (29290 symbols, 44502 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
