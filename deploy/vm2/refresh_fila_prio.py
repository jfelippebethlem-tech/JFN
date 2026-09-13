# ordena a fila do sweep: 1) processos de tipos de contratação (catálogo enum) 2) achados da busca livre 3) o resto
import re
import sqlite3
from pathlib import Path
fila = Path("/home/ubuntu/sei-pcrj/fila.txt"); db = Path("/home/ubuntu/sei-pcrj/data/sei_pcrj.db")
nums = [l.strip() for l in fila.read_text().splitlines() if l.strip()]
prio1, prio2 = set(), set()
if db.exists():
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rx = re.compile(r"CONTRATA|LICITA|DISPENSA|INEXIGIB|PREG[ÃA]O|ADITIVO|CONV[ÊE]NIO|PARCERIA|TERMO DE AJUSTE|INDENIZA|RECONHECIMENTO DE D|EMERGENC|REGISTRO DE PRE|CONCORR|CHAMAMENTO|OBRAS", re.I)
        for p, t in c.execute("SELECT processo, tipo FROM sei_pcrj_enum"):
            if t and rx.search(t): prio1.add(p)
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='sei_pcrj_busca'").fetchone():
            prio2 = {p for (p,) in c.execute("SELECT DISTINCT processo FROM sei_pcrj_busca WHERE processo IS NOT NULL")}
    except sqlite3.Error:
        pass
    finally:
        c.close()
seen, out = set(), []
for grupo in (sorted(n for n in nums if n in prio1), sorted(n for n in nums if n in prio2), sorted(nums)):
    for n in grupo:
        if n not in seen: seen.add(n); out.append(n)
fila.write_text("".join(n + "\n" for n in out))
print(f"fila: {len(out)} (contratação {len(prio1 & set(nums))}, busca {len(prio2 & set(nums))})")
