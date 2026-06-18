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
# GitNexus — Code Intelligence (uso sob demanda)
JFN indexado (MCP `gitnexus_*` + CLI `npx gitnexus`). **Antes de editar um símbolo:** `gitnexus_impact({target, direction:'upstream'})` (reportar blast radius; parar em HIGH/CRITICAL). **Antes de commitar:** `gitnexus_detect_changes()`. Renomear → `gitnexus_rename` (não find-replace). Explorar → `gitnexus_query`/`gitnexus_context`. Detalhe nas skills `.claude/skills/gitnexus/*/SKILL.md`. Índice stale → `npx gitnexus analyze`.
<!-- gitnexus:end -->
