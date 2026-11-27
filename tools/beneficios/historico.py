"""Histórico de benefícios sociais (Portal da Transparência / CGU, dados abertos) × sócios de fornecedores do RJ.
Fase A: Novo Bolsa Família 2023-03→2026-10 (CPF mascarado 4–9 + NIS): casa nome|6díg e APRENDE o NIS de cada sócio.
Fase B: Auxílio Brasil 2021-11→2023-02 e Bolsa Família 2016-01→2021-10: casa pelo NIS aprendido (e por nome|6díg se
houver CPF). Um mês por vez, pausa entre downloads, retoma (mês com saída pronta é pulado). Só linhas do RJ ficam
(nbf_rj_<prog>_<mes>.csv.gz) e os casamentos vão a casamentos.jsonl. Nada de CPF completo: só a máscara do próprio Portal."""
import csv
import gzip
import io
import json
import os
import re
import subprocess
import time
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

D = Path(os.environ.get("BENEF_DIR", Path.home() / "beneficios")); LOG = D / "hist.log"
CH = json.load(open(D / "chaves_socios.json"))                      # "NOME|123456" -> [cnpj]
NIS_F = D / "nis_socios.json"; nis = json.load(open(NIS_F)) if NIS_F.exists() else {}   # nis -> chave
SAIDA = D / "casamentos.jsonl"

def log(*a):
    with open(LOG, "a") as f: print(time.strftime("%d/%m %H:%M"), *a, file=f, flush=True)
def norm(s): return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()).strip()
def meses(a, b):
    y, m = divmod(a, 100); out = []
    while y * 100 + m <= b:
        out.append(y * 100 + m); m += 1
        if m > 12: y, m = y + 1, 1
    return out

def col(cab, *chaves):
    for i, c in enumerate(cab):
        u = norm(c)
        if all(k in u for k in chaves): return i
    return None

def processar(prog, mes):
    pronto = D / f"ok_{prog}_{mes}"
    if pronto.exists(): return
    z = D / f"{prog}_{mes}.zip"
    url = f"https://portaldatransparencia.gov.br/download-de-dados/{prog}/{mes}"
    r = subprocess.run(["curl", "-sfL", "-m", "2400", "-A", "Mozilla/5.0", "-o", str(z), url])
    if r.returncode or not z.exists() or z.stat().st_size < 1000:
        log("SEM ARQUIVO", prog, mes, "rc", r.returncode); z.unlink(missing_ok=True)
        if mes < RECENTE: pronto.write_text("sem-arquivo")      # recente pode só não ter saído ainda: tenta no mês seguinte
        return
    try:
        zz = zipfile.ZipFile(z)
    except zipfile.BadZipFile:
        log("ZIP INVÁLIDO", prog, mes); z.unlink(); return
    n_rj = n_cas = 0
    with zz.open(zz.namelist()[0]) as f, gzip.open(D / f"rj_{prog}_{mes}.csv.gz", "wt", encoding="utf-8", newline="") as out, \
         open(SAIDA, "a") as sai:
        rd = csv.reader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"); cab = next(rd)
        iuf, icpf, inis, inome = col(cab, "UF"), col(cab, "CPF"), col(cab, "NIS"), col(cab, "NOME", "FAVOREC") or col(cab, "NOME")
        imun, ival = col(cab, "NOME", "MUNIC"), col(cab, "VALOR")
        icomp, iref = col(cab, "COMPET"), col(cab, "REFER")
        log("colunas", prog, mes, cab)
        w = csv.writer(out, delimiter=";"); w.writerow(cab)
        for row in rd:
            if iuf is None or row[iuf] != "RJ": continue
            n_rj += 1; w.writerow(row)
            nome = norm(row[inome]) if inome is not None else ""
            d6 = re.sub(r"\D", "", row[icpf]) if icpf is not None else ""
            ni = row[inis].strip() if inis is not None else ""
            chave = f"{nome}|{d6}" if len(d6) == 6 else None
            via = None
            if chave and chave in CH:
                via = "nome+6dig"
                if ni and ni not in nis: nis[ni] = chave
            elif ni and ni in nis and nis[ni].split("|")[0] == nome:
                chave, via = nis[ni], "nis"
            if via:
                n_cas += 1
                sai.write(json.dumps({"prog": prog, "arquivo": mes, "comp": row[icomp] if icomp is not None else None,
                                      "ref": row[iref] if iref is not None else None, "chave": chave, "via": via,
                                      "nis": ni, "municipio": row[imun] if imun is not None else None,
                                      "valor": row[ival] if ival is not None else None, "cnpjs": CH[chave]}, ensure_ascii=False) + "\n")
    z.unlink(); json.dump(nis, open(NIS_F, "w")); pronto.write_text(f"{n_rj};{n_cas}")
    log("ok", prog, mes, "RJ", n_rj, "casamentos", n_cas, "NIS conhecidos", len(nis))

_h = date.today(); FIM = _h.year * 100 + _h.month
_r = _h.month - 3; RECENTE = (_h.year if _r > 0 else _h.year - 1) * 100 + (_r if _r > 0 else _r + 12)

if __name__ == "__main__":
    for mes in reversed(meses(202303, FIM)): processar("novo-bolsa-familia", mes); time.sleep(5)
    for mes in reversed(meses(202111, 202302)): processar("auxilio-brasil", mes); time.sleep(5)
    for mes in reversed(meses(201601, 202110)): processar("bolsa-familia-pagamentos", mes); time.sleep(5)
    n = sum(1 for _ in open(SAIDA)) if SAIDA.exists() else 0
    log("FIM"); print(f"beneficios_historico: casamentos_socio={n} nis_conhecidos={len(nis)}")
