# -*- coding: utf-8 -*-
"""siafe_ne — coletor da NOTA DE EMPENHO do SIAFE-Rio 2 (Execução › Execução Orçamentária › Nota de Empenho).

POR QUE EXISTE (04/11/2026). O JFN só coletava a OB. A NE traz o que a OB não tem: **Fonte** (a ordem
cronológica do Decreto RJ 49.134/2024 art. 9º é "por fonte de recursos"), **Natureza** (elemento de despesa),
**Processo** e o **tipo de reconhecimento de passivo**. Com ela: empenho a posteriori (Lei 4.320 art. 60 —
"É vedada a realização de despesa sem prévio empenho"), DEA/RP e a fonte de cada pagamento.

Grade mapeada por `tools/siafe_mapear.py --detalhar`: tabela `pt1:tblDocumento:tabViewerDec` (`::db`,
`::scroller`, `::ch`), `chkRemoveLimit`, teto de 1.000 registros — a MESMA estrutura da OB Orçamentária.
Não reaproveita o coletor da OB por herança: ele tem o nome da tabela fixo em ~12 pontos e é o canônico
(1,3 mi de linhas); generalizá-lo arriscava o que funciona. Reaproveita as primitivas (`_typeahead`,
`_click_real`, `_login`, `_encerrar`).

A TELA LISTA OS RESTOS A PAGAR. Consultada no exercício 2025, ela traz as NEs de 2025 E as anteriores com
saldo (medido no ITERJ: NE de 2002 ainda viva). `exercicio` = ano da consulta; `ano_ne` = ano do número.

Colunas casadas pelo NOME DO CABEÇALHO, nunca por posição (o SIAFE 1 deslocou R$ 3,41 bi por posição).
Coleta que para perto de 1.000 linhas devolve `capou: true` — não é completa e não finge que é.

Uso:
    PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_ne --ug 133100 --exercicio 2025
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
TBL = "pt1:tblDocumento"
NE_RE = re.compile(r"\b20\d\dNE\d{5}P?\b")
_TETO = 1000
_PLATO = 975            # mesmo critério do coletor da OB: contagem que encosta no teto é suspeita

_DDL = """CREATE TABLE IF NOT EXISTS ne_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, ano_ne INTEGER,
    data_emissao TEXT, doc_alt TEXT, tipo_alt TEXT, status TEXT, credor TEXT, nome_credor TEXT,
    fonte TEXT, natureza TEXT, precatorio TEXT, processo TEXT, tipo_reconhecimento_passivo TEXT,
    assinatura_eletronica TEXT, valor REAL, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))"""
_IDX = ("CREATE INDEX IF NOT EXISTS ix_ne_credor ON ne_siafe(credor)",
        "CREATE INDEX IF NOT EXISTS ix_ne_processo ON ne_siafe(processo)")

_LABEL2COL = {
    "numero": "numero", "ug emitente": "ug_emitente", "data emissao": "data_emissao", "doc. alt.": "doc_alt",
    "tipo alt.": "tipo_alt", "status": "status", "credor": "credor", "nome do credor": "nome_credor",
    "fonte": "fonte", "natureza": "natureza", "precatorio": "precatorio", "processo": "processo",
    "tipo de reconhecimento de passivo": "tipo_reconhecimento_passivo",
    "assinatura eletronica": "assinatura_eletronica", "valor": "valor",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def _money(s: str) -> float | None:
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def ingerir(exercicio: int, header: list[str], linhas: list[list[str]], db=None) -> dict:
    """Grava as linhas colhidas. Coluna pelo nome do cabeçalho; linha sem número de NE é descartada."""
    idx = {}
    for i, h in enumerate(header):
        col = _LABEL2COL.get(_norm(h))
        if col and col not in idx:
            idx[col] = i
    if "numero" not in idx or "ug_emitente" not in idx:
        return {"ok": False, "erro": "cabecalho_sem_numero_ou_ug", "header": header}
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        con.execute(_DDL)
        for q in _IDX:
            con.execute(q)
        agora, n = time.strftime("%F %T"), 0
        for r in linhas:
            rec = {c: (r[i] if i < len(r) else "") for c, i in idx.items()}
            if not NE_RE.fullmatch(rec.get("numero", "").strip()):
                continue
            rec["valor"] = _money(rec.get("valor", ""))
            # `exercicio` é o ano da CONSULTA; a tela lista também os RP com saldo (no ITERJ/2025 havia NE de
            # 2002). O ano da própria NE está no número — guardado à parte para não confundir os dois.
            rec.update(exercicio=int(exercicio), ano_ne=int(rec["numero"][:4]), coletado_em=agora)
            cols = ",".join(rec)
            con.execute(f"INSERT OR REPLACE INTO ne_siafe ({cols}) VALUES ({','.join('?' * len(rec))})",
                        list(rec.values()))
            n += 1
        con.commit()
    finally:
        con.close()
    return {"ok": True, "ingeridas": n, "colunas": sorted(idx)}


# ─────────────────────────────── navegação e colheita (precisa do SIAFE) ───────────────────────────────

async def _ir_para_ne(pg) -> bool:
    """Execução (pt_np4) › Execução Orçamentária (pt_np3) › Nota de Empenho — pelo TEXTO (índice de menu não é
    identidade; ver siafe1-navegacao-e-cabecalho-vivo)."""
    from tools.siafe_mapear import _JS_CLICAR, _JS_IDS, _clicar_id, _ev
    for padrao, alvo in ((r"pt_np4:\d+:pt_cni6::disclosureAnchor$", "Execução"),
                         (r"pt_np3:\d+:pt_cni4::disclosureAnchor$", "Execução Orçamentária")):
        el = [x for x in await _ev(pg, _JS_IDS, padrao) if x["t"] == alvo]
        if not el:
            return False
        await _clicar_id(pg, el[0]["id"])
    if not await _ev(pg, _JS_CLICAR, "Nota de Empenho"):
        return False
    for _ in range(60):
        await pg.wait_for_timeout(2000)
        if await _ev(pg, "()=>!!document.getElementById('" + TBL + ":tabViewerDec::db')"):
            return True
    return False


async def _remover_limite(pg) -> str:
    from tools.siafe_mapear import _ev
    estado = await _ev(pg, r"""()=>{const cb=document.getElementById('""" + TBL + r""":chkRemoveLimit::content');
        if(!cb)return 'ausente'; if(cb.checked)return 'ja_marcado';
        cb.click(); cb.dispatchEvent(new Event('change',{bubbles:true})); return 'marcado';}""")
    if estado == "marcado":
        await pg.wait_for_timeout(8000)
    return estado


async def _filtrar_ug(pg, ug: str) -> dict:
    """Receita do coletor da OB (validada 2026-06-07), com o id desta tabela: Propriedade/Operador por
    typeahead, valor commitado com Tab."""
    from compliance_agent import siafe_ob_orcamentaria as S
    from compliance_agent.siafe_adf import AdfSync
    adf = AdfSync(pg)
    prop = f"{TBL}:table_rtfFilter:0:cbx_col_sel_rtfFilter::content"
    op = f"{TBL}:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"
    if await pg.locator(f'[id="{prop}"]').count() == 0:
        await S._click_real(pg, f"{TBL}:sdtFilter::disAcr"); await adf.wait()
    if await pg.locator(f'[id="{prop}"]').count() == 0:
        return {"ok": False, "erro": "painel de filtro não abriu"}
    await S._typeahead(pg, prop, "UG Emi"); await adf.wait()
    await S._typeahead(pg, op, "começa com"); await adf.wait()
    val = pg.locator('[id*="in_value_rtfFilter"]:visible').last
    if await val.count() == 0:
        return {"ok": False, "erro": "campo de valor não renderizou"}
    await val.click(); await val.press("Control+a"); await val.press("Delete")
    await pg.keyboard.type(str(ug), delay=100)
    await pg.keyboard.press("Tab")
    await adf.wait(); await pg.wait_for_timeout(4000)
    return {"ok": True, "ug": ug}


async def _colher(pg, maxn: int = 20000) -> tuple[list[str], list[list[str]]]:
    """Rola o `::scroller` virtual e colhe o `::db` a cada passo (a tabela só tem ~50 linhas no DOM)."""
    from tools.siafe_mapear import _ev
    header = await _ev(pg, r"""()=>{const h=document.getElementById('""" + TBL + r""":tabViewerDec::ch');
        return h?[...h.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\s+/g,' ').trim()).filter(x=>x):[];}""")
    js_rows = (r"""()=>{const db=document.getElementById('""" + TBL + r""":tabViewerDec::db');const o=[];
        if(db)db.querySelectorAll('tr').forEach(tr=>{const t=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'')
        .replace(/\s+/g,' ').trim());if(t.some(x=>x))o.push(t);});return o;}""")
    sc = TBL + ":tabViewerDec::scroller"
    vistos, linhas, y, seco = set(), [], 0, 0
    while len(linhas) < maxn and seco < 10:
        novos = 0
        for r in await _ev(pg, js_rows):
            m = NE_RE.search(" ".join(r[:2]))
            if m and m.group(0) not in vistos:
                vistos.add(m.group(0)); linhas.append(r); novos += 1
        seco = 0 if novos else seco + 1
        geo = await _ev(pg, "()=>{const s=document.getElementById('" + sc + "');"
                            "return s?{sh:s.scrollHeight,ch:s.clientHeight}:null;}") or {"sh": 0, "ch": 700}
        y += int(max(geo["ch"], 300) * 0.7)
        await _ev(pg, "()=>{const s=document.getElementById('" + sc + "');if(s){s.scrollTop=" + str(y)
                  + ";s.dispatchEvent(new Event('scroll',{bubbles:true}));}}")
        await pg.wait_for_timeout(1100)
        if y >= geo["sh"] - geo["ch"] and not novos:
            break
    return header, linhas


async def coletar_ug(ug: str, exercicio: int) -> dict:
    from playwright.async_api import async_playwright
    from compliance_agent import siafe_ob_orcamentaria as S
    async with async_playwright() as pw:
        ctx, pg = await S._novo_browser(pw, headless=True)
        try:
            lg = await S._login(pg, exercicio)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", "erro": lg.get("erro")}
            if not await _ir_para_ne(pg):
                return {"ok": False, "etapa": "navegacao"}
            lim = await _remover_limite(pg)
            f = await _filtrar_ug(pg, ug)
            if not f.get("ok"):
                return {"ok": False, "etapa": "filtro", **f}
            header, linhas = await _colher(pg)
        finally:
            await S._encerrar(pg, ctx)
    r = ingerir(exercicio, header, linhas)
    capou = _PLATO <= len(linhas) <= _TETO
    return {**r, "ug": ug, "exercicio": exercicio, "colhidas": len(linhas), "limite": lim, "capou": capou,
            "aviso": "encostou no teto de 1.000 — coleta INCOMPLETA, fatiar por número" if capou else ""}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ug", required=True)
    ap.add_argument("--exercicio", type=int, required=True)
    a = ap.parse_args()
    from compliance_agent import host_siafe
    from compliance_agent import siafe_runner as R
    host_siafe.exigir_autorizacao()
    if not R._acquire("siafe_ne"):
        raise SystemExit(f"SIAFE ocupado: {R.lock_status()}")
    try:
        print(json.dumps(asyncio.run(coletar_ug(a.ug, a.exercicio)), ensure_ascii=False))
    finally:
        R._release()


if __name__ == "__main__":
    main()
