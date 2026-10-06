#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fserj_site_docs — índice dos contratos em PDF que a Fundação Saúde publica no site (sem API).

Páginas: rj.gov.br/fundacaosaude/{aquisicao2025,servicos2025,anterioresaquisicao,anterioresservicos}
(12/09/2026: 405 PDFs). O NOME do arquivo já traz o que interessa — tipo, nº do contrato, nº do processo
SEI e fornecedor: "CONTRATO 048.2025_Proc 4203.2023_EXTRACOR COMERCIO ... LTDA.pdf". Cobre o que o SEI
restringe a outras unidades (os autos da FSERJ). Materializa `fserj_site_docs`; `--baixar NOME` baixa os
PDFs do fornecedor e extrai o texto para data/fserj_site_docs/.

Uso: PYTHONPATH=. .venv/bin/python -m tools.fserj_site_docs [--baixar TUISE] [--baixar CMP]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
BASE = "https://www.rj.gov.br"
PAGINAS = ("aquisicao2025", "servicos2025", "aquisicao2026", "servicos2026", "anterioresaquisicao", "anterioresservicos")
DESTINO = _REPO / "data" / "fserj_site_docs"

_RE_PROC = re.compile(r"Proc\.?\s*[-_ ]?\s*(\d{3,6})[.\-/ ](\d{4})", re.I)
_RE_SEI = re.compile(r"SEI-?\s*(\d{6})[_/](\d{6})[_/](\d{4})", re.I)
_RE_NUM = re.compile(r"(?:CONTRATO|TERMO|ARP|COMODATO)[^0-9]{0,25}(\d{2,4})[.\-/](\d{4})", re.I)


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().split())


def parse_nome(url: str) -> dict:
    """Extrai tipo, nº, processo e fornecedor do NOME do arquivo. Fornecedor = último segmento após '_'
    (ou o resto após o nº do contrato quando não há '_'); processo em duas grafias (Proc 4203.2023 / SEI-080002_016174_2024)."""
    nome = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    base = re.sub(r"\.pdf$", "", nome, flags=re.I).strip()
    tipo = "COMODATO" if re.search(r"COMODATO", base, re.I) else ("ARP" if re.match(r"ARP", base, re.I) else
           "TERMO" if re.match(r"TERMO", base, re.I) else "CONTRATO")
    m = _RE_NUM.search(base)
    numero = f"{int(m.group(1)):03d}/{m.group(2)}" if m else None
    proc = None
    ms = _RE_SEI.search(base)
    if ms:
        proc = f"SEI-{ms.group(1)}/{ms.group(2)}/{ms.group(3)}"
    else:
        mp = _RE_PROC.search(base)
        if mp:
            proc = f"SEI-080002/{int(mp.group(1)):06d}/{mp.group(2)}"   # FSERJ = unidade 080002 (conferido no acervo)
    base_sem_sei = _RE_SEI.sub("", base)                       # "SEI-080002_016174_2024" não é fornecedor
    partes = [p.strip(" -_") for p in base_sem_sei.split("_") if p.strip(" -_")]
    forn = partes[-1] if len(partes) > 1 else ""
    if re.fullmatch(r"\d+", forn or "") and len(partes) > 2:      # sufixo "_0" de duplicata
        forn = partes[-2]
    if not re.search(r"[A-Za-z]{3}", forn or ""):
        forn = ""
    if not forn or re.search(r"^(Proc|SEI|ARP)\b", forn, re.I) or len(forn) < 5:
        # sem '_': "CONTRATO 108.2025 RIO TERUMED ... LTDA"
        resto = _RE_NUM.sub("", base, count=1).strip(" -_")
        resto = re.sub(r"^(Proc\.?\s*\S+|SEI-RJ.*?)\s*", "", resto).strip(" -_")
        forn = resto if len(resto) >= 5 and not re.match(r"^SEI", resto, re.I) else ""
    return {"arquivo": nome, "tipo": tipo, "numero": numero, "processo": proc, "fornecedor": _norm(forn)[:160] or None}


def indexar() -> dict:
    import httpx
    linhas = []
    for pg in PAGINAS:
        try:
            r = httpx.get(f"{BASE}/fundacaosaude/{pg}", headers={"User-Agent": "Mozilla/5.0 (JFN fiscalizacao)"},
                          timeout=60, follow_redirects=True)
        except (httpx.HTTPError, OSError) as exc:
            print(f"[fserj-site] {pg}: {exc}", flush=True)
            continue
        if r.status_code != 200:
            continue
        for href in sorted(set(re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text, re.I))):
            url = href if href.startswith("http") else BASE + href
            d = parse_nome(url)
            linhas.append((pg, url, d["arquivo"], d["tipo"], d["numero"], d["processo"], d["fornecedor"]))
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    with con:
        con.execute("CREATE TABLE IF NOT EXISTS fserj_site_docs (pagina TEXT, url TEXT PRIMARY KEY, arquivo TEXT, tipo TEXT, "
                    "numero TEXT, processo TEXT, fornecedor TEXT, texto_path TEXT, visto_em TEXT)")
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for l in linhas:
            con.execute("INSERT INTO fserj_site_docs (pagina,url,arquivo,tipo,numero,processo,fornecedor,visto_em) VALUES (?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(url) DO UPDATE SET visto_em=excluded.visto_em, fornecedor=excluded.fornecedor, processo=excluded.processo",
                        (*l, agora))
    n_proc = sum(1 for l in linhas if l[5]); n_forn = sum(1 for l in linhas if l[6])
    con.close()
    return {"pdfs": len(linhas), "com_processo": n_proc, "com_fornecedor": n_forn}


def baixar(nome_like: str, max_docs: int = 12) -> list[dict]:
    """Baixa os PDFs do fornecedor (LIKE no nome normalizado) e grava o texto em data/fserj_site_docs/."""
    import fitz
    import httpx
    DESTINO.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=120)
    rows = con.execute("SELECT url, arquivo FROM fserj_site_docs WHERE fornecedor LIKE ? AND texto_path IS NULL LIMIT ?",
                       (f"%{_norm(nome_like)}%", max_docs)).fetchall()
    out = []
    for url, arquivo in rows:
        try:
            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (JFN fiscalizacao)"}, timeout=120, follow_redirects=True)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                continue
            texto = "".join(p.get_text() for p in fitz.open(stream=r.content, filetype="pdf"))
            if len(texto.strip()) < 200:
                # contrato ESCANEADO (6 dos 8 da TUISE vieram com 0 chars): OCR bounded da casa
                from compliance_agent.sei.ocr_docs import ocr_documento
                texto = ocr_documento(r.content, tipo="pdf") or texto
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, ImportError) as exc:
            print(f"[fserj-site] {arquivo[:60]}: {exc}", flush=True)
            continue
        alvo = DESTINO / (re.sub(r"[^A-Za-z0-9._-]+", "_", arquivo)[:150] + ".txt")
        alvo.write_text(texto, encoding="utf-8")
        with con:   # sem texto (nem OCR) fica sem texto_path — volta a ser tentado na próxima rodada
            con.execute("UPDATE fserj_site_docs SET texto_path=? WHERE url=?", (str(alvo) if len(texto.strip()) >= 200 else None, url))
        out.append({"arquivo": arquivo, "chars": len(texto), "texto_path": str(alvo)})
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baixar", action="append", default=[], help="nome (LIKE) do fornecedor cujos PDFs baixar")
    ap.add_argument("--max", type=int, default=12)
    a = ap.parse_args()
    r = indexar()
    print(f"[fserj-site] {r['pdfs']} PDFs indexados · {r['com_processo']} com processo · {r['com_fornecedor']} com fornecedor")
    for n in a.baixar:
        for d in baixar(n, a.max):
            print(f"   baixado {d['arquivo'][:70]} ({d['chars']} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
