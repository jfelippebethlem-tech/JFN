# -*- coding: utf-8 -*-
"""Baixa os ANEXOS (inteiro teor) dos contratos da Prefeitura do Rio pelo CCON (VM-2).

Porta: ContasRio → coluna "Anexos (Inteiro Teor)" → ``siafic-apps-externas.rio.rj.gov.br/ccon-web/?contrato=N``.
A página tem um desafio aritmético client-side e a API (``/ccon-api``) só responde ao próprio
navegador (F5 reseta HTTP puro) — por isso tudo acontece dentro do Playwright, por cliques.
Anexos típicos: contrato assinado, projeto básico/TR, ofício "autorizo", despachos do SEI.

Entrada: os CSVs ``data/contasrio/contratos_<ano>.csv`` (contasrio_export.py).
Saída: ``data/ccon.db::ccon_anexo`` (texto extraído; PDF escaneado → OCR das 6 primeiras páginas)
+ cópia em ``~/shared-brain/ccon.db`` (Syncthing → VM-1 ``tools/contasrio_ingest.py``).

    .venv/bin/python ccon_anexos.py --max 40 --segundos 1500
    .venv/bin/python ccon_anexos.py --contrato 2611958        # um só, verboso
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.async_api import async_playwright

RAIZ = Path(__file__).resolve().parent
DB = RAIZ / "data" / "ccon.db"
CSV_DIR = RAIZ / "data" / "contasrio"
SHARED = Path.home() / "shared-brain" / "ccon.db"
CCON = "https://siafic-apps-externas.rio.rj.gov.br/ccon-web/?contrato={c}"
OCR_PAGINAS = 6
_RX_CONTRATO = re.compile(r"ccon-web/\?contrato=(\d+)")
_RX_DESAFIO = re.compile(r"(\d+)\s*([+\-×x*])\s*(\d+)")

DDL = """
CREATE TABLE IF NOT EXISTS ccon_anexo (
    contrato TEXT NOT NULL, anexo_id INTEGER NOT NULL, tipo TEXT, descricao TEXT, arquivo TEXT,
    media_type TEXT, n_bytes INTEGER, texto TEXT, erro TEXT, capturado_em TEXT, PRIMARY KEY (contrato, anexo_id));
CREATE TABLE IF NOT EXISTS ccon_contrato (
    contrato TEXT PRIMARY KEY, n_anexos INTEGER, erro TEXT, capturado_em TEXT);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _brl(s: str) -> float:
    try:
        return float((s or "0").strip().replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def contratos_dos_csv(csv_dir: Path = CSV_DIR) -> list[tuple[str, float, str]]:
    """(id CCON, total pago, ano) de todos os CSVs, sem repetição, maiores pagamentos primeiro
    dentro do ano mais recente primeiro."""
    vistos: dict[str, tuple[float, str]] = {}
    for arq in sorted(csv_dir.glob("contratos_*.csv"), reverse=True):
        with open(arq, encoding="latin-1", newline="") as f:
            rows = list(csv.reader(f, delimiter=";"))
        for r in rows[2:]:
            if len(r) < 19:
                continue
            m = _RX_CONTRATO.search(r[13])
            if m and m.group(1) not in vistos:
                vistos[m.group(1)] = (_brl(r[18]), r[4].strip())
    return sorted(((c, v, a) for c, (v, a) in vistos.items()), key=lambda x: (x[2], x[1]), reverse=True)


def extrair_texto(path: Path) -> str:
    """PDF → pdftotext; sem camada de texto → OCR (tesseract, 6 páginas). Outros formatos → ''."""
    if path.suffix.lower() != ".pdf" and path.read_bytes()[:5] != b"%PDF-":
        return ""
    r = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=180)
    texto = r.stdout.decode("utf-8", "replace").strip()
    # camada de texto "de verdade" ou só um carimbo (extrato de 2 MB com 284 chars) → OCR
    if len(texto) >= 40 and (len(texto) >= 500 or path.stat().st_size < 300_000):
        return texto
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", "200", "-l", str(OCR_PAGINAS), "-png", str(path), f"{d}/p"],
                       capture_output=True, timeout=240)
        partes = [subprocess.run(["tesseract", str(png), "-", "-l", "por"], capture_output=True, timeout=240)
                  .stdout.decode("utf-8", "replace") for png in sorted(Path(d).glob("p*.png"))]
    ocr = "\n".join(partes).strip()
    return f"[OCR {len(partes)} pág.]\n{ocr}" if len(ocr) >= 40 else texto


async def _resolver_desafio(page) -> bool:
    try:
        await page.wait_for_selector("#captcha-challenge", state="visible", timeout=8000)
    except Exception:
        return True   # já validado na sessão
    m = _RX_DESAFIO.match((await page.inner_text("#captcha-challenge")).strip())
    if not m:
        return False
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    r = a + b if op == "+" else a - b if op == "-" else a * b
    await page.fill("#captcha-answer", str(r))
    await page.click("#captcha-submit")
    return True


async def capturar_contrato(page, contrato: str, pasta: Path, *, diag=None) -> dict:
    """Abre a página do contrato, lê a lista de anexos (JSON da API interceptado) e baixa cada um
    por clique em 'Download'. Retorna {anexos:[...]} ou {erro}."""
    lista: list[dict] = []

    async def _resp(r):
        if "ccon-api/api/anexos?" in r.url and r.status == 200:
            try:
                lista.extend(await r.json())
            except Exception:
                pass
    page.on("response", _resp)
    try:
        await page.goto(CCON.format(c=contrato), wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        if not await _resolver_desafio(page):
            return {"erro": "desafio ilegível"}
        for _ in range(30):
            await asyncio.sleep(1)
            txt = await page.inner_text("body")
            if lista or "Nenhum anexo" in txt or "Erro" in txt[:400]:
                break
        if not lista:
            txt1 = " ".join((await page.inner_text("body")).split())
            return {"anexos": [], "erro": None if "Nenhum anexo" in txt1 else f"sem lista: {txt1[-160:]}"}
        await asyncio.sleep(6)   # a página ainda renderiza/instrumenta (Dynatrace) — o bisect só funcionou com esta folga
        pasta.mkdir(parents=True, exist_ok=True)
        saida = []
        # clique no <a download> cancelava 2 em 6 (Chromium); navegar uma aba nova até o link baixa
        # todos (medido no contrato 2512362, 13/09/2026).
        hrefs = await page.evaluate("()=>[...document.querySelectorAll('a.btn-download')].map(a=>a.href)")
        por_id = {m.group(1): h for h in hrefs for m in [re.search(r"anexos/(\d+)/download", h)] if m}
        for item in lista:
            nome = re.sub(r"[^\w.\-]+", "_", item.get("nomeArquivo") or f"anexo_{item['id']}")[:150]
            alvo = pasta / f"{item['id']}_{nome}"
            href = por_id.get(str(item["id"]))
            if not href:
                saida.append({**item, "arquivo": None, "n_bytes": None, "texto": None, "erro": "sem link de download"})
                continue
            aba = await page.context.new_page()
            try:
                d = None
                for tentativa in (1, 2):
                    try:
                        async with aba.expect_download(timeout=90000) as dl:
                            try:
                                await aba.goto(href, timeout=90000)
                            except Exception:
                                pass   # "Download is starting" é o esperado
                        d = await dl.value
                        break
                    except Exception:
                        # quedas intermitentes (F5/bot-defense derruba pedidos em rajada): espera e tenta 1×;
                        # o contrato fica com erro e volta na fila do próximo lote.
                        if tentativa == 2:
                            raise
                        await aba.close()
                        await asyncio.sleep(20)
                        aba = await page.context.new_page()
                await d.save_as(str(alvo))
                texto = extrair_texto(alvo)
                saida.append({**item, "arquivo": alvo.name, "n_bytes": alvo.stat().st_size, "texto": texto})
                if diag:
                    diag(f"  {contrato} anexo {item['id']} {item.get('tipoAnexoNome')} · {alvo.stat().st_size} B → {len(texto)} chars")
            except Exception as e:  # noqa: BLE001 — um anexo não derruba o contrato
                saida.append({**item, "arquivo": None, "n_bytes": None, "texto": None, "erro": f"{type(e).__name__}: {str(e)[:120]}"})
                if diag:
                    diag(f"  {contrato} anexo {item['id']} ERRO {type(e).__name__}: {str(e)[:160]}")
            finally:
                await aba.close()
                await asyncio.sleep(4)   # ritmo: um anexo por vez, sem rajada
        com_erro = sum(1 for a in saida if a.get("erro"))
        return {"anexos": saida, "erro": f"{com_erro} anexo(s) com erro" if com_erro else None}
    finally:
        page.remove_listener("response", _resp)


def gravar(con: sqlite3.Connection, contrato: str, r: dict) -> None:
    for a in r.get("anexos") or []:
        con.execute("INSERT OR REPLACE INTO ccon_anexo VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (contrato, a["id"], a.get("tipoAnexoNome"), a.get("descricao"), a.get("arquivo"),
                     a.get("mediaType"), a.get("n_bytes"), a.get("texto"), a.get("erro"), _now()))
    con.execute("INSERT OR REPLACE INTO ccon_contrato VALUES (?,?,?,?)",
                (contrato, len(r.get("anexos") or []), r.get("erro"), _now()))
    con.commit()


async def lote(maxn: int, segundos: int, so: str | None = None) -> dict:
    con = sqlite3.connect(DB, timeout=60)
    con.executescript(DDL)
    if so:
        fila = [(so, 0.0, "")]
    else:
        feitos = {r[0] for r in con.execute("SELECT contrato FROM ccon_contrato WHERE erro IS NULL")}
        fila = [c for c in contratos_dos_csv() if c[0] not in feitos][:maxn]
    print(f"{_now()} ccon: {len(fila)} contrato(s) na fila (teto {maxn}, {segundos}s)", flush=True)
    ini, ok, err, n_anexos = time.time(), 0, 0, 0
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await b.new_context(accept_downloads=True)
        page = await ctx.new_page()
        try:
            for contrato, _, ano in fila:
                if time.time() - ini > segundos:
                    break
                try:
                    r = await asyncio.wait_for(capturar_contrato(page, contrato, RAIZ / "data" / "ccon" / contrato,
                                                                 diag=lambda m: print(m, flush=True)), 600)
                except Exception as e:  # noqa: BLE001
                    r = {"erro": f"{type(e).__name__}: {str(e)[:150]}"}
                gravar(con, contrato, r)
                ok += 0 if r.get("erro") else 1
                err += 1 if r.get("erro") else 0
                n_anexos += len(r.get("anexos") or [])
        finally:
            await b.close()
    con.close()
    try:
        SHARED.parent.mkdir(exist_ok=True)
        shutil.copy2(DB, SHARED)
    except OSError as e:
        print(f"cópia p/ shared-brain falhou: {e}", flush=True)
    res = {"contratos_ok": ok, "contratos_erro": err, "anexos": n_anexos}
    print(f"{_now()} ccon fim: {res}", flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--segundos", type=int, default=1500)
    ap.add_argument("--contrato", default=None)
    a = ap.parse_args()
    asyncio.run(lote(a.max, a.segundos, a.contrato))


if __name__ == "__main__":
    main()
