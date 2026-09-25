#!/bin/bash
# Puxa nºs SEI.RIO frescos da VM-1 (pcrj_doe_materia, alimentado pelo cron doweb) e une à fila local.
cd /home/ubuntu/sei-pcrj || exit 1
NOVA=$(ssh -o BatchMode=yes -o ConnectTimeout=15 vm1 'cd ~/JFN && .venv/bin/python -c "
import sqlite3, json, re
c=sqlite3.connect(\"file:data/pcrj.db?mode=ro\", uri=True)
seen=set()
for (p,) in c.execute(\"SELECT processos FROM pcrj_doe_materia WHERE processos IS NOT NULL\"):
    try: arr=json.loads(p)
    except Exception: continue
    for n in arr:
        if re.fullmatch(r\"\d{5,6}\.\d{6}/\d{4}-\d{2}\", n or \"\"): seen.add(n)
print(chr(10).join(sorted(seen)))
"' 2>/dev/null)
if [ -n "$NOVA" ]; then
  { cat fila.txt 2>/dev/null; echo "$NOVA"; } | sort -u > fila.txt.new && mv fila.txt.new fila.txt
  echo "$(date -Is) fila atualizada: $(wc -l < fila.txt) nºs" >> data/sweep_cron.log
fi
# prioridade: contratação (catálogo enum) > busca livre > resto — sem isso a fila era alfabética
.venv/bin/python refresh_fila_prio.py >> data/sweep_cron.log 2>&1
