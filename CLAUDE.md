# CLAUDE.md — JFN Intelligence Engine (ENXUTO)

**JFN** = motor + barramento de auditoria/compliance do Estado do RJ (TCE-RJ/controle externo).
Owner: jfelippebethlem-tech · Branch de trabalho: **`feat/lista-limpa`** · VM Linux GCP, `~/JFN`.

> **Este arquivo é injetado a CADA turno — manter ENXUTO (economia de contexto).** Detalhe em:
> - **`docs/REFERENCIA-PROJETO.md`** — DOCUMENTO ÚNICO (estado vivo, roadmap, acertos/erros, §10 log por
>   sessão, §11 RETOMADA). **Sessão nova: "continue pelo docs/REFERENCIA-PROJETO.md".**
> - **`docs/CLAUDE-REFERENCIA-COMPLETA.md`** — conhecimento jurídico/orçamentário completo (modalidades,
>   ilícitos, controle externo, CEIS/CNEP, matriz TCU P×I, estrutura SIAFE, UGs, padrão de relatório, multiplataforma).
> - **`AMBIENTE.md`** / `ambiente.json` — onde tudo roda + boot.

---

## REGRAS ABSOLUTAS

1. **Estética impecável** (Kroll/Deloitte): capa, seções numeradas, tabelas alinhadas, rating 🔴🟡🟢 com score,
   R$ com milhar+2 casas, fontes citadas. Nada funcional-mas-feio.
2. **OB (Ordem Bancária) = pagamento = verdade.** Empenho ≠ pagamento; nunca citar empenho como "total pago".
3. **Credenciais só em `.env`/secrets** (gitignored), nunca em código/log/git; `os.environ.get(...)`. `auth.json` nunca versionar.
4. **Git:** sem force-push sem ok; commit por unidade relevante (sem spam); msgs semânticas; Co-Authored-By: Claude Opus 4.8.
5. **Contexto/cota:** cortar só DESPERDÍCIO (reler arquivo já em contexto, pollar subprocesso, dump grande),
   nunca profundidade. **Ler arquivos grandes em PARTES (offset/limit); grep/tail em vez de dump.** Offload pesado
   p/ background. Salvar estado cedo; nunca despachar pela metade. Sessão muito longa cai por contexto → recomeçar limpo.
6. **Honestidade:** indício, nunca acusação; INDISPONÍVEL ≠ 0; nunca inventar número; presunção de regularidade;
   score = indício interno; CPF de sócio mascarado (LGPD).

## ECOSSISTEMA & BARRAMENTO

**Yoda** (Telegram, `~/hermes-agent`, `hermes-gateway.service`) = maestro → aciona o JFN pela **API
`127.0.0.1:8000`** (`server.py`, `jfn.service`). Rotas: `POST /api/relatorio/inteligencia` (fornecedor),
`/api/relatorio/orgao` (órgão), `GET /api/ugs` (/UG), `/api/sweeps/status`, `/api/siafe/stats`,
`/api/compliance/investigar` (pesquisa web). Capacidades = **`capabilities.yaml`** (fonte única) → `/api/lista`.

**Produtos** (md+pdf+xlsx): `/relatorio` fornecedor (`reporting/inteligencia.py`) + parecer **Lex** (`lex.py`,
grau 🟢🟡🔴); `/orgao` (`reporting/inteligencia_orgao.py`) + Lex de órgão; **Dossiê** (`dossie.py`); **Massare**.
Resolvem por nome/CNPJ/UG; ambíguo → `{ambiguo, pergunta, candidatos}`. /relatorio e /orgao são ASSÍNCRONOS
(respondem "gerando" e o JFN empurra os docs no Telegram).

## LLM — ALOCAÇÃO (importante)

- **Sweep do SEI** (triagem mecânica **E o raciocínio sobre direcionamento/fraude**) → **nous `stepfun:free`**
  (ilimitado/100% grátis). É a ÚNICA IA do volume do sweep. **Cerebras NÃO é ilimitado → nunca no volume do sweep.**
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** (qualidade) + **cerebras** como rede de segurança (nunca caem).
- **Pool free_llm e Yoda** → **cerebras + gemini** (redundância/fallback). Chaves no `.env`/auth.json.

## FATOS-CHAVE

- **DB** `data/compliance.db`: `ordens_bancarias` (OB 2019-2026, ~1,12M, 77% c/ CNPJ). `favorecido_cpf`=CNPJ(14)/CPF(11).
- **Duas numerações de UG**: TFE (6 díg) vs SIAFE-Rio 2. **ITERJ = `133100`** (TFE)=270042. Órgão resolve pelo
  CÓDIGO (`compliance_agent/ugs.py` + `data/ug_canonico.json`), não pelo texto da OB.
- **SIAFE-Rio 2**: WAF bloqueia IP não-gov (VM acessa por login). `siafe_runner diario` (cron 05:00, incremental)
  + `siafe_sweep_full` (backfill supervisionado). Exercícios: 2024="3",2025="2",2026="1".
- **SEI sweep** (`tools/sei_sweep.py` + `sei_supervisor.sh`, resumível): lê processo a processo (login itkava);
  ficha (`sei_ficha.py`, nous) inventaria docs (edital/contrato/parecer/anexos) + red flags + raciocínio de
  direcionamento/fraude. Correlação OB↔SEI: `correlacao_sei.py` (campo Processo → `numero_sei`).

> Operacional/jurídico completo: `docs/CLAUDE-REFERENCIA-COMPLETA.md` + `docs/REFERENCIA-PROJETO.md`.
