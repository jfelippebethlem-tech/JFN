#!/usr/bin/env python3
"""
SWEEP do SEI — lê os processos das OBs **um a um**, com LOGIN ÚNICO (itkava) e sessão reusada.

Confirmado ao vivo (2026-06-09): o reader lê processo a processo (ex.: SEI-330003/002534/2024 → 10 docs).
O `ler()` faz login a cada chamada (~49s); aqui logamos UMA vez e iteramos `ler_processo` (~15s/processo).

Honesto e seguro:
  - Prioriza por VALOR (maior exposição primeiro); pula o que já está em cache (<24h).
  - Fora do escopo do itkava (0 docs) é registrado e seguimos — não martela.
  - Resumível (checkpoint `data/sei_cache/sei_sweep_progress.json`).
  - Respeita a pausa do SIAFE (`data/.pause_sweep_2`) e o browser_lock (nunca 2 browsers).
  - Para sozinho se o login cair (WAF) ou ao atingir --max.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max 50          # lê até 50 processos novos
    PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max 50 --ug 133100   # só processos de OBs de uma UG
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "compliance.db"
CACHE = REPO / "data" / "sei_cache"
PROG = CACHE / "sei_sweep_progress.json"
PAUSE = REPO / "data" / ".pause_sei_sweep"  # pausa PRÓPRIA (o browser_lock já serializa com o SIAFE)
LOG = REPO / "data" / "sei_sweep.log"


def _log(m: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def _carregar_prog() -> dict:
    if PROG.exists():
        try:
            return json.loads(PROG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"feitos": {}}  # proc -> {n_docs, em}


def _salvar_prog(p: dict):
    PROG.parent.mkdir(parents=True, exist_ok=True)
    PROG.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def _unidades_legiveis() -> set[str]:
    """Unidades SEI que o itkava JÁ leu (cache cdp_*.json com documentos>0) — escopo aprendido.
    Ex.: de 'cdp_SEI_330003_002534_2024.json' (10 docs) extrai a unidade '330003'."""
    uni: set[str] = set()
    for cf in CACHE.glob("cdp_SEI_*.json"):
        try:
            d = json.loads(cf.read_text(encoding="utf-8"))
            if len(d.get("documentos") or []) > 0:
                m = re.search(r"cdp_SEI_(\d{6})_", cf.name)
                if m:
                    uni.add(m.group(1))
        except Exception:
            pass
    return uni


def _unidade(proc: str) -> str:
    m = re.match(r"SEI-(\d{6})/", proc)
    return m.group(1) if m else ""


def _fila(ug: str | None, limite: int) -> list[tuple]:
    """Processos SEI distintos das OBs, priorizando as UNIDADES que o itkava já leu (escopo
    aprendido), depois por valor desc. Evita queimar tempo em processos fora de escopo."""
    con = sqlite3.connect(str(DB))
    where = "numero_sei LIKE 'SEI-%/%/20%'"
    args: list = []
    if ug:
        where += " AND ug_codigo=?"
        args.append(ug)
    rows = con.execute(
        f"SELECT numero_sei, COUNT(*) nob, ROUND(SUM(valor),2) tot FROM ordens_bancarias "
        f"WHERE {where} GROUP BY numero_sei ORDER BY tot DESC LIMIT ?",
        (*args, limite * 12 + 200),
    ).fetchall()
    con.close()
    legiveis = _unidades_legiveis()
    # ordena: unidade legível primeiro (escopo conhecido), depois valor
    rows.sort(key=lambda r: (0 if _unidade(r[0]) in legiveis else 1, -(r[2] or 0)))
    return rows


def _ja_lido_ok(proc: str) -> bool:
    """True só se o processo já foi lido COM SUCESSO (documentos>0) e fresco (<7d). Um cache de 0 docs
    é leitura intermitente que FALHOU — não pular, retentar (a abertura do SEI é flaky)."""
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    if not cf.exists():
        return False
    try:
        c = json.loads(cf.read_text(encoding="utf-8"))
        if len(c.get("documentos") or []) > 0 and c.get("_cached_at"):
            return (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < 7 * 86400
    except Exception:
        pass
    return False


async def run(max_n: int, ug: str | None, tentativas_login: int = 20):
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from compliance_agent.collectors.sei_cdp import _proxy_do_env
    from tools.sei_reader import login, ler_processo
    from playwright.async_api import async_playwright

    prog = _carregar_prog()

    def _pular(p: str) -> bool:
        if _ja_lido_ok(p):
            return True
        f = prog["feitos"].get(p)
        # já lido com docs, ou já tentado >=3x sem sucesso (processo vazio/restrito de verdade)
        return bool(f and (f.get("n_docs", 0) > 0 or f.get("tentativas", 1) >= 3))

    fila = [(p, nob, tot) for (p, nob, tot) in _fila(ug, max_n) if not _pular(p)][:max_n]
    if not fila:
        _log("nada novo na fila (tudo já lido/cacheado).")
        return
    _log(f"fila: {len(fila)} processos novos (de OBs{'/UG ' + ug if ug else ''}); login único itkava…")

    await aguardar_load_async(max_por_core=1.5, espera_max=120)
    proxy = _proxy_do_env()
    n_ok = n_zero = n_doc_total = 0
    async with browser_lock_async(espera_max=600), async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                     **({"proxy": proxy} if proxy else {}))
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        try:
            if not await login(pg, tentativas=tentativas_login):
                _log("ABORTADO: login itkava não venceu o WAF agora (tente mais tarde).")
                return
            _log("login OK — varrendo…")
            for i, (proc, nob, tot) in enumerate(fila, 1):
                if PAUSE.exists():
                    _log("pausa detectada (.pause_sei_sweep) — encerrando limpo."); break
                t0 = time.time()
                # a busca→abrir do SEI é INTERMITENTE (cai na caixa) — retenta até abrir (docs/relacionados>0),
                # como o ler_com_cadeia. Sem retry, leituras válidas viravam "0 docs" (era o bug do sweep).
                try:
                    r, nd = {}, 0
                    for _try in range(3):
                        # SEMPRE fresco: _ja_lido_ok já pulou os sucessos; aqui são 0-doc/novos → não usar cache 0-doc.
                        r = await ler_processo(pg, proc, usar_cache=False)
                        nd = len(r.get("documentos") or [])
                        # sucesso = DOCUMENTOS>0. relacionados sozinho (sem docs) é a CAIXA/desktop (~40 inbox),
                        # NÃO um processo aberto — não contar como sucesso.
                        if nd > 0:
                            break
                        await asyncio.sleep(2)
                except Exception as e:  # noqa: BLE001
                    _log(f"  [{i}/{len(fila)}] {proc} ERRO {type(e).__name__}: {str(e)[:60]}")
                    continue
                _f = prog["feitos"].get(proc, {})
                prog["feitos"][proc] = {"n_docs": nd, "tentativas": _f.get("tentativas", 0) + 1,
                                        "rel": len(r.get("relacionados") or []),
                                        "em": datetime.now().isoformat(timespec="seconds")}
                _salvar_prog(prog)
                if nd:
                    n_ok += 1; n_doc_total += nd
                else:
                    n_zero += 1
                _log(f"  [{i}/{len(fila)}] {proc} → {nd} docs (R$ {tot:,.0f}, {nob} OBs) {time.time()-t0:.0f}s")
        finally:
            await b.close()
    _log(f"FIM: {n_ok} com docs ({n_doc_total} docs), {n_zero} sem (fora de escopo/vazio). "
         f"Progresso em {PROG.name}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--ug", type=str, default=None)
    a = ap.parse_args()
    asyncio.run(run(a.max, a.ug))


if __name__ == "__main__":
    main()
