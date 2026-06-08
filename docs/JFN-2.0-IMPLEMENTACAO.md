# JFN 2.0 — Log de Implementação (para avaliação posterior)

## ▶ RETOMADA RÁPIDA (ler PRIMEIRO se a sessão caiu / contexto estourou)
> Trabalho de DIAS — projetado para sobreviver a quedas de sessão. **Para continuar exatamente de onde parou:**
> 1. `cd ~/JFN && git checkout jfn-2.0` (branch de trabalho; `linux` é o estável/rede de segurança).
> 2. Ler **este doc inteiro** + o spec-fonte: `docs/refs/JFN-DOCUMENTO-MESTRE-CONSOLIDADO.{pdf,txt}` (o §7 traz
>    o `capabilities.yaml` completo; §5 o passo-a-passo por onda). O PDF foi copiado p/ o repo porque o cache do
>    Hermes se auto-limpa.
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
| 1 | Orquestração (router do YAML, política de modelo) | ⏳ |
| 2 | PNCP + conflito doador↔contrato (Lex) | ⏳ |
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
