#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEI-RJ — reader AUTENTICADO da VM (login itkava + Pesquisa interna), na MESMA sessão.

PROVADO ao vivo (2026-06-06): da própria VM, com Chromium real + retry (vence o WAF de fingerprint),
loga como itkava/ITERJ SEM captcha e — clicando os LINKS internos do app (não URL crua) — chega à
Pesquisa autenticada com a sessão intacta (unidade ITERJ/CHEGAB confirmada). Base p/ o Lex ler a íntegra
real do SEI direto da VM, sem proxy/Actions.

Fluxo: login (form txtUsuario/#pwdSenha/#selOrgao→ITERJ + ACESSAR, retry+backoff) → clicar "Pesquisa
Rápida" → buscar o processo. FALTA (próximo passo bounded): trocar p/ o protocolo EXATO
(#txtProtocoloPesquisa na pesquisa avançada), abrir o processo (procedimento_trabalhar) e extrair a árvore
de documentos reaproveitando os extractors de `compliance_agent/collectors/sei_cdp.py`, gravando em
data/sei_cache/cdp_<proc>.json (Lex consome 24h).

Uso: python tools/sei_reader.py "SEI-070002/008633/2022"
"""
from __future__ import annotations
import asyncio
import os
import re
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from compliance_agent.envfile import carregar_env
carregar_env()

URL = os.environ.get("SEI_LOGIN_URL") or \
    "https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ&sigla_sistema=SEI&infra_url=L3NlaS8="
U, P, ORG = os.environ.get("SEI_USER", "itkava"), os.environ.get("SEI_PASS", ""), os.environ.get("SEI_ORGAO", "iterj")


async def _goto_retry(pg, url, n=8):
    for _ in range(n):
        try:
            r = await pg.goto(url, wait_until="domcontentloaded", timeout=20000); return r.status if r else None
        except Exception:
            await pg.wait_for_timeout(2500)
    return None


async def login(pg, tentativas=40) -> bool:
    """Loga no SEI interno (itkava/ITERJ) vencendo o flap do WAF. Retorna True se autenticou."""
    for _ in range(tentativas):
        if not await _goto_retry(pg, URL, 3):
            continue
        form = await pg.evaluate(r"""()=>{const q=s=>document.querySelector(s);const o=q('#selOrgao')||q('select');
          return {user:!!q('input[name="txtUsuario"]'),pwd:!!q('#pwdSenha'),opts:o?[...o.options].map(x=>({v:x.value,t:(x.text||'').trim()})):[]};}""")
        if not form["user"] or not form["pwd"]:
            await pg.wait_for_timeout(2000); continue
        await pg.fill('input[name="txtUsuario"]', U)
        try: await pg.fill('#pwdSenha', P)
        except Exception: pass
        await pg.evaluate(r"""(p)=>{document.querySelectorAll('#pwdSenha,input[name=\"pwdSenha\"]').forEach(e=>e.value=p);}""", P)
        cand = [o for o in form["opts"] if re.search(r"\biterj\b|terras", o["t"], re.I)]
        if cand:
            await pg.select_option('#selOrgao', value=cand[0]["v"])
        await pg.evaluate(r"""()=>{const b=[...document.querySelectorAll('button,input[type=submit],a')].find(e=>/acessar|entrar|logar/i.test((e.value||e.innerText||'').trim()));if(b)b.click();}""")
        await pg.wait_for_timeout(6000)
        if "login.php" not in pg.url:
            return True
        await pg.wait_for_timeout(1500)
    return False


async def abrir_pesquisa(pg) -> bool:
    """Clica a Pesquisa interna (clique real preserva os tokens de sessão). Retorna True se chegou na busca."""
    await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a,area,img')].find(x=>/pesquis/i.test((x.id||'')+' '+(x.title||'')+' '+(x.innerText||'')+' '+(x.getAttribute&&x.getAttribute('onclick')||'')));if(e)e.click();}""")
    await pg.wait_for_timeout(5000)
    return "#pwdSenha" not in ((await pg.content()) or "")


CACHE_DIR = _REPO / "data" / "sei_cache"


async def _extrair_de_todos_frames(pg) -> dict:
    """Roda o extractor da árvore/texto em TODOS os frames (o SEI usa iframes ifrArvore/ifrVisualizacao)."""
    from compliance_agent.collectors.sei_cdp import _JS_LE_ARVORE_E_TEXTO
    docs, rel, textos = {}, {}, []
    cadeado = False
    for fr in pg.frames:
        try:
            d = await fr.evaluate(_JS_LE_ARVORE_E_TEXTO)
        except Exception:
            continue
        for doc in d.get("documentos", []):
            if doc.get("url"):
                docs[doc["url"]] = doc
        for r in d.get("relacionados", []):  # processos relacionados (cadeia licitação↔contrato↔pagamento)
            if r.get("url"):
                rel[r["url"]] = r
        cadeado = cadeado or bool(d.get("cadeado"))  # cadeado de acesso restrito em qualquer frame
        if d.get("texto") and len(d["texto"]) > 80:
            textos.append(d["texto"])
    docs_l = list(docs.values())
    return {"documentos": docs_l, "relacionados": list(rel.values()), "cadeado": cadeado,
            "n_docs_restritos": sum(1 for d in docs_l if d.get("restrito")),
            "texto": "\n\n".join(textos)[:20000]}


async def seguir_relacionados(pg, proc_url: str, relacionados: list, max_rel: int = 5) -> list[dict]:
    """Abre cada processo RELACIONADO (na MESMA sessão, URL viva) e extrai a árvore. Reusado pelo
    ler_com_cadeia E pelo sweep — o processo de pagamento aponta p/ a licitação/contrato (a substância
    vive no relacionado). Dedup por id_procedimento; pula o próprio processo. Honesto: erro por relacionado."""
    vistos: set = set()
    alvos: list = []
    for r in (relacionados or []):
        url = r.get("url") or ""
        pid = _id_proc(url)
        if pid and pid not in vistos and f"id_procedimento={pid}" not in (proc_url or ""):
            vistos.add(pid)
            alvos.append((pid, url, r.get("titulo") or r.get("texto") or ""))
        if len(alvos) >= max_rel:
            break
    cadeia: list = []
    for pid, url, titulo in alvos:
        try:
            await pg.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                await pg.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            for _ in range(8):  # espera ATIVA a árvore (ifrArvore) carregar
                await pg.wait_for_timeout(1500)
                if any("arvore" in (fr.url or "").lower() for fr in pg.frames):
                    await pg.wait_for_timeout(1500)
                    break
            dump = await _extrair_de_todos_frames(pg)
            txt = dump.get("texto", "")
            cadeia.append({
                "id_procedimento": pid, "titulo_rel": titulo[:80], "url": url[:90],
                "n_docs": len(dump.get("documentos", [])), "n_texto": len(txt),
                "eh_licitacao": eh_licitacao(txt),
                "documentos": dump.get("documentos", [])[:30], "texto": txt,
            })
        except Exception as e:  # noqa: BLE001
            cadeia.append({"id_procedimento": pid, "erro": str(e)[:100]})
    return cadeia


async def ler_processo(pg, proc: str, usar_cache: bool = True) -> dict:
    """Busca o processo na pesquisa autenticada, abre e extrai a íntegra (árvore + docs). Grava cdp_*.json."""
    import json as _json
    from datetime import datetime
    from compliance_agent.collectors.sei_cdp import _abrir_primeiro_resultado
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    if usar_cache and cache_file.exists():
        try:
            c = _json.loads(cache_file.read_text(encoding="utf-8"))
            if c.get("_cached_at") and (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < 86400:
                c["_de_cache"] = True; return c
        except Exception:
            pass
    # navega p/ a Pesquisa AVANÇADA (menu "Pesquisa") — clique REAL preserva a sessão
    await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
    await pg.wait_for_timeout(5000)
    tem_avancada = await pg.evaluate("""()=>!!document.querySelector('#txtProtocoloPesquisa,input[name="txtProtocoloPesquisa"]')""")
    if tem_avancada:
        # protocolo EXATO: fill; se o ADF não aceitar, keyboard.type (keystrokes reais)
        try: await pg.fill('#txtProtocoloPesquisa', proc)
        except Exception: pass
        if not await pg.evaluate("""()=>{const e=document.querySelector('#txtProtocoloPesquisa');return e?e.value:''}"""):
            try:
                await pg.click('#txtProtocoloPesquisa'); await pg.keyboard.type(proc, delay=40)
            except Exception: pass
        # itkava acessa TODAS as unidades, mas a avançada vem com "Restringir ao Órgão da Unidade" MARCADO →
        # processo de outra unidade dá 0 resultados. DESMARCAR p/ busca GLOBAL (lição 2026-06-12).
        await pg.evaluate(r"""()=>{document.querySelectorAll('input[type=checkbox]').forEach(c=>{const l=((c.id||'')+' '+(c.name||'')+' '+(c.parentElement?(c.parentElement.innerText||''):'')).toLowerCase();if(/restring|unidade\s+do\s+[óo]rg|[óo]rg[ãa]o\s+da\s+unidade/.test(l)&&c.checked){try{c.click();}catch(e){}}});}""")
        # SUBMIT robusto: o clique-por-texto às vezes não dispara o form do SEI. Tenta botão por id/valor,
        # submit() do form, e Enter no campo (lição 2026-06-12: a busca ficava parada no FORM).
        await pg.evaluate(r"""()=>{
          const byId=document.querySelector('#sbmPesquisar,#sbmProtocoloPesquisa,#btnPesquisar,input[name="sbmPesquisar"]');
          if(byId){byId.click();return 'id';}
          const b=[...document.querySelectorAll('button,input[type=submit],input[type=button]')].find(e=>/pesquisar/i.test((e.value||e.innerText||'')));
          if(b){b.click();return 'txt';}
          const f=document.querySelector('#frmProtocoloPesquisa,form[name="frmProtocoloPesquisa"],form[action*="protocolo_pesquisar"]');
          if(f){f.submit();return 'form';}
          return 'none';
        }""")
        try:
            await pg.click('#txtProtocoloPesquisa'); await pg.keyboard.press('Enter')
        except Exception: pass
    else:
        # fallback: pesquisa rápida (escopo da unidade)
        await pg.evaluate(r"""(n)=>{const i=document.querySelector('#txtPesquisaRapida');if(i){i.value=n;const f=document.getElementById('frmProtocoloPesquisaRapida');if(f)f.submit();}}""", proc)
    try: await pg.wait_for_load_state("networkidle", timeout=15000)
    except Exception: pass
    await pg.wait_for_timeout(4000)
    await _abrir_primeiro_resultado(pg)
    await pg.wait_for_timeout(3000)
    dump = await _extrair_de_todos_frames(pg)
    res = {"numero": proc, "url": pg.url, "documentos": dump["documentos"],
           "relacionados": dump.get("relacionados", []), "cadeado": dump.get("cadeado", False),
           "n_docs_restritos": dump.get("n_docs_restritos", 0), "texto": dump["texto"],
           "captcha_resolvido": False, "_login": {"ok": True, "via": "sei_reader/itkava"}}
    # conteúdo dos primeiros documentos
    docs_txt = []
    for doc in dump["documentos"][:8]:
        try:
            await pg.goto(doc["url"], wait_until="domcontentloaded", timeout=20000)
            await pg.wait_for_timeout(900)
            t = await pg.evaluate("()=>document.body?document.body.innerText.slice(0,6000):''")
            if t and len(t) > 50:
                docs_txt.append({"doc": (doc.get("texto") or "")[:80], "conteudo": t})
        except Exception:
            continue
    res["conteudo_documentos"] = docs_txt
    tot = res["texto"] + "\n\n" + "\n\n".join(d["conteudo"] for d in docs_txt)
    res["cnpjs"] = sorted(set(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", tot)))
    res["valores"] = sorted(set(re.findall(r"R\$\s*[\d.,]+", tot)))
    res["_cached_at"] = datetime.now().isoformat()
    try:
        cache_file.write_text(_json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        res["_cache_path"] = str(cache_file)
    except Exception:
        pass
    return res


async def ler(numero: str, usar_cache: bool = True, tentativas_login: int = 30) -> dict:
    """READER SEI CANÔNICO (login itkava/ITERJ, SEM captcha) — única porta de leitura do SEI.

    PADRÃO do `numero` (processo SEI-RJ): `SEI-UUUUUU/NNNNNN/AAAA` = unidade/sequencial/ano —
    ex.: `SEI-070002/008633/2022`. Também aceita a forma curta `E-NN/NNN/AAAA` (ex.: `E-12/345/2026`)
    e com/sem o prefixo `SEI-`. É o protocolo EXATO digitado na Pesquisa Avançada do SEI.

    Uso:
        from tools.sei_reader import ler
        integra = await ler("SEI-070002/008633/2022")     # ou: await ler("E-12/345/2026")
    CLI:  PYTHONPATH=. .venv/bin/python -m tools.sei_reader "SEI-070002/008633/2022"

    Lança Chromium, autentica como itkava, abre a pesquisa e lê o processo, devolvendo a íntegra
    {numero, texto, documentos, conteudo_documentos, cnpjs, valores, erro?}. Cache 24h
    (data/sei_cache/cdp_*.json). Honesto: SEI_PASS vazio ou login não vencido => {erro INDISPONÍVEL},
    nunca conteúdo fabricado. Requer SEI_PASS no .env e Chromium (Playwright) instalado.
    """
    import json as _json
    from datetime import datetime

    cache_file = CACHE_DIR / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', numero)}.json"
    if usar_cache and cache_file.exists():
        try:
            c = _json.loads(cache_file.read_text(encoding="utf-8"))
            if c.get("_cached_at") and (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < 86400:
                c["_de_cache"] = True
                return c
        except Exception:
            pass
    if not P:
        return {"numero": numero, "erro": "INDISPONÍVEL: SEI_PASS vazio (.env)", "texto": "", "conteudo_documentos": []}
    try:
        # guarda de recurso (VM 2 cores): cede se o load está alto e serializa com o sweep SIAFE
        # (browser_lock) — nunca 2 browsers ao mesmo tempo (já derrubou a sessão). Aditivo/honesto:
        # se não houver folga/lock em tempo hábil, devolve INDISPONÍVEL em vez de crashar a VM.
        from compliance_agent.recursos import browser_lock_async, aguardar_load_async
        await aguardar_load_async(max_por_core=1.5, espera_max=90)
        from playwright.async_api import async_playwright
        # Proxy permitido (opção B p/ furar o WAF do SEI a partir da VM): SEI_PROXY_URL/PROXY_URL no .env.
        # Aditivo — sem proxy, launch idêntico ao de antes. Reusa o parser do sei_cdp (host/credenciais).
        from compliance_agent.collectors.sei_cdp import _proxy_do_env
        _proxy = _proxy_do_env()
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": _proxy} if _proxy else {}))
            ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    return {"numero": numero, "texto": "", "conteudo_documentos": [],
                            "erro": "INDISPONÍVEL: login itkava não autenticou (WAF/credencial)"}
                return await ler_processo(pg, numero, usar_cache=usar_cache)
            finally:
                await b.close()
    except Exception as e:  # noqa: BLE001
        return {"numero": numero, "texto": "", "conteudo_documentos": [],
                "erro": f"sei_reader/itkava: {str(e)[:140]}"}


# ── Seguir a CADEIA de processos relacionados (execução → licitação) ───────────
_MARK_LICITACAO = ("edital", "atestado", "qualificac", "habilitac", "pregao", "pregão", "licitac",
                   "termo de referencia", "termo de referência", "ata de registro", "concorrencia",
                   "concorrência", "julgamento", "desclassific", "inabilit", "proposta de preco")


def _id_proc(url: str) -> str:
    m = re.search(r"id_procedimento=(\d+)", url or "")
    return m.group(1) if m else ""


def eh_licitacao(texto: str) -> bool:
    """Heurística: o texto do processo parece uma LICITAÇÃO (edital/ata/atestado), não execução."""
    low = (texto or "").lower()
    return sum(low.count(k) for k in _MARK_LICITACAO) >= 3


async def ler_com_cadeia(numero: str, *, max_rel: int = 5, tentativas_login: int = 30) -> dict:
    """Lê um processo E SEGUE a cadeia de processos RELACIONADOS (na MESMA sessão — a URL do relacionado
    extraída agora tem hash válido p/ `goto`). Resolve o caso real: a OB aponta p/ a EXECUÇÃO; a LICITAÇÃO
    (edital/ata) vive num processo relacionado. Devolve {processo, cadeia:[{id,url,n_docs,eh_licitacao,
    texto,refs}]}. Guarda de recurso (não crashar a VM). Honesto: erros reportados, nunca fabricados."""
    if not P:
        return {"numero": numero, "erro": "INDISPONÍVEL: SEI_PASS vazio (.env)"}
    out: dict = {"numero": numero, "cadeia": []}
    try:
        from compliance_agent.recursos import browser_lock_async, aguardar_load_async
        await aguardar_load_async(max_por_core=1.5, espera_max=90)
        from playwright.async_api import async_playwright
        # Proxy permitido (opção B p/ furar o WAF do SEI a partir da VM): SEI_PROXY_URL/PROXY_URL no .env.
        # Aditivo — sem proxy, launch idêntico ao de antes. Reusa o parser do sei_cdp (host/credenciais).
        from compliance_agent.collectors.sei_cdp import _proxy_do_env
        _proxy = _proxy_do_env()
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": _proxy} if _proxy else {}))
            ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    return {"numero": numero, "erro": "INDISPONÍVEL: login itkava não autenticou"}
                # busca→abrir do SEI é INTERMITENTE (Onda 1) — retry até abrir (relacionados/docs > 0)
                proc = {}
                for tentativa in range(3):
                    proc = await ler_processo(pg, numero, usar_cache=False)
                    if (proc.get("relacionados") or proc.get("documentos")):
                        break
                    out.setdefault("tentativas_abertura", 0)
                    out["tentativas_abertura"] += 1
                    await pg.wait_for_timeout(2000)
                out["processo"] = {k: proc.get(k) for k in ("numero", "url", "documentos", "relacionados",
                                                             "cnpjs", "valores", "motivo_zero")}
                # segue a ÁRVORE de relacionados (função compartilhada com o sweep)
                out["cadeia"] = await seguir_relacionados(pg, proc.get("url") or "",
                                                          proc.get("relacionados") or [], max_rel=max_rel)
                return out
            finally:
                await b.close()
    except Exception as e:  # noqa: BLE001
        out["erro"] = f"ler_com_cadeia: {str(e)[:140]}"
        return out


async def main():
    from playwright.async_api import async_playwright
    proc = sys.argv[1] if len(sys.argv) > 1 else "SEI-070002/008633/2022"
    if not P:
        print("SEI_PASS vazio"); return
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        if not await login(pg):
            print("FALHOU login"); await b.close(); return
        print("✅ LOGADO:", pg.url[:80], flush=True)
        print("→ Lendo processo (pesquisa avançada):", proc, flush=True)
        res = await ler_processo(pg, proc, usar_cache=False)
        print(f"   docs: {len(res.get('documentos',[]))} | texto: {len(res.get('texto',''))} chars "
              f"| conteúdo docs: {len(res.get('conteudo_documentos',[]))} | CNPJs: {len(res.get('cnpjs',[]))} "
              f"| valores: {len(res.get('valores',[]))}")
        print("   cache:", res.get("_cache_path", "(não salvo)"))
        print("   amostra texto:", (res.get("texto", "")[:300] or "(vazio)").replace("\n", " "))
        if os.environ.get("SEI_DEBUG_SHOT"):
            try:
                await pg.screenshot(path=os.environ["SEI_DEBUG_SHOT"], full_page=True)
                # também salva os frames p/ diagnóstico
                fr = [{"name": f.name, "url": f.url[:90]} for f in pg.frames]
                print("   FRAMES:", fr)
                print("   SHOT:", os.environ["SEI_DEBUG_SHOT"])
            except Exception as e:
                print("   shot erro:", e)
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
