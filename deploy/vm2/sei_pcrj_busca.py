# -*- coding: utf-8 -*-
"""Busca LIVRE na pesquisa pública do SEI da Prefeitura do Rio (VM-2).

Descoberta 13/09/2026: o formulário público esconde os campos `txtDescricaoPesquisa`/`as_q`
(busca livre no Solr do SEI), mas o servidor os honra. Com "Documentos Gerados/Recebidos"
marcados, um termo (nome de fornecedor, expressão) devolve PROCESSOS e DOCUMENTOS de todo o
acervo — inclusive da era Processo.rio (SMS-OFI-2023/…) — paginados por AJAX
(`md_pesq_controlador_ajax_externo.php?…&isPaginacao=true&inicio=N&rowsSolr=50`), sem
captcha novo por página. É a porta de DESCOBERTA: quais processos existem para cada alvo.

Entrada: ``~/shared-brain/sei_pcrj_busca_termos.txt`` (termo<TAB>origem<TAB>peso; VM-1).
Saída: ``data/sei_pcrj.db::sei_pcrj_busca`` (termo, prot, titulo, tipo_registro, unidade, data,
href) + processos novos anexados a ``fila.txt`` (o sweep captura árvore e assinaturas).

    .venv/bin/python sei_pcrj_busca.py --max-termos 30 --segundos 1500
    .venv/bin/python sei_pcrj_busca.py --termo "TUISE"          # um só, verboso
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import time
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

import sei_pcrj_sweep as S

TERMOS = Path.home() / "shared-brain" / "sei_pcrj_busca_termos.txt"
FILA = S.RAIZ / "fila.txt"
ROWS = 50
TETO_ITENS = 2000          # por termo: além disso o termo é genérico demais
_RX_PROC = re.compile(r"^\d{6}\.\d{6}/20\d{2}-\d{2}$")

DDL = """CREATE TABLE IF NOT EXISTS sei_pcrj_busca (
    termo TEXT NOT NULL, prot TEXT NOT NULL, processo TEXT, titulo TEXT, tipo_registro TEXT, unidade TEXT, data TEXT,
    snippet TEXT, href TEXT, capturado_em TEXT, PRIMARY KEY (termo, prot));
CREATE TABLE IF NOT EXISTS sei_pcrj_busca_termo (
    termo TEXT PRIMARY KEY, itens INTEGER, lidos INTEGER, erro TEXT, capturado_em TEXT);"""

_JS_LINHAS = """() => [...document.querySelectorAll('tr.pesquisaTituloRegistro')].map(tr => {
    const td = tr.querySelector('td[data-prot]');
    const a = tr.querySelector('a[href]');
    let meta = '', snip = '', nxt = tr.nextElementSibling;
    for (let k = 0; k < 2 && nxt && !nxt.classList.contains('pesquisaTituloRegistro'); k++, nxt = nxt.nextElementSibling) {
        const t = nxt.innerText.replace(/\\s+/g, ' ').trim();
        if (nxt.classList.contains('resSnippet')) snip = t.slice(0, 600); else meta = t.slice(0, 300); }
    return {prot: td ? td.getAttribute('data-prot') : null,
            titulo: tr.innerText.replace(/\\s+/g, ' ').trim().slice(0, 300),
            href: a ? a.href : null, meta, snip};
})"""

_JS_AJAX = """async (ini) => {
    const resp = await fetch('md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar'
        + '&id_orgao_acesso_externo=0&isPaginacao=true&inicio=' + ini + '&rowsSolr=%d',
        {method: 'POST', body: new URLSearchParams($('#seiSearch').serialize())});
    const txt = await resp.text();
    let d; try { d = JSON.parse(txt); } catch (e) { return {status: resp.status, itens: null, linhas: []}; }
    const box = document.createElement('table'); box.innerHTML = d.html || '';
    const linhas = [...box.querySelectorAll('tr.pesquisaTituloRegistro')].map(tr => {
        const td = tr.querySelector('td[data-prot]'); const a = tr.querySelector('a[href]');
        let meta = '', snip = '', nxt = tr.nextElementSibling;
        for (let k = 0; k < 2 && nxt && !nxt.classList.contains('pesquisaTituloRegistro'); k++, nxt = nxt.nextElementSibling) {
            const t = nxt.textContent.replace(/\\s+/g, ' ').trim();
            if (nxt.classList.contains('resSnippet')) snip = t.slice(0, 600); else meta = t.slice(0, 300); }
        return {prot: td ? td.getAttribute('data-prot') : null,
                titulo: tr.textContent.replace(/\\s+/g, ' ').trim().slice(0, 300), href: a ? a.href : null, meta, snip};
    });
    return {status: resp.status, itens: d.itens, linhas};
}""" % ROWS

_RX_META = re.compile(r"Unidade:\s*(\S+).*?Data:\s*(\d{2}/\d{2}/\d{4})")
_RX_PROC_TIT = re.compile(r"n[ºo]\s*(\d{6}\.\d{6}/20\d{2}-\d{2}|[A-Z]{2,5}-[A-Z]{3}-20\d{2}/\d{5}(?:\.\d+)?)")


def _linha(termo: str, ln: dict) -> tuple | None:
    prot = (ln.get("prot") or "").strip()
    if not prot:
        return None
    m = _RX_META.search(ln.get("meta") or "")
    titulo = ln.get("titulo") or ""
    tipo = "processo" if _RX_PROC.match(prot) else ("documento" if prot.isdigit() else "legado")
    mp = _RX_PROC_TIT.search(titulo)
    processo = prot if tipo == "processo" else (mp.group(1) if mp else None)
    return (termo, prot, processo, titulo[:300], tipo, m.group(1) if m else None, m.group(2) if m else None,
            (ln.get("snip") or "")[:600] or None, ln.get("href"), S._now())


async def _abrir_busca(page, termo: str) -> bool:
    """Formulário com busca livre + documentos gerados/recebidos (o campo é oculto: setar por JS)."""
    if not await S._abrir_form(page, "", espera=4):
        return False
    await page.evaluate("""(q) => {
        for (const id of ['chkSinDocumentosGerados', 'chkSinDocumentosRecebidos']) {
            const c = document.getElementById(id); if (c && !c.checked) c.click(); }
        for (const id of ['txtDescricaoPesquisa', 'as_q']) {
            const e = document.getElementById(id) || document.querySelector('[name="' + id + '"]');
            if (e) { e.value = q; } }
        const p = document.getElementById('partialfields'); if (p) p.value = '';
    }""", termo)
    return True


async def buscar_termo(page, termo: str, *, max_captchas: int = 20, diag=None) -> dict:
    if not await _abrir_busca(page, termo):
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
            if not await _abrir_busca(page, termo):
                break
            continue
        linhas = await page.evaluate(_JS_LINHAS)
        itens = None
        ini = ROWS
        while True:
            r = await page.evaluate(_JS_AJAX, ini)
            if itens is None:
                itens = r.get("itens")
            if not r.get("linhas"):
                break
            linhas.extend(r["linhas"])
            ini += ROWS
            if itens is not None and (ini >= itens or ini >= TETO_ITENS):
                break
            await asyncio.sleep(0.8)
        if diag:
            diag(f"'{termo}': {itens} itens no Solr, {len(linhas)} linhas lidas ({lido} captcha)")
        return {"itens": itens, "linhas": linhas, "captchas": lido}
    return {"erro": "captcha não resolvido"}


def gravar(con: sqlite3.Connection, termo: str, r: dict) -> int:
    novos_proc = 0
    if r.get("linhas"):
        regs = [t for t in (_linha(termo, ln) for ln in r["linhas"]) if t]
        con.executemany("INSERT OR IGNORE INTO sei_pcrj_busca VALUES (?,?,?,?,?,?,?,?,?,?)", regs)
        procs = {t[2] for t in regs if t[2] and _RX_PROC.match(t[2])}
        if procs:
            atuais = set(FILA.read_text().split()) if FILA.exists() else set()
            novos = sorted(procs - atuais)
            if novos:
                with open(FILA, "a", encoding="utf-8") as f:
                    f.write("".join(n + "\n" for n in novos))
            novos_proc = len(novos)
    con.execute("INSERT OR REPLACE INTO sei_pcrj_busca_termo VALUES (?,?,?,?,?)",
                (termo, r.get("itens"), len(r.get("linhas") or []), r.get("erro"), S._now()))
    con.commit()
    return novos_proc


def _termos_pendentes(con: sqlite3.Connection) -> list[str]:
    feitos = {r[0] for r in con.execute("SELECT termo FROM sei_pcrj_busca_termo WHERE erro IS NULL")}
    saida = []
    for ln in TERMOS.read_text(encoding="utf-8").splitlines():
        t = ln.split("\t")[0].strip()
        if t and t not in feitos:
            saida.append(t)
    return saida


async def lote(max_termos: int, segundos: int, so: str | None = None) -> dict:
    con = sqlite3.connect(S.DB, timeout=60)
    con.executescript(DDL)
    termos = [so] if so else (_termos_pendentes(con) if TERMOS.exists() else [])[:max_termos]
    print(f"{S._now()} busca: {len(termos)} termo(s) (teto {max_termos}, {segundos}s)", flush=True)
    ini, ok, err, novos = time.time(), 0, 0, 0

    async def run(pg):
        nonlocal ok, err, novos
        for termo in termos:
            if time.time() - ini > segundos:
                break
            try:
                r = await asyncio.wait_for(buscar_termo(pg, termo, diag=lambda m: print("  " + m, flush=True)), 600)
            except (PlaywrightError, asyncio.TimeoutError, OSError) as e:
                r = {"erro": f"{type(e).__name__}: {str(e)[:150]}"}
            novos += gravar(con, termo, r)
            ok += 0 if r.get("erro") else 1
            err += 1 if r.get("erro") else 0
    await S._com_browser(run)
    con.close()
    res = {"termos_ok": ok, "termos_erro": err, "processos_novos_na_fila": novos}
    print(f"{S._now()} busca fim: {res}", flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-termos", type=int, default=30)
    ap.add_argument("--segundos", type=int, default=1500)
    ap.add_argument("--termo", default=None)
    a = ap.parse_args()
    asyncio.run(lote(a.max_termos, a.segundos, a.termo))


if __name__ == "__main__":
    main()
