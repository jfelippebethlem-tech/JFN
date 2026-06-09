# JFN — DOCUMENTO ÚNICO DE REFERÊNCIA DO PROJETO

> **Este é o ÚNICO documento de referência do projeto** (decisão do dono 2026-06-09). Consolida o que já foi
> tentado, acertos e erros, o roadmap, os gaps de qualidade e as best-practices. **Padrão daqui pra frente:
> manter SÓ este doc atualizado** (em vez de espalhar handoffs). Os docs antigos viram histórico/detalhe.
>
> **Como trabalhar (diretriz do dono):** quanto mais complexo, mais cuidado e DETALHISMO. A cada melhoria:
> (1) ler a documentação/o que já existe → (2) pesquisar best-practice da área → (3) planejar com visão global
> → (4) executar com **qualidade máxima** → (5) **testar e corrigir** → (6) **gerar os produtos reais e medir
> se a qualidade MELHOROU ou PIOROU** vs antes → (7) checkpoint+commit+atualizar ESTE doc. Nunca agir às cegas.
> Honestidade sempre: indício, nunca acusação; INDISPONÍVEL ≠ 0; nunca inventar número.

Última atualização: 2026-06-09.

---

## 1. VISÃO & NORTE
JFN = motor + barramento de **auditoria e compliance do Estado do RJ** (TCE-RJ/controle externo). Ecossistema:
**JFN** (relatórios/risco), **Lex** (parecer jurídico/tomada de contas), **Massare** (mercado/previsão),
**Yoda/Hermes** (bot Telegram = maestro, aciona o JFN pela API `127.0.0.1:8000`).
Norte: outputs **perfeitos** (padrão Kroll/Deloitte) · integrado/baixa-fricção · **grátis** (respeita a VM) ·
rápido/belo/sem ruído · **honesto** · sistema **pensante**. Regra-mãe: **OB (Ordem Bancária) = verdade de
pagamento**, nunca empenho.

## 2. ESTADO VIVO (onde tudo roda)
- **VM Linux GCP**, dir `~/JFN`. Branch de trabalho: **`feat/lista-limpa`** (não pushado; tudo commitado).
- **`jfn.service`** = user service (`systemctl --user restart jfn.service`); API em `127.0.0.1:8000`.
- **Bot**: `hermes-gateway.service` (Yoda, `~/hermes-agent`, venv=`venv/`). Default LLM = `gemini-2.5-flash`.
- **LLM válido**: Gemini (pool de 9 chaves em `~/.hermes/.env`/auth.json — rotação) + **nous (100% grátis/sem
  limite)** via auth.json (OAuth, token 15min auto-refresh). Groq/OpenRouter sem crédito.
- **Sweeps**: SIAFE 2 vivo (supervisor cron auto-relança; base `ob_orcamentaria_siafe` ~94k+ e subindo).
  SIAFE 1 = conta **ALERJ-only** (só o dono libera a chave p/ todas as UGs). **SEI sweep** novo (ver §6).
- **Cron**: manutenção dom 03:00; folha 06:00; siafe_runner diário 05:00; **massare.daily 06:15 + backtest
  dom 04:30** (Massare se cobra sozinho).
- DB: `data/compliance.db` (OB 2019-2026, 1.121.307 OBs, 77% c/ CNPJ). `favorecido_cpf`=CNPJ(14)/CPF(11).
  **UG 133100 = ITERJ** (mapa canônico `data/ug_canonico.json`).

## 3. O QUE ESTÁ PRONTO (produtos · coletores · infra)
**Produtos (barramento, 3 formatos md+pdf+xlsx):**
- **/relatorio** (fornecedor) — `reporting/inteligencia.py`: perfil, rede sócio×OB×SEI×endereço, pagamentos
  por ano (top-12), concentração HHI, contratos (SIAFE+TCE-RJ), matriz risco TCU P×I, red flags
  (RF-01..05 incl. **CNAE×objeto** e **troca de controle**), parecer + recomendações.
- **/orgao** — `reporting/inteligencia_orgao.py`: concentração por fornecedor, geográfica (honesta),
  **pagamentos recorrentes idênticos (ACFE)**, marcação de transferências intergov, parecer.
- **Lex** — `lex.py`: parecer jurídico (achados R2/R3/R5/R6/R7/R8/R9/R10/R11/R12, dosimetria, encaminhamento
  por severidade), análise discursiva via **gemini** sobre o SEI; lê a íntegra do cache cdp_*.json.
- **Dossiê 360** — `dossie.py`: cadastro+sanções+rede+conflito TSE+OB+**red flags estruturais** no score.
- **Massare** — backtest OOS (356k pregões), edge vs taxa-base, `/placar` honesto, teses c/ track record.
- **Yoda** — `/lista` curado (Massare/SIAFE incluídos), wiring por capabilities.yaml.

**Coletores/base:** TFE OB (1,1M), SIAFE 1+2 (23 colunas ricas), TSE 542k doações, PNCP (itens/preço),
correlação OB↔SEI, grafo de poder, CEIS/CNEP (ver gap em §5), mídia adversa GDELT (keyless).

**Infra/qualidade (sessão 2026-06-09):** `pyproject.toml` (ruff/pytest/coverage), `tests/conftest.py`
(marker network), **golden numbers** (`tests/test_golden_numbers.py`), **scorecard** (`tools/scorecard.py`),
gate de lint no pre-commit, ruff 733→37, suíte ~299 verde. `entidades_gov.py` (classificador intra-gov
compartilhado). Nome canônico de UG em 6 produtos.

## 4. ROADMAP / BACKLOG (de ECOSSISTEMA-EVOLUCAO.md, priorizado)
**P0 — Fundação:** quarentena de ingestão (Great Expectations: valor>0, CNPJ mód-11, UG no domínio, dedup por
hash OB) **ANTES de qualquer ML** · **proveniência** (fonte+timestamp+status; INDISPONÍVEL≠0) · score de
anomalia ensemble (PyOD ECOD+IForest) · 3 regras determinísticas (same-day split, concentração>30%,
fracionamento) · `/anomalias` (FEITO parcial) · camada DuckDB · roteamento por regra antes do LLM · log de
interação do Yoda · backup cifrado off-VM + rotacionar token git.
**P1 — Enriquecimento robusto:** cache+retry+**circuit breaker** no enriquecimento (ganha ~80% da
instabilidade) · fallback PNCP · **resolução de entidade (Splink, CNPJ-raiz+razão+endereço)** → destrava
grafo/concentração · detector de red-flags completo · Camoufox/stealth+proxy p/ TFE · replay HTTP SIAFE ·
proxy p/ SEI · cruzamento integra-SEI×OB + extração Docling/VLM · memória Mem0 no Yoda.
**P2 — Relacional/explicável:** grafo fornecedor-órgão (networkx→GNN) · **SHAP** no relatório · calibração por
UG + PU-learning · relatório agêntico · Agent SDK supervisor.
**Diferidos (decisão, não gap):** crypto_ws daemon; chaves grátis opcionais (reportam INDISPONÍVEL); wiring
slash no gateway vivo; split de god-files (Fase 3).

## 5. GAPS DE QUALIDADE CONHECIDOS
**Críticos:** Lex×SEI (precisa input SEI real — destravado nesta sessão, ver §6) · Massare hit-rate OOS (44
pendentes — mitigado pelo backtest + cron grade_due) · conluio intra-licitação (PNCP só expõe vencedor →
indetectável por dado público estruturado).
**Moderados:** OpenCorporates não existe · ExifTool wrapper (`enrich/exif.py`) não existe · paridade
render_md↔HTML (tabela mensal só no HTML) · `/lista` lento no gateway (fast-path pendente).
**⚠ Itens da lista que JÁ estavam feitos (corrigido 2026-06-09 cont.):** (a) **CNPJ matriz+filial**: o
/relatorio fornecedor JÁ consolida por raiz-8 (`inteligencia.py:213-339`, `LIKE raiz%`, representante=matriz
0001, quebra por estabelecimento — CC 44/985/1.142; STJ REsp 1.286.122). **Nuance de honestidade aberta:** não
há guarda contra raízes governamentais/placeholder (ex.: `00394460` Min. Economia 11 "filiais", `00000000`
Pasep) — consolidar essas como uma PJ privada seria errado; só importa se rodarem DD em CNPJ de governo. (b)
**Quarentena de ingestão**: JÁ existe (`anomalias.py:quarentena()` — valor≤0, sem favorecido, exercício nulo,
**CNPJ mód-11**, dup por chave de negócio). Porém a tabela `ob_quarentena` está **stale** (rodou 06-06, só marcou
valor≤0=32.752; CNPJ/dup atuais=0) e **não filtra os produtos**. Impacto medido na base inteira: 0 negativos,
0 sem-favorecido, **1 dup**, 32.597 valor=0 (somam R$ 0 → só inflam CONTAGENS, não os totais). Baixa alavancagem.
**Dívida técnica:** god-files server.py (1959), inteligencia.py (1789/1871), lex.py (1041) — split só
oportunístico. Sem mypy/coverage rodando ainda (instalados). Ruff baseline 37.

## 6. SEI — ESTADO (RESOLVIDO nesta sessão, 2026-06-09)
- **O reader LÊ processo a processo** (`tools/sei_reader.ler`, login itkava vence o flap do WAF; já é
  frame-aware via `_extrair_de_todos_frames` lendo ifrArvore/ifrVisualizacao). Provas: 330003/002534 → 10 docs.
  > ⚠️ O "WAF bloqueia tudo" anterior era **bug**: `pkill -f "siafe_sweep_full 2"` se auto-matava (padrão na
  > linha do shell → shell morria antes do reader rodar). LIÇÃO: pkill por padrão que aparece no próprio comando
  > se auto-mata (use `pgrep -f "sei[_]ficha"` com colchete ou kill por PID).
- **`tools/sei_sweep.py`** — varre os processos das OBs (42k distintos): **login único**, **scope-aware**
  (prioriza unidades que o itkava lê: 140001/270042/270060/330003/520003 — 1.303 processos in-scope),
  **retry** da abertura intermitente (sucesso=docs>0; relacionados-sozinho=caixa), **segue a ÁRVORE**
  (`seguir_relacionados`: pagamento→licitação/contrato), **resumível** (checkpoint), respeita browser_lock,
  `--cnpj <CNPJ>` pré-carrega o SEI de um fornecedor antes do /relatorio dele. Lento (~50s/proc) — "aos poucos".
- **`tools/sei_ficha.py`** — extrai do `conteudo_documentos` REAL (não do `texto`=menu lixo) uma **ficha-índice
  compacta** (storage ~3-7× menor). **ISOLAMENTO DE QUALIDADE (regra-mãe):** o **stepfun:free** (nous, grátis)
  só na MECÂNICA do sweep (triagem em massa); os **PRODUTOS** (/relatorio, /orgao, Lex) usam **gemini (forte)**.
  Detalhe: stepfun/nemotron são modelos de **RACIOCÍNIO** → `max_tokens` ALTO (4000) + ler o campo `reasoning`
  se `content` vier vazio (senão 502/sem-JSON). Token nous auto-refresh.

## 7. BEST-PRACTICES / BENCHMARKS (o padrão de qualidade)
- **Honestidade/dados:** OB=verdade; proveniência marcada; INDISPONÍVEL≠0; linguagem condicional ("merece
  apuração", nunca "houve fraude"); score=indício interno, nunca acusação pública; CPF de sócio mascarado (LGPD);
  base legal = atribuição do Poder Público.
- **Financeiro:** matriz P×I (1-9, Score=P×I, faixas Baixo/Médio/Alto/Extremo); red flags ACFE 2024
  (concentração≥60%, dispensas sob teto, aditivos>25/50%, gap empenho→liquidação>90d); sobrepreço por
  CATMAT/CATSER da época; pesquisa de preços ≥3 cotações, mediana se CV>25% (Ac. 1875/2021-TCU).
- **Estética (Kroll/Deloitte):** capa+10 seções+sumário, rating 🔴🟡🟢 c/ score, números milhar+2 casas, fontes
  citadas, ≥3 SVG vetorial, hash SHA-256, **nada funcional-mas-feio**.
- **IA:** nunca LLM no hot-path do produto (benchmark offline); roteamento por regra antes do LLM (~80% sem
  token); modelo por tarefa (default gemini-flash; jurídico→gemini-pro sob confirmação; bulk→nous grátis);
  **stepfun só coleta, gemini analisa** (§6).
- **Engenharia:** mudança pequena/isolada/**verificada com o artefato real**; **verificar o PDF ENTREGUE**
  (3 renderizadores: MD/FPDF/HTML); golden numbers travam regressão; scorecard mede cada checkpoint; commit por
  unidade; documentar erros & acertos NESTE doc.

## 8. ACERTOS & ERROS (lições que não podem se perder)
- **⛔ V2 revertida (2026-06-08):** bolar LLM no hot-path do relatório + mudar render/scoring do que funcionava
  = regressão (saiu PIOR). LIÇÃO: gerar o **artefato real cedo** como baseline; perfeição = perfeiçoar o
  existente, não expandir; wiring mínimo; nunca LLM síncrono no hot-path sem cache+bound.
- **✅ Instrumentar antes de afirmar:** sem scorecard/golden, "melhor" é opinião. O lint sozinho pagou **4 bugs
  reais** (asyncio/timedelta/StreamingResponse undefined; duplicata silenciosa em router.py).
- **✅ Conectar fatos entre produtos:** o sinal de fachada (CNAE×objeto, troca de controle) atravessa
  /relatorio · Lex · dossiê via **helper compartilhado** (não cópia).
- **✅ Honestidade dura no Massare:** edge médio −0,0127 (não bate o ingênuo no geral); ^GSPC "62%" é pior que
  sempre "sobe". Track record só é honesto contra a **taxa-base certa**.
- **✅ Testar antes de ligar:** o CEIS keyless retorna "limpo" porque o **download falha silencioso** (cache=None)
  = falso-negativo. NÃO ligar path não-verificado. (Por isso: "teste tudo, não aja às cegas.")
- **✅ Ler o código real > confiar no handoff:** o "fix de frames do SEI" já estava feito; o reader funcionava.
- **Bug do auto-pkill:** ver §6.
- **Modelo de raciocínio (nous):** ler `reasoning`, max_tokens alto — ver §6.

## 9. PENDÊNCIAS DEPENDENTES DO DONO
- **SIAFE 1**: liberar a chave/perfil p/ todas as UGs (conta ALERJ-only).
- **SEI de outras unidades**: o itkava lê seu escopo; processos fora (ex.: Saúde/Previdência) = 0 docs (acesso).
- **CEIS/CNEP**: consertar o download keyless do CSV da CGU OU `TRANSPARENCIA_API_KEY`.

## 10. LOG POR SESSÃO (datado — o que cada sessão fez, acertos & erros)
> Padrão: cada sessão adiciona seu bloco datado aqui. Ao FIM de cada loop: debug + avaliar storage/RAM/CPU
> (liberar espaço se preciso) e registrar.

### Sessão 2026-06-09 (esta)
**Tema:** loops de benchmark + qualidade dos produtos; depois frente SEI (reader/sweep/ficha) e LLM grátis.
**Feito:**
- **23 loops (6-28)**: fundação de benchmark (pyproject, scorecard, golden numbers, ruff 733→37, **4 bugs reais**),
  /relatorio (RF-04/05, crescimento honesto), /orgao (recorrentes idênticos, honestidade geográfica, intergov),
  Lex (R6/R11 via helper compartilhado), dossiê (red flags estruturais), Massare (backtest 356k pregões +
  /placar honesto + cron), /lista (Massare/SIAFE), nome canônico de UG em 6 produtos, filtro intra-gov
  (anomalias/cartel), F821 resolvidos.
- **Frente SEI**: descoberto que o reader **funciona** (bug do auto-pkill); `tools/sei_sweep.py` (login único,
  scope-aware, retry, árvore, resumível, `--cnpj`); `tools/sei_ficha.py` (ficha-índice via **stepfun:free**,
  modelo de raciocínio resolvido); **isolamento de qualidade** cravado (stepfun só coleta; gemini analisa).
- **Este documento de referência único** criado (consolida ~40 docs).
**Erros/lições desta sessão:** auto-pkill se mata; CEIS keyless com download quebrado (falso-negativo); modelo
de raciocínio exige max_tokens alto + ler `reasoning`; **testar tudo antes de ligar; ler a doc antes de planejar.**
**Commits-chave:** 0552059·c37f339·67b3387·efb33f7 (loops); SEI: a485e7c·3ecd9fd·1085e31·5b44937·080a5a0·cf86c65.
**Recursos (fim da sessão 2026-06-09):** disco 17G/48G (34%, **32G livre**) · RAM usada 2,5G/7,8G (**5,3G livre**)
· load 0.58 · compliance.db 1,2G + **WAL 130M** (cron dom 03:00 faz checkpoint/VACUUM) · sei_cache 1,9M. **Sem
necessidade de liberar espaço.** SIAFE2 sweep ✓ vivo, SEI sweep ✓ vivo.

### Sessão 2026-06-09 (continuação — loop de glifos no PDF + auditoria de gaps stale)
**Tema:** loop de qualidade do artefato ENTREGUE (PDF), seguindo a metodologia (ler→medir baseline→fix
isolado→regenerar produto→medir→commit).
**Feito (Loop 1):**
- **BUG corrigido no PDF do parecer Lex:** os indicadores 🔴🟡🟢 e a seta ⤴ vazavam para a fonte **DejaVu (que
  não os possui)** → fpdf2 emitia "missing glyphs" e o PDF entregue mostrava **tofu/quadrados** (viola a regra
  de estética nº1). Causa-raiz: `lex.py:_t()` retornava a string **sem tratamento no path Unicode** (`_uni=True`,
  pois a DejaVu registra OK). **Fix:** mapear os glifos que a DejaVu não tem → equivalentes que ela tem (verificado
  empiricamente via fpdf2: 🔴🟡🟢→**●**, ⤴→**↗**). **Medição (MGS, produto real):** ANTES = 1+ warning + tofu;
  DEPOIS = **0 warnings**, 3×● + 5×↗ renderizados, 0 emoji órfão, 0 `�`; risco/score/grau inalterados (sem
  regressão). Mesma blindagem aplicada ao **`inteligencia_orgao.py:_t()`** (bug latente idêntico) — regerado,
  **output idêntico** (R$ 292.292.309,08 / 2457 OBs), 0 warnings. **dossie** verificado: sem defeito (Helvetica +
  `_ascii`, sem emoji). **Suíte: 299 passed**, golden numbers ✓.
- **Auditoria de gaps stale (§5 corrigida):** os "alvos #1/#3" da retomada (quarentena, matriz+filial) **já
  estavam feitos** no código — confirma a lição "ler o código real > confiar no handoff/doc". §5 atualizada com a
  medição honesta (base limpa: 0 negativos, 1 dup, 32.597 valor=0 que só inflam contagens) e a nuance aberta
  (sem guarda p/ raiz governamental na consolidação por raiz).
**Decisão documentada (não-feito consciente):** 40 `ln=True` (fpdf2 DeprecationWarning) em 4 renderizadores que
funcionam — migração p/ `new_x/new_y` é churn amplo em código de render que funciona (risco V2 > ganho de só
silenciar warning). **Deferido** como limpeza de baixa prioridade; preferir mudança pequena/isolada/verificada.
**ACERTOS:** (1) seguir a metodologia à risca pegou um defeito **no artefato ENTREGUE** (PDF), que nenhum teste
de número pegaria — "verificar o PDF entregue" funciona. (2) Verificar a cobertura de glifos da DejaVu
**empiricamente** (via fpdf2) antes de escolher os substitutos — não chutar (● ↗ confirmados presentes; ⤴ emoji
ausentes). (3) Endurecer o irmão (`/orgao`) com **verificação de output-idêntico** (mesmos R$/OBs) = blindagem
sem regressão. (4) Auditar os "alvos" da doc contra o código real evitou retrabalho (quarentena e matriz+filial
já feitas). (5) Medir a base inteira antes de priorizar: revelou que a quarentena é baixa-alavancagem (base limpa).
**ERROS/LIÇÕES:** (1) o glyph-warning do fpdf2 **só dispara no path Unicode quando a fonte registra mas não tem o
glifo** — emoji nunca devem ir cru p/ DejaVu (a blindagem tem de estar ANTES do early-return `_uni`). (2) De novo:
a lista de gaps da doc **envelhece**; medir o produto/código real cedo é o que revela o gap verdadeiro (o defeito
estava no PDF, não nos "alvos" §11). (3) Quase caí na tentação de migrar os 40 `ln=True` no fim da sessão — seria
churn amplo em render que funciona (risco V2); a regra "pequeno/isolado/verificado" venceu → deferido.
**Commits-chave:** `4236046` (fix glifos Lex+orgao + doc §5/§10).
**Recursos (fim):** load **0.61** · RAM **4.2G livre**/7,8G · disco **32G livre**/48G (34%) · `compliance.db` 1,2G +
WAL **130M** (cron dom 03:00 faz checkpoint/VACUUM) · **sem necessidade de liberar espaço**. Sweeps ao fim:
**SIAFE 2 ✓ supervisionado** (pid do supervisor vivo, auto-cura) · **SEI ✓ relançado** (`--max 12`, resumível,
checkpoint 15+ feitos).

## 11. ⏯️ RETOMADA — INSTRUÇÕES PERMANENTES (ler ANTES de continuar, sessão nova)
**Branch `feat/lista-limpa` (não pushado, tudo commitado). Serviço/sweeps vivos.** O dono pediu para continuar
com TODAS estas instruções:
1. **Fazer o projeto INTEIRO melhorar** em loops, com **qualidade MÁXIMA e perfeição** (CLAUDE.md regra 1).
2. **Cada loop (rigoroso):** (a) **ler a documentação/o que já existe** (este doc + código real) ANTES de
   planejar; (b) **pesquisar best-practice/benchmark** da área/função; (c) **planejar com visão global**;
   (d) **executar** com qualidade máxima (mudança pequena/isolada/verificada); (e) **testar e corrigir**;
   (f) **gerar TODOS os produtos reais** (/relatorio MGS, /orgao ITERJ, Lex, dossiê, Massare) e **medir se a
   qualidade MELHOROU ou PIOROU** vs antes (comparar o artefato — PDF entregue, não só MD); (g)
   **checkpoint+commit+atualizar ESTE doc** (seção 10, datado por sessão) com acertos & erros.
3. **Detalhismo proporcional à complexidade:** quanto mais complexo, mais cuidado. **Testar tudo, nunca agir às
   cegas.**
4. **Ao FIM de cada loop:** debug + avaliar **storage/RAM/CPU**; liberar espaço se preciso; registrar os números.
5. **UM só documento de referência** = este (`docs/REFERENCIA-PROJETO.md`), datado por sessão. Não espalhar handoffs.
6. **Honestidade sempre:** indício nunca acusação; INDISPONÍVEL≠0; nunca inventar número.
7. **Isolamento de qualidade (LLM):** stepfun:free (nous, grátis) **só na mecânica do sweep SEI**; produtos
   (/relatorio, /orgao, Lex) **só gemini (forte)**. Ver §6.
8. **Sweeps sempre vivos** quando der (SIAFE 2 + SEI), respeitando CPU (não rodar sweep+suíte+Playwright juntos).

**Próximos alvos de maior alavancagem (de §4/§5, ranqueados):** (1) **quarentena de ingestão** P0
(pré-requisito de qualquer score); (2) **proveniência/INDISPONÍVEL** honesta nas 3 camadas de enriquecimento;
(3) **resolução de entidade** (Splink, CNPJ-raiz) → destrava grafo/concentração + consolida matriz+filial;
(4) **rodar o SEI sweep aos poucos** (resumível) → enriquece Lex/relatorio; (5) consertar **CEIS/CNEP keyless**
(download da CGU está quebrado → falso-negativo). **A cada um: medir o produto antes/depois.**

**Estado SEI vivo:** `tools/sei_sweep.py` rodando `--max 10` em background (resumível, checkpoint
`data/sei_cache/sei_sweep_progress.json`); ficha via stepfun:free (token nous auto-refresh).

---
*Manter ESTE documento como referência única, datado por sessão. Docs antigos em `docs/` = histórico/detalhe
(consultar por tema). Plano de qualidade: `docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md`.*
