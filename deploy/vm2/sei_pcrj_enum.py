# -*- coding: utf-8 -*-
"""Enumera TODOS os processos públicos do SEI da Prefeitura do Rio, dia a dia (VM-2).

Como: a pesquisa pública aceita `as_q="*"` (campo oculto) com "Processos" marcado e janela de
datas explícita; o Solr devolve cada processo gerado no dia (nº, tipo, unidade, data), paginado
por AJAX sem captcha novo (medido 13/09/2026: 01/09/2026 = 3.557 processos, paginação até o fim).
Um captcha por dia consultado. Não abre conteúdo — é o CATÁLOGO completo, que vira alvo dirigido
(por tipo de processo/unidade) para a captura de árvore e para os pedidos de vistas.

Saída: ``data/sei_pcrj.db::sei_pcrj_enum`` (processo, tipo, unidade, data) e ``sei_pcrj_enum_dia``.

    .venv/bin/python sei_pcrj_enum.py --dias 10 --segundos 1500        # dias ainda não enumerados
    .venv/bin/python sei_pcrj_enum.py --dia 01/09/2026                  # um só, verboso
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import time
from datetime import date, datetime, timedelta

from playwright.async_api import Error as PlaywrightError

import sei_pcrj_busca as B
import sei_pcrj_sweep as S

INICIO_SEI = date(2025, 12, 5)     # SEI!RIO substituiu o Processo.rio em 05/12/2025
ROWS = 50
_RX_META = re.compile(r"Unidade:\s*(\S+).*?Data:\s*(\d{2}/\d{2}/\d{4})")
_RX_TIPO = re.compile(r"^(.*?)\s*n[ºo]\s*\d{6}\.\d{6}/20\d{2}-\d{2}")

DDL = """CREATE TABLE IF NOT EXISTS sei_pcrj_enum (
    processo TEXT PRIMARY KEY, tipo TEXT, unidade TEXT, data TEXT, dia_consulta TEXT, capturado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_sei_pcrj_enum_tipo ON sei_pcrj_enum(tipo);
CREATE TABLE IF NOT EXISTS sei_pcrj_enum_dia (
    dia TEXT PRIMARY KEY, itens INTEGER, lidos INTEGER, captchas INTEGER, erro TEXT, capturado_em TEXT);"""


async def _abrir_dia(page, dia: str) -> bool:
    if not await B._abrir_busca(page, "*"):
        return False
    await page.evaluate("""(d) => {
        for (const id of ['chkSinDocumentosGerados', 'chkSinDocumentosRecebidos']) {
            const c = document.getElementById(id); if (c && c.checked) c.click(); }
        const p = document.getElementById('partialfields'); if (p) p.value = 'sta_prot:P';
        const r = document.getElementById('optPeriodoExplicito'); if (r) r.checked = true;
        for (const id of ['txtDataInicio', 'txtDataFim']) { const e = document.getElementById(id); if (e) e.value = d; }
    }""", dia)
    return True


async def enumerar_dia(page, dia: str, *, max_captchas: int = 20, diag=None) -> dict:
    if not await _abrir_dia(page, dia):
        return {"erro": "form não abriu"}
    for lido in range(1, max_captchas + 1):
        img = await page.query_selector(S._SEL_CAP_IMG)
        if not img:
            break
        ocr = S.ocr_captcha(await img.screenshot())
        fld = await page.query_selector(S._SEL_CAP_FLD)
        if fld and ocr:
            await fld.fill(ocr)
        await S._submeter(page)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
        except PlaywrightError:
            pass
        await asyncio.sleep(1.5)
        low = S._norm_txt(await page.inner_text("body"))
        if S._ERRO_CAPTCHA in low:
            if not await _abrir_dia(page, dia):
                break
            continue
        linhas = await page.evaluate(B._JS_LINHAS)
        itens, ini = None, ROWS
        while True:
            r = await page.evaluate(B._JS_AJAX, ini)
            if itens is None:
                itens = r.get("itens")
            if not r.get("linhas"):
                break
            linhas.extend(r["linhas"])
            ini += ROWS
            if itens is not None and ini >= itens:
                break
            await asyncio.sleep(0.5)
        if diag:
            diag(f"{dia}: {itens} processos no Solr, {len(linhas)} lidos ({lido} captcha)")
        return {"itens": itens, "linhas": linhas, "captchas": lido}
    return {"erro": "captcha não resolvido"}


def _registro(ln: dict, dia: str) -> tuple | None:
    prot = (ln.get("prot") or "").strip()
    if not B._RX_PROC.match(prot):
        return None
    m = _RX_META.search(ln.get("meta") or "")
    mt = _RX_TIPO.match(ln.get("titulo") or "")
    return (prot, (mt.group(1).strip() if mt else None), m.group(1) if m else None, m.group(2) if m else None, dia, S._now())


def gravar(con: sqlite3.Connection, dia: str, r: dict) -> int:
    regs = [t for t in (_registro(ln, dia) for ln in (r.get("linhas") or [])) if t]
    con.executemany("INSERT OR IGNORE INTO sei_pcrj_enum VALUES (?,?,?,?,?,?)", regs)
    con.execute("INSERT OR REPLACE INTO sei_pcrj_enum_dia VALUES (?,?,?,?,?,?)",
                (dia, r.get("itens"), len(regs), r.get("captchas"), r.get("erro"), S._now()))
    con.commit()
    return len(regs)


def _dias_pendentes(con: sqlite3.Connection) -> list[str]:
    """Do dia mais recente para trás até 05/12/2025; um dia conta como feito quando lidos ≥ itens."""
    feitos = {d for d, it, li in con.execute("SELECT dia, itens, lidos FROM sei_pcrj_enum_dia WHERE erro IS NULL")
              if it is not None and li >= it}
    hoje = date.today()
    saida = []
    d = hoje - timedelta(days=1)
    while d >= INICIO_SEI:
        s = d.strftime("%d/%m/%Y")
        if s not in feitos:
            saida.append(s)
        d -= timedelta(days=1)
    return saida


async def lote(max_dias: int, segundos: int, so: str | None = None) -> dict:
    con = sqlite3.connect(S.DB, timeout=60)
    con.executescript(DDL)
    dias = [so] if so else _dias_pendentes(con)[:max_dias]
    print(f"{S._now()} enum: {len(dias)} dia(s) (teto {max_dias}, {segundos}s)", flush=True)
    ini, ok, err, n = time.time(), 0, 0, 0

    async def run(pg):
        nonlocal ok, err, n
        for dia in dias:
            if time.time() - ini > segundos:
                break
            try:
                r = await asyncio.wait_for(enumerar_dia(pg, dia, diag=lambda m: print("  " + m, flush=True)), 900)
            except (PlaywrightError, asyncio.TimeoutError, OSError) as e:
                r = {"erro": f"{type(e).__name__}: {str(e)[:150]}"}
            n += gravar(con, dia, r)
            ok += 0 if r.get("erro") else 1
            err += 1 if r.get("erro") else 0
    await S._com_browser(run)
    con.close()
    res = {"dias_ok": ok, "dias_erro": err, "processos": n}
    print(f"{S._now()} enum fim: {res}", flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dias", type=int, default=10)
    ap.add_argument("--segundos", type=int, default=1500)
    ap.add_argument("--dia", default=None, help="DD/MM/AAAA")
    a = ap.parse_args()
    if a.dia:
        datetime.strptime(a.dia, "%d/%m/%Y")
    asyncio.run(lote(a.dias, a.segundos, a.dia))


if __name__ == "__main__":
    main()
