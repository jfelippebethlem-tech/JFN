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
