#!/usr/bin/env python3
"""
MGS CLEAN — Coleta de Ordens Bancárias Pagas no SIAFE2, por ano e por órgão.

Para cada exercício (2021–2026):
  → Faz login no SIAFE com o valor de exercício correto
  → Navega: Execução → Execução Financeira → Ordens Bancárias
  → Abre o filtro e pesquisa pelo CNPJ favorecido 19.088.605/0001-04
  → Lê TODAS as páginas da tabela
  → Salva em data/sei_cache/mgsclean_obs_{ano}.json

Saída final:
  data/sei_cache/mgsclean_obs_resumo.md   — tabela consolidada ano × órgão
  data/sei_cache/mgsclean_obs_todas.json  — todas as OBs

Pré-requisito:
  Chrome rodando: chrome --remote-debugging-port=9222 --user-data-dir=<dir>
  SIAFE_USER e SIAFE_PASS no .env (ou ~/.hermes/.env)

Uso:
  cd /home/user/JFN
  python _SANDBOX/auditar_mgs_obs_siafe.py           # todos os anos
  python _SANDBOX/auditar_mgs_obs_siafe.py 2025 2026  # anos específicos
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

# ── Carregar .env ────────────────────────────────────────────────────────────
for _env in [Path.home() / ".hermes" / ".env", Path(__file__).parents[1] / ".env"]:
    if _env.exists():
        for _ln in _env.read_text(encoding="utf-8", errors="replace").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                k, v = _ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ── Constantes ───────────────────────────────────────────────────────────────
CNPJ_MGS    = "19088605000104"
CNPJ_FMT    = "19.088.605/0001-04"
CDP_URL     = "http://127.0.0.1:9222"
LOGIN_URL   = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/autenticacao/autenticacao.xhtml"
SIAFE_HOME  = "https://siafe2.fazenda.rj.gov.br/Siafe/"
CACHE_DIR   = Path(__file__).parents[1] / "data" / "sei_cache"

# Mapa ano → valor do SELECT exercício na tela de login do SIAFE
# (confirmado: 2026=1, 2025=2, 2024=3, 2023=4; provavelmente 2022=5, 2021=6)
EXERCICIO_MAP = {2026: "1", 2025: "2", 2024: "3", 2023: "4", 2022: "5", 2021: "6"}

# ── Utilitários ──────────────────────────────────────────────────────────────

def _parse_money(s: str) -> float:
    try:
        return float(re.sub(r"[^\d,]", "", str(s)).replace(",", ".") or "0")
    except Exception:
        return 0.0


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            pass
    return None


def _fmt_r(v: float) -> str:
    return f"R$ {v:>15,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ── Playwright helpers ───────────────────────────────────────────────────────

async def _wait(pg, ms: int = 3000):
    try:
        await pg.wait_for_load_state("domcontentloaded", timeout=ms)
    except Exception:
        pass
    await asyncio.sleep(max(1.5, ms / 2000))


async def _dismiss(pg, iters: int = 6):
    for _ in range(iters):
        r = await pg.evaluate("""() => {
            for (const el of document.querySelectorAll('#myBtnOk, a.x7j, a.xg2, button')) {
                const t = el.textContent.trim().toLowerCase();
                const r = el.getBoundingClientRect();
                if ((t==='ok'||t==='sim'||t==='fechar') && r.width>0 && r.height>0) {
                    el.click(); return t;
                }
            }
            return null;
        }""")
        if r:
            await asyncio.sleep(1.5)
        else:
            break


# ── Login ────────────────────────────────────────────────────────────────────

async def _login(pg, ano: int) -> bool:
    usuario = os.environ.get("SIAFE_USER") or os.environ.get("SIAFE_USUARIO", "")
    senha   = os.environ.get("SIAFE_PASS") or os.environ.get("SIAFE_SENHA", "")
    if not usuario or not senha:
        print("  [ERRO] Credenciais ausentes: defina SIAFE_USER e SIAFE_PASS no .env")
        return False

    exercicio_val = EXERCICIO_MAP.get(ano, "1")
    print(f"  → Login exercício {ano} (SELECT value={exercicio_val})…")

    await pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    await _dismiss(pg)

    # Preenche usuário e senha via JS (funciona com os inputs ADF da tela de login)
    await pg.evaluate("""(u, s) => {
        const set = (id, v) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.value = v;
            ['input','change','blur'].forEach(ev =>
                el.dispatchEvent(new Event(ev, {bubbles: true})));
        };
        set('loginBox:itxUsuario::content', u);
        set('loginBox:itxSenhaAtual::content', s);
    }""", usuario, senha)
    await asyncio.sleep(1)

    # Seleciona cliente (RJ=0) e exercício
    for sel_id, val in [("cbxCliente", "0"), ("cbxExercicio", exercicio_val)]:
        try:
            loc = pg.locator(f'[id*="{sel_id}"]').first
            await loc.select_option(val)
            await asyncio.sleep(1)
        except Exception as exc:
            print(f"  [WARN] select {sel_id}: {exc}")

    # Clica em OK
    await pg.evaluate("""() => {
        const btn = document.getElementById('loginBox:btnConfirmar')
            || document.querySelector('[id*="btnConfirmar"]')
            || document.querySelector('input[type="submit"], button[type="submit"]');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(7)
    await _dismiss(pg)

    ok = "login" not in pg.url.lower() and "autenticacao" not in pg.url.lower()
    print(f"  → Login {'OK ✔' if ok else 'FALHOU ✖'} — {pg.url[:80]}")
    return ok


# ── Navegação para Ordens Bancárias ─────────────────────────────────────────

async def _ir_obs(pg) -> bool:
    """Navega até Execução > Execução Financeira > Ordens Bancárias."""
    if "ordembancaria" in pg.url.lower():
        return True

    # IDs confirmados pela rotina de auditoria (SIAFE-rotina-auditoria.md)
    menu_steps = [
        ("Execução",           "pt1:pt_np4:1:pt_cni6::disclosureAnchor"),
        ("Execução Financeira","pt1:pt_np3:1:pt_cni4::disclosureAnchor"),
        ("Ordens Bancárias",   "pt1:pt_np2:8:pt_cni3"),
    ]

    for label, element_id in menu_steps:
        print(f"    → Menu: {label}")
        for attempt in range(4):
            r = await pg.evaluate(f"""() => {{
                const el = document.getElementById('{element_id}');
                if (el) {{
                    const r = el.getBoundingClientRect();
                    if (r.width > 0) {{ el.click(); return 'id-click'; }}
                }}
                // Fallback: busca por texto
                for (const a of document.querySelectorAll('a, span, td')) {{
                    const t = a.textContent.trim();
                    if (t === '{label}' || t.startsWith('{label[:8]}')) {{
                        const r = a.getBoundingClientRect();
                        if (r.width > 0) {{ a.click(); return 'text-click'; }}
                    }}
                }}
                return null;
            }}""")
            if r:
                await asyncio.sleep(4)
                await _dismiss(pg)
                break
            await asyncio.sleep(3)
        else:
            print(f"    [WARN] Não clicou em '{label}' após 4 tentativas")

    await asyncio.sleep(3)
    ok = "ordembancaria" in pg.url.lower()
    print(f"    → Tela OB: {'OK ✔' if ok else 'FALHOU ✖'} ({pg.url[:80]})")
    return ok


# ── Filtrar por CNPJ ─────────────────────────────────────────────────────────

async def _filtrar_cnpj(pg, cnpj: str) -> bool:
    """
    Abre o painel de filtro da grade tblOrdemBancaria e pesquisa pelo CNPJ.
    Retorna True se o filtro foi aplicado com sucesso.
    """
    print(f"    → Aplicando filtro CNPJ {cnpj}…")

    # 1. Abre o acordeão de filtro
    r = await pg.evaluate("""() => {
        const ids = [
            'pt1:tblOrdemBancaria:pnlAccordionDec_afrCl0',
            'pt1:tblOrdemBancaria:sdtFilter::disAcr',
        ];
        for (const id of ids) {
            const el = document.getElementById(id);
            if (el && el.getBoundingClientRect().width > 0) {
                el.click(); return 'accordion: ' + id;
            }
        }
        // Fallback: qualquer botão com texto "Filtro" visível
        for (const el of document.querySelectorAll('a, span, button')) {
            const t = el.textContent.trim();
            if (t === 'Filtro' || t === 'Pesquisar' || t === 'Filtrar') {
                const r = el.getBoundingClientRect();
                if (r.width > 0) { el.click(); return 'filtro-text'; }
            }
        }
        return null;
    }""")
    if r:
        await asyncio.sleep(3)
        await _dismiss(pg)
    else:
        print("    [WARN] Acordeão de filtro não encontrado")

    # 2. Digita o CNPJ no campo de favorecido/CNPJ
    # A rotina confirma: "campo Favorecido/CNPJ do filtro, digitar o CNPJ"
    typed = await pg.evaluate(f"""(cnpj) => {{
        // Tenta campos cujo label/placeholder/id sugira favorecido ou CNPJ
        const candidates = [
            ...document.querySelectorAll('input[type="text"], input[type="number"]')
        ].filter(el => {{
            const id = (el.id || '').toLowerCase();
            const ph = (el.placeholder || '').toLowerCase();
            const lbl = document.querySelector('label[for="' + el.id + '"]');
            const lblText = lbl ? lbl.textContent.toLowerCase() : '';
            return (id.includes('favorecido') || id.includes('credor') || id.includes('cnpj') ||
                    ph.includes('favorecido') || ph.includes('cnpj') ||
                    lblText.includes('favorecido') || lblText.includes('cnpj')) &&
                   el.getBoundingClientRect().width > 0;
        }});
        if (candidates.length > 0) {{
            const el = candidates[0];
            el.focus();
            el.value = cnpj;
            ['input','change','blur'].forEach(ev => el.dispatchEvent(new Event(ev, {{bubbles: true}})));
            return 'typed-in: ' + (el.id || el.placeholder || 'input');
        }}
        // Fallback: primeiro campo de texto visível no painel de filtro
        const panel = document.querySelector('[id*="tblOrdemBancaria"][id*="filter"], [id*="tblOrdemBancaria"][id*="Filter"], [id*="pnlAccordion"]');
        if (panel) {{
            const inp = panel.querySelector('input[type="text"]');
            if (inp && inp.getBoundingClientRect().width > 0) {{
                inp.focus(); inp.value = cnpj;
                ['input','change','blur'].forEach(ev => inp.dispatchEvent(new Event(ev, {{bubbles: true}})));
                return 'typed-fallback';
            }}
        }}
        return null;
    }}""", cnpj)

    if typed:
        print(f"    → Campo preenchido: {typed}")
        # Dispara a pesquisa: tenta teclado ou botão
        await pg.keyboard.press("Enter")
        await asyncio.sleep(5)
        await _dismiss(pg)
        # Tenta também clicar em "Pesquisar"/"Filtrar" se Enter não funcionou
        await pg.evaluate("""() => {
            for (const el of document.querySelectorAll('button, input[type="button"], a')) {
                const t = el.textContent.trim().toLowerCase();
                if ((t === 'pesquisar' || t === 'filtrar' || t === 'consultar') &&
                    el.getBoundingClientRect().width > 0) {
                    el.click(); return t;
                }
            }
        }""")
        await asyncio.sleep(5)
        await _dismiss(pg)
        return True
    else:
        print("    [WARN] Campo de favorecido/CNPJ não encontrado — lendo tudo e filtrando em Python")
        return False


# ── Leitura da tabela ────────────────────────────────────────────────────────

_JS_READ_TABLE = r"""
() => {
    // Localiza tabela de OBs (tblOrdemBancaria ou tblOBOrcamentaria)
    let container = document.querySelector('[id*="tblOrdemBancaria"]')
                 || document.querySelector('[id*="tblOBOrcamentaria"]');
    if (!container) return {found: false, header: [], rows: []};

    const tbl = container.querySelector('table') || container.closest('table') || container;
    let header = [];
    const rows = [];

    for (const tr of tbl.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('td,th')]
            .map(c => c.textContent.replace(/\s+/g,' ').trim());
        if (!cells.some(c => c.length > 0)) continue;

        // Cabeçalho
        if (!header.length && cells.some(c => c === 'Número' || c === 'Numero')) {
            header = cells;
            continue;
        }
        // Linha de dado: começa com padrão ANO+OB ou é linha de dado válida
        if (/^\d{4}(OB|ob)\d+/.test(cells[0])) {
            rows.push(cells);
        }
    }
    return {found: true, header, rows};
}
"""

_JS_NEXT_PAGE = r"""
() => {
    // Botão "próxima página" no paginador ADF
    const sels = [
        '[id*="tblOrdemBancaria"][id*="next"]',
        '[id*="tblOrdemBancaria"][id*="Next"]',
        'a[title="Próxima Página"]',
        'a[title="Next Page"]',
        'button[title*="Próx"]',
    ];
    for (const s of sels) {
        const el = document.querySelector(s);
        if (el && !el.disabled && el.getBoundingClientRect().width > 0) {
            el.click(); return 'next: ' + (el.id || el.title);
        }
    }
    // Botões de seta/texto genéricos no paginador
    for (const el of document.querySelectorAll('a,button')) {
        const t = el.textContent.trim();
        const ti = (el.title || '').toLowerCase();
        const r = el.getBoundingClientRect();
        if (r.width > 0 && !el.disabled && (t === '>' || t === '>>'
                || ti.includes('próx') || ti.includes('next'))) {
            el.click(); return 'nav: ' + t;
        }
    }
    return null;
}
"""


async def _ler_todas_paginas(pg) -> tuple[list, list]:
    """Lê todas as páginas da tabela de OBs. Retorna (header, rows)."""
    header: list = []
    all_rows: list = []
    pagina = 1

    while True:
        result = await pg.evaluate(_JS_READ_TABLE)
        if not result.get("found"):
            print(f"    [WARN] Tabela não encontrada na pág {pagina}")
            break

        h = result.get("header", [])
        rows = result.get("rows", [])
        if h and not header:
            header = h
        all_rows.extend(rows)
        print(f"    → Pág {pagina}: {len(rows)} linhas")

        if len(rows) < 10:  # última página (tipicamente < tamanho da página)
            break

        nxt = await pg.evaluate(_JS_NEXT_PAGE)
        if not nxt:
            break

        pagina += 1
        await asyncio.sleep(4)
        await _dismiss(pg)

    return header, all_rows


# ── Parsing das linhas ───────────────────────────────────────────────────────

def _parse_rows(header: list, rows: list, cnpj_filter: str | None = None) -> list[dict]:
    """
    Converte linhas da tabela em dicts.
    Filtra opcionalmente por CNPJ do favorecido.

    Colunas confirmadas pela rotina de auditoria:
      Número | UG Emitente | UG Pagadora | Data Emissão | Status | Tipo | Tipo de OB |
      Favorecido(CNPJ) | Nome do Favorecido | GD | Processo | RE | PD |
      Status de Envio | Valor | Assinatura Digital
    """
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        idx[h.lower().strip()] = i

    def cell(row, *keys):
        for k in keys:
            i = idx.get(k)
            if i is not None and i < len(row):
                v = row[i].strip()
                if v and v != "\xa0":
                    return v
        # fallback: positional guesses for known columns
        pos = {"numero": 0, "ug emitente": 1, "data emissão": 3, "data emissao": 3,
               "valor": 14, "favorecido": 7, "nome do favorecido": 8, "processo": 10}
        for k in keys:
            p = pos.get(k)
            if p is not None and p < len(row):
                v = row[p].strip()
                if v and v != "\xa0":
                    return v
        return ""

    records = []
    for row in rows:
        numero = cell(row, "número", "numero")
        if not numero or not re.match(r"\d{4}[Oo][Bb]\d+", numero):
            continue

        fav_cnpj_raw = cell(row, "favorecido(cnpj)", "favorecido", "credor", "cnpj")
        fav_cnpj = re.sub(r"\D", "", fav_cnpj_raw)[:14]

        if cnpj_filter and fav_cnpj != cnpj_filter:
            continue

        data_str = cell(row, "data emissão", "data emissao", "data")
        dt = _parse_date(data_str)
        valor_str = cell(row, "valor", "value")
        valor = _parse_money(valor_str)

        records.append({
            "numero_ob":       numero,
            "ug_emitente":     cell(row, "ug emitente", "ug"),
            "data_emissao":    data_str,
            "ano":             dt.year if dt else None,
            "mes":             dt.month if dt else None,
            "favorecido_cnpj": fav_cnpj,
            "favorecido_nome": cell(row, "nome do favorecido", "nome do credor"),
            "valor":           valor,
            "processo":        cell(row, "processo", "processo sei"),
            "status":          cell(row, "status"),
        })

    return records


# ── Resolução de nomes de UG ─────────────────────────────────────────────────

_UG_NOMES = {
    # Mapeamento parcial de códigos de UG para nomes de órgão (RJ)
    # Será ampliado conforme os dados coletados
    "300100": "Secretaria de Estado da Fazenda",
    "270001": "SEPM — Polícia Militar",
    "270003": "FUNESBOM — Corpo de Bombeiros",
    "270005": "Tribunal de Justiça (Fundo Especial)",
    "270006": "TCE — Tribunal de Contas do Estado",
    "270009": "PGE — Procuradoria Geral do Estado",
    "270015": "SECEC — Secretaria de Cultura",
    "270016": "FUNESBOM",
    "270020": "RIOPREVIDÊNCIA",
    "270024": "INEA",
    "270029": "Fundo Estadual de Saúde",
    "270042": "ITERJ",
    "270051": "SEPM — Polícia Militar",
    "270060": "Casa Civil",
}

def _ug_nome(codigo: str) -> str:
    return _UG_NOMES.get(codigo, codigo)


# ── Relatório final ──────────────────────────────────────────────────────────

def _gerar_relatorio(todas_obs: list[dict], anos: list[int]) -> str:
    """Gera o relatório consolidado em Markdown."""
    lines = [
        "# OBs PAGAS — MGS CLEAN SOLUCOES E SERVICOS LTDA",
        f"**CNPJ:** {CNPJ_FMT}",
        f"**Fonte:** SIAFE2 — Execução > Execução Financeira > Ordens Bancárias",
        f"**Coleta:** {datetime.now():%Y-%m-%d %H:%M}",
        f"**Anos:** {', '.join(str(a) for a in sorted(anos))}",
        "",
    ]

    total_geral = sum(ob["valor"] for ob in todas_obs)
    lines += [
        f"**Total geral de OBs pagas:** {_fmt_r(total_geral)} ({len(todas_obs)} OBs)",
        "",
        "---",
        "",
    ]

    # ── Por ano ──
    por_ano: dict[int, list] = defaultdict(list)
    for ob in todas_obs:
        if ob["ano"]:
            por_ano[ob["ano"]].append(ob)

    for ano in sorted(por_ano.keys()):
        obs_ano = por_ano[ano]
        total_ano = sum(ob["valor"] for ob in obs_ano)
        lines += [
            f"## Ano {ano} — {_fmt_r(total_ano)} ({len(obs_ano)} OBs)",
            "",
        ]

        # ── Por mês ──
        por_mes: dict[int, list] = defaultdict(list)
        for ob in obs_ano:
            if ob["mes"]:
                por_mes[ob["mes"]].append(ob)

        lines.append("### Por mês")
        lines.append("| Mês | OBs | Valor (R$) |")
        lines.append("|---|---:|---:|")
        for mes in sorted(por_mes.keys()):
            obs_mes = por_mes[mes]
            lines.append(f"| {mes:02d}/{ano} | {len(obs_mes)} | {sum(ob['valor'] for ob in obs_mes):>15,.2f} |".replace(",", "X").replace(".", ",").replace("X", "."))
        lines.append(f"| **TOTAL** | **{len(obs_ano)}** | **{total_ano:>15,.2f}** |".replace(",", "X").replace(".", ",").replace("X", "."))
        lines.append("")

        # ── Por órgão (UG Emitente) ──
        por_ug: dict[str, list] = defaultdict(list)
        for ob in obs_ano:
            ug = ob.get("ug_emitente") or "—"
            por_ug[ug].append(ob)

        lines.append("### Por órgão (UG Emitente)")
        lines.append("| Órgão | UG Code | OBs | Valor (R$) |")
        lines.append("|---|---|---:|---:|")
        for ug, obs_ug in sorted(por_ug.items(), key=lambda x: -sum(o["valor"] for o in x[1])):
            tv = sum(ob["valor"] for ob in obs_ug)
            nome = _ug_nome(ug)
            lines.append(f"| {nome} | {ug} | {len(obs_ug)} | {tv:>15,.2f} |".replace(",", "X").replace(".", ",").replace("X", "."))
        lines.append("")

        # ── Detalhamento (primeiras 30 OBs) ──
        lines.append("### Detalhamento das OBs")
        lines.append("| Número OB | Data | UG | Valor (R$) | Processo SEI | Status |")
        lines.append("|---|---|---|---:|---|---|")
        for ob in sorted(obs_ano, key=lambda o: (o.get("data_emissao") or "")):
            lines.append(
                f"| {ob['numero_ob']} | {ob['data_emissao']} | {ob.get('ug_emitente','—')} "
                f"| {ob['valor']:>15,.2f} | {ob.get('processo','—')} | {ob.get('status','—')} |"
                .replace(",", "X").replace(".", ",").replace("X", ".")
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Resumo consolidado (matriz ano × órgão) ──
    lines.append("## Resumo consolidado — Valor PAGO por ano e por órgão")
    lines.append("")

    todos_ugs = sorted({ob.get("ug_emitente", "—") for ob in todas_obs})
    todos_anos_ord = sorted(por_ano.keys())

    # Cabeçalho da tabela
    header_row = "| Órgão |" + "".join(f" {a} |" for a in todos_anos_ord) + " TOTAL |"
    sep_row    = "|---|" + "---:|" * (len(todos_anos_ord) + 1)
    lines.append(header_row)
    lines.append(sep_row)

    totais_ano = {a: 0.0 for a in todos_anos_ord}
    for ug in todos_ugs:
        nome = _ug_nome(ug)
        row = f"| {nome} |"
        tot_ug = 0.0
        for a in todos_anos_ord:
            v = sum(ob["valor"] for ob in por_ano.get(a, []) if ob.get("ug_emitente") == ug)
            tot_ug += v
            totais_ano[a] = totais_ano.get(a, 0.0) + v
            row += f" {v:,.2f} |".replace(",", "X").replace(".", ",").replace("X", ".") if v else " — |"
        row += f" {tot_ug:,.2f} |".replace(",", "X").replace(".", ",").replace("X", ".")
        lines.append(row)

    # Linha de totais por ano
    tot_row = "| **TOTAL** |"
    tot_geral = 0.0
    for a in todos_anos_ord:
        v = totais_ano.get(a, 0.0)
        tot_geral += v
        tot_row += f" **{v:,.2f}** |".replace(",", "X").replace(".", ",").replace("X", ".")
    tot_row += f" **{tot_geral:,.2f}** |".replace(",", "X").replace(".", ",").replace("X", ".")
    lines.append(tot_row)
    lines.append("")

    return "\n".join(lines)


# ── Fluxo principal ──────────────────────────────────────────────────────────

async def coletar_ano(pg, ano: int) -> list[dict]:
    """Coleta OBs de um ano: login, navegação, filtro, leitura, parse."""
    print(f"\n{'='*60}")
    print(f" Coletando OBs do ano {ano}")
    print(f"{'='*60}")

    # Login com o exercício correto
    if not await _login(pg, ano):
        print(f"  [ERRO] Login falhou para ano {ano}. Pulando.")
        return []

    # Navega até Ordens Bancárias
    if not await _ir_obs(pg):
        print(f"  [WARN] Não chegou na tela de OBs para ano {ano}")
        # Tenta continuar mesmo assim — a tabela pode estar acessível

    # Aplica filtro por CNPJ
    filtrado = await _filtrar_cnpj(pg, CNPJ_MGS)
    if not filtrado:
        print("  [INFO] Filtro não aplicado — lendo tudo e filtrando em Python")

    # Lê todas as páginas
    header, rows = await _ler_todas_paginas(pg)
    print(f"  → Total lido: {len(rows)} linhas (header: {len(header)} colunas)")

    # Parse e filtra pelo CNPJ se o filtro UI não foi aplicado
    cnpj_f = None if filtrado else CNPJ_MGS
    records = _parse_rows(header, rows, cnpj_filter=cnpj_f)
    print(f"  → OBs MGS CLEAN: {len(records)} | Total: {_fmt_r(sum(r['valor'] for r in records))}")

    # Persiste cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"mgsclean_obs_{ano}.json"
    out.write_text(json.dumps({
        "ano": ano, "cnpj": CNPJ_MGS, "header": header,
        "obs": records, "total_linhas_lidas": len(rows),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → Salvo: {out}")

    return records


async def main(anos: list[int] | None = None):
    from playwright.async_api import async_playwright

    if anos is None:
        anos = list(EXERCICIO_MAP.keys())
    anos = sorted(anos, reverse=True)  # mais recente primeiro

    print(f"\nMGS CLEAN OB Auditor — anos: {anos}")
    print(f"CNPJ: {CNPJ_FMT}")
    print(f"CDP: {CDP_URL}")
    print()

    p = await async_playwright().start()

    # Tenta conectar ao Chrome existente
    browser = None
    try:
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=30000)
        print("✔ Chrome conectado via CDP")
    except Exception as exc:
        print(f"✖ Chrome não encontrado em {CDP_URL}: {exc}")
        print("  Inicie o Chrome com:")
        print('  chrome --remote-debugging-port=9222 --user-data-dir="C:/JFN/profile"')
        await p.stop()
        return

    # Pega ou abre uma aba para uso
    page = None
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "siafe2.fazenda" in pg.url.lower():
                page = pg
                break
        if page:
            break
    if not page:
        # Abre nova aba
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
    print(f"  Aba: {page.url[:80]}\n")

    todas_obs: list[dict] = []

    try:
        for ano in anos:
            obs = await coletar_ano(page, ano)
            todas_obs.extend(obs)

    except Exception as exc:
        print(f"\n[ERRO FATAL] {exc}")
        import traceback; traceback.print_exc()
    finally:
        await p.stop()

    if not todas_obs:
        print("\n[WARN] Nenhuma OB coletada.")
        return

    # Salva JSON consolidado
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    json_path = CACHE_DIR / "mgsclean_obs_todas.json"
    json_path.write_text(json.dumps(todas_obs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✔ JSON consolidado: {json_path}")

    # Gera e salva relatório Markdown
    md = _gerar_relatorio(todas_obs, anos)
    md_path = CACHE_DIR / "mgsclean_obs_resumo.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"✔ Relatório Markdown: {md_path}")

    # Imprime resumo no terminal
    print("\n" + "="*70)
    print(md)


if __name__ == "__main__":
    _anos = [int(a) for a in sys.argv[1:] if a.isdigit()] or None
    asyncio.run(main(_anos))
