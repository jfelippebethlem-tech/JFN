# -*- coding: utf-8 -*-
"""
SIAFE-Rio 2 — varredura da tela "Execução > Execução Financeira > OB Orçamentária"
(tela `ordemBancariaOrcamentariaCad.jsp`, tabela ADF `pt1:tblOBOrcamentaria:tabViewerDec`).

ABORDAGEM (a mais robusta): o Playwright LOGA (tratando o diálogo de sessão única do SIAFE) e abre a tela;
depois **rola a tabela virtualizada de verdade** e colhe as linhas do DOM à medida que o Oracle ADF as
carrega por PPR. Assim o navegador cuida de ViewState/clientTokens/fetch sozinho — sem replay frágil.

Login: SIAFE_USER (CPF) e SIAFE_PASS vêm SÓ do .env (nunca hardcoded). Sessão é única por usuário: ao logar,
o SIAFE pergunta "usuário já logado... Deseja continuar? [Sim]" e FECHA a outra sessão (ex.: seu navegador).

USO:
    cd ~/JFN
    .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria --exercicio 2025 --max 300
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

LOGIN_URL = "https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp"
TABLE_DB = "pt1:tblOBOrcamentaria:tabViewerDec::db"   # container rolável do corpo da tabela
OB_RE = re.compile(r"20\d\dOB\d{5,6}")
_STATE = _REPO / "data" / "sei_cache" / "siafe_state.json"
_CKPT = _REPO / "data" / "sei_cache" / "ob_orcamentaria_checkpoint.json"


class SessaoPerdida(Exception):
    """Disparada quando o SIAFE nos desconecta no meio (ex.: o Mestre Jorge logou e tomou a sessão única)."""


async def _sessao_perdida(pg) -> bool:
    """Detecta se fomos REALMENTE deslogados. ESTRITO: só voltar pro login.jsp ou mensagem explícita de
    expiração conta — NÃO confundir com o widget 'Sua sessão expira em...' do workspace (falso positivo)."""
    try:
        url = (pg.url or "").lower()
        if "login.jsp" in url:
            # confirma que o form de login está presente (não só a URL)
            return await pg.evaluate("""()=>!!document.getElementById('loginBox:itxSenhaAtual::content')""")
        txt = ((await pg.inner_text("body")) or "").lower()
    except Exception:
        return True  # página morreu = trate como perda
    return any(k in txt for k in ("sessão expirada", "sessao expirada", "sessão encerrada",
                                  "sessao encerrada", "sua sessão expirou", "sua sessao expirou",
                                  "faça login novamente", "faca login novamente"))


async def _click_texto(pg, textos: list[str]):
    """Clica via JS no 1º elemento VISÍVEL cujo texto bate (sem o auto-wait de 30s do Playwright)."""
    return await pg.evaluate(
        """(textos)=>{
            const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none' && s.opacity!=='0'; };
            const els = [...document.querySelectorAll('a,button,span,div,td,input[type=button],input[type=submit]')];
            for (const t of textos) {
                const el = els.find(e => ((e.innerText||e.value||'').trim() === t) && vis(e));
                if (el) { el.click(); return t; }
            }
            return null;
        }""", textos)


async def _login(pg, exercicio: int):
    from compliance_agent.envfile import carregar_env
    try:
        carregar_env()
    except Exception:
        pass
    u = (os.environ.get("SIAFE_USER") or "").strip()
    p = (os.environ.get("SIAFE_PASS") or "").strip()
    if not u or not p:
        return {"ok": False, "erro": "sem SIAFE_USER/SIAFE_PASS no .env"}
    await pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
    await pg.wait_for_timeout(2500)
    # ORDEM IMPORTA: usuário → exercício → SENHA por último, e Enter na senha (o form ADF submete com o
    # foco no campo de senha; setar o <select> por último tira o foco e o submit não dispara).
    # RECEITA PROVADA (diagnóstico): preencher usuário+senha e CLICAR o botão de login direto pelo ID
    # (clique real do Playwright dispara o handler ADF). NÃO usar Enter antes (quebra o submit). NÃO mexer
    # no select de exercício antes (autoSubmit/PPR quebra). Exercício é tratado depois do login.
    await pg.fill('[id="loginBox:itxUsuario::content"]', u)
    await pg.fill('[id="loginBox:itxSenhaAtual::content"]', p)
    await pg.wait_for_timeout(400)
    try:
        await pg.click('[id="loginBox:btnConfirmar"]', timeout=8000)
    except Exception:
        await pg.evaluate("""()=>{const b=document.getElementById('loginBox:btnConfirmar');if(b)b.click();}""")
    await pg.wait_for_timeout(4000)
    # SEQUÊNCIA DE POPUPS pós-Ok (sessão única "já logado" + avisos/termos). Clica nos botões conhecidos
    # até não haver mais (até 7 rodadas). Tudo via JS por ID/texto (sem o auto-wait de 30s do Playwright).
    for _ in range(7):
        agiu = await pg.evaluate(
            """()=>{
                const vis = el => { if(!el) return false; const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
                // 1) botão "Sim" do diálogo de sessão única (id conhecido)
                const sim = document.getElementById('myBtnConfirm');
                if (vis(sim)) { sim.click(); return 'sim'; }
                // 2) qualquer botão/link visível de confirmação/aviso
                const alvo = ['Sim','Continuar','Confirmar','Ciente','Estou ciente','Acessar','Prosseguir','Fechar','OK','Ok'];
                const els = [...document.querySelectorAll('button,a,input[type=button],input[type=submit]')];
                for (const t of alvo) {
                    const el = els.find(e => ((e.innerText||e.value||'').trim()===t) && vis(e)
                                              && (e.id||'').indexOf('loginBox:btnConfirmar')<0);
                    if (el) { el.click(); return t; }
                }
                return null;
            }""")
        if not agiu:
            break
        await pg.wait_for_timeout(2800)
    await pg.wait_for_timeout(3000)
    body = ((await pg.inner_text("body")) or "")
    bl = body.lower()
    # marcadores de sucesso: sumiu o campo de senha do login E/OU apareceu o menu do workspace
    tem_senha_login = await pg.evaluate("""()=>!!document.getElementById('loginBox:itxSenhaAtual::content')""")
    tem_workspace = await pg.evaluate("""()=>[...document.querySelectorAll('a.xyo')].some(e=>(e.innerText||'').trim()==='Execução')||/workspace/.test(location.href)""")
    print(f"   [login] url={pg.url} | senha_login={tem_senha_login} workspace={tem_workspace} | body[:140]={body[:140].replace(chr(10),' ')!r}", flush=True)
    if any(k in bl for k in ("token", "código de verificação", "autenticação de dois")):
        return {"ok": False, "erro": "mfa", "detail": "SIAFE pediu MFA — fornecer o código."}
    if tem_workspace or not tem_senha_login:
        return {"ok": True, "url": pg.url}
    try:
        await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_login.png"))
    except Exception:
        pass
    return {"ok": False, "erro": "login_falhou", "url": pg.url, "body": body[:300]}


async def _shot(pg, nome):
    try:
        await pg.screenshot(path=str(_REPO / "data/sei_cache" / f"nav_{nome}.png"))
    except Exception:
        pass


async def _contar_linhas(pg) -> int:
    return await pg.evaluate(
        r"""()=>{const db=document.getElementById('""" + TABLE_DB + r"""');
            return db ? [...db.querySelectorAll('tr')].filter(tr=>/20\d\dOB\d{5,6}/.test(tr.innerText||'')).length : 0;}""")


async def _glasspane_ativo(pg) -> bool:
    """True se há um glasspane/spinner de carregamento do ADF visível (tabela ainda carregando)."""
    return await pg.evaluate(r"""()=>{
        const vis = e => { const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
            return r.width>3 && r.height>3 && s.visibility!=='hidden' && s.display!=='none'; };
        return [...document.querySelectorAll('.AFBlockingGlassPane,[id*="glassPane"],[id*="GlassPane"],.xlk,.x1ie')].some(vis);
    }""")


async def tabela_pronta(pg) -> bool:
    """Detector de 'load concluído': tabela existe + tem linhas de OB + sem glasspane + contagem estável."""
    if await _glasspane_ativo(pg):
        return False
    n1 = await _contar_linhas(pg)
    if n1 <= 0:
        return False
    await pg.wait_for_timeout(1500)
    if await _glasspane_ativo(pg):
        return False
    n2 = await _contar_linhas(pg)
    return n2 == n1 and n2 > 0  # estável entre duas leituras


async def _navegar(pg) -> dict:
    """Execução → Execução Financeira → OB Orçamentária. Retorna {ok, itens_submenu}."""
    await _shot(pg, "0_poslogin")
    await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
    await pg.wait_for_timeout(1800)
    await _shot(pg, "1_execucao")
    await pg.evaluate(r"""()=>{const a=document.getElementById('pt1:pt_np3:1:pt_cni4::disclosureAnchor')||[...document.querySelectorAll('a.xyo')].find(e=>(e.innerText||'').trim()==='Execução Financeira');if(a)a.click();}""")
    await pg.wait_for_timeout(2200)
    await _shot(pg, "2_execfinanceira")
    itens = await pg.evaluate(r"""()=>[...document.querySelectorAll('a')].map(e=>(e.innerText||'').trim()).filter(t=>t.length>2&&t.length<60)""")
    # clica EXATAMENTE em "OB Orçamentária" (não em "Execução Orçamentária", que também casa "orçamentária")
    clicou = await pg.evaluate(r"""()=>{
        const norm = s => (s||'').trim().toLowerCase().replace(/\s+/g,' ');
        const els = [...document.querySelectorAll('a')];
        let el = els.find(e => norm(e.innerText)==='ob orçamentária' || norm(e.innerText)==='ob orcamentaria');
        if(!el) el = els.find(e => /^ob\s+or[çc]ament[áa]ria$/.test(norm(e.innerText)));
        if(el){el.click();return (el.innerText||'').trim();}
        return null;
    }""")
    await pg.wait_for_timeout(2000)
    await _shot(pg, "3_clicou_ob_orcamentaria")
    # a grade é PESADA e demora bastante a aparecer/carregar — espera a tabela (poll até ~90s)
    achou = False
    for i in range(45):
        await pg.wait_for_timeout(2000)
        achou = await pg.evaluate(r"""()=>!!document.querySelector('[id*="tblOBOrcamentaria"]')""")
        if achou:
            break
        if i in (10, 25):
            await _shot(pg, f"4_aguardando_tabela_{i}")
    # detector de LOAD CONCLUÍDO: espera a tabela ficar pronta (linhas + sem spinner + contagem estável)
    pronta = False
    if achou:
        for _ in range(30):  # até ~70s
            if await tabela_pronta(pg):
                pronta = True
                break
            await pg.wait_for_timeout(2000)
    await _shot(pg, "5_tabela_final")
    n_ini = await _contar_linhas(pg) if achou else 0
    return {"ok": bool(achou and pronta), "clicou": clicou, "linhas_iniciais": n_ini,
            "itens_submenu": [t for t in itens if "ob" in t.lower() or "orçament" in t.lower() or "orcament" in t.lower()][:10]}


TABLE = "pt1:tblOBOrcamentaria:tabViewerDec"
_EV_SCROLL = ('<m xmlns="http://oracle.com/richClient/comm">'
              '<k v="type"><s>scroll</s></k><k v="first"><n>{first}</n></k><k v="rows"><n>50</n></k></m>')


def _viewstate_txt(text):
    m = (re.search(r'javax\.faces\.ViewState[^>]*?>\s*<!\[CDATA\[(.*?)\]\]>', text, re.S)
         or re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', text)
         or re.search(r'<value>([^<]+)</value>', text))
    return m.group(1) if m else None


def _parse_rows_txt(text):
    """Extrai linhas de OB do envelope PPR (regex). Retorna lista de listas (células)."""
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.S):
        cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        cells = [re.sub(r'\s+', ' ', x) for x in cells]
        if OB_RE.search(tr) and len([c for c in cells if c]) >= 4:
            rows.append(cells)
    return rows


TABLE_SCROLLER = "pt1:tblOBOrcamentaria:tabViewerDec::scroller"


async def _colher(pg, maxn: int, vistos: set, linhas: list, save_cb=None) -> list:
    """Colhe as OBs ROLANDO O CONTAINER VIRTUAL (`::scroller`, ~40000px), colhendo o corpo (`::db`) a cada
    passo. A tabela é virtualizada (só ~50 linhas no DOM por vez) e tem limite de 1000 registros por
    consulta — rolar o ::db (1950px) não bastava; é o ::scroller que dispara o fetch do ADF.
    Levanta SessaoPerdida se deslogar. `save_cb()` persiste o progresso."""
    header = await pg.evaluate(r"""()=>{
        const h=document.querySelector('[id="pt1:tblOBOrcamentaria:tabViewerDec::ch"]')||document.querySelector('[id*="tblOBOrcamentaria"][id*="::ch"]');
        if(!h)return[];return [...h.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\s+/g,' ').trim()).filter(x=>x);
    }""")
    js_rows = r"""()=>{const db=document.getElementById('""" + TABLE_DB + r"""');const o=[];if(db)db.querySelectorAll('tr').forEach(tr=>{const tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').replace(/\s+/g,' ').trim());if(tds.some(x=>x))o.push(tds);});return o;}"""
    js_geo = r"""()=>{const s=document.getElementById('""" + TABLE_SCROLLER + r"""');return s?{top:s.scrollTop,sh:s.scrollHeight,ch:s.clientHeight}:null;}"""

    def js_scroll_to(y):
        return (r"""()=>{const s=document.getElementById('""" + TABLE_SCROLLER + r"""');
            if(!s)return -1;s.scrollTop=""" + str(int(y)) + r""";
            s.dispatchEvent(new Event('scroll',{bubbles:true}));return s.scrollTop;}""")

    async def _harvest():
        novos = 0
        for r in await pg.evaluate(js_rows):
            m = OB_RE.search(" ".join(r))
            if m and m.group(0) not in vistos and len([c for c in r if c]) >= 4:
                vistos.add(m.group(0)); linhas.append(r); novos += 1
        return novos

    await _harvest()  # 1ª janela (já no DOM)
    geo = await pg.evaluate(js_geo) or {"sh": 0, "ch": 727}
    sh, ch = geo["sh"], max(geo["ch"], 300)
    passo = int(ch * 0.7)  # sobreposição p/ não pular linhas
    y, seco, ciclo = 0, 0, 0
    while len(linhas) < maxn and seco < 10:
        y += passo
        await pg.evaluate(js_scroll_to(y))
        await pg.wait_for_timeout(1100)  # espera o ADF buscar/renderizar o próximo bloco
        novos = await _harvest()
        seco = 0 if novos else seco + 1
        if save_cb and novos:
            save_cb(header, linhas)
        ciclo += 1
        # chegou ao fim do scroller? recalcula (pode crescer conforme carrega) e encerra se passou do fim
        geo = await pg.evaluate(js_geo)
        if geo:
            sh = max(sh, geo["sh"])
            if y >= sh - ch and not novos:
                break
        if ciclo % 8 == 0 and await _sessao_perdida(pg):
            if save_cb:
                save_cb(header, linhas)
            raise SessaoPerdida(f"deslogado após colher {len(linhas)} OBs")
    if save_cb:
        save_cb(header, linhas)
    return header


def _ckpt_load(exercicio: int) -> tuple[set, list, list]:
    try:
        d = json.loads(_CKPT.read_text(encoding="utf-8"))
        if d.get("exercicio") == exercicio:
            linhas = d.get("linhas", [])
            vistos = set()
            for r in linhas:
                m = OB_RE.search(" ".join(r))
                if m:
                    vistos.add(m.group(0))
            return vistos, linhas, d.get("header", [])
    except Exception:
        pass
    return set(), [], []


def _ckpt_save(exercicio: int, header: list, linhas: list):
    try:
        _CKPT.parent.mkdir(parents=True, exist_ok=True)
        _CKPT.write_text(json.dumps({"exercicio": exercicio, "header": header, "linhas": linhas},
                                    ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


async def coletar(exercicio=2025, maxn=300, headless=True, vistos=None, linhas=None) -> dict:
    """Uma passada: login → navega → colhe. Acumula em `vistos`/`linhas` (para retomar entre tentativas)."""
    from playwright.async_api import async_playwright
    vistos = vistos if vistos is not None else set()
    linhas = linhas if linhas is not None else []
    save_cb = lambda h, ls: _ckpt_save(exercicio, h, ls)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=headless, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1600, "height": 1000},
                                  user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        _t0 = time.time()
        _log = lambda m: print(f"[{time.time()-_t0:5.1f}s] {m}", flush=True)
        try:
            _log("login: iniciando...")
            log = await _login(pg, exercicio)
            _log(f"login: {log}")
            if not log.get("ok"):
                return {"ok": False, "etapa": "login", **log}
            _log("navegação: Execução > Execução Financeira > OB Orçamentária...")
            nav = await _navegar(pg)
            _log(f"navegação: {nav}")
            if not nav.get("ok"):
                try:
                    await pg.screenshot(path=str(_REPO / "data/sei_cache/ERRO_nav_ob_orc.png"))
                except Exception:
                    pass
                return {"ok": False, "etapa": "navegacao", "detail": "tabela tblOBOrcamentaria não apareceu",
                        "itens_submenu": nav.get("itens_submenu")}
            try:
                await ctx.storage_state(path=str(_STATE))
            except Exception:
                pass
            _log(f"colhendo (rolando a tabela, alvo {maxn})...")
            header = await _colher(pg, maxn, vistos, linhas, save_cb)
            _log(f"colheu {len(linhas)} OBs | header={header}")
            return {"ok": True, "exercicio": exercicio, "header": header, "n": len(linhas), "linhas": linhas}
        finally:
            await b.close()


async def coletar_resiliente(exercicio=2025, maxn=100000, max_tentativas=24,
                             headless=True, coordenar=True, espera_fallback_s=3600,
                             _sleep=None, _aguardar=None) -> dict:
    """
    Varredura RESILIENTE à sessão única do SIAFE. Se o Mestre Jorge logar e nos derrubar (ou vice-versa),
    a sessão cai: salvamos o progresso (checkpoint) e, em vez de esperar um tempo fixo, **perguntamos no
    Telegram** e aguardamos o Jorge liberar (ele responde 'siafe livre' → o Yoda seta o flag). Aí RETOMAMOS
    de onde paramos. Se `coordenar=False`, cai no modo de espera fixa (`espera_fallback_s`).
    """
    _sleep = _sleep or asyncio.sleep
    try:
        from compliance_agent import siafe_coord
    except Exception:
        siafe_coord = None
    _aguardar = _aguardar or (siafe_coord.aguardar_liberacao if (siafe_coord and coordenar) else None)

    async def _esperar(motivo):
        if _aguardar:
            # roda o aguardar (bloqueante) numa thread para não travar o loop async
            await asyncio.to_thread(_aguardar, motivo)
            if siafe_coord:
                siafe_coord.set_status("coletor_rodando", "varredura em curso")
        else:
            await _sleep(espera_fallback_s)

    vistos, linhas, _ = _ckpt_load(exercicio)
    # antes de logar (e derrubar o Jorge), se ele marcou 'ocupado', pergunta e aguarda liberar
    if siafe_coord and coordenar and siafe_coord.get_status() == "ocupado":
        await _esperar("preciso iniciar a varredura, mas o flag está 'ocupado'")
    ultimo = len(linhas)
    for tentativa in range(1, max_tentativas + 1):
        try:
            res = await coletar(exercicio, maxn, headless=headless, vistos=vistos, linhas=linhas)
        except SessaoPerdida as e:
            print(f"[resiliente] sessão perdida ({e}). {len(linhas)} OBs salvas. Coordenando via Telegram...", flush=True)
            await _esperar(f"fui desconectado no meio da varredura (já tenho {len(linhas)} OBs)")
            continue
        if not res.get("ok"):
            if res.get("erro") == "mfa":
                if siafe_coord:
                    siafe_coord.notificar("🔐 SIAFE pediu MFA na varredura — me mande o código, Mestre Jorge.")
                return {"ok": False, "erro": "mfa", "n": len(linhas),
                        "detail": "SIAFE pediu MFA — preciso do código do Mestre Jorge."}
            print(f"[resiliente] falha '{res.get('etapa')}' ({res.get('erro') or res.get('detail')}). Coordenando...", flush=True)
            await _esperar(f"falhei na etapa '{res.get('etapa')}' do SIAFE")
            continue
        if len(linhas) >= maxn:
            return {"ok": True, "completo": False, "exercicio": exercicio,
                    "header": res.get("header", []), "n": len(linhas), "linhas": linhas}
        # passada concluiu sem perder sessão → varredura completa
        return {"ok": True, "completo": True, "exercicio": exercicio,
                "header": res.get("header", []), "n": len(linhas), "linhas": linhas}
    return {"ok": False, "erro": "max_tentativas", "n": len(linhas), "linhas": linhas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int, default=2025)
    ap.add_argument("--max", type=int, default=300)
    a = ap.parse_args()
    res = asyncio.run(coletar(a.exercicio, a.max))
    if not res.get("ok"):
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"OK — {res['n']} OBs colhidas (exercício {res['exercicio']})")
    print("HEADER:", res["header"])
    for r in res["linhas"][:5]:
        print("  ", r[:10])


if __name__ == "__main__":
    main()
