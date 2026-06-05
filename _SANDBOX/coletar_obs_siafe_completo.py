#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MGS CLEAN — Coleta completa de Ordens Bancárias no SIAFE (2023–2026)
Roda na máquina Windows com acesso ao SIAFE.

Uso (uma linha, sem configuração manual):
    python _SANDBOX/coletar_obs_siafe_completo.py

Requerimentos (Windows):
    pip install playwright
    playwright install chromium

Credenciais em ~/.hermes/.env ou .env (nunca no git):
    SIAFE_USER=14398839712
    SIAFE_PASS=214398Jfn

Saída:
    data/sei_cache/mgsclean_obs_AAAA.json   — OBs por ano
    data/sei_cache/mgsclean_obs_todas.json  — todas as OBs consolidadas
    data/sei_cache/mgsclean_obs_resumo.md   — relatório Markdown (org × mês × OB)

Depois de rodar, gere o PDF:
    python _SANDBOX/gerar_relatorio_obs_pdf.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── Carregar .env ─────────────────────────────────────────────────────────────
for _env in [
    Path.home() / ".hermes" / ".env",
    Path(__file__).parents[1] / ".env",
    Path("C:/JFN/jfn/.env"),
]:
    if _env.exists():
        for _ln in _env.read_text(encoding="utf-8", errors="replace").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                k, v = _ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ── Constantes ────────────────────────────────────────────────────────────────
CNPJ       = "19088605000104"
CNPJ_FMT   = "19.088.605/0001-04"
LOGIN_URL  = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
CACHE_DIR  = Path(__file__).parents[1] / "data" / "sei_cache"
TIMEOUT    = 45_000   # ms

# Exercício → valor do SELECT na tela de login
# 2027=0, 2026=1, 2025=2, 2024=3, 2023=4, 2022=5, 2021=6 (confirmado ao vivo)
EXERCICIOS = {2026: "1", 2025: "2", 2024: "3", 2023: "4"}

MESES_PT = {
    1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
    7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro",
}

_UG_NOMES = {
    "270001":"SEPM — Polícia Militar",        "270003":"FUNESBOM",
    "270005":"Tribunal de Justiça (FESP)",   "270006":"TCE-RJ",
    "270009":"PGE",                           "270015":"SECEC",
    "270016":"FUNESBOM",                      "270020":"RIOPREVIDÊNCIA",
    "270024":"INEA",                          "270029":"Fundo Est. Saúde",
    "270042":"ITERJ",                         "270051":"PM — Polícia Militar",
    "270060":"Casa Civil",                    "300100":"SEFAZ-RJ",
}

def _ug_nome(c): return _UG_NOMES.get(str(c), str(c))
def _brl(v):
    s = f"{abs(v):,.2f}".replace(",","X").replace(".","," ).replace("X",".")
    return f"R$ {s}"
def _parse_money(s):
    try: return float(re.sub(r"[^\d,]","",str(s)).replace(",",".") or "0")
    except: return 0.0
def _parse_date(s):
    for fmt in ("%d/%m/%Y","%Y-%m-%d"):
        try: return datetime.strptime(s.strip(), fmt)
        except: pass
    return None


# ── Helpers de espera / dismiss ───────────────────────────────────────────────

async def _aguardar(pg, ms=3000):
    try: await pg.wait_for_load_state("networkidle", timeout=ms)
    except: pass
    await asyncio.sleep(max(1.5, ms/2000))


async def _fechar_popups(pg, tentativas=8):
    """Fecha modais ADF (OK/Sim/Fechar) que bloqueiam a navegação."""
    for _ in range(tentativas):
        fechou = await pg.evaluate("""() => {
            for (const sel of ['#myBtnOk','[id*="dlg"][id*="Ok"]','[id*="popup"][id*="ok"]']) {
                const el = document.querySelector(sel);
                if (el) { const r=el.getBoundingClientRect(); if(r.width>0){el.click();return sel;} }
            }
            for (const el of document.querySelectorAll('button,a,input[type="button"]')) {
                const t = el.textContent.trim().toLowerCase();
                const r = el.getBoundingClientRect();
                if (r.width>0 && (t==='ok'||t==='sim'||t==='fechar'||t==='confirmar'))
                    { el.click(); return t; }
            }
            return null;
        }""")
        if fechou:
            print(f"    → Popup fechado: {fechou}")
            await asyncio.sleep(2)
        else:
            break


async def _clique_real(pg, element_id: str, label: str = "") -> bool:
    """
    Executa clique REAL no elemento — necessário para menus Oracle ADF.
    JS el.click() não funciona no ADF; Playwright .click() dispara evento real.
    """
    lbl = label or element_id[-30:]
    # 1. Tenta pelo ID exato
    try:
        loc = pg.locator(f'[id="{element_id}"]')
        if await loc.count() > 0:
            await loc.first.scroll_into_view_if_needed(timeout=5000)
            await loc.first.click(timeout=8000, force=True)
            print(f"    ✔ Clique (id): {lbl}")
            return True
    except Exception as e:
        print(f"    [w] id click {lbl}: {e}")

    # 2. Tenta por ID parcial
    try:
        loc = pg.locator(f'[id*="{element_id[-20:]}"]').first
        await loc.click(timeout=8000, force=True)
        print(f"    ✔ Clique (id parcial): {lbl}")
        return True
    except Exception:
        pass

    # 3. Tenta por texto (fallback)
    if label:
        try:
            loc = pg.get_by_text(label, exact=True).first
            if await loc.count() > 0:
                await loc.click(timeout=8000, force=True)
                print(f"    ✔ Clique (texto): {label}")
                return True
        except Exception:
            pass

    print(f"    ✖ Não clicou: {lbl}")
    return False


# ── PASSO 1: Login ────────────────────────────────────────────────────────────

async def _login(pg, ano: int) -> bool:
    usuario = os.environ.get("SIAFE_USER") or os.environ.get("SIAFE_USUARIO","")
    senha   = os.environ.get("SIAFE_PASS") or os.environ.get("SIAFE_SENHA","")
    if not usuario or not senha:
        print("  [ERRO] Credenciais não encontradas. Defina SIAFE_USER e SIAFE_PASS no .env")
        sys.exit(1)

    exercicio_val = EXERCICIOS.get(ano, "1")
    print(f"\n  → Login exercício {ano} (valor SELECT={exercicio_val}) …")

    # Carrega a tela de login
    await pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=TIMEOUT)
    await asyncio.sleep(3)
    await _fechar_popups(pg)

    # Preenche usuário: clica no campo e digita (ADF requer keystroke real)
    for field_id, value in [
        ("loginBox:itxUsuario::content",     usuario),
        ("loginBox:itxSenhaAtual::content",  senha),
    ]:
        try:
            el = pg.locator(f'[id="{field_id}"]').first
            await el.click(timeout=5000)
            await el.fill("")
            await pg.keyboard.type(value, delay=60)
            await asyncio.sleep(0.5)
        except Exception as exc:
            print(f"    [w] campo {field_id}: {exc}")
            # Fallback JS
            await pg.evaluate(f"""(v)=>{{
                const el=document.getElementById('{field_id}');
                if(el){{el.value=v;['input','change','blur'].forEach(e=>
                    el.dispatchEvent(new Event(e,{{bubbles:true}})));}}
            }}""", value)

    # Seleciona cliente (RJ) e exercício
    for sel_part, val in [
        ("cbxCliente",   "0"),
        ("cbxExercicio", exercicio_val),
    ]:
        try:
            loc = pg.locator(f'[id*="{sel_part}"]').first
            await loc.select_option(val, timeout=5000)
            await asyncio.sleep(1)
        except Exception as exc:
            print(f"    [w] select {sel_part}: {exc}")

    await asyncio.sleep(1)

    # Clica em OK / btnConfirmar (clique REAL)
    confirmou = False
    for btn_id in ["loginBox:btnConfirmar", "btnConfirmar"]:
        try:
            loc = pg.locator(f'[id*="{btn_id}"]').first
            if await loc.count() > 0:
                await loc.click(timeout=5000)
                confirmou = True
                break
        except Exception:
            pass

    if not confirmou:
        # Fallback: submit via Enter
        await pg.keyboard.press("Enter")

    # Aguarda carregar (pode ser lento)
    await asyncio.sleep(7)
    await _fechar_popups(pg)
    await asyncio.sleep(2)

    url_atual = pg.url.lower()
    ok = "login" not in url_atual and "autenticacao" not in url_atual
    print(f"  → Login {'✔ OK' if ok else '✖ FALHOU'} — {pg.url[:90]}")
    return ok


# ── PASSO 2: Navegar até Ordens Bancárias ────────────────────────────────────

async def _ir_obs(pg) -> bool:
    """
    Execução → Execução Financeira → Ordens Bancárias.
    Usa cliques REAIS (obrigatório para menus ADF).
    """
    if "ordembancaria" in pg.url.lower():
        return True

    print("  → Navegando: Execução > Execução Financeira > Ordens Bancárias")

    # Passo 1: menu "Execução"
    await _clique_real(pg, "pt1:pt_np4:1:pt_cni6::disclosureAnchor", "Execução")
    await asyncio.sleep(4)
    await _fechar_popups(pg)

    # Passo 2: sub-menu "Execução Financeira"
    await _clique_real(pg, "pt1:pt_np3:1:pt_cni4::disclosureAnchor", "Execução Financeira")
    await asyncio.sleep(4)
    await _fechar_popups(pg)

    # Passo 3: item "Ordens Bancárias"
    await _clique_real(pg, "pt1:pt_np2:8:pt_cni3", "Ordens Bancárias")
    await asyncio.sleep(5)
    await _fechar_popups(pg)

    ok = "ordembancaria" in pg.url.lower()
    if not ok:
        print(f"  [WARN] URL esperada (ordembancaria) não encontrada: {pg.url[:80]}")
        # Tenta achar a tabela mesmo sem a URL correta
        tbl = await pg.evaluate("()=>!!document.querySelector('[id*=tblOrdemBancaria]')")
        ok = tbl
        print(f"  → Tabela tblOrdemBancaria na página: {tbl}")

    print(f"  → Tela OB: {'✔ OK' if ok else '✖ FALHOU'}")
    return ok


# ── PASSO 4: Filtrar pelo CNPJ ────────────────────────────────────────────────

async def _filtrar_cnpj(pg, cnpj: str) -> bool:
    """
    Abre o filtro da grade Ordens Bancárias e filtra pelo CNPJ do favorecido.
    IDs confirmados na rotina de auditoria (SIAFE-rotina-auditoria.md).
    """
    print(f"  → Aplicando filtro CNPJ {cnpj} …")

    # Abre acordeão de filtro (clique REAL)
    abriu = await _clique_real(
        pg,
        "pt1:tblOrdemBancaria:pnlAccordionDec_afrCl0",
        "Filtro acordeão OB",
    )
    if not abriu:
        # Fallback: disclosure alternativo
        await _clique_real(pg, "pt1:tblOrdemBancaria:sdtFilter::disAcr", "Filtro")
    await asyncio.sleep(3)
    await _fechar_popups(pg)

    # Preenche campo Favorecido/CNPJ
    preencheu = False
    for cnpj_val in [cnpj, CNPJ_FMT]:  # tenta sem e com formatação
        preencheu = await pg.evaluate(f"""(cnpj) => {{
            const campos = [...document.querySelectorAll(
                '[id*="tblOrdemBancaria"] input[type="text"], input[placeholder*="favorecido" i], input[placeholder*="cnpj" i]'
            )];
            const candidatos = campos.filter(el => {{
                const id  = (el.id || '').toLowerCase();
                const ph  = (el.placeholder || '').toLowerCase();
                const lbl = document.querySelector('label[for="'+el.id+'"]');
                const lt  = lbl ? lbl.textContent.toLowerCase() : '';
                return (id.includes('favorecido') || id.includes('cnpj') || id.includes('credor') ||
                        ph.includes('favorecido') || ph.includes('cnpj') || lt.includes('favorecido') ||
                        lt.includes('cnpj')) && el.getBoundingClientRect().width > 0;
            }});
            if (candidatos.length === 0) return false;
            const el = candidatos[0];
            el.focus();
            el.value = '';
            ['input','keydown'].forEach(e => el.dispatchEvent(new Event(e, {{bubbles:true}})));
            el.value = cnpj;
            ['input','change','blur'].forEach(e => el.dispatchEvent(new Event(e, {{bubbles:true}})));
            return el.id || 'ok';
        }}""", cnpj_val)
        if preencheu:
            print(f"    → Campo preenchido ({cnpj_val}): {preencheu}")
            break

    if not preencheu:
        print("    [WARN] Campo favorecido não encontrado — lendo tudo e filtrando em Python")
        return False

    # Dispara pesquisa com Enter
    await pg.keyboard.press("Enter")
    await asyncio.sleep(5)
    await _fechar_popups(pg)

    # Tenta clicar em botão "Pesquisar" também
    await pg.evaluate("""() => {
        for (const el of document.querySelectorAll('button,input[type="button"],a')) {
            const t = (el.textContent||el.value||'').trim().toLowerCase();
            if ((t==='pesquisar'||t==='filtrar'||t==='consultar') && el.getBoundingClientRect().width>0)
                { el.click(); return t; }
        }
    }""")
    await asyncio.sleep(5)
    await _fechar_popups(pg)
    return True


# ── PASSO 5: Leitura da tabela (todas as páginas) ─────────────────────────────

_JS_LER_TABELA = r"""
() => {
    const container = document.querySelector('[id*="tblOrdemBancaria"]')
                   || document.querySelector('[id*="tblOBOrcamentaria"]');
    if (!container) return {found: false, header: [], rows: []};

    const tbl = container.querySelector('table') || container.closest('table') || container;
    const header = [];
    const rows   = [];

    for (const tr of tbl.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('td,th')]
            .map(c => c.textContent.replace(/\s+/g,' ').trim());
        if (!cells.some(c => c.length > 0)) continue;

        if (!header.length && cells.some(c => /^N[úu]mero$/i.test(c))) {
            header.push(...cells); continue;
        }
        if (/^\d{4}(OB|ob)\d+/.test(cells[0])) rows.push(cells);
    }
    return {found: true, header, rows};
}
"""

_JS_PROX_PAG = r"""
() => {
    const sels = [
        '[id*="tblOrdemBancaria"][id*="next"]',
        '[id*="tblOrdemBancaria"][id*="Next"]',
        'a[title="Próxima Página"]','a[title="Next Page"]',
        'button[title*="Próx"]',
    ];
    for (const s of sels) {
        const el = document.querySelector(s);
        if (el && !el.disabled && el.getBoundingClientRect().width > 0)
            { el.click(); return 'ok:' + (el.id||el.title); }
    }
    for (const el of document.querySelectorAll('a,button')) {
        const t = el.textContent.trim(); const ti = (el.title||'').toLowerCase();
        const r = el.getBoundingClientRect();
        if (r.width>0 && !el.disabled && (t==='>'||t==='>>'||ti.includes('próx')||ti.includes('next')))
            { el.click(); return 'nav:'+t; }
    }
    return null;
}
"""


async def _ler_todas_paginas(pg) -> tuple[list, list]:
    header: list = []
    all_rows: list = []
    pagina = 1

    while True:
        res = await pg.evaluate(_JS_LER_TABELA)
        if not res.get("found"):
            print(f"    [WARN] Tabela OB não encontrada na pág {pagina}")
            break

        h    = res.get("header", [])
        rows = res.get("rows", [])
        if h and not header:
            header = h

        all_rows.extend(rows)
        print(f"    → Pág {pagina}: {len(rows)} linhas")

        if len(rows) < 5:  # última página (tipicamente < tamanho de página)
            break

        nxt = await pg.evaluate(_JS_PROX_PAG)
        if not nxt:
            break

        pagina += 1
        await asyncio.sleep(4)
        await _fechar_popups(pg)

    return header, all_rows


# ── Parse das linhas ──────────────────────────────────────────────────────────

def _parse_rows(header: list, rows: list, cnpj_filter=None) -> list[dict]:
    idx: dict[str, int] = {h.lower().strip(): i for i, h in enumerate(header)}

    def cell(row, *keys):
        for k in keys:
            i = idx.get(k)
            if i is not None and i < len(row):
                v = row[i].strip()
                if v and v != "\xa0": return v
        # fallback posicional (ordem confirmada pelo SIAFE-rotina-auditoria.md)
        pos = {"número":0,"numero":0,"ug emitente":1,"data emissão":3,"data emissao":3,
               "valor":14,"favorecido(cnpj)":7,"nome do favorecido":8,"processo":10,"status":4}
        for k in keys:
            p = pos.get(k.lower())
            if p is not None and p < len(row):
                v = row[p].strip()
                if v and v != "\xa0": return v
        return ""

    records = []
    for row in rows:
        num = cell(row,"número","numero")
        if not num or not re.match(r"\d{4}(OB|ob)\d+", num): continue

        fav_raw = cell(row,"favorecido(cnpj)","favorecido","cnpj")
        fav     = re.sub(r"\D","",fav_raw)[:14]
        if cnpj_filter and fav != cnpj_filter: continue

        data_s = cell(row,"data emissão","data emissao","data")
        dt     = _parse_date(data_s)
        valor  = _parse_money(cell(row,"valor","value"))

        records.append({
            "numero_ob":        num,
            "ug_emitente":      cell(row,"ug emitente","ug"),
            "ug_pagadora":      cell(row,"ug pagadora"),
            "data_emissao":     data_s,
            "ano":              dt.year  if dt else None,
            "mes":              dt.month if dt else None,
            "favorecido_cnpj":  fav,
            "favorecido_nome":  cell(row,"nome do favorecido","nome do credor","nome"),
            "valor":            valor,
            "processo":         cell(row,"processo","processo sei"),
            "status":           cell(row,"status"),
            "tipo_ob":          cell(row,"tipo de ob","tipo ob"),
        })

    return records


# ── Coleta de um exercício ────────────────────────────────────────────────────

async def _coletar_exercicio(browser, ano: int) -> list[dict]:
    """Cria nova aba, faz login no exercício dado, coleta OBs, fecha aba."""
    print(f"\n{'='*60}")
    print(f" Exercício {ano}")
    print(f"{'='*60}")

    ctx  = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = await ctx.new_page()

    try:
        # Login
        ok = await _login(page, ano)
        if not ok:
            print(f"  [ERRO] Login falhou para {ano}")
            return []

        # Navegar até OBs
        await _ir_obs(page)

        # Filtrar pelo CNPJ
        filtrou = await _filtrar_cnpj(page, CNPJ)

        # Ler tabela
        header, rows = await _ler_todas_paginas(page)
        print(f"  → Total lido: {len(rows)} linhas")

        # Parse
        cnpj_f   = None if filtrou else CNPJ
        records  = _parse_rows(header, rows, cnpj_filter=cnpj_f)
        total    = sum(r["valor"] for r in records)
        print(f"  → OBs MGS CLEAN: {len(records)} | {_brl(total)}")

        # Cache por ano
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = CACHE_DIR / f"mgsclean_obs_{ano}.json"
        out.write_text(
            json.dumps({"ano":ano,"cnpj":CNPJ,"header":header,"obs":records,
                        "total_linhas_lidas":len(rows)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  → Salvo: {out}")
        return records

    except Exception as exc:
        print(f"  [ERRO] Exercício {ano}: {exc}")
        import traceback; traceback.print_exc()
        return []
    finally:
        try: await page.close()
        except: pass


# ── Relatório Markdown ────────────────────────────────────────────────────────

def _gerar_relatorio(todas: list[dict], anos: list[int]) -> str:
    total_g = sum(ob["valor"] for ob in todas)
    coleta  = datetime.now().strftime("%Y-%m-%d %H:%M")

    L = [
        "# ORDENS BANCÁRIAS PAGAS — MGS CLEAN SOLUCOES E SERVICOS LTDA",
        "",
        f"- **CNPJ:** {CNPJ_FMT}",
        f"- **Fonte:** SIAFE2 — Execução > Execução Financeira > Ordens Bancárias",
        f"- **Coleta:** {coleta}",
        f"- **Anos cobertos:** {', '.join(str(a) for a in sorted(anos))}",
        f"- **Total geral pago:** {_brl(total_g)} ({len(todas)} OBs)",
        "",
        "> Múltiplas OBs por mês são normais: cada nota fiscal/competência gera uma OB separada.",
        "",
        "---",
        "",
    ]

    # Seção 1: Resumo por ano
    L += ["## 1. Resumo por Ano", "", "| Ano | OBs | Total Pago |","|-|-:|-:|"]
    for ano in sorted(anos):
        obs_a = [ob for ob in todas if ob.get("ano")==ano]
        v = sum(ob["valor"] for ob in obs_a)
        L.append(f"| {ano} | {len(obs_a)} | {_brl(v)} |")
    L += [f"| **TOTAL** | **{len(todas)}** | **{_brl(total_g)}** |","","---",""]

    # Seção 2: Matriz órgão × ano
    struct = defaultdict(lambda: defaultdict(list))
    for ob in todas:
        if ob.get("ano") and ob.get("ug_emitente"):
            struct[ob["ano"]][ob["ug_emitente"]].append(ob)

    todos_ugs = sorted(
        {ob.get("ug_emitente","") for ob in todas if ob.get("ug_emitente")},
        key=lambda u: -sum(ob["valor"] for ob in todas if ob.get("ug_emitente")==u),
    )
    todos_anos = sorted(anos)

    L += ["## 2. Matriz Órgão × Ano", ""]
    hdr = "| Órgão | UG |" + "".join(f" {a} |" for a in todos_anos) + " TOTAL |"
    sep = "|---|---|" + "---:|"*(len(todos_anos)+1)
    L += [hdr, sep]
    totcol = {a:0.0 for a in todos_anos}
    for ug in todos_ugs:
        nome = _ug_nome(ug)[:32]
        row  = f"| {nome} | {ug} |"
        tot  = 0.0
        for a in todos_anos:
            v = sum(ob["valor"] for ob in struct[a].get(ug,[]))
            totcol[a] += v; tot += v
            row += (f" {_brl(v)} |" if v else " — |")
        row += f" {_brl(tot)} |"
        L.append(row)
    tr = "| **TOTAL** | — |"
    tt = 0.0
    for a in todos_anos:
        tr += f" {_brl(totcol[a])} |"; tt += totcol[a]
    L += [tr + f" {_brl(tt)} |", "", "---", ""]

    # Seção 3: Por órgão → por mês → cada OB individual
    L += [
        "## 3. Detalhamento por Órgão — Cada OB por Mês",
        "",
        "> Cada linha = uma Ordem Bancária individual com seu número único.",
        "",
    ]
    for ano in todos_anos:
        L += [f"### === Exercício {ano} ===", ""]
        ugs_ano = sorted(struct[ano].keys(),
                         key=lambda u: -sum(ob["valor"] for ob in struct[ano][u]))
        for ug in ugs_ano:
            obs_ug = sorted(struct[ano][ug],
                            key=lambda o: (o.get("mes") or 0, o.get("data_emissao") or ""))
            nome    = _ug_nome(ug)
            total_u = sum(ob["valor"] for ob in obs_ug)
            L += [
                f"#### {nome} (UG {ug}) — {_brl(total_u)} — {len(obs_ug)} OBs",
                "",
                "| Mês | Nº OB | Data | Valor (R$) | Processo SEI | Status |",
                "|---|---|---|---:|---|---|",
            ]
            por_mes: dict[int,list] = defaultdict(list)
            for ob in obs_ug:
                if ob.get("mes"): por_mes[ob["mes"]].append(ob)

            for mes in sorted(por_mes.keys()):
                obs_m   = sorted(por_mes[mes], key=lambda o: o.get("data_emissao") or "")
                sub     = sum(ob["valor"] for ob in obs_m)
                mes_abr = f"{MESES_PT[mes][:3]}/{ano}"
                for i, ob in enumerate(obs_m):
                    ml = mes_abr if i==0 else ""
                    p  = (ob.get("processo") or "")[:30]
                    st = (ob.get("status")   or "")[:12]
                    v  = f"{ob['valor']:,.2f}".replace(",","X").replace(".","," ).replace("X",".")
                    L.append(f"| {ml} | {ob['numero_ob']} | {ob['data_emissao']} | {v} | {p} | {st} |")
                sv = f"{sub:,.2f}".replace(",","X").replace(".","," ).replace("X",".")
                L.append(f"| **{mes_abr} sub** | | | **{sv}** | {len(obs_m)} OBs | |")

            tv = f"{total_u:,.2f}".replace(",","X").replace(".","," ).replace("X",".")
            L += [f"| **TOTAL {ano}** | | | **{tv}** | {len(obs_ug)} OBs | |",""]
        L += ["---",""]

    # Seção 4: Resumo mensal geral
    L += ["## 4. Resumo Mensal — Todos os Órgãos",""]
    for ano in todos_anos:
        obs_a = [ob for ob in todas if ob.get("ano")==ano]
        total_a = sum(ob["valor"] for ob in obs_a)
        L += [f"### Ano {ano}", "", "| Mês | OBs | Total Pago | % do ano |", "|-|-:|-:|-:|"]
        por_mes: dict[int,list] = defaultdict(list)
        for ob in obs_a:
            if ob.get("mes"): por_mes[ob["mes"]].append(ob)
        for mes in sorted(por_mes.keys()):
            obs_m = por_mes[mes]
            v     = sum(ob["valor"] for ob in obs_m)
            pct   = v/total_a*100 if total_a else 0
            vf    = f"{v:,.2f}".replace(",","X").replace(".","," ).replace("X",".")
            L.append(f"| {MESES_PT[mes]}/{ano} | {len(obs_m)} | {vf} | {pct:.1f}% |")
        taf = f"{total_a:,.2f}".replace(",","X").replace(".","," ).replace("X",".")
        L += [f"| **TOTAL** | **{len(obs_a)}** | **{taf}** | 100% |","",""]

    return "\n".join(L)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    from playwright.async_api import async_playwright

    # Anos a coletar (args opcionais)
    anos = sorted(
        [int(a) for a in sys.argv[1:] if a.isdigit() and int(a) in EXERCICIOS]
        or list(EXERCICIOS.keys()),
        reverse=True,  # mais recente primeiro
    )
    print(f"\n{'='*60}")
    print(f"  MGS CLEAN — Coleta de Ordens Bancárias SIAFE")
    print(f"  CNPJ: {CNPJ_FMT}")
    print(f"  Anos: {anos}")
    print(f"{'='*60}")

    p = await async_playwright().start()

    # Tenta CDP primeiro (Chrome já aberto); senão lança browser próprio
    browser = None
    try:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=5000)
        print("✔ Chrome conectado via CDP (porta 9222)")
    except Exception:
        print("ℹ Chrome CDP não disponível — lançando Chromium via Playwright …")
        browser = await p.chromium.launch(
            headless=False,       # visível para debug (troque para True em produção)
            slow_mo=200,          # ritmo humano — evita bloqueio ADF
            args=["--start-maximized"],
        )
        print("✔ Chromium lançado")

    todas_obs: list[dict] = []

    try:
        for ano in anos:
            obs_ano = await _coletar_exercicio(browser, ano)
            todas_obs.extend(obs_ano)
            if ano != anos[-1]:
                await asyncio.sleep(3)  # pausa entre anos

        if not todas_obs:
            print("\n[AVISO] Nenhuma OB coletada.")
            return

        # Persiste consolidado
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f_json = CACHE_DIR / "mgsclean_obs_todas.json"
        f_json.write_text(
            json.dumps({"obs": todas_obs, "coleta": datetime.now().isoformat()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n✔ Consolidado: {f_json} ({len(todas_obs)} OBs)")

        # Relatório Markdown
        md = _gerar_relatorio(todas_obs, anos)
        f_md = CACHE_DIR / "mgsclean_obs_resumo.md"
        f_md.write_text(md, encoding="utf-8")
        print(f"✔ Relatório MD: {f_md}")

        total = sum(ob["valor"] for ob in todas_obs)
        print(f"\n{'='*60}")
        print(f"  TOTAL GERAL PAGO: {_brl(total)}")
        print(f"  OBs coletadas:    {len(todas_obs)}")
        print(f"  Anos:             {', '.join(str(a) for a in sorted(anos))}")
        print(f"{'='*60}")
        print("\nPróximo passo:")
        print("  python _SANDBOX/gerar_relatorio_obs_pdf.py")

    finally:
        try: await browser.close()
        except: pass
        await p.stop()


if __name__ == "__main__":
    asyncio.run(main())
