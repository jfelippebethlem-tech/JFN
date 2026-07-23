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
import logging
import os
import re
import sys
from pathlib import Path

from playwright.async_api import Error as PWError
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from compliance_agent.envfile import carregar_env
carregar_env()

logger = logging.getLogger(__name__)

URL = os.environ.get("SEI_LOGIN_URL") or \
    "https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ&sigla_sistema=SEI&infra_url=L3NlaS8="
U, P, ORG = os.environ.get("SEI_USER", "itkava"), os.environ.get("SEI_PASS", ""), os.environ.get("SEI_ORGAO", "iterj")
# TTL do cache de leitura (antes hardcoded 86400 em 3 pontos): processo em ebulição (sessão
# marcada amanhã) pode pedir SEI_CACHE_TTL menor sem tocar código.
CACHE_TTL = int(os.environ.get("SEI_CACHE_TTL", "86400"))


async def _ate(pg, cond, max_ms: int = 6000, passo: int = 250) -> bool:
    """Espera EVENT-BASED com teto: retorna assim que ``cond()`` (async) vira True.
    Teto = o sleep fixo antigo → pior caso idêntico, caso típico segundos mais rápido
    (lição scrapling 2026-06: o ganho real é trocar wait_for_timeout por condição)."""
    gasto = 0
    while gasto < max_ms:
        try:
            if await cond():
                return True
        except Exception as exc:
            logger.debug("sondagem da condição de espera falhou: %s", exc)
        await pg.wait_for_timeout(passo)
        gasto += passo
    return False


async def _goto_retry(pg, url, n=8):
    for _ in range(n):
        try:
            r = await pg.goto(url, wait_until="domcontentloaded", timeout=20000); return r.status if r else None
        except PWError:
            await pg.wait_for_timeout(2500)
    return None


async def _sair_do_login(pg) -> bool:
    return "login.php" not in (pg.url or "")


async def _tem_campo_protocolo(pg) -> bool:
    return bool(await pg.evaluate(
        """()=>!!document.querySelector('#txtProtocoloPesquisa,input[name="txtProtocoloPesquisa"]')"""))


async def _tem_resultado_ou_arvore(pg) -> bool:
    """Pós-submit da pesquisa: True quando a lista de resultados OU a árvore (ifrArvore) já pintou."""
    if any("arvore" in (fr.url or "").lower() or fr.name == "ifrArvore" for fr in pg.frames):
        return True
    return bool(await pg.evaluate(
        r"""()=>!!document.querySelector('a[href*="procedimento_trabalhar"],#tblResultado,table.resultado,#conteudo table')"""))


def escolher_orgao(opcoes: list[dict], pedido: str | None) -> str | None:
    """Valor do `#selOrgao` para o órgão `pedido` — ou o ITERJ (padrão histórico).

    O SEI só serve o TEOR de documentos do órgão da sessão; para os demais devolve a
    lista de órgãos (que o coletor capturava como se fosse o documento). Poder escolher
    o órgão é o que destrava a leitura cross-unit — o itkava enxerga todos.

    Pedido inválido NÃO derruba o login: cai no padrão. Sem o padrão na lista, devolve
    None (não escolher é mais honesto que escolher o órgão errado).
    """
    def _casa(texto: str, alvo: str) -> bool:
        # \b para não casar SES dentro de SESPORT
        return bool(re.search(rf"\b{re.escape(alvo)}\b", texto or "", re.I))

    if pedido:
        for o in opcoes:
            if _casa(o.get("t", ""), pedido.strip()):
                return o.get("v")
    for o in opcoes:
        if re.search(r"\biterj\b|terras", o.get("t", ""), re.I):
            return o.get("v")
    return None


async def login(pg, tentativas=40, orgao: str | None = None) -> bool:
    """Loga no SEI interno (itkava) vencendo o flap do WAF. Retorna True se autenticou.

    `orgao` escolhe a unidade da sessão (sigla ou parte do nome). Sem ele, ITERJ —
    comportamento histórico dos 18 chamadores existentes."""
    for _ in range(tentativas):
        if not await _goto_retry(pg, URL, 3):
            continue
        form = await pg.evaluate(r"""()=>{const q=s=>document.querySelector(s);const o=q('#selOrgao')||q('select');
          return {user:!!q('input[name="txtUsuario"]'),pwd:!!q('#pwdSenha'),opts:o?[...o.options].map(x=>({v:x.value,t:(x.text||'').trim()})):[]};}""")
        if not form["user"] or not form["pwd"]:
            await pg.wait_for_timeout(2000); continue
        await pg.fill('input[name="txtUsuario"]', U)
        try: await pg.fill('#pwdSenha', P)
        except Exception as exc: logger.debug("fill do #pwdSenha falhou (fallback via evaluate): %s", exc)
        await pg.evaluate(r"""(p)=>{document.querySelectorAll('#pwdSenha,input[name=\"pwdSenha\"]').forEach(e=>e.value=p);}""", P)
        valor = escolher_orgao(form["opts"], orgao)
        if valor:
            await pg.select_option('#selOrgao', value=valor)
        await pg.evaluate(r"""()=>{const b=[...document.querySelectorAll('button,input[type=submit],a')].find(e=>/acessar|entrar|logar/i.test((e.value||e.innerText||'').trim()));if(b)b.click();}""")
        await _ate(pg, lambda: _sair_do_login(pg), 6000)
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
    # Assinatura do FRAMESET DO MENU do SEI (barra lateral do itkava): 2+ itens de menu no innerText.
    # Sem esse guard, o `texto` do processo vinha poluído com "GOVERNO DO ESTADO… Base de Conhecimento Blocos…"
    # (a casca do menu), não o conteúdo do processo/doc. Fix 2026-07-09.
    _MENU_SIG = ("Base de Conhecimento", "Controle de Processos", "Pontos de Controle",
                 "Processos Sobrestados", "Acompanhamento Especial")
    for fr in pg.frames:
        try:
            d = await fr.evaluate(_JS_LE_ARVORE_E_TEXTO)
        except PWError:
            continue
        for doc in d.get("documentos", []):
            if doc.get("url"):
                docs[doc["url"]] = doc
        for r in d.get("relacionados", []):  # processos relacionados (cadeia licitação↔contrato↔pagamento)
            if r.get("url"):
                rel[r["url"]] = r
        cadeado = cadeado or bool(d.get("cadeado"))  # cadeado de acesso restrito em qualquer frame
        txt = d.get("texto") or ""
        eh_menu = sum(s in txt for s in _MENU_SIG) >= 2  # frameset do menu → não é conteúdo do processo
        if txt and len(txt) > 80 and not eh_menu:
            textos.append(txt)
    # arvore_vista = algum frame tem a árvore de documentos (infraArvoreNo) — é O sinal de "processo
    # ABERTO de fato". Sem ele, 0 docs = leitura que caiu na CAIXA/desktop, não processo vazio.
    # Necessário desde o filtro do menu no sei_cdp (2026-07-09): a caixa deixou de vir com rel~40,
    # então a heurística rel>=15 dos consumidores ficou cega p/ a caixa. Fix 2026-07-10.
    arvore_vista = False
    for fr in pg.frames:
        try:
            if "infraArvoreNo" in await fr.content():
                arvore_vista = True
                break
        except PWError:
            continue
    # AUTORIDADE: completa com os nós do HTML-FONTE da árvore (o DOM é virtualizado e subconta —
    # ver arvore_do_fonte). Merge por id_documento: o fonte traz TODOS; o DOM fica como fallback.
    if arvore_vista:
        try:
            def _idd(u):
                m = re.search(r"id_documento=(\d+)", u or ""); return m.group(1) if m else u
            vistos = {_idd(u) for u in docs}
            for doc in await arvore_do_fonte(pg):
                if _idd(doc["url"]) not in vistos:
                    docs[doc["url"]] = doc
        except Exception as exc:
            logger.debug("merge arvore_do_fonte falhou (segue só com DOM): %s", exc)
    docs_l = list(docs.values())
    return {"documentos": docs_l, "relacionados": list(rel.values()), "cadeado": cadeado,
            "n_docs_restritos": sum(1 for d in docs_l if d.get("restrito")),
            "arvore_vista": arvore_vista,
            "texto": "\n\n".join(textos)[:20000]}


def _grava_cache_atomico(cache_file, res: dict) -> None:
    """Grava o cdp_*.json ATÔMICO (tmp+rename por PID). write_text direto deixava JSON RASGADO
    quando o processo era morto por timeout no meio do write (o refichar flagrou 'JSON inválido'
    em caches de 06/22-jun). Fix 2026-07-10."""
    import json as _json
    tmp = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
    tmp.write_text(_json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(cache_file)


def _dec_sei(body: bytes) -> str:
    """Decodifica resposta do SEI: tenta UTF-8 estrito; se estourar, latin-1 (o SEI mistura os dois)."""
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("latin-1", "replace")


def _parse_nos_arvore(html: str) -> list[dict]:
    """Parseia TODOS os ``new infraArvoreNo(tipo,id,pai,url,alvo,titulo,titulo2,icone,...)`` de um HTML
    da árvore/pasta do SEI. Tokenizador ciente de strings (args podem ser ``null`` e títulos podem ter
    aspas escapadas — o regex simples só casava nós 100% string, 5 de 73). Retorna docs no formato do
    extractor de DOM ({texto,titulo,url,restrito}) só dos nós tipo DOCUMENTO."""
    docs = []
    for m in re.finditer(r'new\s+infraArvoreNo\(', html):
        i = m.end(); depth = 1; args = []; cur = ""; instr = False; esc = False
        while i < len(html) and depth > 0 and len(args) < 16:
            ch = html[i]
            if instr:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': instr = False
                cur += ch
            else:
                if ch == '"': instr = True; cur += ch
                elif ch == '(': depth += 1; cur += ch
                elif ch == ')':
                    depth -= 1
                    if depth == 0: args.append(cur.strip()); break
                    cur += ch
                elif ch == ',' and depth == 1: args.append(cur.strip()); cur = ""
                else: cur += ch
            i += 1
        def _unq(s):
            s = (s or "").strip()
            return s[1:-1].replace('\\"', '"').replace("\\/", "/") if s.startswith('"') else None
        if len(args) < 7:
            continue
        tipo = (_unq(args[0]) or "").upper()
        url = _unq(args[3]) or ""
        titulo = _unq(args[6]) or _unq(args[5]) or ""
        icones = " ".join(a for a in args[7:11] if a and a != "null")
        if tipo != "DOCUMENTO" or "id_documento=" not in url:
            continue
        full = url if url.startswith("http") else ("https://sei.rj.gov.br/sei/" + url.lstrip("/"))
        docs.append({"texto": titulo[:120], "titulo": titulo[:160], "url": full,
                     "restrito": bool(re.search(r"cadeado|restrit|sigilo", icones, re.I))})
    return docs


async def arvore_do_fonte(pg) -> list[dict]:
    """AUTORIDADE da árvore (fix 2026-07-09), 100% HTTP pela MESMA sessão itkava — zero DOM, zero timing.

    Por que: o DOM da árvore é VIRTUALIZADO (renderiza ~10 nós de 73) e as PASTAS são LAZY-LOAD — o HTML
    inicial só traz docs fora de pasta + placeholders AGUARDE (provado no túnel SEI-460001/000779/2023:
    DOM=10 âncoras, fonte=73 nós, 34 pastas fechadas; ``Nos[]`` é INACESSÍVEL ao evaluate). Raspar DOM ou
    parsear só o HTML inicial SUBCONTA docs — era a causa-raiz do "5 docs de 34" e do sweep flaky.

    Como: (1) HTML VIVO do frame da árvore via ``fr.content()`` (sessão autenticada, ``infra_hash`` fresco —
    um GET novo pode re-renderizar/expirar o hash) → parseia os nós soltos; (2) as pastas lazy-load são
    expandidas pelo LOADER NATIVO do SEI no browser (``_expandir_pastas_e_ler``; replicar o POST
    ``procedimento_paginar`` às cegas é frágil) e lidas do DOM materializado. Dedup por id_documento.
    Devolve docs no formato do extractor de DOM p/ merge transparente."""
    for fr in pg.frames:
        # detecta o frame da árvore por CONTEÚDO (tem 'infraArvoreNo') — nome/URL do frame variam
        try:
            html = await fr.content()
        except PWError:
            continue
        if "infraArvoreNo" not in html:
            continue
        docs = {d["url"]: d for d in _parse_nos_arvore(html)}
        n_pastas = len(re.findall(r"Pastas\[\d+\]\['link'\]", html))
        if n_pastas:
            # A árvore é PAGINADA em PASTAS lazy-load. A carga é um POST (procedimento_paginar) que só
            # monta com os hidden hdnArvore/hdnPastaAtual/hdnProtocolos — replicar o POST às cegas é
            # frágil. O robusto é usar o LOADER NATIVO do SEI no browser (abrirFecharPasta), que dispara
            # o XHR correto (provado 2026-07-09: DOM 10→35 âncoras), esperar os 'Aguarde...' resolverem e
            # ler as âncoras já materializadas no DOM. Fica 100% na sessão itkava, sem forjar requisição.
            got = await _expandir_pastas_e_ler(fr)
            for d in got:
                docs.setdefault(d["url"], d)
        if docs:
            def _idd(x):
                mm = re.search(r"id_documento=(\d+)", x); return mm.group(1) if mm else x
            uniq = {}
            for d in docs.values():
                uniq.setdefault(_idd(d["url"]), d)
            return list(uniq.values())
    return []


_JS_EXPANDE_PASTAS = r"""async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // ids de pasta: dos hidden Pastas[] (fonte) ou dos onclick abrirFecharPasta
  let ids = [];
  try { const m = document.documentElement.innerHTML.match(/Pastas\[(\d+)\]\['link'\]/g) || [];
        ids = [...new Set(m.map(s => 'PASTA' + s.match(/\d+/)[0]))]; } catch (e) {}
  if (!ids.length) document.querySelectorAll("[onclick*='abrirFecharPasta']").forEach(el => {
      const mm = (el.getAttribute('onclick') || '').match(/abrirFecharPasta\('([^']+)'\)/); if (mm) ids.push(mm[1]); });
  ids = [...new Set(ids)].sort((a, b) => (+a.slice(5)) - (+b.slice(5)));
  let chamou = 0;
  for (const id of ids) {
    try {
      if (typeof abrirFecharPasta === 'function') { abrirFecharPasta(id); chamou++; }
      else if (typeof objArvore !== 'undefined' && objArvore.processarNoJuncao) { objArvore.processarNoJuncao(id.substring(5)); chamou++; }
    } catch (e) {}
    await sleep(150);
    for (let i = 0; i < 40; i++) { if (!document.body.innerText.includes('Aguarde...')) break; await sleep(300); }
  }
  const out = [];
  for (const a of document.querySelectorAll('a[href*="id_documento="]')) {
    const t = (a.textContent || a.title || '').trim();
    if (t) out.push({ t: t.slice(0, 160), u: a.href });
  }
  return { chamou, docs: out };
}"""


async def _expandir_pastas_e_ler(fr) -> list[dict]:
    """Aciona o loader nativo do SEI (``abrirFecharPasta``) em cada pasta da árvore, espera os
    placeholders 'Aguarde...' resolverem e devolve os documentos já materializados no DOM.
    Formato de doc idêntico ao extractor ({texto,titulo,url,restrito})."""
    try:
        res = await fr.evaluate(_JS_EXPANDE_PASTAS)
    except PWError as exc:
        logger.debug("_expandir_pastas_e_ler: evaluate falhou: %s", exc)
        return []
    docs = []
    for a in (res or {}).get("docs", []):
        docs.append({"texto": (a.get("t") or "")[:120], "titulo": (a.get("t") or "")[:160],
                     "url": a.get("u") or "", "restrito": False})
    logger.debug("_expandir_pastas_e_ler: chamou=%s docs=%s", (res or {}).get("chamou"), len(docs))
    return docs


async def abrir_processo(pg, proc: str, tentativas: int = 4):
    """Abre o processo e GARANTE a árvore viva — com retry (o 1º submit às vezes é comido pelo ADF;
    provado ao vivo 2026-07-09: tent 0 falha, tent 1–2 abrem). Detecta a árvore por CONTEÚDO
    (``infraArvoreNo`` no HTML do frame), não por nome/URL. Retorna o frame da árvore ou None."""
    for _ in range(tentativas):
        try:
            await _ler_cracked(pg, proc)
        except Exception as exc:
            logger.debug("abrir_processo: cracked falhou p/ %s: %s", proc, exc)
        await pg.wait_for_timeout(1500)
        for fr in pg.frames:
            try:
                if "infraArvoreNo" in await fr.content():
                    return fr
            except PWError:
                continue
    # FALLBACK quicksearch (fix 2026-07-12): processo de OUTRA unidade (ex.: SEAS 070026, Juventude
    # 280001) que o caminho CRACKED do ITERJ vê mas não abre — a PESQUISA RÁPIDA do topo abre por
    # número completo (mesma lógica que já existe no ler() canônico). Aditivo e sem regressão: só roda
    # quando o loop cracked acima não achou a árvore; para os processos que já abriam, retorna antes.
    try:
        await _abrir_por_quicksearch(pg, proc)
        await _esperar_arvore(pg)
        for fr in pg.frames:
            try:
                if "infraArvoreNo" in await fr.content():
                    return fr
            except PWError:
                continue
    except PWError as exc:
        logger.debug("abrir_processo: quicksearch fallback falhou p/ %s: %s", proc, exc)
    return None


async def _esperar_arvore(pg, voltas: int = 16) -> bool:
    """Espera ATIVA o frame da árvore de documentos (``ifrArvore``) carregar — a árvore do SEI
    aparece num iframe e o parser precisa dela presente ANTES de extrair (lição cracked 06-12:
    'A árvore abre, mas o parser pega 0 docs se extrair cedo demais'). Retorna True se a árvore
    apareceu. Honesto: nunca trava — após ``voltas`` desiste e deixa a extração rodar com o que tem."""
    for _ in range(voltas):
        for fr in pg.frames:
            u = (fr.url or "").lower()
            if "arvore" in u or fr.name == "ifrArvore":
                # achou o frame; dá um respiro p/ os <a> dos documentos pintarem
                await pg.wait_for_timeout(2000)
                return True
        await pg.wait_for_timeout(1500)
    return False


async def _abrir_por_quicksearch(pg, proc: str) -> dict:
    """Abre o processo pela PESQUISA RÁPIDA do topo (``#txtPesquisaRapida``) com o número COMPLETO (com 'SEI-').
    É o modo canônico de abrir um processo por número no SEI — a busca AVANÇADA por 'Nº SEI' às vezes retorna 0
    resultados (cai na caixa da unidade). Espera ativa o ``ifrArvore`` e extrai de todos os frames. 3ª tentativa
    (após normal e cracked); degrada honesto (dump vazio se a caixa não existir ou nada abrir). Fix 2026-07-09."""
    numero = proc if re.match(r"(?i)^sei-", (proc or "")) else "SEI-" + re.sub(r"(?i)^sei[-\s]*", "", (proc or ""))
    try:
        preencheu = await pg.evaluate(r"""(n)=>{
          const i=document.querySelector('#txtPesquisaRapida,input[name="txtPesquisaRapida"]');
          if(!i) return false;
          i.value=n; i.focus();
          const f=document.getElementById('frmProtocoloPesquisaRapida')||i.form; if(f){/* submete no Enter */}
          return true;
        }""", numero)
        if not preencheu:
            return {"documentos": []}
        await pg.keyboard.press("Enter")
    except PWError as exc:
        logger.debug("quick-search: preencher/Enter falhou p/ %s: %s", numero, exc)
        return {"documentos": []}
    try:
        await pg.wait_for_load_state("networkidle", timeout=12000)
    except PWError as exc:
        logger.debug("quick-search: networkidle estourou p/ %s: %s", numero, exc)
    await _esperar_arvore(pg)
    await pg.wait_for_timeout(1200)
    dump = await _extrair_de_todos_frames(pg)
    dump["via"] = "quicksearch"
    dump["url"] = pg.url
    return dump


async def _ler_cracked(pg, proc: str) -> dict:
    """CAMINHO SEPARADO (anti-regressão) p/ processo de OUTRA unidade que o itkava VÊ mas a busca
    'normal' do ITERJ não abre (ex.: consórcios Vieira/MUV na 510001). NÃO toca em ``ler_processo``.

    Método CRACKED (provado por screenshot do dono 06-12): ☰ → Pesquisa →
      - radio **Processos** selecionado (não 'Documentos')
      - ☑ **Considerar Documentos**
      - **Restringir ao Órgão da Unidade** DESMARCADO + Órgão Gerador 'Todos'
      - protocolo **SEM** o prefixo 'SEI-' (ex.: ``510001/000876/2024``)
      - clicar **Pesquisar** (``#sbmPesquisar``) UMA vez e **esperar a NAVEGAÇÃO** (expect_navigation) —
        NÃO duplo-submit (clicar+Enter quebra), NÃO ``_abrir_primeiro_resultado`` (navega p/ fora da árvore).
    A árvore aparece DIRETO após Pesquisar; espera ativa o ``ifrArvore`` e extrai de todos os frames.
    Degrada honesto: marca ``cadeado``/``n_docs_restritos`` (alguns docs do processo podem ser restritos)
    e nunca inventa. Retorna o mesmo formato de dump de ``_extrair_de_todos_frames`` + ``via``/``url``."""
    proto = re.sub(r"(?i)^sei[-\s]*", "", (proc or "").strip())  # SEM prefixo 'SEI-'
    # 1) abre a Pesquisa interna (clique REAL preserva a sessão)
    await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
    await _ate(pg, lambda: _tem_campo_protocolo(pg), 5000)
    if not await _tem_campo_protocolo(pg):
        return {"documentos": [], "relacionados": [], "via": "cracked", "erro_cracked": "campo de pesquisa não apareceu"}
    # 2) protocolo SEM prefixo
    try:
        await pg.fill('#txtProtocoloPesquisa', proto)
    except PWError as exc:
        logger.debug("fill do #txtProtocoloPesquisa (cracked) falhou, tentando keyboard.type: %s", exc)
    if not await pg.evaluate("""()=>{const e=document.querySelector('#txtProtocoloPesquisa');return e?e.value:''}"""):
        try:
            await pg.click('#txtProtocoloPesquisa'); await pg.keyboard.type(proto, delay=40)
        except PWError as exc:
            logger.warning("não preencheu o protocolo %s no #txtProtocoloPesquisa (cracked): %s", proto, exc)
    # 3) radio 'Processos' (não 'Documentos') + ☑ 'Considerar Documentos' + 'Restringir ao Órgão' DESMARCADO
    await pg.evaluate(r"""()=>{
      const txt=el=>((el&&el.parentElement?el.parentElement.innerText:'')||'').toLowerCase();
      // radio 'Processos' (não 'Documentos'): usa o LABEL PRÓPRIO do radio (r.labels), NÃO o innerText do pai —
      // o fieldset 'Pesquisar' contém as DUAS palavras, então o filtro por innerText do pai nunca marcava
      // 'Processos' e a busca rodava em modo 'Documentos' → caía na caixa da unidade (0 docs). Fix 2026-07-08.
      const labelDe=r=>{
        if(r.labels&&r.labels.length) return [...r.labels].map(l=>(l.innerText||'').trim()).join(' ');
        const s=r.nextElementSibling; if(s&&/label/i.test(s.tagName||'')) return (s.innerText||'').trim();
        if(r.nextSibling&&r.nextSibling.nodeType===3) return (r.nextSibling.textContent||'').trim();
        return '';
      };
      for(const r of document.querySelectorAll('input[type=radio]')){
        const lab=labelDe(r).toLowerCase(); const idv=((r.id||'')+' '+(r.value||'')).toLowerCase();
        if((/\bprocessos?\b/.test(lab)||/processo/.test(idv)) && !(/\bdocumentos?\b/.test(lab)||/documento/.test(idv))){
          try{r.checked=true; r.click();}catch(e){}
        }
      }
      // reforço: clicar o LABEL cujo texto é EXATAMENTE 'Processos' (toggla o radio via for=)
      const lp=[...document.querySelectorAll('label')].find(l=>/^\s*processos?\s*$/i.test((l.innerText||'')));
      if(lp){ try{lp.click();}catch(e){} }
      // checkboxes
      for(const c of document.querySelectorAll('input[type=checkbox]')){
        const l=((c.id||'')+' '+(c.name||'')+' '+txt(c)).toLowerCase();
        if(/considerar\s+documento|considerar_documento/.test(l) && !c.checked){ try{c.click();}catch(e){} }
        if(/restring|[óo]rg[ãa]o\s+da\s+unidade|unidade\s+do\s+[óo]rg/.test(l) && c.checked){ try{c.click();}catch(e){} }
      }
      // Órgão Gerador 'Todos' (se houver select de órgão, deixa na opção vazia/'Todos')
      for(const s of document.querySelectorAll('select')){
        const l=((s.id||'')+' '+(s.name||'')).toLowerCase();
        if(/orgao|[óo]rg[ãa]o/.test(l)){
          const todos=[...s.options].find(o=>/^\s*$/.test(o.value)||/todos/i.test(o.text));
          if(todos){ try{s.value=todos.value; s.dispatchEvent(new Event('change',{bubbles:true}));}catch(e){} }
        }
      }
    }""")
    await pg.wait_for_timeout(800)
    if os.environ.get("SEI_DEBUG_SHOT"):
        try:
            await pg.screenshot(path=os.environ["SEI_DEBUG_SHOT"].replace(".png", "_form.png"), full_page=True)
        except PWError as exc:
            logger.debug("screenshot de debug do formulário (SEI_DEBUG_SHOT) falhou: %s", exc)
    # 4) clicar 'Pesquisar' UMA vez + esperar a NAVEGAÇÃO (sem duplo-submit, sem _abrir_primeiro_resultado)
    try:
        async with pg.expect_navigation(wait_until="domcontentloaded", timeout=25000):
            await pg.evaluate(r"""()=>{const b=document.querySelector('#sbmPesquisar')||[...document.querySelectorAll('button,input[type=submit],input[type=button]')].find(e=>/pesquisar/i.test(e.value||e.innerText||''));if(b)b.click();}""")
    except PWError as exc:
        # navegação pode não disparar como 'navigation' (frameset) — segue p/ a espera ativa da árvore
        logger.debug("expect_navigation após Pesquisar (cracked) não disparou: %s", exc)
    try:
        await pg.wait_for_load_state("networkidle", timeout=15000)
    except PWError as exc:
        logger.debug("networkidle após Pesquisar (cracked) estourou o timeout: %s", exc)
    # 5) espera ATIVA o ifrArvore antes de extrair
    achou_arvore = await _esperar_arvore(pg)
    await pg.wait_for_timeout(1500)
    if os.environ.get("SEI_DEBUG_SHOT"):
        try:
            await pg.screenshot(path=os.environ["SEI_DEBUG_SHOT"], full_page=True)
        except PWError as exc:
            logger.debug("screenshot de debug (SEI_DEBUG_SHOT) falhou: %s", exc)
    dump = await _extrair_de_todos_frames(pg)
    dump["via"] = "cracked"
    dump["url"] = pg.url
    dump["arvore_carregou"] = achou_arvore
    return dump


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
            except PWError as exc:
                logger.debug("networkidle no relacionado %s estourou o timeout: %s", pid, exc)
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


def _url_conteudo_doc(url: str) -> str:
    """URL de CONTEÚDO do documento a partir do href do NÓ da árvore. No SEI-RJ atual o nó vem como
    ``acao=arvore_visualizar&acao_origem=procedimento_visualizar&...&id_documento=..`` — mas o CONTEÚDO é
    servido por ``acao=documento_visualizar``. Sem `id_documento`/`arvore_visualizar` devolve a url como está."""
    if "acao=arvore_visualizar" in url and "id_documento=" in url:
        u = url.replace("acao=arvore_visualizar", "acao=documento_visualizar")
        return u.replace("acao_origem=procedimento_visualizar", "acao_origem=arvore_visualizar")
    return url


async def _frame_arvore(pg):
    """Frame da ÁRVORE viva = o que tem âncoras de documento clicáveis (``a[href*=id_documento=]``);
    prefere o de mais âncoras (o ifrArvoreHtml). None se não houver árvore carregada na página."""
    best, best_n = None, 0
    for fr in pg.frames:
        try:
            n = int(await fr.evaluate("()=>document.querySelectorAll('a[href*=\"id_documento=\"]').length") or 0)
        except (PWError, TypeError, ValueError):
            n = 0
        if n and n > best_n:
            best_n, best = n, fr
    return best


async def _frame_visualizacao(pg):
    """O iframe onde o SEI 4.x carrega o CONTEÚDO do documento clicado na árvore (name=ifrVisualizacao)."""
    for fr in pg.frames:
        if "ifrvisualizacao" in (fr.name or "").lower():
            return fr
    return None


async def _conteudo_via_arvore(pg, doc: dict) -> dict | None:
    """Lê o conteúdo do doc pela ÁRVORE VIVA — o único caminho que funciona cross-unit (provado
    2026-07-13). Clica o nó (``a[id_documento]``) no frame da árvore → o SEI carrega o doc no
    ``ifrVisualizacao`` com contexto/hash CORRETOS. Doc NATIVO = texto inline do editor; doc
    ESCANEADO/EXTERNO = placeholder "…nova janela" → segue o link ``documento_download_anexo`` (PDF/
    imagem, hash válido, request.get na sessão) → OCR. Degrada honesto (None)."""
    m = re.search(r"id_documento=(\d+)", doc.get("url") or "")
    if not m:
        return None
    idd = m.group(1)
    arv = await _frame_arvore(pg)
    if arv is None:
        return None
    vf = await _frame_visualizacao(pg)
    url_antes = (vf.url if vf else "") or ""
    try:
        clicou = await arv.evaluate(
            """(idd)=>{const a=[...document.querySelectorAll('a[href*="id_documento="]')]
                 .find(x=>x.href.includes('id_documento='+idd)); if(a){a.click();return true;} return false;}""",
            idd)
    except PWError:
        return None
    if not clicou:
        return None
    # espera EVENT-BASED o ifrVisualizacao trocar de conteúdo (teto ~6s; nativo carrega em <1s)
    txt = ""
    for _ in range(24):
        await pg.wait_for_timeout(250)
        vf = await _frame_visualizacao(pg)
        if not vf or (vf.url or "") == url_antes:
            continue
        try:
            txt = (await vf.evaluate("()=>document.body?document.body.innerText:''")) or ""
        except PWError:
            txt = ""
        if txt.strip():
            break
    txt = txt.strip()
    from compliance_agent.sei.ocr_docs import ocr_documento  # import LAZY
    # placeholder de doc EXTERNO/escaneado ("Clique aqui … nova janela") → baixa o anexo e OCR
    if "nova janela" in txt.lower() or len(txt) < 120:
        try:
            links = await vf.evaluate(
                "()=>[...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')||'').filter(Boolean)") if vf else []
        except PWError:
            links = []
        for s in links:
            mm = re.search(r"controlador\.php\?[^'\"]*(?:documento_download|download_anexo)[^'\"]*", s or "")
            if not mm:
                continue
            u = mm.group(0).replace("&amp;", "&")
            full = u if u.startswith("http") else ("https://sei.rj.gov.br/sei/" + u.lstrip("/"))
            try:
                r = await pg.context.request.get(full, timeout=45000)
                if not r.ok:
                    continue
                body = await r.body()
                ct = (r.headers.get("content-type") or "").lower()
                tipo = "pdf" if (body[:5] == b"%PDF-" or "pdf" in ct) else ("imagem" if ct.startswith("image/") else None)
                loop = asyncio.get_event_loop()
                if not tipo:
                    # anexo OFFICE (planilha Excel de medição/faturamento, minuta Word):
                    # antes caía aqui em `continue` e o doc sumia. Extrai o texto direto
                    # (openpyxl/xlrd/python-docx). .doc binário antigo devolve '' honesto.
                    from compliance_agent.sei.office_texto import texto_de_office
                    off = await loop.run_in_executor(None, lambda: texto_de_office(body, ct))
                    if off and len(off.strip()) > 20:
                        return {"doc": (doc.get("texto") or "")[:80],
                                "conteudo": off.strip()[:20000], "via": "office"}
                    continue
                txt_ocr = await loop.run_in_executor(None, lambda: ocr_documento(body, tipo=tipo))
                if txt_ocr and len(txt_ocr.strip()) > 20:
                    # anexo_bytes preserva o PDF ORIGINAL (imagens/fotos de prova) p/ quem
                    # arquiva — só quando é PDF (imagem solta não vira .pdf direto). Chave
                    # ADITIVA: outros chamadores leem só conteudo/doc/via.
                    return {"doc": (doc.get("texto") or "")[:80], "conteudo": txt_ocr.strip()[:20000],
                            "via": "ocr", "anexo_bytes": body if tipo == "pdf" else None}
            except (PWError, RuntimeError, OSError, ValueError) as exc:
                logger.warning("download/OCR do anexo (via árvore) %r falhou: %s", (doc.get("texto") or "")[:60], str(exc)[:80])
        return None
    # documento NATIVO (editor): texto inline já renderizado no ifrVisualizacao
    if len(txt) > 50:
        return {"doc": (doc.get("texto") or "")[:80], "conteudo": txt[:20000], "via": "arvore"}
    return None


async def _conteudo_doc(pg, doc: dict) -> dict | None:
    """Extrai o conteúdo de UM documento do SEI pela ÁRVORE VIVA (caminho canônico 2026-07-13).

    Por que pela árvore: request.get/goto direto na url do doc CAEM NO LOGIN — o nó vem com
    ``acao=arvore_visualizar`` e um ``infra_hash`` assinado sobre os params; converter p/
    ``documento_visualizar`` mantendo o hash invalida a assinatura → o SEI redireciona p/ login (a
    "casca" de 893 chars — "GOVERNO DO ESTADO… Sistema Eletrônico de Informações" — que poluía TODO
    conteúdo cross-unit era a própria tela de login). Só clicar o nó na árvore viva dá a url de conteúdo
    certa (ver ``_conteudo_via_arvore``). Degrada honesto: retorna None se não conseguir (nunca inventa).
    """
    via = await _conteudo_via_arvore(pg, doc)
    if via is not None:
        return via
    # Há árvore viva mas o doc não rendeu conteúdo (restrito/anexo sem link/etc.): NÃO faz goto —
    # destruiria a árvore e envenenaria os próximos docs. Devolve None honesto.
    if await _frame_arvore(pg) is not None:
        return None
    # LEGADO (sem árvore viva na página — chamador fora do fluxo de árvore): caminho antigo por url.
    url_c = _url_conteudo_doc(doc.get("url") or "")
    try:
        from compliance_agent.sei.ocr_docs import ocr_documento  # import LAZY
        resp = await pg.context.request.get(url_c, timeout=40000)
        if resp.ok:
            ct = (resp.headers.get("content-type") or "").lower()
            url_l = url_c.lower()
            tipo = "pdf" if ("pdf" in ct or url_l.endswith(".pdf")) else (
                "imagem" if (ct.startswith("image/") or url_l.endswith(
                    (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"))) else None)
            if tipo:
                body = await resp.body()
                loop = asyncio.get_event_loop()
                txt_ocr = await loop.run_in_executor(None, lambda: ocr_documento(body, tipo=tipo))
                if txt_ocr and len(txt_ocr.strip()) > 20:
                    return {"doc": (doc.get("texto") or "")[:80], "conteudo": txt_ocr, "via": "ocr"}
    except Exception as exc:
        logger.warning("download/OCR do doc %r falhou: %s", (doc.get("texto") or doc.get("url") or "")[:80], exc)
    try:
        await pg.goto(url_c, wait_until="domcontentloaded", timeout=20000)
        await pg.wait_for_timeout(1100)
    except PWError:
        return None
    _MENU = ("AGENERSA AGERIO", "Base de Conhecimento", "Controle de Processos")
    best = ""
    for fr in pg.frames:
        try:
            t = await fr.evaluate("()=>document.body?document.body.innerText:''")
        except PWError:
            continue
        t = t or ""
        if any(s in t for s in _MENU):  # frameset do menu → não é o doc
            continue
        if len(t) > len(best):
            best = t
    best = best[:8000]
    if best and len(best.strip()) > 50:
        return {"doc": (doc.get("texto") or "")[:80], "conteudo": best}
    return None


async def _montar_resultado_cracked(pg, proc: str, dump: dict, usar_cache: bool = True) -> dict:
    """Monta o resultado canônico (mesmo formato de ``ler_processo``) a partir do dump CRACKED:
    extrai o conteúdo dos primeiros docs, regex de cnpjs/valores e grava ``cdp_*.json``. Honesto:
    propaga ``cadeado``/``n_docs_restritos`` (docs restritos do processo) sem inventar conteúdo."""
    from datetime import datetime
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    res = {"numero": proc, "url": dump.get("url") or pg.url, "via": "cracked",
           "documentos": dump.get("documentos", []), "relacionados": dump.get("relacionados", []),
           "cadeado": dump.get("cadeado", False), "n_docs_restritos": dump.get("n_docs_restritos", 0),
           "arvore_carregou": dump.get("arvore_carregou"), "texto": dump.get("texto", ""),
           "captcha_resolvido": False, "_login": {"ok": True, "via": "sei_reader/itkava+cracked"}}
    # Mesmo bound do caminho normal (SEI_MAX_DOCS=40): o antigo [:8] deixava os anexos
    # de NF (que vêm tarde na árvore) fora do OCR — gargalo corrigido. OCR de scan via _conteudo_doc.
    _max_docs = int(os.environ.get("SEI_MAX_DOCS", "40"))
    docs_txt = []
    for doc in dump.get("documentos", [])[:_max_docs]:
        c = await _conteudo_doc(pg, doc)
        if c:
            docs_txt.append(c)
    res["conteudo_documentos"] = docs_txt
    tot = res["texto"] + "\n\n" + "\n\n".join(d["conteudo"] for d in docs_txt)
    res["cnpjs"] = sorted(set(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", tot)))
    res["valores"] = sorted(set(re.findall(r"R\$\s*[\d.,]+", tot)))
    res["_cached_at"] = datetime.now().isoformat()
    try:
        _grava_cache_atomico(cache_file, res)
        res["_cache_path"] = str(cache_file)
    except OSError as exc:
        logger.warning("gravação do cache %s (cracked) falhou: %s", cache_file, exc)
    return res


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
            if c.get("_cached_at") and (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < CACHE_TTL:
                c["_de_cache"] = True; return c
        except (OSError, ValueError) as exc:
            logger.warning("leitura do cache %s falhou, seguindo p/ leitura viva: %s", cache_file, exc)
    # navega p/ a Pesquisa AVANÇADA (menu "Pesquisa") — clique REAL preserva a sessão
    await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
    await _ate(pg, lambda: _tem_campo_protocolo(pg), 5000)
    tem_avancada = await _tem_campo_protocolo(pg)
    if tem_avancada:
        # protocolo EXATO: fill; se o ADF não aceitar, keyboard.type (keystrokes reais)
        try: await pg.fill('#txtProtocoloPesquisa', proc)
        except Exception as exc: logger.debug("fill do #txtProtocoloPesquisa falhou, tentando keyboard.type: %s", exc)
        if not await pg.evaluate("""()=>{const e=document.querySelector('#txtProtocoloPesquisa');return e?e.value:''}"""):
            try:
                await pg.click('#txtProtocoloPesquisa'); await pg.keyboard.type(proc, delay=40)
            except Exception as exc:
                logger.warning("não preencheu o protocolo %s no #txtProtocoloPesquisa: %s", proc, exc)
        # avançada vem com "Restringir ao Órgão da Unidade" MARCADO → desmarcar p/ busca global (lição 2026-06-12).
        await pg.evaluate(r"""()=>{document.querySelectorAll('input[type=checkbox]').forEach(c=>{const l=((c.id||'')+' '+(c.name||'')+' '+(c.parentElement?(c.parentElement.innerText||''):'')).toLowerCase();if(/restring|unidade\s+do\s+[óo]rg|[óo]rg[ãa]o\s+da\s+unidade/.test(l)&&c.checked){try{c.click();}catch(e){}}});}""")
        # SUBMIT robusto: o clique-por-texto às vezes não dispara o form do SEI. Tenta botão por id/valor,
        # submit() do form, e Enter no campo (lição 2026-06-12: a busca ficava parada no FORM).
        # ⚠ MÉTODO CRACKED (fotos do dono) p/ processo de OUTRA unidade = clicar Pesquisar 1× + expect_navigation +
        # espera ativa ifrArvore (sem _abrir). Abre 510001 isolado, MAS quebrou o ITERJ 270042 quando portado aqui →
        # revertido; portar com cuidado testando os DOIS casos. Ver [[vault/aprendizados/sei-leitura-itkava]].
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
        except Exception as exc: logger.debug("Enter no #txtProtocoloPesquisa (submit extra) falhou: %s", exc)
    else:
        # fallback: pesquisa rápida (escopo da unidade)
        await pg.evaluate(r"""(n)=>{const i=document.querySelector('#txtPesquisaRapida');if(i){i.value=n;const f=document.getElementById('frmProtocoloPesquisaRapida');if(f)f.submit();}}""", proc)
    try: await pg.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc: logger.debug("networkidle após submit da pesquisa estourou o timeout: %s", exc)
    await _ate(pg, lambda: _tem_resultado_ou_arvore(pg), 4000)
    await _abrir_primeiro_resultado(pg)
    await pg.wait_for_timeout(3000)
    dump = await _extrair_de_todos_frames(pg)
    res = {"numero": proc, "url": pg.url, "documentos": dump["documentos"],
           "relacionados": dump.get("relacionados", []), "cadeado": dump.get("cadeado", False),
           "n_docs_restritos": dump.get("n_docs_restritos", 0), "texto": dump["texto"],
           "captcha_resolvido": False, "_login": {"ok": True, "via": "sei_reader/itkava"}}
    # conteúdo dos documentos (TODOS, bounded a 40 p/ não estourar; OCR de scan via _conteudo_doc)
    _max_docs = int(os.environ.get("SEI_MAX_DOCS", "40"))
    docs_txt = []
    for doc in dump["documentos"][:_max_docs]:
        c = await _conteudo_doc(pg, doc)
        if c:
            docs_txt.append(c)
    res["conteudo_documentos"] = docs_txt
    tot = res["texto"] + "\n\n" + "\n\n".join(d["conteudo"] for d in docs_txt)
    res["cnpjs"] = sorted(set(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", tot)))
    res["valores"] = sorted(set(re.findall(r"R\$\s*[\d.,]+", tot)))
    res["_cached_at"] = datetime.now().isoformat()
    # CAIXA/leitura FALHA (0 docs + inbox da unidade OU nenhuma árvore aberta) → NÃO gravar
    # cache (envenenava a memória: consumidor via "0 docs"=vazio por 24h — INDISPONÍVEL ≠ 0) e marcar
    # p/ o caller. Fix constância 2026-07-03; ver vault/aprendizados/sei-leitura-itkava.
    # 2026-07-10: o filtro do menu (sei_cdp) zerou o rel~40 da caixa → rel>=15 ficou cego; o sinal
    # direto agora é arvore_vista=False (nenhum frame com infraArvoreNo = processo NÃO abriu).
    if not res["documentos"] and (len(res["relacionados"]) >= 15 or not dump.get("arvore_vista")):
        res["indisponivel"] = True
        return res
    try:
        _grava_cache_atomico(cache_file, res)
        res["_cache_path"] = str(cache_file)
    except OSError as exc:
        logger.warning("gravação do cache %s falhou: %s", cache_file, exc)
    return res


async def ler(numero: str, usar_cache: bool = True, tentativas_login: int = 30,
              tentar_publico: bool = True) -> dict:
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
            if c.get("_cached_at") and (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < CACHE_TTL:
                c["_de_cache"] = True
                return c
        except (OSError, ValueError) as exc:
            logger.warning("leitura do cache %s falhou, seguindo p/ leitura viva: %s", cache_file, exc)
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
                res = await ler_processo(pg, numero, usar_cache=usar_cache)
                # FALLBACK CRACKED (anti-regressão, caminho SEPARADO): o ITERJ (270042) passa pelo
                # caminho normal acima (zero risco). Se o normal NÃO trouxe documentos (típico de
                # processo de OUTRA unidade — ex.: consórcios Vieira/MUV na 510001 — que o itkava VÊ
                # mas a busca 'normal' do ITERJ não abre), tenta o método CRACKED no MESMO browser
                # (Processos + Considerar Documentos + Pesquisar + expect_navigation + ifrArvore).
                if not res.get("documentos"):
                    try:
                        dump = await _ler_cracked(pg, numero)
                        if dump.get("documentos"):
                            res = await _montar_resultado_cracked(pg, numero, dump, usar_cache)
                    except Exception as e:  # noqa: BLE001
                        res.setdefault("_cracked_erro", str(e)[:120])
                # 3ª tentativa: PESQUISA RÁPIDA do topo (a avançada por 'Nº SEI' às vezes retorna 0 → caixa)
                if not res.get("documentos"):
                    try:
                        dump = await _abrir_por_quicksearch(pg, numero)
                        if dump.get("documentos"):
                            res = await _montar_resultado_cracked(pg, numero, dump, usar_cache)
                    except Exception as e:  # noqa: BLE001
                        res.setdefault("_quicksearch_erro", str(e)[:120])
                return res
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
        # mesmo fallback de ler(): se o caminho normal não trouxe docs, tenta o método CRACKED
        if not res.get("documentos"):
            print("   normal=0 docs → tentando CRACKED…", flush=True)
            dump = await _ler_cracked(pg, proc)
            print(f"   cracked: docs={len(dump.get('documentos',[]))} rel={len(dump.get('relacionados',[]))} "
                  f"arvore={dump.get('arvore_carregou')} url={(dump.get('url') or '')[:70]}", flush=True)
            if dump.get("documentos"):
                res = await _montar_resultado_cracked(pg, proc, dump, usar_cache=False)
        print(f"   docs: {len(res.get('documentos',[]))} | via: {res.get('via','normal')} "
              f"| texto: {len(res.get('texto',''))} chars "
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
            except PWError as e:
                print("   shot erro:", e)
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
