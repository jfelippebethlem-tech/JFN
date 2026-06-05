# -*- coding: utf-8 -*-
"""
Coleta de OBs no SIAFE reutilizando a SESSÃO autenticada (sem novo login/MFA).

Aproveita a navegação já pronta de `_SANDBOX/coletar_obs_agora.py` (_ir_obs, _ir_lista_favorecido,
_filtrar_por_cnpj, _ler_tabela), mas injeta o storage_state salvo por siafe_session.py — então NÃO
faz login (válido por ~30 dias com o device-trust). Resultado: OBs por empresa/exercício.

Uso: python -m compliance_agent.coletar_obs_sessao --cnpj 19088605000104 --ano 2025
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "sei_cache"
STATE = DATA / "siafe_state.json"
APP_URL = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/"


def _load_collector():
    """Carrega o módulo _SANDBOX/coletar_obs_agora.py por caminho."""
    p = _REPO / "_SANDBOX" / "coletar_obs_agora.py"
    spec = importlib.util.spec_from_file_location("coletar_obs_agora", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _navegar_ob(pg):
    """Execução → Execução Financeira → Ordens Bancárias (caminho mapeado em docs/SIAFE-NAVEGACAO.md).
    Retorna True se a grade pt1:tblOrdemBancaria apareceu."""
    # 1) menu Execução (anchor xyo, texto exato)
    await pg.evaluate(r"""() => {const a=[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução'); if(a)a.click();}""")
    await pg.wait_for_timeout(1800)
    # 2) Execução Financeira (disclosureAnchor)
    await pg.evaluate(r"""() => {const a=document.getElementById('pt1:pt_np3:1:pt_cni4::disclosureAnchor')
                                  || [...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução Financeira'); if(a)a.click();}""")
    await pg.wait_for_timeout(2200)
    # 3) Ordens Bancárias (por texto)
    await pg.evaluate(r"""() => {const a=[...document.querySelectorAll('a')].find(e=>(e.innerText||'').trim()==='Ordens Bancárias'); if(a)a.click();}""")
    await pg.wait_for_timeout(10000)
    return await pg.evaluate(r"""() => !!document.querySelector('[id*="tblOrdemBancaria"]')""")


async def coletar(cnpj, cnpj_fmt, ano, max_paginas=3):
    if not STATE.exists():
        return {"erro": "sem sessão — rode siafe_session --login primeiro"}
    mod = _load_collector()
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(
            viewport={"width": 1366, "height": 900}, locale="pt-BR",
            timezone_id="America/Sao_Paulo", ignore_https_errors=True,
            storage_state=str(STATE),
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            # Login NORMAL, mas com o cookie de device-trust carregado -> SIAFE NÃO pede MFA,
            # e o workspace ADF renderiza corretamente (carregar /faces/ direto vinha em branco).
            ok = await mod._login(pg, ano)
            if not ok:
                await mod._screenshot(pg, "ERRO_login_sessao")
                return {"erro": "login (com trust) falhou", "url": pg.url}

            # navega até as OBs pelo caminho mapeado (Execução > Execução Financeira > Ordens Bancárias)
            nav = await _navegar_ob(pg)
            if not nav:
                nav = await mod._ir_obs(pg)  # fallback
            if not nav:
                await mod._screenshot(pg, "ERRO_nav_obs_sessao")
                return {"erro": "não chegou na tela de OBs", "url": pg.url}

            # lê a grade real (tabViewerDec) com paginação; filtra por favorecido em Python
            HEADERS = ["numero", "ug_emitente", "ug_pagadora", "data_emissao", "status", "tipo",
                       "tipo_ob", "favorecido", "nome_favorecido", "gd", "processo", "re", "pd",
                       "status_envio", "valor", "assinatura"]
            todas, vistos = [], set()
            for pag in range(1, max_paginas + 1):
                page_rows = await pg.evaluate(r"""() => {
                  const db=document.getElementById('pt1:tblOrdemBancaria:tabViewerDec::db'); if(!db) return [];
                  const out=[];
                  db.querySelectorAll('tr').forEach(tr=>{const tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').replace(/\s+/g,' ').trim()); if(tds.some(x=>x)&&tds.length>=14) out.push(tds);});
                  return out;
                }""")
                for r in page_rows:
                    num = r[0] if r else ""
                    if num and num not in vistos:
                        vistos.add(num)
                        todas.append(dict(zip(HEADERS, r)))
                # próxima página (botão next do ADF), se existir e habilitado
                avancou = await pg.evaluate(r"""() => {
                  const nx=[...document.querySelectorAll('a,div')].find(e=>/próxim|proxim|next/i.test((e.title||e.getAttribute('aria-label')||''))&&!/disabled/i.test(e.className)&&e.getBoundingClientRect().width>0);
                  if(nx){nx.click(); return true;} return false;}""")
                if not avancou:
                    break
                await pg.wait_for_timeout(3500)
            return {"cnpj": cnpj, "ano": ano, "headers": HEADERS, "n_total_lidas": len(todas), "rows": todas}
        except Exception as e:
            try:
                await mod._screenshot(pg, "ERRO_coleta_sessao")
            except Exception:
                pass
            return {"erro": f"{type(e).__name__}: {str(e)[:160]}", "url": pg.url}
        finally:
            await b.close()


def _money_br(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def ingest_obs(rows, ano):
    """Grava as OBs coletadas no compliance.db (idempotente por numero_ob). Dedup vs TFE: tabela
    separada (ordens_bancarias = nominal do SIAFE; TFE fica em tfe_cache, agregado)."""
    import sqlite3
    from datetime import datetime
    db = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data")) / "compliance.db"
    if not db.exists():
        return 0
    con = sqlite3.connect(str(db))
    n = 0
    for r in rows:
        num = (r.get("numero") or "").strip()
        if not num:
            continue
        try:
            de = r.get("data_emissao", "")
            data = datetime.strptime(de, "%d/%m/%Y").date().isoformat() if de else None
        except Exception:
            data = None
        proc = (r.get("processo") or "").strip()
        vals = dict(numero_ob=num, data_emissao=data, ug_codigo=r.get("ug_emitente"),
                    favorecido_nome=r.get("nome_favorecido"), valor=_money_br(r.get("valor")),
                    tipo_ob=r.get("tipo_ob"), status=r.get("status"),
                    numero_processo=proc, numero_sei=proc if proc and proc != "não há" else None,
                    categoria="siafe_ob", exercicio=str(ano))
        ex = con.execute("SELECT id FROM ordens_bancarias WHERE numero_ob=?", (num,)).fetchone()
        if ex:
            con.execute("""UPDATE ordens_bancarias SET data_emissao=?, ug_codigo=?, favorecido_nome=?,
                           valor=?, tipo_ob=?, status=?, numero_processo=?, numero_sei=?, categoria=?,
                           exercicio=? WHERE id=?""",
                        (vals["data_emissao"], vals["ug_codigo"], vals["favorecido_nome"], vals["valor"],
                         vals["tipo_ob"], vals["status"], vals["numero_processo"], vals["numero_sei"],
                         vals["categoria"], vals["exercicio"], ex[0]))
        else:
            cols = ",".join(vals.keys()); ph = ",".join("?" * len(vals))
            con.execute(f"INSERT INTO ordens_bancarias({cols}) VALUES({ph})", tuple(vals.values()))
        n += 1
    con.commit(); con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cnpj", default="19088605000104")
    ap.add_argument("--cnpj-fmt", default="19.088.605/0001-04")
    ap.add_argument("--ano", type=int, default=2025)
    ap.add_argument("--nome", default="", help="filtra OBs cujo Nome do Favorecido contém este termo")
    ap.add_argument("--max-paginas", type=int, default=3)
    ap.add_argument("--ingest", action="store_true", help="grava as OBs no compliance.db (ordens_bancarias)")
    a = ap.parse_args()
    res = asyncio.run(coletar(a.cnpj, a.cnpj_fmt, a.ano, max_paginas=a.max_paginas))
    if "erro" in res:
        print(json.dumps(res, ensure_ascii=False))
    else:
        rows = res["rows"]
        # filtra por favorecido (nome contém termo OU favorecido == CNPJ) — opcional
        termo = (a.nome or "").upper()
        if termo:
            rows = [r for r in rows if termo in (r.get("nome_favorecido", "") or "").upper()
                    or termo in (r.get("favorecido", "") or "").upper()]
        print(f"OBs lidas: {res['n_total_lidas']} | após filtro '{a.nome}': {len(rows)}")
        out = DATA / f"obs_sessao_{a.cnpj}_{a.ano}.json"
        out.write_text(json.dumps({**res, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"salvo em {out}")
        for r in rows[:6]:
            print(f"  {r.get('numero')} | {r.get('data_emissao')} | {r.get('nome_favorecido','')[:30]} | proc={r.get('processo')} | R$ {r.get('valor')}")
        if a.ingest:
            ning = ingest_obs(rows, a.ano)
            print(f"  → ingeridas no compliance.db (ordens_bancarias): {ning}")


if __name__ == "__main__":
    main()
