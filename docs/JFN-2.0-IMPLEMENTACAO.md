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
| 0 | capabilities.yaml + validador + gen + obs_trace | 🟡 em execução |
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

## Diário de execução
- **2026-06-08** — Branch `jfn-2.0` criada. Documento lido e analisado. Iniciada Onda 0 (fundação aditiva).
