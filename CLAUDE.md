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
**Yoda** (Telegram, maestro) → aciona o JFN pela **API `127.0.0.1:8000`** (`server.py`). **Produtos** (md+pdf+xlsx):
`/relatorio` fornecedor (`inteligencia`) + **Lex** (`lex`, 🟢🟡🔴) · `/orgao` (`inteligencia_orgao`) + Lex de órgão ·
**Dossiê** · **Massare**. Resolvem por **nome/CNPJ/UG** (ambíguo → `{ambiguo,pergunta,candidatos}`); `/relatorio`,
`/orgao`, `/dossie` são ASSÍNCRONOS (empurram os docs no Telegram).
> Caminho/callers de QUALQUER símbolo (`inteligencia`/`inteligencia_orgao`/`lex`/`correlacao_sei`/`ugs`) →
> `gitnexus_context({name})`. Mecânica do barramento (capabilities.yaml→`/api/lista`, fluxo assíncrono Telegram,
> lista de produtos, caminhos canônicos) → `docs/REFERENCIA-PROJETO.md` §4 / `docs/CAPACIDADES.md` sob demanda.

## LLM (isolamento de qualidade)
- **Sweep SEI** (triagem + raciocínio de fraude, em volume) → **nous `stepfun:free`** (ilimitado/grátis; ÚNICA IA do sweep). **Cerebras nunca no volume do sweep.**
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** (qualidade) + **cerebras** (rede de segurança).
- **Pool free_llm e Yoda** → cerebras + gemini (redundância). Chaves em `.env`/`auth.json`.

## FATOS-CHAVE (invariantes sempre-on; resto sob demanda)
- **DB principal = `data/compliance.db`** (tabela `ordens_bancarias` = OB = pagamento). **ITERJ = UG `133100`** (TFE).
- Fatos de dados (DB schema/colunas · dupla numeração de UG · SIAFE-Rio 2/WAF · SEI sweep) → `docs/INDEX.md` /
  `docs/CLAUDE-REFERENCIA-COMPLETA.md` (§"FATOS DE DADOS" e §"UGs Relevantes") sob demanda. Símbolos no código → `gitnexus_context({name})`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence (uso sob demanda)
JFN indexado (MCP `gitnexus_*` + CLI `npx gitnexus`). **Antes de editar um símbolo:** `gitnexus_impact({target, direction:'''upstream'''})` (blast radius; parar em HIGH/CRITICAL). **Antes de commitar:** `gitnexus_detect_changes()`. Renomear → `gitnexus_rename`. Explorar → `gitnexus_query`/`gitnexus_context`. Detalhe nas skills `.claude/skills/gitnexus/*`. Stale → `npx gitnexus analyze`.
<!-- gitnexus:end -->
