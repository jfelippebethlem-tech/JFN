# HANDOFF — SIAFE sweep + ecossistema (2026-06-07)

## ESTADO (deixar moer; tudo auto-curável e hands-off)
Rodando na VM (independente do Claude/terminal — `setsid`/`nohup`/`cron`):
- **Supervisor** `tools/siafe_supervisor.sh` (cron a cada min o ressuscita) → mantém os 2 sweeps vivos
  (relança no crash do Playwright; resumíveis por checkpoint UG:ano + sub-prefixo).
- **Sweep SIAFE 2** (2024-26) e **SIAFE 1** (2016-23) — `tools/siafe_sweep_full.py {2,1}`, em PARALELO.
- **Sócios/diretores por OB** — `tools/enriquecer_socios_ob.py` (BrasilAPI QSA).
- **Ao concluir os 2 sweeps:** o supervisor dispara `tools/pos_sweep_analise.py` → VACUUM + análise
  (OBs por ano/UG, SEI, sócios) → relatório `docs/ANALISE-POS-SWEEP-*.md` + **AVISO no Telegram**.

Progresso em 2026-06-07 ~19h40 UTC: **40.688 OBs** (SIAFE 1+2), checkpoints S2=22/615, S1=13/1640,
sócios=13.341 CNPJs. (Backfill histórico é multi-dia.)

## O QUE FOI ENTREGUE NESTA SESSÃO
- **§8b RESOLVIDO** (teto 1000): filtro ADF por TYPEAHEAD + commit do valor (Tab no 2.0 / cliente ADF
  `AdfValueChangeEvent.queue` no 1). `coletar_por_ug` / `coletar_por_ug_grande` (subdivisão por Número).
- **SIAFE 1 destravado** (2016-2023, antes bloqueado) — mesma receita, op "começa com" + evento ADF.
- **Ponto único `siafe_runner`** (lockfile): `diario` (cron 05:00, incremental — base fresca sem sweep),
  `ug`, `sweep`, `verificar DD/MM/AAAA` (overflow de dia >1000). Rotas `/api/siafe/atualizar|sweep|status|stats`.
- **Verificador de dia** (dias de folha >1000) integrado ao diário.
- **Correlação OB↔SEI** (17.450 OBs) + automática no fim do diário; **cruzamento OB↔CNPJ↔SEI↔sócios** validado.
- **Yoda testado** comandando leitura E ação (lockfile recusa concorrência) — `hermes -z`.
- **Storage:** uv cache −308M; livro Lex 14M→.txt. **Análise do ecossistema** documentada.
- Docs: PLAYBOOK-EXECUTOR.md (TL;DR), SIAFE-RIO2-GUIA-AUTOMACAO.md, FLEXVISION-EVOLUCAO.md,
  SCRAPING-SITES-DIFICEIS.md, ECOSSISTEMA-ANALISE-2026-06-07.md, RELATORIO-ECOSSISTEMA-2026-06-07.txt.

## TODO PÓS-SWEEP (revisão MANUAL — não automatizado p/ não arriscar)
1. **Lock por sistema** (`siafe_lock_{1,2}.json`) — hoje 1 lock compartilhado (seguro, mas bloqueia o diário
   à toa enquanto só o SIAFE 1 roda). NÃO trocar o nome mid-run.
2. **Remover dead-code** `collectors/sei_sei_direct.py` (0 refs — confirmar + `git rm`).
3. **Dividir módulos grandes** (hermes_goal, inteligencia, telegram, terceirizados) — legibilidade.
4. **Stats com "frescor"** (data da última OB por ano em /api/siafe/stats).
5. **SIAFE 1 ug-grande** — validar a subdivisão no SIAFE 1 (ALERJ 2023 capou em 1000 na coleta direta).
6. (opcional) `/api/siafe/*` só ficam ativas após reload do jfn.service (que não reiniciamos por regra).

## COMO RETOMAR
Quando chegar o Telegram "ANÁLISE PÓS-SWEEP pronta" → ler `docs/ANALISE-POS-SWEEP-*.md` e fechar o TODO acima.
Comandos: ver `docs/PLAYBOOK-EXECUTOR.md` (TL;DR no topo). SIAFE 1 = `JFN_SIAFE_LOGIN_URL=...www5.../SiafeRio/...`.

## ✅ RESOLVIDO (2026-06-07, sessão seguinte) — SIAFE 1 falsos-vazios: causa REAL ≠ hipótese §41
A hipótese do §41 (trocar o `selUg` de contexto p/ a UG alvo) era **IMPOSSÍVEL e desnecessária**. Investigação
ao vivo (`tools/_probe_selug.py`, já removido) provou:
- O `selUg` da **conta SIAFE 1** só expõe **2 opções**: `TODAS` (default) e `010100 - ALERJ`. TJRJ/INEA/etc.
  **nem existem** no seletor → a conta é **escopada à ALERJ** no SIAFE 1 (www5/SiafeRio).
- Com contexto=`TODAS` e sem filtro, **300/300 linhas = ALERJ**. A conta não enxerga outras UGs no SIAFE 1.
- **Causa real dos ~105 falsos-0:** o cache de UGs era **COMPARTILHADO** (`ugs_siafe.json`). O S2 (siafe2, conta
  com 205 UGs) escrevia o cache; o S1 **reusava** essa lista de 205 UGs contra a conta ALERJ-only → 205×8 anos = 0
  exceto ALERJ. Não era escopo de listagem; era lista de UGs errada.

**FIX aplicado:** (1) cache de UGs **por sistema** `data/sei_cache/ugs_siafe_{1,2}.json` (`tools/siafe_sweep_full.py`);
`ugs_siafe_1.json=["010100"]`. (2) não prepender TJRJ se a conta não tiver acesso. (3) checkpoint S1 podado p/
ALERJ-only (8 anos, ~21k OBs, todos ok). (4) flag de pausa por sistema no supervisor (`data/.pause_sweep_$S`).
Agora o S1 loga **SWEEP COMPLETO em segundos** sem gerar 0s. SIAFE 2 (2024-26, todas as UGs) intacto.

> ⚠️ **GAP DE DADOS (limitação de credencial, não bug):** 2016-2023 das UGs **≠ ALERJ** é **inacessível** com
> a conta atual do SIAFE 1. **Triplo-confirmado** (2026-06-07): (a) `selUg` só tem TODAS+ALERJ; (b) "começa com 0"
> = 1000 linhas 100% ALERJ; (c) "começa com 03/02/04/27/30" (exclui ALERJ) = 0. GAP REAL é estreito: só
> **2016-2018 das UGs ≠ ALERJ** (o TFE/`ordens_bancarias` já cobre 2019-2026 com TODAS as ~120 UGs).
>
> **QUANDO CHEGAR a credencial SIAFE 1 com acesso GLOBAL (decisão do Jorge 2026-06-07):**
> 1. Pôr no `.env` (ou `~/.hermes/.env`) as vars **`SIAFE1_USER` / `SIAFE1_PASS`** (precedência por sistema já
>    implementada em `_login`; SIAFE 2 segue com `SIAFE_USER/PASS` intacto).
> 2. `rm data/sei_cache/ugs_siafe_1.json` (regenera a lista de UGs do selUg da nova conta).
> 3. `rm data/sei_cache/siafe_sweep_full_1.json` (limpa o checkpoint ALERJ-only p/ varrer todas as UGs) —
>    ou manter (ALERJ não re-coleta; as novas UGs entram).
> 4. Deixar o supervisor relançar (ou `PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full 1`). Pronto:
>    o código varre 2016-2023 de todas as UGs sem nenhuma outra alteração.

## ✅ COBERTURA DE ENDEREÇO (goal 2026-06-07) — todo CNPJ coletado tem endereço
Diagnóstico: `rede_societaria.ingerir` marcava o CNPJ como "feito" (sentinela em `socios_fornecedor`) mesmo quando
a BrasilAPI devolvia erro/429, **sem gravar endereço e sem retentar** → 843 CNPJs válidos (inclusive Banco do
Brasil) ficaram sem endereço por falha transitória (NÃO eram entidades especiais — todos retornam endereço na
BrasilAPI). Fix: `tools/backfill_enderecos.py` (idempotente, backoff de 429) ataca direto o gap de
`endereco_fornecedor`. Rodar com `run_in_background`; recomputa o gap a cada execução (cobre novos CNPJs do sweep).
