#!/bin/bash
# Sweep noturno de ATAS DE JULGAMENTO (PNCP) → julgamento → lances → índice.
# Fecha a maior lacuna do Índice de Direcionamento (2026-07-22: 31 atas p/ 52k resultados;
# famílias certame_ata e conluio ficavam INDISPONÍVEIS por falta desta matéria-prima).
# Single-instance (flock), bounded (LIMITE/noite), OFF-HOURS (escrever no compliance.db
# em horário de uso trava as rotas de leitura do painel — regra da casa).
set -u
cd /home/ubuntu/JFN || exit 1
LIMITE="${1:-400}"
LOG=data/sweep_atas.log
exec 9>/tmp/sweep_atas_julgamento.lock
flock -n 9 || { echo "$(date -Is) já rodando — pulo" >> "$LOG"; exit 0; }
{
  echo "═══ $(date -Is) sweep atas (limite $LIMITE) ═══"
  # 1) baixa atas novas do PNCP (só certames competitivos sem ata; OCR cap 8 pág)
  PYTHONPATH=. .venv/bin/python -m compliance_agent.collectors.atas_julgamento "$LIMITE"
  # 2) ata → certame_julgamento (decisões/inabilitações/trivialidade) + recálculo do índice
  PYTHONPATH=. .venv/bin/python -m tools.backfill_dossie_mestre --fases julgamento_pncp
  # 3) lances literais → proposta_item (screens de conluio)
  PYTHONPATH=. .venv/bin/python -m compliance_agent.editais.coletor_propostas --backfill
  # 4) re-índice dos certames com lance novo (conluio/competição acendem onde há matéria)
  PYTHONPATH=. .venv/bin/python - <<'PY'
from compliance_agent.editais.indice_certame import calcular_e_persistir
import sqlite3
con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True)
certames = [r[0] for r in con.execute(
    "SELECT DISTINCT certame FROM proposta_item UNION SELECT certame FROM certame_julgamento")]
con.close()
ok = err = 0
for c in certames:
    try:
        calcular_e_persistir(c); ok += 1
    except Exception:
        err += 1
print(f"re-indice: {ok} ok, {err} erro")
PY
  echo "─── $(date -Is) fim"
} >> "$LOG" 2>&1
