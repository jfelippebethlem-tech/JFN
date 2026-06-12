# HANDOFF COMPLETO — Ecossistema Mestre Jorge (2026-06-06)

> **Para outra IA revisar / histórico.** Resumo de tudo que foi feito nesta jornada nos 4 agentes
> (JFN, Massare, Yoda, Hermes), o estado atual, e o status HONESTO de cada meta do Mestre Jorge.
> Preferências do usuário: `docs/PREFERENCIAS-MESTRE-JORGE.md` (LER). Pipeline de OBs: `docs/JFN-PIPELINE-OBS.md`.

## Infra 24/7 na VM (systemd-user, linger ligado)
| Serviço/timer | Função | Quando |
|---|---|---|
| `jfn.service` | servidor/painel JFN (porta 8000) | sempre |
| `hermes-gateway.service` | Mestre Yoda (bot Telegram) | sempre |
| `jfn-ronda.timer` | health-check do JFN + alerta Telegram | a cada 10min |
| `massare-daily.timer` | ciclo diário do Massare (prevê/avalia/aprende) | 07:30 UTC |
| `jfn-tfe.timer` | resumo despesa D-1 | 08:00 UTC |
| `jfn-tfe-ob.timer` | base COMPLETA de OBs (download + ingestão) | seg 09:00 UTC |

## JFN — auditoria/compliance RJ
- **Base de OBs (pagamento/liquidação) COMPLETA:** **612.698 OBs (2023-2026), R$78,75bi**, via download
  TFE `fornecedor_ob.zip` (sem MFA/ADF). Campos: número, credor (CNPJ/CPF), **nome do órgão**, **objeto
  (Histórico→categoria)**, **data de pagamento**, valor. Coletor: `compliance_agent/collectors/tfe_ob.py`.
- **Despesa TOTAL** (folha/previdência/dívida por elemento): `despesa_execucao` — 2024 R$104,8bi, 2023 R$99,2bi
  (bate com LOA R$100bi+). Coletor: `tfe_aberto.py::ingest_db`. Resolve a dúvida de cobertura.
- **Categorização por área/objeto:** `categorizar.py` — Saúde 13k, Educação 8k, Diárias 7,6k, Obras 3,5k,
  Locação, Manutenção, etc. "Outros" reduzido 31,6k→14,9k. Diárias de servidores ESTÃO na base.
- **Relatório robusto HTML** (padrão Kroll/Control Risks): `reports/html_report.py` — sumário+rating composto,
  matriz TCU P×I, red flags c/ fundamento legal, distribuição por área/órgão pagador, HHI, recomendações.
- **Run cronometrado:** pipeline completo (ingest 80k + auditoria + relatório) em **101s (1,7 min)** — alvo 10-15min OK.
- **SIAFE direto:** login+MFA resolvido (sessão 30d). Replay PPR (`siafe_ppr.py`) coleta as 50 e o protocolo
  ADF está documentado, mas avançar o range está bloqueado (`contentDelivery:immediate`/fetchSize:50 — precisa
  capturar o "goNext" real via DevTools/mitmproxy). **Redundante:** a base completa já vem do TFE. Ver `SIAFE-NAVEGACAO.md`.
- **Bugs corrigidos:** `free_llm.py` (qwen_chat_async, GROQ_MODEL_*); painel destravado.

## Massare — super-agente financeiro
- **Sede de dados:** `massare/data/massare.db`, **26 ativos × 20 anos** BR+EUA (índices, commodities, tech,
  cripto, DXY) + macro + sentimento. Coletor `collect.py --backfill`.
- **Variável humana:** `behavior.py` (Fear&Greed, VIX, curva de juros).
- **Modelos:** `engine.py` (ensemble adaptativo, walk-forward), `ml.py` (regime HMM + XGBoost purgado).
  **HONESTO:** acerto direcional ~55% OOS (S&P 55,4%; XGBoost NÃO bate baseline 60,5%). **>80% é IMPOSSÍVEL**
  — o sistema MEDE a realidade (não fabrica). Edge real = regime + gestão de risco, não adivinhar direção.
- **Aprendizado contínuo:** `learning.py` (diário de previsões avaliado vs realizado + lições cross-agente).

## Yoda / Hermes
- Modelo afinado (gemini-2.5-flash, reasoning high, personality concise), **memória corrigida** (limites
  1375→4000), fantasma de respawn limpo, skill fantasma do cron removida, cron BOM DIA enriquecido (07:30),
  rotinas na memória, conciso (regra: mais conciso que o Claude, completo no pedido).
- **Fix do bug de memória** do Hermes (replace por #índice + erros acionáveis): branch
  `claude/fix-memory-resolve-for-weaker-models` em `~/hermes-agent` (76 testes), aguardando avaliação.

## Status HONESTO das metas (Stop hook)
| Meta | Status |
|---|---|
| Yoda: resolver/melhorar/testar/commit | ✅ |
| Avaliar 4 agentes + melhorar + testes reais | ✅ |
| JFN acessa SIAFE e pega OBs (liquidação) | ✅ via TFE (612k); SIAFE direto = 50 (ADF bloqueia o resto) |
| Melhorar SEI/TFE | ✅ TFE (completo); SEI: objeto via Histórico (nº processo confiável só no SIAFE/contrato) |
| Rodar 24/7 na VM | ✅ (6 serviços/timers) |
| Massare 20a BR+EUA + variável humana + aprendizado | ✅ |
| Acerto >80% | 🔴 IMPOSSÍVEL (provado; honesto ~55%) |
| Testar runs JFN 10-15min | ✅ (1,7 min) |
| Documentar p/ outras IAs + commit tudo | ✅ (este handoff + docs/ + commits) |

## Pendências (escolha do Mestre Jorge)
- SIAFE tempo-real + folha nominal: capturar o cURL do "goNext" no DevTools → eu fecho o replay.
- Cruzar credores com CEIS/CNEP (sanções) e PNCP (contratos por CNPJ).
- Massare: features pandas-ta, backtest com custos, Deflated Sharpe.
