#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TUNNEL WINDOWS — Relay entre Chrome (9222) e JFN Server

Este script roda na MÁQUINA WINDOWS que tem acesso ao SIAFE.
Ele:
  1. Conecta ao Chrome no modo debug (porta 9222)
  2. Conecta ao JFN Server via WebSocket reverso
  3. Coleta as Ordens Bancárias 2023-2026 e envia ao servidor
  4. Servidor salva no banco e faz git push automaticamente

USO:
    python _SANDBOX/tunnel_windows.py

    # Ou com servidor explícito:
    python _SANDBOX/tunnel_windows.py --server ws://IP-DO-SERVIDOR:8000/tunnel

PRÉ-REQUISITOS (já satisfeitos se JFN.bat já rodou):
    pip install websockets playwright
    playwright install chromium
    Chrome rodando: --remote-debugging-port=9222

.env necessário:
    SIAFE_USER=<CPF>
    SIAFE_PASS=<senha>
    JFN_SERVER=ws://IP:8000/tunnel   (opcional — padrão: ws://localhost:8000/tunnel)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── Carregar .env ──────────────────────────────────────────────────────────────
for _env_path in [
    Path.home() / ".hermes" / ".env",
    Path(__file__).parents[1] / ".env",
    Path("C:/JFN/jfn/.env"),
    Path("C:/Users") / os.environ.get("USERNAME", "user") / "JFN" / ".env",
]:
    if _env_path.exists():
        for _ln in _env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                k, v = _ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SIAFE_USER  = os.environ.get("SIAFE_USER", "")
SIAFE_PASS  = os.environ.get("SIAFE_PASS", "")
JFN_SERVER  = os.environ.get("JFN_SERVER", "ws://localhost:8000/tunnel")
CNPJ        = "19088605000104"
CNPJ_FMT    = "19.088.605/0001-04"
NOME_EMP    = "MGS CLEAN SOLUCOES E SERVICOS LTDA"
LOGIN_URL   = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
EXERCICIOS  = {2026: "1", 2025: "2", 2024: "3", 2023: "4"}
TIMEOUT     = 40_000

# ── Seletores CSS ──────────────────────────────────────────────────────────────
SEL_USER    = "input[id*='itxUsuario']"
SEL_PASS    = "input[id*='itxSenhaAtual']"
SEL_CLI     = "select[id*='cbxCliente']"
SEL_EXE     = "select[id*='cbxExercicio']"
SEL_BTN_OK  = "button[id*='btnOk'], input[id*='btnOk'], a[id*='btnOk']"
_JS_LER_GRADE = """
(function() {
  var t = document.querySelector("table[id*='tblOrdemBancaria']");
  if (!t) return {headers:[], rows:[]};
  var ths = Array.from(t.querySelectorAll("thead th, thead td, tr.header td"))
    .map(c=>c.innerText.trim());
  var trs = Array.from(t.querySelectorAll("tbody tr"))
    .map(r=>Array.from(r.querySelectorAll("td")).map(c=>c.innerText.trim()));
  return {headers: ths, rows: trs.filter(r=>r.some(c=>c))};
})()
"""
_JS_PROXIMA = """
(function() {
  var btns = Array.from(document.querySelectorAll("a, button, span"))
    .filter(e => /próxim|next|>/i.test(e.innerText||e.title||"")
      && !e.closest('[style*="display:none"]'));
  if (!btns.length) return false;
  btns[0].click();
  return true;
})()
"""


# ──────────────────────────────────────────────────────────────────────────────
# Coleta de OBs
# ──────────────────────────────────────────────────────────────────────────────

async def _login(page, ano: int):
    exe_val = EXERCICIOS[ano]
    print(f"  [login] abrindo {LOGIN_URL} (exercício {ano})...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=TIMEOUT)
    await asyncio.sleep(2)

    for sel in [SEL_USER]:
        await page.click(sel, timeout=TIMEOUT)
        await page.keyboard.type(SIAFE_USER, delay=60)

    await page.click(SEL_PASS, timeout=TIMEOUT)
    await page.keyboard.type(SIAFE_PASS, delay=60)

    try:
        await page.select_option(SEL_CLI, value="0", timeout=8000)
    except Exception:
        pass
    try:
        await page.select_option(SEL_EXE, value=exe_val, timeout=8000)
    except Exception:
        pass

    await page.click(SEL_BTN_OK, timeout=TIMEOUT)
    await asyncio.sleep(4)
    url = page.url
    print(f"  [login] pós-login URL={url[:80]}")
    return "login" not in url.lower()


async def _ir_obs(page):
    """Navega para o módulo Ordens Bancárias no menu ADF."""
    # Tenta menu a.xgg (sempre renderizado no DOM)
    itens = await page.query_selector_all("a.xgg")
    for item in itens:
        txt = (await item.inner_text()).strip().lower()
        if "ordem" in txt and "bancária" in txt:
            await item.click()
            await asyncio.sleep(3)
            print("  [nav] OB Orçamentária via a.xgg OK")
            return True

    # Fallback: Execução Financeira → OB Orçamentária
    for top in await page.query_selector_all("a.xgh, a[class*='menu']"):
        txt = (await top.inner_text()).strip().lower()
        if "execução" in txt and "financ" in txt:
            await top.click()
            await asyncio.sleep(1.5)
            break

    itens = await page.query_selector_all("a.xgg, a[class*='menuItem']")
    for item in itens:
        txt = (await item.inner_text()).strip().lower()
        if "ordem" in txt and "bancária" in txt:
            await item.click()
            await asyncio.sleep(3)
            print("  [nav] OB via fallback xgh+xgg OK")
            return True

    # pt1 ID fallback
    for sel in [
        "a[id*='ExecucaoFinanceira']", "a[id*='OrdemBancaria']",
        "td[id*='OrdemBancaria']",
    ]:
        try:
            await page.click(sel, timeout=5000)
            await asyncio.sleep(2)
            print(f"  [nav] OB via {sel} OK")
            return True
        except Exception:
            pass

    print("  [nav] AVISO: não encontrou link de OB Orçamentária")
    return False


async def _filtrar_cnpj(page):
    """Abre filtro e pesquisa pelo CNPJ da MGS CLEAN."""
    filter_sels = [
        "a[id*='sdtFilter'], span[id*='sdtFilter']",
        "[id*='Accordion'][id*='Dec']",
    ]
    for sel in filter_sels:
        try:
            await page.click(sel, timeout=8000)
            await asyncio.sleep(1.5)
            break
        except Exception:
            pass

    # Campo CNPJ do favorecido
    cnpj_inputs = await page.query_selector_all(
        "input[id*='cnpj'], input[id*='Cnpj'], input[id*='CNPJ'], "
        "input[id*='favorecido'], input[id*='cpf']"
    )
    if cnpj_inputs:
        await cnpj_inputs[0].triple_click()
        await cnpj_inputs[0].type(CNPJ_FMT, delay=40)
    else:
        # Campo de texto genérico de pesquisa
        inputs = await page.query_selector_all("input[type='text']:visible")
        if inputs:
            await inputs[-1].triple_click()
            await inputs[-1].type(CNPJ_FMT, delay=40)

    pesq_sels = [
        "button[id*='btnPesquisar'], input[id*='btnPesquisar']",
        "a[id*='btnPesquisar'], button[id*='Pesquisar']",
    ]
    for sel in pesq_sels:
        try:
            await page.click(sel, timeout=6000)
            await asyncio.sleep(4)
            return True
        except Exception:
            pass

    # Enter como último recurso
    await page.keyboard.press("Enter")
    await asyncio.sleep(4)
    return True


async def _ler_todas_paginas(page) -> list[dict]:
    obs: list[dict] = []
    pagina = 1
    while True:
        result = await page.evaluate(_JS_LER_GRADE)
        headers = result.get("headers", [])
        rows    = result.get("rows", [])
        print(f"    pág {pagina}: {len(rows)} linhas, headers={headers[:6]}")

        for row in rows:
            ob = _mapear_linha(headers, row)
            if ob:
                obs.append(ob)

        tem_prox = await page.evaluate(_JS_PROXIMA)
        if not tem_prox:
            break
        pagina += 1
        await asyncio.sleep(2.5)

    return obs


def _mapear_linha(headers: list[str], row: list[str]) -> dict | None:
    """Mapeia linha da grade para dict de OB."""
    if not any(row):
        return None
    # Mapa flexível por texto do header
    hmap = {h.lower(): i for i, h in enumerate(headers)}

    def _col(*keys):
        for k in keys:
            for h, i in hmap.items():
                if k in h and i < len(row):
                    return row[i].strip()
        # Fallback posicional
        return ""

    val_raw = _col("valor")
    try:
        val = float(re.sub(r"[^\d,]", "", val_raw).replace(",", ".")) if val_raw else 0.0
    except Exception:
        val = 0.0

    numero = _col("número", "numero", "ob")
    if not numero:
        # Tenta posição 0
        numero = row[0].strip() if row else ""
    if not numero:
        return None

    return {
        "numero_ob":        numero,
        "data_emissao":     _col("data", "emissão"),
        "ug_codigo":        _col("ug emitente", "ug emit"),
        "ug_nome":          "",
        "favorecido_cpf":   CNPJ_FMT,
        "favorecido_nome":  NOME_EMP,
        "valor":            val,
        "tipo_ob":          _col("tipo"),
        "status":           _col("status"),
        "numero_processo":  _col("processo"),
        "categoria":        "mgs_clean_real",
        "fonte":            "siafe_tunnel",
        "raw_json":         json.dumps(dict(zip(headers, row))),
    }


async def _coletar_ano(page, ano: int) -> list[dict]:
    print(f"\n{'='*60}")
    print(f"  COLETANDO OBs — Exercício {ano}")
    print(f"{'='*60}")

    ok_login = await _login(page, ano)
    if not ok_login:
        print(f"  AVISO: login pode ter falhado para {ano}")

    ok_nav = await _ir_obs(page)
    if not ok_nav:
        print(f"  ERRO: não conseguiu navegar para OBs em {ano}")
        return []

    await _filtrar_cnpj(page)
    obs = await _ler_todas_paginas(page)
    for ob in obs:
        ob["exercicio"] = ano

    print(f"  [{ano}] Total: {len(obs)} OBs")
    return obs


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket tunnel — conecta ao servidor JFN
# ──────────────────────────────────────────────────────────────────────────────

async def _run_collection(ws_send, anos: list[int]):
    """Executa coleta completa e envia resultados via WebSocket."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            # Tenta conectar ao Chrome já aberto na porta 9222
            browser = await pw.chromium.connect_over_cdp(
                "http://127.0.0.1:9222", timeout=10000
            )
            print("  Conectado ao Chrome em modo debug (porta 9222)")
        except Exception:
            # Lança Chromium headless próprio
            browser = await pw.chromium.launch(headless=False)
            print("  Chrome 9222 não disponível, iniciando Chromium próprio")

        ctx  = await browser.new_context(locale="pt-BR")
        page = await ctx.new_page()

        todas_obs: list[dict] = []
        for ano in sorted(anos, reverse=True):
            await ws_send({"type": "progress", "msg": f"Coletando exercício {ano}..."})
            try:
                obs = await _coletar_ano(page, ano)
                todas_obs.extend(obs)
                await ws_send({
                    "type": "obs_batch",
                    "ano": ano,
                    "obs": obs,
                    "count": len(obs),
                })
                print(f"  [{ano}] {len(obs)} OBs enviadas ao servidor")
            except Exception as e:
                msg = f"Erro no exercício {ano}: {e}"
                print(f"  ERRO: {msg}")
                await ws_send({"type": "error", "ano": ano, "msg": msg})

        await browser.close()

    await ws_send({
        "type": "done",
        "total": len(todas_obs),
        "msg": f"Coleta concluída: {len(todas_obs)} OBs totais",
    })
    return todas_obs


async def tunnel_main(server_url: str):
    try:
        import websockets
    except ImportError:
        print("Instalando websockets...")
        os.system(f"{sys.executable} -m pip install websockets -q")
        import websockets

    if not SIAFE_USER or not SIAFE_PASS:
        print("ERRO: SIAFE_USER / SIAFE_PASS não definidos no .env")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  JFN TUNNEL — Conectando a {server_url}")
    print(f"{'='*60}\n")

    try:
        async with websockets.connect(server_url, ping_interval=30) as ws:
            print("  Conectado ao servidor JFN!")
            await ws.send(json.dumps({"type": "hello", "role": "windows_tunnel"}))

            async for raw in ws:
                msg = json.loads(raw)
                t   = msg.get("type", "")
                print(f"  ← {t}: {str(msg)[:120]}")

                if t == "collect":
                    anos = msg.get("anos", [2023, 2024, 2025, 2026])
                    print(f"\n  Iniciando coleta para anos: {anos}")

                    async def ws_send(payload: dict):
                        await ws.send(json.dumps(payload))

                    await _run_collection(ws_send, anos)

                elif t == "ping":
                    await ws.send(json.dumps({"type": "pong"}))

    except KeyboardInterrupt:
        print("\n  Interrompido pelo usuário.")
    except Exception as e:
        print(f"  ERRO na conexão: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="JFN Tunnel — relay entre Chrome local e JFN Server"
    )
    parser.add_argument(
        "--server",
        default=os.environ.get("JFN_SERVER", "ws://localhost:8000/tunnel"),
        help="URL WebSocket do servidor JFN (padrão: ws://localhost:8000/tunnel)",
    )
    args = parser.parse_args()
    asyncio.run(tunnel_main(args.server))
