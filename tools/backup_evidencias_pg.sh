#!/usr/bin/env bash
# Backup noturno do banco da plataforma de evidências (PostgreSQL da VM-2, banco jfn_evidencias) — Fase 3 (23/11/2026).
# pg_dump formato custom na VM-2 → arquivo na VM-1 → porta única de armazenamento (classe backup_db = insubstituível:
# Drive + 2ª cópia num remoto grátis; hash conferido antes de apagar o local). Sem binário novo, sem nuvem paga.
# Restauração: pg_restore -d jfn_evidencias <arquivo>  (ver deploy/vm2/postgres/restaurar_teste.sh).
set -u
cd /home/ubuntu/JFN || exit 1
mkdir -p data/backups
arq="data/backups/evidencias_pg_$(date +%Y%m%d).dump"
if ! timeout 1800 ssh -o BatchMode=yes -o ConnectTimeout=20 vm2-ts \
     "sudo -n -u postgres pg_dump -Fc -d jfn_evidencias" > "$arq.tmp"; then
  echo "$(date '+%F %T') pg_dump falhou — backup NÃO feito (o anterior segue no armazenamento)"; rm -f "$arq.tmp"; exit 1
fi
[ -s "$arq.tmp" ] || { echo "$(date '+%F %T') dump vazio — backup NÃO feito"; rm -f "$arq.tmp"; exit 1; }
mv "$arq.tmp" "$arq"
echo "$(date '+%F %T') dump ok: $(stat -c %s "$arq") bytes"
PYTHONPATH=. nice -n 15 timeout 3600 .venv/bin/python -m compliance_agent.armazenamento guardar "$arq" \
  --classe backup_db --apagar-local
echo "$(date '+%F %T') armazenamento rc=$?"
