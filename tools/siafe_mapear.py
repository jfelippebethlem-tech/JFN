#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siafe_mapear — sonda SÓ DE LEITURA que mapeia o SIAFE-Rio 2: árvore de menus e, por tela, colunas
da grade e propriedades do filtro. Não clica em ação nenhuma (incluir, alterar, excluir, imprimir).

POR QUE EXISTE (04/11/2026). O JFN coleta UMA tela do SIAFE (OB Orçamentária). NE, NL, PD, OB de
Retenção, Guia de Devolução, Bloqueio Judicial e Contratos estão fora — e é deles que saem a ordem
cronológica (art. 141 L.14.133), o pagamento sem liquidação e o empenho a posteriori (art. 60 L.4.320).
Antes de escrever coletor, o mapa: o que cada tela mostra, com que nome de coluna.

Sessão única: pega o lock do siafe_runner e respeita host_siafe.exigir_autorizacao().

Uso:
    PYTHONPATH=. .venv/bin/python tools/siafe_mapear.py --menu
    PYTHONPATH=. .venv/bin/python tools/siafe_mapear.py --telas "Nota de Empenho,Nota de Liquidação"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from compliance_agent import siafe_ob_orcamentaria as S
from compliance_agent import siafe_runner as R

_REPO = Path(__file__).resolve().parents[1]
SAIDA = _REPO / "data" / "siafe_mapa.json"
PARCIAL = _REPO / "data" / "siafe_mapa_parcial.json"   # gravado tela a tela: queda no meio não perde o lido
QUEM = "siafe_mapear"

_JS_LINKS = r"""()=>[...document.querySelectorAll('a')].map(e=>({t:(e.innerText||'').trim(),
    id:e.id||'', cls:e.className||'', vis:!!(e.offsetWidth||e.offsetHeight)}))
    .filter(x=>x.t.length>1&&x.t.length<80)"""

# Como o coletor que funciona (_navegar): item de menu é `a.xyo`, clicado pelo TEXTO, sem filtro de
# visibilidade — o filtro descartava os submenus e o clique genérico acertava outra âncora (04/11/2026).
_JS_CLICAR = r"""(alvo)=>{const norm=s=>(s||'').trim().toLowerCase().replace(/\s+/g,' ');
    const els=[...document.querySelectorAll('a')];
    const el=els.find(e=>e.classList.contains('xyo')&&norm(e.innerText)===norm(alvo))
          ||els.find(e=>norm(e.innerText)===norm(alvo));
    if(el){el.click();return true;}return false;}"""

# estrutura da grade para escrever o coletor: ids do corpo/scroller virtual, checkbox de remover o teto,
# e 3 linhas de amostra (CPF mascarado). Só lê o DOM.
_JS_DETALHE = r"""()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);
    const db=ids.filter(i=>/::db$/.test(i)), sc=ids.filter(i=>/::scroller$/.test(i)),
          ch=ids.filter(i=>/::ch$/.test(i)), lim=ids.filter(i=>/RemoveLimit|chkLimit|Limite/i.test(i));
    const corpo=db.length?document.getElementById(db[0]):null; const linhas=[];
    if(corpo)[...corpo.querySelectorAll('tr')].slice(0,3).forEach(tr=>linhas.push([...tr.querySelectorAll('td')]
        .map(td=>(td.innerText||'').replace(/\s+/g,' ').trim().replace(/\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b/g,'***.$2.$3-**'))));
    const filtro=ids.filter(i=>/sdtFilter|Filtro|filter|selProp|ac[A-Z]?\d|it\d+::content/i.test(i)).slice(0,40);
    const nlin=corpo?corpo.querySelectorAll('tr').length:0;
    const rod=[...document.querySelectorAll('span,div')].map(e=>(e.innerText||'').trim()).filter(t=>/registro|Total|linhas/i.test(t)&&t.length<80).slice(0,6);
    return {db, sc, ch, lim, nlin, linhas, filtro, rodape:rod};}"""

# colunas da grade + opções dos selects (propriedades do filtro) — só lê o DOM
_JS_TELA = r"""()=>{const vis=e=>!!(e.offsetWidth||e.offsetHeight);
    const cols=[...document.querySelectorAll('[id*="tbl"] th, [id*="tbl"] [role=columnheader]')]
        .filter(vis).map(e=>(e.innerText||'').trim()).filter(Boolean);
    const sels=[...document.querySelectorAll('select')].filter(vis).map(s=>({id:s.id,
        opts:[...s.options].map(o=>(o.text||'').trim()).filter(Boolean).slice(0,80)}));
    const tabelas=[...document.querySelectorAll('[id*="tbl"]')].map(e=>e.id).filter(i=>/tbl[A-Z]/.test(i)).slice(0,10);
    return {cols:[...new Set(cols)], sels, tabelas, titulo:document.title};}"""


_JS_IDS = r"""(pad)=>[...document.querySelectorAll('a')].filter(e=>new RegExp(pad).test(e.id||''))
    .map(e=>({t:(e.innerText||'').trim(),id:e.id}))"""


async def _ev(pg, js: str, arg=None, tentativas: int = 15):
    """evaluate que aguenta navegação: clicar numa tela recarrega a página e o `evaluate` seguinte caía com
    "Execution context was destroyed" (04/11/2026, 3ª passada — perdeu a passada inteira)."""
    from playwright.async_api import Error as PWError
    for i in range(tentativas):
        try:
            return await (pg.evaluate(js) if arg is None else pg.evaluate(js, arg))
        except PWError as exc:
            if "context was destroyed" not in str(exc) and "navigat" not in str(exc) or i == tentativas - 1:
                raise
            await pg.wait_for_timeout(2000)


def _caminho(tela: str) -> tuple[str, str] | None:
    """(módulo, 2º nível) da tela, lido do último mapa de menu gravado — clicar pelo caminho conhecido em
    vez de varrer os 13 módulos para cada tela."""
    if not SAIDA.exists():
        return None
    for ex in reversed(json.loads(SAIDA.read_text(encoding="utf-8")).get("execucoes", [])):
        for mod, arv in (ex.get("menu") or {}).items():
            for sg, telas in arv.items():
                if tela.lower() in (t.lower() for t in telas):
                    return mod, sg
    return None


async def _clicar_id(pg, id_: str, espera_ms: int = 2500) -> None:
    from playwright.async_api import Error as PWError
    try:
        await pg.evaluate("(i)=>{const e=document.getElementById(i);if(e)e.click();}", id_)
    except PWError:                # PPR em voo derruba o contexto: a página segue, o clique pegou
        pass
    await pg.wait_for_timeout(espera_ms)


async def _expandir(pg, topo: str) -> dict[str, list[str]]:
    """Módulo (pt_np4) → 2º nível (pt_np3) → telas. Clica SÓ o módulo e depois cada item do 2º nível;
    clicar toda âncora de disclosure pulava para outros módulos (04/11/2026, 2ª passada)."""
    mods = [x for x in await _ev(pg, _JS_IDS, r"pt_np4:\d+:pt_cni6::disclosureAnchor$") if x["t"] == topo]
    if not mods:
        return {}
    await _clicar_id(pg, mods[0]["id"])
    segundo = await _ev(pg, _JS_IDS, r"pt_np3:\d+:pt_cni4::disclosureAnchor$")
    base = {x["t"] for x in await _ev(pg, _JS_LINKS)}
    arvore: dict[str, list[str]] = {}
    for sg in segundo:
        await _clicar_id(pg, sg["id"])
        agora = {x["t"] for x in await _ev(pg, _JS_LINKS)}
        arvore[sg["t"]] = sorted(agora - base - {x["t"] for x in segundo})
    return arvore


async def mapear(menu: bool, telas: list[str], exercicio: int, prazo_s: int,
                 detalhar: bool = False, espera_grade: int = 30) -> dict:
    from playwright.async_api import Error as PWError, async_playwright
    inicio, out = time.time(), {"exercicio": exercicio, "em": time.strftime("%F %T")}
    from compliance_agent.recursos import browser_lock_async
    # o MESMO lock de navegador do coletor da OB e do dreno: o lock do siafe_runner sozinho não os segura,
    # e duas sessões na mesma conta derrubam uma à outra (sessão única por IP).
    async with browser_lock_async(nome="siafe", espera_max=900), async_playwright() as pw:
        ctx, pg = await S._novo_browser(pw, headless=True)
        try:
            lg = await S._login(pg, exercicio)
            out["login"] = {k: v for k, v in lg.items() if k in ("ok", "erro", "etapa")}
            if not lg.get("ok"):
                return out
            await S._shot(pg, "mapa_0_poslogin")
            topo = [x["t"] for x in await pg.evaluate(_JS_LINKS) if x["vis"] and "xyo" in x["cls"]]
            out["topo"] = topo
            if menu:
                out["menu"] = {}
                for t in topo:
                    if time.time() - inicio > prazo_s:
                        out["cortado_por_prazo"] = True
                        break
                    out["menu"][t] = await _expandir(pg, t)
                    await S._shot(pg, f"mapa_menu_{t[:20]}")
            out["telas"] = {}
            for tela in telas:
                if time.time() - inicio > prazo_s:
                    out["cortado_por_prazo"] = True
                    break
                cam = _caminho(tela)
                if not cam:
                    out["telas"][tela] = {"achou": False, "motivo": "fora do último mapa de menu (rode --menu)"}
                    continue
                mod, sg = cam
                mods = [x for x in await _ev(pg, _JS_IDS, r"pt_np4:\d+:pt_cni6::disclosureAnchor$") if x["t"] == mod]
                if mods:
                    await _clicar_id(pg, mods[0]["id"])
                segs = [x for x in await _ev(pg, _JS_IDS, r"pt_np3:\d+:pt_cni4::disclosureAnchor$") if x["t"] == sg]
                if segs:
                    await _clicar_id(pg, segs[0]["id"])
                achou = await _ev(pg, _JS_CLICAR, tela)
                if not achou:
                    out["telas"][tela] = {"achou": False, "caminho": [mod, sg]}
                    continue
                info = {}
                for _ in range(espera_grade):  # a grade é pesada: espera aparecer
                    await pg.wait_for_timeout(2000)
                    info = await _ev(pg, _JS_TELA)    # aguenta contexto destruído por PPR
                    if info["cols"] or info["sels"]:
                        break
                await S._shot(pg, f"mapa_tela_{tela[:24]}")
                out["telas"][tela] = {"achou": True, "caminho": [mod, sg], **info}
                if detalhar:
                    out["telas"][tela]["detalhe"] = await _ev(pg, _JS_DETALHE)
                    # a grade pode morar num iframe, que o `document` da página principal não vê
                    out["telas"][tela]["frames"] = []
                    for fr in pg.frames[1:]:
                        try:
                            out["telas"][tela]["frames"].append({"url": fr.url[:160],
                                                                 "detalhe": await fr.evaluate(_JS_DETALHE)})
                        except PWError as exc:  # frame sumindo no meio é esperado
                            out["telas"][tela]["frames"].append({"url": fr.url[:160], "erro": str(exc)[:80]})
                PARCIAL.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        finally:
            await S._encerrar(pg, ctx)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", action="store_true")
    ap.add_argument("--telas", default="")
    ap.add_argument("--exercicio", type=int, default=2026)
    ap.add_argument("--prazo", type=int, default=1200, help="segundos; corta antes da janela do dreno")
    ap.add_argument("--detalhar", action="store_true", help="ids da grade, teto e 3 linhas de amostra")
    ap.add_argument("--espera-grade", type=int, default=30, help="ciclos de 2 s esperando a grade")
    a = ap.parse_args()
    from compliance_agent import host_siafe
    host_siafe.exigir_autorizacao()
    if not R._acquire(QUEM):
        raise SystemExit(f"SIAFE ocupado: {R.lock_status()}")
    try:
        r = asyncio.run(mapear(a.menu, [t.strip() for t in a.telas.split(",") if t.strip()],
                               a.exercicio, a.prazo, a.detalhar, a.espera_grade))
    finally:
        R._release()
    antigo = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    antigo.setdefault("execucoes", []).append(r)
    SAIDA.write_text(json.dumps(antigo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: r[k] for k in r if k != "menu"}, ensure_ascii=False)[:1500])
    for t, arv in (r.get("menu") or {}).items():
        print(f"\n## {t}")
        for sg, telas in arv.items():
            print(f"  ▸ {sg}: " + " · ".join(telas))


if __name__ == "__main__":
    main()
