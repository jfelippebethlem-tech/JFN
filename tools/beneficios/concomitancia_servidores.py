"""Servidores/nomeados do RJ (folha GESPERJ/DPRJ/TJRJ, CPF mascarado 3–8) × benefícios sociais (Portal, máscara 4–9).
Chave comum: nome normalizado + dígitos 4–8 (5). Relê os rj_<prog>_<mes>.csv.gz já baixados pelo benef_hist.py;
grava concomitancias_servidores.jsonl = benefício pago no MESMO mês em que a pessoa aparece na folha (com a bruta).
Idempotente: refaz tudo a cada chamada (barato: só lê os arquivos do RJ)."""
import csv
import glob
import gzip
import json
import os
import re
import unicodedata
from pathlib import Path

D = Path(os.environ.get("BENEF_DIR", Path.home() / "beneficios"))
CH = json.load(open(D / "chaves_servidores.json"))      # "NOME|12345" -> {vinc:[...], meses:{"2026-06": bruta}}
def norm(s): return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()).strip()
def col(cab, *ks):
    for i, c in enumerate(cab):
        if all(k in norm(c) for k in ks): return i
out = open(D / "concomitancias_servidores.jsonl", "w"); n_conc = n_cas = 0; arqs = 0
for arq in sorted(glob.glob(str(D / "rj_*.csv.gz"))):
    prog, mes = Path(arq).name[3:-7].rsplit("_", 1); arqs += 1
    with gzip.open(arq, "rt", encoding="utf-8") as f:
        rd = csv.reader(f, delimiter=";"); cab = next(rd)
        icpf, inome, icomp, ival, imun = col(cab, "CPF"), col(cab, "NOME", "FAVOREC"), col(cab, "COMPET"), col(cab, "VALOR"), col(cab, "NOME", "MUNIC")
        if icpf is None: continue                       # programa sem CPF: só a ponte por NIS (sócios) — não há NIS na folha
        for row in rd:
            d = re.sub(r"\D", "", row[icpf])
            if len(d) != 6: continue
            k = f"{norm(row[inome])}|{d[:5]}"
            e = CH.get(k)
            if not e: continue
            n_cas += 1
            comp = row[icomp] if icomp is not None else mes
            m = f"{comp[:4]}-{comp[4:6]}" if len(comp) == 6 else comp
            if m in e["meses"]:                           # concomitância: salário e benefício no mesmo mês
                n_conc += 1
                out.write(json.dumps({"chave": k, "prog": prog, "competencia": m, "beneficio": row[ival] if ival is not None else None,
                                      "municipio": row[imun] if imun is not None else None, "bruta_folha": e["meses"][m],
                                      "vinculos": e["vinc"]}, ensure_ascii=False) + "\n")
out.close()
print("beneficios_servidores:", json.dumps({"arquivos_rj": arqs, "casamentos_nome5": n_cas, "concomitancias_mesmo_mes": n_conc}))
