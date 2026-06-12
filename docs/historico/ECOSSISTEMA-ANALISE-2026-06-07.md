# Análise do ecossistema (código) — 2026-06-07
Análise estrutural NÃO-gated (do CÓDIGO, não dos dados do sweep). Plano de racionalização p/ executar
PÓS-SWEEP (não mexer mid-run: os sweeps usam o código; remoções arriscam derrubá-los; ver modelo branch-por-SO).

## Tamanho
- `compliance_agent`: 107 módulos, ~31.394 linhas.
- Maiores (candidatos a DIVIDIR p/ legibilidade — não urgente): hermes_goal.py (1260), reporting/inteligencia.py
  (1257), notifications/telegram.py (1143), collectors/terceirizados.py (1105), siafe_ob_orcamentaria.py (959),
  agent.py (955), collectors/siafe_ob.py (918), lex.py (903), scheduler.py (877), rules/engine.py (864).

## Código morto — candidatos (heurística: 0 imports + sem __main__)
- ✅ REAL: `compliance_agent/collectors/sei_sei_direct.py` (0 referências) — coletor SEI experimental superado.
  AÇÃO PÓS-SWEEP: confirmar (grep + docs/config) e remover via `git rm` (manter histórico).
- ❌ FALSO-POSITIVO (NÃO remover): `database/migrations/002_*.py`, `003_*.py` — migrations run-once (aplicadas
  pelo runner de migração, não importadas de propósito).
- Nota: `collectors/siafe_ob.py` TEM refs (não é morto); o novo fluxo é `siafe_ob_orcamentaria.py` + `siafe_runner.py`.

## Racionalização já FEITA nesta sessão
- Ponto único de coleta SIAFE (`siafe_runner`) com lockfile; coletores explorativos do FlexVision removidos
  (flexvision_explore/map.py); correlação OB↔SEI automática no diário; playbook/CLAUDE.md unificados.

## TODO pós-sweep (do playbook): lock-por-sistema, VACUUM, remover sei_sei_direct.py, stats com "frescor".
