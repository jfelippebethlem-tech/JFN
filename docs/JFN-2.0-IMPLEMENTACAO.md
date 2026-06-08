# JFN 2.0 — Log de Implementação (para avaliação posterior)

## ▶ RETOMADA RÁPIDA (ler PRIMEIRO se a sessão caiu / contexto estourou)
> Trabalho de DIAS — projetado para sobreviver a quedas de sessão. **Para continuar exatamente de onde parou:**
> 1. `cd ~/JFN && git checkout jfn-2.0` (branch de trabalho; `linux` é o estável/rede de segurança).
> 2. Ler **este doc inteiro** + os specs-fonte em `docs/refs/` (preservados porque o cache do Hermes auto-limpa):
>    **`JFN-DOCUMENTO-MESTRE-CONSOLIDADO-v2.{pdf,txt}`** (VERSÃO ATUAL — usar esta; §7 = `capabilities.yaml`, §5 =
>    passo-a-passo por onda) e **`JFN-ADICIONAL-DUE-DILIGENCE-OSINT.{pdf,txt}`** (metodologia DD/OSINT + catálogo de
>    ferramentas grátis). (`...-CONSOLIDADO.{pdf,txt}` sem sufixo = v1, histórico.)
> 3. Olhar a tabela **"Progresso por onda"** e o **"Diário de execução"** (fim do doc) — a última linha diz o
>    ponto exato. Pegar a primeira onda/ item não-✅ e seguir o §5 do spec.
> 4. Regras inquebráveis: **branch `jfn-2.0`**; **aditivo**; `pytest -q` antes de cada commit; **commitar cada
>    unidade** (estado salvo cedo); **NÃO tocar módulos SIAFE enquanto os sweeps rodarem** (`pgrep -f siafe_sweep_full`);
>    **TODAS as ferramentas/fontes 100% GRATUITAS** (sem IBKR/nada pago — §4 do spec); invariantes §0.
> 5. **Pesquisa DD+OSINT** (pedida pelo dono) roda em agentes de background; quando concluírem, os relatórios são
>    salvos em `docs/research/DD-METODOLOGIA.md` e `docs/research/OSINT-METODOLOGIA.md`. **Se esses arquivos NÃO
>    existirem**, a sessão caiu antes — RELANÇAR a pesquisa (DD: padrão Kroll/ACFE/FATF; OSINT: grafo/adverse-media/
>    fontes BR grátis) e dobrar nas Ondas 4/6/7/10.
> 6. Estado vivo a conferir: `git log --oneline -15`, `git status`, `pgrep -f siafe_sweep_full` (sweep S2),
>    `systemctl --user is-active hermes-gateway` (Yoda).

> **Fonte:** `docs/refs/JFN-DOCUMENTO-MESTRE-CONSOLIDADO.pdf` (recebido via Telegram 2026-06-08, autor: IA externa;
> original cacheado em `~/.hermes/cache/documents/`). **Branch de trabalho: `jfn-2.0`** (de `linux`; reverter = `git checkout linux`).
> Disciplina: 1 onda por vez, **aditivo**, `pytest -q` antes de cada commit, **TODAS as ferramentas GRATUITAS**,
> **não tocar nos módulos dos sweeps SIAFE enquanto rodarem**. Documentar cada passo aqui.

## Análise do documento (resumo)
Spec de 12 ondas (0–11) para elevar o JFN de "auditor reativo" a: **(1) vigilante** (Radar 24/7),
**(2) grafo único de poder** (sócios+servidores+doações+contratos+nomeações), **(3) instrumento de mandato**
(achado → minuta ALERJ/TCE/MP). Correção arquitetural central: **não são 5 agentes** — é **1 runtime (Hermes) +
1 orquestrador (Yoda) + 1 motor (JFN)** com módulos de domínio; o contrato único é `capabilities.yaml`.
Camada de dados **100% gratuita** (PNCP, TSE, BCB/Focus, FRED, brapi, Yahoo/Stooq, websocket cripto, GDELT, Finnhub).

## Invariantes (§0 — nunca violar)
OB=pagamento (≠empenho) · honestidade de dados (REAL vs CACHE, nunca fabricar) · honestidade jurídica
(indícios, nunca acusação) · honestidade de mercado (OOS+custos, nunca prometer certeza) · estética due
diligence · credenciais só em .env · SIAFE sessão única por sistema · LGPD.

## Decisões de execução (minhas, documentadas)
- **Ordem:** Onda 0 (fundação) → 2 (PNCP+conflito) → 3 (motor de risco) → 8 (Massare notícia/macro) → demais.
  As ondas 2/3/8 são prioridade do dono e majoritariamente **aditivas** (módulos/rotas novas; não tocam sweeps).
- **DIFERIDO com motivo:**
  - `siafe_worker.py` (Onda 0): extrair a sessão SIAFE da API para um worker. ⚠️ O sweep S2 está rodando e o
    próprio documento manda não mexer nos módulos SIAFE durante os sweeps → fazer só após os sweeps terminarem.
  - **Desbloqueio SEI via proxy** (Onda 0): exige `SEI_PROXY_URL` (proxy residencial BR) que não temos → pendente.
  - Deprecar `agent.py`/`scheduler.py` (Onda 1): risco em sistema vivo → após cobertura comportamental.
- **Chaves grátis a obter (§8):** Finnhub, brapi.dev (token grátis) — onde faltar, marcar INDISPONÍVEL (nunca fabricar).

## Progresso por onda
| Onda | Escopo | Status |
|---|---|---|
| 0 | capabilities.yaml + validador + obs_trace | 🟢 núcleo ✅ (gen_*→Onda 1; siafe_worker/SEI-proxy diferidos) |
| 1 | Orquestração (router do YAML, política de modelo) | 🟡 geradores+config ✅; dispatcher nativo no gateway + decisão de roteamento adaptativo PENDENTE |
| 2 | PNCP + conflito doador↔contrato (Lex) | 🟡 `lex_conflito.py` (doador↔SÓCIO↔OB) ✅ testado; TSE carregando; rotas /api/conflito+/api/pncp pendentes |
| 3 | Motor de risco (Benford/sobrepreço/score) | ⏳ |
| 4 | Grafo de Poder + Dossiê 360 | ⏳ |
| 5 | SEI inteligência em escala | ⏳ |
| 6 | Radar 24/7 | ⏳ |
| 7 | Relatório classe mundial (HTML→PDF) | ⏳ |
| 8 | Massare notícia/macro/Focus | ⏳ |
| 9 | Massare teses + validação López de Prado | ⏳ |
| 10 | Lex + instrumentos de mandato | ⏳ |
| 11 | Higiene técnica | ⏳ (parte já feita na campanha de otimização anterior) |

## ✅ DEFINIÇÃO DE PRONTO + LIMPEZA DE MEMÓRIA (último passo — NÃO esquecer)
Quando **todas as 12 ondas estiverem ✅ e a suíte verde**, a sessão que concluir DEVE, como ato de encerramento:
1. Mesclar `jfn-2.0` → `linux` (PR/merge), confirmar `pytest -q`, e atualizar a tabela acima toda para ✅.
2. **Limpar a memória persistente** (o dono pediu): `rm` em
   `~/.claude/projects/-home-jfelippebethlem/memory/jfn-2.0-implementacao.md` e **remover a linha
   "▶ JFN 2.0 — CONTINUAR AQUI"** do `MEMORY.md` (o histórico permanece no git/docs; só sai o ponteiro de
   retomada que era carregado em toda sessão). Opcional: deixar 1 linha curta "JFN 2.0 entregue em <data>".
3. Anunciar conclusão ao dono no Telegram.
> ⚠️ Não há remoção automática por tempo; a limpeza é este passo deliberado. A IA NÃO lembra sozinha entre
> sessões — por isso esta instrução vive aqui e na memória: quem fechar a Onda 11 executa.

## ⏸️ SWEEP SIAFE 2 — PAUSADO (2026-06-08, a pedido do dono para implementar a Onda 1)
**Ponto de parada (para retomar):** 86 UG:ano feitos (29 UGs com dado), parou em **110100/2024** no meio de uma
subdivisão ug-grande; **48.600 OBs** (2024-26) no banco. Checkpoint: `data/sei_cache/siafe_sweep_full_2.json`
(resumível; o sub-checkpoint da ug-grande retoma sozinho). **Pausa:** flag `data/.pause_sweep_2` (supervisor
respeita e NÃO relança). **PARA RETOMAR:** `rm data/.pause_sweep_2` (o supervisor relança em ≤1 min) OU
`PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full 2`. SIAFE 1 (ALERJ) já estava completo. ⚠️ Com o sweep
PARADO, agora é seguro mexer nos módulos SIAFE (ex.: `siafe_worker.py` da Onda 0, diferido).
**Download TSE** (doações RJ+presidente, todos os anos) roda em processo SEPARADO (`/tmp/tse_load.py`,
`data/tse_load.out`) — NÃO é o sweep; deixar terminar (popula `doacoes_eleitorais` p/ o conflito da Onda 2).

## ⏳ DECISÃO PENDENTE DO DONO — roteamento de modelo do Hermes (Onda 1)
**Como está hoje (investigado):** Hermes NÃO é adaptativo por tarefa. Usa **1 modelo default p/ tudo**
(`gemini-2.5-flash`) e só troca em FALHA (fallback failure-based). Não há roteamento por dificuldade.
**Config atual aplicada** (`~/.hermes/config.yaml`, backup `config.yaml.bak.jfn2-onda1-*`): default
gemini-2.5-flash; `api_max_retries:3`; fallback ordem **gemini-lite → gemini-2.0 → mistral-large →
mistral-small → nous×3 (100% free, por último — a pedido do dono)**. Gateway reinicia saudável.
**O dono quer ADAPTATIVO:** default 100% free; casos difíceis → modelos melhores. Isso NÃO existe hoje —
precisa construir. **Aguardando decisão:** (1) **A** heurística simples (gatilhos→escala) vs **B** semantic
router (ModernBERT/LoRA); (2) default 100%-free = **nous** ou manter **gemini-2.5-flash (free-tier)**.
Quando decidir → implementar via overlay idempotente no gateway (ponto: `run.py:13078 _tools`).

## Onda 1 — estado detalhado
✅ FEITO: `tools/gen_router_tools.py` (→ `data/jfn_tools.json` + `~/.hermes/jfn_tools.json`, 17 tools ativas/15
futuras), `tools/gen_capabilities_md.py` (→ `docs/CAPACIDADES.md` + `data/yoda_capabilities_prompt.txt`),
pre-commit (valida+regenera, local), política de modelo no config.yaml (acima).
⏳ FALTA: dispatcher NATIVO de tool-calling no gateway (injetar jfn_tools.json em `_tools` run.py:13078 +
executor function-call→HTTP/CLI, via overlay idempotente); injetar `yoda_capabilities_prompt.txt` no system
prompt (registro fechado, mata invenção de web_search); deprecar `agent.py`/`scheduler.py` (hermes_goal único);
roteamento adaptativo (decisão acima).

## Diário de execução
- **2026-06-08** — Branch `jfn-2.0` criada (de `linux`) e pushada p/ origin. Documento mestre lido e analisado;
  PDF+texto preservados em `docs/refs/`. Infra de RETOMADA + memória persistente criadas. Pesquisa DD+OSINT
  lançada em background (salvar em `docs/research/`). Invariante reforçado: **todas as ferramentas GRATUITAS**.
  Iniciada Onda 0 (fundação aditiva: capabilities.yaml → validador → obs_trace).
- **2026-06-08 (cont.)** — ✅ **Pesquisa DD + OSINT concluída e salva** em `docs/research/DD-METODOLOGIA.md` e
  `docs/research/OSINT-METODOLOGIA.md` (citadas, 2024-2026). Ambas trazem **"MAPA PARA O JFN"** com técnica → onda →
  lib/fonte grátis → critério de aceite. Achados-chave a aplicar: **proveniência por dado (lineage)** e **declarar
  nível de DD aplicado** (Onda 7) = maior salto rumo a Kroll; **screening CEIS/CNEP** via API Portal Transparência
  (Onda 2, chave grátis); **UBO regra-50%** sobre `rede_societaria.py` (Onda 4); **followthemoney+Splink+networkx**
  p/ Grafo de Poder (Onda 4); **GDELT DOC 2.0** p/ adverse media no Radar (Onda 6); **LGPD: base legal = obrigação
  legal/atribuição do Poder Público, NÃO legítimo interesse** (invariante a registrar). Libs novas grátis a pinar
  quando usadas: followthemoney, splink, python-louvain/leidenalg/igraph, pyvis, rapidfuzz.
- **2026-06-08 (Onda 0 núcleo ✅)** — Criados e TESTADOS (106 testes verdes):
  `capabilities.yaml` (32 capacidades: 17 PRONTO, 15 em onda); `tools/validate_capabilities.py` (schema + checa
  que rota PRONTO existe no server.py — CI-friendly); `compliance_agent/obs_trace.py` (correlation-id +
  `GET /api/trace/{id}`, wiring aditivo em `server.py` via `register_trace(app)`, best-effort); `tests/test_jfn2_onda0.py`.
  Aceite Onda 0(b) validado por TestClient (header X-Correlation-Id + /api/trace mostra etapas). ⚠️ Ativa no
  servidor vivo só no próximo reload do jfn.service (não reiniciei p/ não perturbar; sweeps rodam fora do jfn.service).
  **DIFERIDO:** `siafe_worker.py` (sweep S2 ativo) e desbloqueio SEI (sem `SEI_PROXY_URL`). `gen_router_tools.py`
  e `gen_capabilities_md.py` + hook pre-commit → **Onda 1** (onde o roteador do Yoda consome o YAML).
  **PRÓXIMO: Onda 2** (PNCP + conflito doador↔contrato) — prioridade do dono, aditiva. Ver mapa em
  `docs/research/DD-METODOLOGIA.md` (#1 screening, #10 COI) e `OSINT-METODOLOGIA.md` (doação↔contrato, cartel).
- **2026-06-08 (background deps + novos specs)** — ✅ Instaladas (todas GRÁTIS, núcleo intacto, 104 smoke verde):
  `rapidfuzz, python-louvain, igraph, leidenalg, pyvis, python-bcb, splink` (pinadas em `requirements.txt`).
  Diferidas com motivo: `followthemoney` (precisa libicu/apt), `sentence-transformers`/`vectorbt`/`weasyprint`
  (na sua onda). **Torch pode ser reinstalado SE preciso — sempre `--index-url .../whl/cpu`** (autorizado pelo dono).
  - ✅ **2 novos specs recebidos via Telegram e preservados:** `docs/refs/JFN-DOCUMENTO-MESTRE-CONSOLIDADO-v2.{pdf,txt}`
    (mestre atualizado — USAR ESTE) e `docs/refs/JFN-ADICIONAL-DUE-DILIGENCE-OSINT.{pdf,txt}` (metodologia DD/OSINT
    + catálogo de ferramentas grátis: Aleph/OpenCorporates/Brasil.io etc., marcando [JFN]/[INTEGRAR]/[MANUAL]).
  - 🔴 **REQUISITO CRÍTICO da Onda 2 (instrução do dono):** o conflito NÃO é só doador-CNPJ == fornecedor-CNPJ.
    Tem que **cruzar doadores TSE × SÓCIOS (QSA, `socios_fornecedor`) das empresas que têm contrato/OB** — i.e., o
    doador (CPF/CNPJ) pode ser SÓCIO da contratada, não a contratada em si. Estender `tse.cruzar_doacoes_contratos`
    (hoje só casa CNPJ direto) para incluir o join via QSA. Mesmo raciocínio p/ parentesco (DD #9/#10).
