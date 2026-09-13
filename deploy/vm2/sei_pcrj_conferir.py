# -*- coding: utf-8 -*-
"""Baixa ÍNTEGRAS do SEI da Prefeitura do Rio pela Conferência de Autenticidade (VM-2).

A pesquisa pública do prefeitura.sei.rio não abre documento nenhum; a conferência
(``controlador_externo.php?acao=documento_conferir``) abre — com o par verificador+CRC
que o D.O. Rio publica. A VM-1 colhe os pares (tools/pcrj_sei_crc_harvest.py) em
``~/shared-brain/sei_pcrj_crc_pares.txt`` (Syncthing); aqui cada par vira uma linha de
``sei_pcrj_documento`` no ``data/sei_pcrj.db`` (que o run_sweep.sh já copia de volta).

    .venv/bin/python sei_pcrj_conferir.py --max 60 --segundos 1500
    .venv/bin/python sei_pcrj_conferir.py --par 5950912 B3825257     # um só, verboso
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

import sei_pcrj_sweep as S

PARES = Path.home() / "shared-brain" / "sei_pcrj_crc_pares.txt"
CONFERIR = (f"{S.BASE}/sei/controlador_externo.php?acao=documento_conferir"
            "&id_orgao_acesso_externo=0")
_RX_ASSIN = re.compile(r"Lista de Assinaturas \((\d+) registros?\):(.*)$", re.S)
_RX_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)

DDL = """CREATE TABLE IF NOT EXISTS sei_pcrj_documento (
    verificador TEXT NOT NULL, crc TEXT NOT NULL, processo TEXT,
    arquivo TEXT, content_type TEXT, n_bytes INTEGER, texto TEXT,
    assinantes TEXT, erro TEXT, captcha_tentativas INTEGER, capturado_em TEXT,
    PRIMARY KEY (verificador, crc))"""


def _html_para_texto(html: str) -> str:
    t = _RX_TAG.sub(" ", html)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


OCR_PAGINAS = 6   # PDF escaneado (planta, ofício digitalizado): OCR só das primeiras páginas


def _pdf_para_texto(dados: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as f:
        f.write(dados)
        f.flush()
        r = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=120)
        texto = r.stdout.decode("utf-8", "replace").strip()
        if len(texto) >= 40:
            return texto
        # sem camada de texto → OCR (tesseract já está na VM-2 pelo captcha)
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["pdftoppm", "-r", "200", "-l", str(OCR_PAGINAS), "-png", f.name, f"{d}/p"],
                           capture_output=True, timeout=180)
            partes = []
            for png in sorted(Path(d).glob("p*.png")):
                o = subprocess.run(["tesseract", str(png), "-", "-l", "por"], capture_output=True, timeout=180)
                partes.append(o.stdout.decode("utf-8", "replace"))
        ocr = "\n".join(partes).strip()
        return f"[OCR {min(OCR_PAGINAS, len(partes))} pág.]\n{ocr}" if len(ocr) >= 40 else texto


def extrair_texto(content_type: str, dados: bytes) -> str:
    """HTML nativo do SEI → texto; PDF (anexo externo) → pdftotext. O erro da nota
    `integras-pcrj-tres-portas-uma-aberta` foi ler HTML como PDF: aqui o content-type manda."""
    ct = (content_type or "").lower()
    if "pdf" in ct or dados[:5] == b"%PDF-":
        return _pdf_para_texto(dados)
    if "html" in ct or b"<html" in dados[:2000].lower():
        return _html_para_texto(dados.decode("utf-8", "replace"))
    return ""


def _assinantes(texto_pagina: str) -> list[str]:
    m = _RX_ASSIN.search(texto_pagina)
    if not m:
        return []
    corpo = m.group(2)
    linhas = [ln.strip() for ln in corpo.splitlines() if ln.strip()]
    return [ln for ln in linhas[1:] if ln and not ln.startswith("Assinante")][: int(m.group(1)) + 2]


async def conferir(page, verificador: str, crc: str, *, max_captchas: int = 8, diag=None) -> dict:
    await page.goto(CONFERIR, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(3)
    await page.fill("#txtCodigoVerificador", verificador)
    await page.fill("#txtCrc", crc)
    for lido in range(1, max_captchas + 1):
        cap = await page.query_selector(S._SEL_CAP_IMG)
        if cap:
            ocr = S.ocr_captcha(await cap.screenshot())
            if ocr:
                await page.fill(S._SEL_CAP_FLD, ocr)
        await page.click("#sbmPesquisar", timeout=8000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(2)
        txt = await page.inner_text("body")
        low = S._norm_txt(txt)
        if S._ERRO_CAPTCHA in low:
            continue
        if "download do documento" not in low:
            motivo = "par não confere" if ("nao confere" in low or "nao encontrado" in low
                                           or "invalid" in low) else "sem link de download"
            return {"erro": motivo, "captcha_tentativas": lido}
        links = await page.evaluate(
            "()=>[...document.querySelectorAll('a[href]')].map(a=>a.href).filter(h=>/hash_download/.test(h))")
        resp = await page.context.request.get(links[0], timeout=120000)
        dados = await resp.body()
        ct = resp.headers.get("content-type", "")
        cd = resp.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";]+)', cd)
        texto = extrair_texto(ct, dados)
        if diag:
            diag(f"{verificador}/{crc}: {resp.status} {ct.split(';')[0]} {len(dados)} B → {len(texto)} chars")
        return {"arquivo": m.group(1) if m else None, "content_type": ct.split(";")[0],
                "n_bytes": len(dados), "texto": texto, "assinantes": _assinantes(txt),
                "captcha_tentativas": lido}
    return {"erro": "captcha não resolvido", "captcha_tentativas": max_captchas}


def _pares_pendentes(con: sqlite3.Connection, arq: Path) -> list[tuple[str, str, str]]:
    feitos = {tuple(r) for r in con.execute("SELECT verificador, crc FROM sei_pcrj_documento")}
    saida = []
    for ln in arq.read_text(encoding="utf-8").splitlines():
        partes = ln.split("\t")
        if len(partes) < 2:
            continue
        v, c = partes[0].strip(), partes[1].strip().upper()
        if (v, c) not in feitos:
            saida.append((v, c, partes[2].strip() if len(partes) > 2 else ""))
    return saida


def gravar(con: sqlite3.Connection, v: str, c: str, proc: str, r: dict) -> None:
    con.execute(
        "INSERT OR REPLACE INTO sei_pcrj_documento VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (v, c, proc or None, r.get("arquivo"), r.get("content_type"), r.get("n_bytes"),
         r.get("texto"), json.dumps(r.get("assinantes") or [], ensure_ascii=False),
         r.get("erro"), r.get("captcha_tentativas"), S._now()))
    con.commit()


async def lote(maxn: int, segundos: int) -> dict:
    con = sqlite3.connect(S.DB, timeout=60)
    con.execute(DDL)
    pend = _pares_pendentes(con, PARES) if PARES.exists() else []
    print(f"{S._now()} conferir: {len(pend)} pendentes (teto {maxn}, {segundos}s)", flush=True)
    ini = time.time()
    ok = err = 0

    async def run(pg):
        nonlocal ok, err
        for v, c, proc in pend[:maxn]:
            if time.time() - ini > segundos:
                break
            try:
                r = await asyncio.wait_for(conferir(pg, v, c, diag=lambda m: print("  " + m, flush=True)), 300)
            except Exception as e:  # noqa: BLE001 — um par não derruba o lote
                r = {"erro": f"{type(e).__name__}: {str(e)[:150]}"}
            gravar(con, v, c, proc, r)
            ok += 0 if r.get("erro") else 1
            err += 1 if r.get("erro") else 0
    await S._com_browser(run)
    con.close()
    res = {"ok": ok, "erro": err, "pendentes_restantes": max(0, len(pend) - ok - err)}
    print(f"{S._now()} conferir fim: {res}", flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--segundos", type=int, default=1500)
    ap.add_argument("--par", nargs=2, metavar=("VERIFICADOR", "CRC"))
    a = ap.parse_args()
    if a.par:
        async def um(pg):
            r = await conferir(pg, a.par[0], a.par[1].upper(), diag=print)
            print(json.dumps({k: (v[:300] if isinstance(v, str) else v) for k, v in r.items()}, ensure_ascii=False, indent=1))
        asyncio.run(S._com_browser(um))
        return
    asyncio.run(lote(a.max, a.segundos))


if __name__ == "__main__":
    main()
