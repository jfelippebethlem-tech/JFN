"""
Leitura de processos SEI-RJ via Chrome debug (porta 9222) — CAPTCHA via OCR.

Fluxo:
- Conecta no Chrome pela CDP na porta 9222
- Abre a página de pesquisa pública do SEI
- Preenche o número do processo e dispara a busca
- Se aparecer CAPTCHA de imagem:
    1) Localiza a imagem do captcha (captcha.php)
    2) Lê o texto com OCR (compliance_agent.captcha_solver / pytesseract)
    3) Preenche o campo e reenvia
- Lê a árvore de documentos do processo na íntegra
- Extrai CPFs, CNPJs, valores e referências cruzadas

O OCR é importado de forma lazy para não exigir cv2/pytesseract em ambientes
que só rodam a suíte offline.

Uso (standalone):
    python -m compliance_agent.collectors.sei_cdp "E-12/345/2026"
"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

CDP_URL = "http://127.0.0.1:9222"
SEI_PESQUISA = (
    "https://sei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php"
)
SEI_PESQUISA_PUBLICA = (
    SEI_PESQUISA
    + "?acao_externa=protocolo_pesquisar"
    + "&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6"
)
SEI_CONTROLADOR = "https://sei.rj.gov.br/sei/controlador.php"

CACHE_DIR = Path("data/sei_cache")

# Máximo de tentativas de OCR no CAPTCHA antes de desistir
MAX_TENTATIVAS_CAPTCHA = int(os.environ.get("SEI_CAPTCHA_TENTATIVAS", "4"))

# ── Login interno autenticado (usuário ITKAVA) ────────────────────────────────
# O app autenticado do SEI (SIP) não passa pela pesquisa pública (WAF/CAPTCHA).
# IMPORTANTE: o usuário é MINÚSCULO ("itkava") — faz diferença no login do SIP.
SEI_USER = os.environ.get("SEI_USER", "itkava")
SEI_PASS = os.environ.get("SEI_PASS", "")
SEI_ORGAO = os.environ.get("SEI_ORGAO", "ERJ")       # órgão do SEI-RJ (Estado do Rio de Janeiro)
SEI_LOGIN_URL = os.environ.get(
    "SEI_LOGIN_URL",
    "https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ&sigla_sistema=SEI&infra_url=L3NlaS8=")


def _tem_credenciais_sei() -> bool:
    return bool(SEI_PASS)


_JS_PREENCHE_LOGIN = r"""
(c) => {
    const u = document.querySelector('#txtUsuario, input[name="txtUsuario"], input[name*="suario"]');
    const p = document.querySelector('#pwdSenha, input[name="pwdSenha"], input[type="password"]');
    const o = document.querySelector('#selOrgao, select[name="selOrgao"], select[name*="rgao"]');
    if (u) { u.value = c.u; }
    if (p) { p.value = c.p; }
    if (o && c.o) {
        for (const opt of o.options) {
            if (opt.text.trim() === c.o || opt.value === c.o) { o.value = opt.value; break; }
        }
    }
    return {u: !!u, p: !!p, o: !!o};
}
"""

_JS_CLICA_LOGIN = r"""
() => {
    const b = document.querySelector('#sbmLogin, #Acessar, button[type="submit"], input[type="submit"]');
    if (b) { b.click(); return true; }
    const f = document.querySelector('form'); if (f) { f.submit(); return true; }
    return false;
}
"""


async def login_sei_interno(page) -> dict:
    """Loga no SEI interno (SIP) com o usuário ITKAVA (minúsculo). Contorna a pesquisa pública (WAF/CAPTCHA).
    Configuração via .env: SEI_USER (default 'itkava'), SEI_PASS, SEI_ORGAO, SEI_LOGIN_URL. Retorna {ok}/{erro}."""
    if not _tem_credenciais_sei():
        return {"erro": "SEI_PASS não configurado no .env — login interno indisponível"}
    try:
        await page.goto(SEI_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.0)
        body = (await page.inner_text("body")).lower()
        if any(m in body for m in _WAF_MARK):
            return {"erro": "WAF bloqueou a página de login (IP da VM não autorizado) — rodar de IP gov/permitido"}
        achou = await page.evaluate(_JS_PREENCHE_LOGIN, {"u": SEI_USER, "p": SEI_PASS, "o": SEI_ORGAO})
        if not achou.get("p"):
            return {"erro": "campo de senha não encontrado na página de login (conferir SEI_LOGIN_URL/seletores)"}
        await asyncio.sleep(0.4)
        await page.evaluate(_JS_CLICA_LOGIN)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(1.5)
        txt = (await page.inner_text("body")).lower()
        if any(m in txt for m in ("senha inválida", "senha invalida", "usuário ou senha", "usuario ou senha",
                                  "não foi possível", "nao foi possivel")):
            return {"erro": "login recusado (usuário/senha/órgão) — confira credenciais e SEI_ORGAO"}
        # sinais de sessão autenticada
        autent = any(m in txt for m in ("controle de processos", "menu", "sair", "pesquisar")) and \
            "login.php" not in (page.url or "")
        return {"ok": True, "autenticado": autent, "url": page.url}
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}


_WAF_MARK = ("web page blocked", "url you requested has been blocked", "attack id", "acesso negado")


# ── Detecção de CAPTCHA ────────────────────────────────────────────────────────

_JS_DETECTA_CAPTCHA = r"""
() => {
    const imgCaptcha = document.querySelector(
        'img[src*="captcha"], img[src*="Captcha"], img[id*="aptcha"]'
    );
    const campoCaptcha = document.querySelector(
        'input[id*="aptcha"], input[name*="aptcha"], input[id*="Captcha"], '
        + 'input[id*="InfraCaptcha"]'
    );
    const temImgCaptcha = !!(imgCaptcha || campoCaptcha);
    const txt = (document.body ? document.body.innerText : '').toLowerCase();
    const mencionaCaptcha = txt.includes('captcha')
        || txt.includes('digite os caracteres')
        || txt.includes('código da imagem')
        || txt.includes('codigo da imagem');
    return {
        presente: temImgCaptcha || mencionaCaptcha,
        tipo: temImgCaptcha ? 'imagem' : (mencionaCaptcha ? 'texto' : ''),
        img_src: imgCaptcha ? imgCaptcha.src : '',
    };
}
"""

_JS_TEM_RESULTADO = r"""
() => {
    const linksProc = document.querySelectorAll(
        'a[href*="procedimento_trabalhar"], a[href*="procedimento_visualizar"], '
        + 'a[href*="md_pesq_processo"], a[onclick*="procedimento"]'
    );
    const tabela = document.querySelector('table.infraTable, table[id*="Tabela"], .infraAreaTabela');
    const txt = (document.body ? document.body.innerText : '').toLowerCase();
    const semResultado = txt.includes('nenhum registro') || txt.includes('não encontrado');
    return {
        tem: (linksProc.length > 0 || !!tabela) && !semResultado,
        n_links: linksProc.length,
        sem_resultado: semResultado,
    };
}
"""

_JS_PREENCHE_BUSCA = r"""
(numero) => {
    const campo = document.querySelector(
        'input[id*="txtProtocoloPesquisa"], input[id*="txtPesquisaRapida"], '
        + 'input[name*="protocolo"], input[id*="Protocolo"], input[type="text"]'
    );
    if (!campo) return 'campo não encontrado';
    campo.focus();
    campo.value = numero;
    campo.dispatchEvent(new Event('input', {bubbles: true}));
    campo.dispatchEvent(new Event('change', {bubbles: true}));
    return 'preenchido';
}
"""

_JS_CLICA_PESQUISAR = r"""
() => {
    for (const el of document.querySelectorAll('button, input[type="submit"], input[type="button"], a')) {
        const t = (el.value || el.textContent || '').trim().toLowerCase();
        const r = el.getBoundingClientRect();
        if (r.width <= 0) continue;
        if (t === 'pesquisar' || t === 'buscar' || t === 'consultar') {
            el.click();
            return 'clicado: ' + t;
        }
    }
    return null;
}
"""

_JS_LE_ARVORE_E_TEXTO = r"""
() => {
    const docs = [];
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.href || '';
        const texto = (a.textContent || '').trim();
        if (!texto) continue;
        if (/documento_visualizar|exibir_documento|md_doc|acessar_documento|procedimento_visualizar/i.test(href)) {
            docs.push({texto: texto.slice(0, 120), url: href});
        }
    }
    const corpo = document.body ? document.body.innerText : '';
    return {
        url: location.href,
        title: document.title,
        documentos: docs.slice(0, 80),
        texto: corpo.slice(0, 12000),
    };
}
"""


# ── Helpers de conexão ─────────────────────────────────────────────────────────

async def _chrome_disponivel() -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{CDP_URL}/json/version")
            return r.status_code == 200
    except Exception:
        return False


async def _aba_sei(browser):
    """Acha uma aba já no portal SEI, ou usa a primeira disponível."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "portalsei" in pg.url.lower() or "/sei/" in pg.url.lower():
                return pg
    if browser.contexts and browser.contexts[0].pages:
        return browser.contexts[0].pages[0]
    return None


def _is_captcha_page(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in [
        "captcha", "digite os caracteres", "código da imagem", "codigo da imagem",
    ])


# ── Resolução do CAPTCHA via OCR ───────────────────────────────────────────────

async def _resolver_captcha_ocr(page) -> bool:
    """
    Lê o CAPTCHA de imagem com OCR e preenche o campo. Retorna True se conseguiu
    preencher e reenviar. Usa compliance_agent.captcha_solver (import lazy).
    """
    captcha = await page.evaluate(_JS_DETECTA_CAPTCHA)
    img_src = captcha.get("img_src", "")
    if not img_src:
        return False

    # Tenta ler a imagem direto do DOM (mais confiável que baixar de novo)
    texto_ocr = ""
    try:
        from compliance_agent.captcha_solver import solve_captcha_url
        texto_ocr = await asyncio.to_thread(solve_captcha_url, img_src)
    except Exception as e:
        print(f"[SEI] OCR falhou: {e}")
        return False

    if not texto_ocr:
        return False

    campo = await page.query_selector(
        'input[id*="InfraCaptcha"], input[id*="txtCaptcha"], '
        'input[name*="txtCaptcha"], input[id*="aptcha"], input[name*="aptcha"]'
    )
    if not campo:
        return False

    await campo.fill(texto_ocr)
    await asyncio.sleep(0.3)
    await page.evaluate(_JS_CLICA_PESQUISAR)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    await asyncio.sleep(1.5)
    return True


# ── API original: busca crua e devolve texto/HTML ─────────────────────────────

async def submit_sei_search(numero: str, *, max_attempts: int = MAX_TENTATIVAS_CAPTCHA) -> dict:
    """
    Busca um processo no SEI e devolve o texto/HTML da página de resultado.
    Resolve o CAPTCHA de imagem via OCR automaticamente.
    """
    if not await _chrome_disponivel():
        return {"erro": "Chrome 9222 indisponível. Abra o Chrome debug (HERMES.bat passo 4)."}

    from playwright.async_api import async_playwright
    p = browser = page = None
    try:
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=30000)
        page = await _aba_sei(browser)
        if page is None:
            return {"erro": "Nenhuma aba encontrada no Chrome."}

        # Login interno (usuário itkava) quando há credenciais — sessão autenticada dispensa CAPTCHA.
        if _tem_credenciais_sei():
            lg = await login_sei_interno(page)
            if lg.get("erro"):
                # WAF bloqueia o IP da VM até no login; segue p/ a pesquisa pública (best-effort)
                pass

        await page.goto(SEI_PESQUISA_PUBLICA, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.5)

        await page.evaluate(_JS_PREENCHE_BUSCA, numero)
        await asyncio.sleep(0.5)
        await page.evaluate(_JS_CLICA_PESQUISAR)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        txt = await page.inner_text("body")
        for _ in range(max_attempts):
            if not _is_captcha_page(txt):
                break
            ok = await _resolver_captcha_ocr(page)
            if not ok:
                break
            txt = await page.inner_text("body")

        try:
            Path("data/tmp").mkdir(parents=True, exist_ok=True)
            Path("data/tmp/sei_last_search.html").write_text(await page.content(), encoding="utf-8")
            Path("data/tmp/sei_last_search.txt").write_text(txt, encoding="utf-8")
        except Exception:
            pass

        return {
            "ok": True,
            "texto": txt,
            "url": page.url,
            "captcha_resolvido": not _is_captcha_page(txt),
        }
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}
    finally:
        try:
            if p:
                await p.stop()
        except Exception:
            pass


# ── Leitura completa do processo (árvore + documentos) ────────────────────────

async def ler_processo_sei_via_chrome(
    numero_sei: str,
    *,
    avisar: Optional[Callable] = None,
    usar_cache: bool = True,
    max_tentativas_captcha: int = MAX_TENTATIVAS_CAPTCHA,
) -> dict:
    """
    Lê um processo SEI na íntegra via Chrome (porta 9222), resolvendo o CAPTCHA
    de imagem automaticamente por OCR.

    Args:
        numero_sei: número do processo (ex.: "E-12/345/2026").
        avisar:     callback async opcional para notificar progresso (ex.: Telegram).
        usar_cache: se True, devolve cache de até 24h.
        max_tentativas_captcha: quantas vezes tentar resolver o CAPTCHA por OCR.

    Returns:
        dict com: numero, url, documentos[], texto, cpfs, cnpjs, valores,
        captcha_resolvido (bool), erro (se houver).
    """
    numero = re.sub(r"\s+", "", numero_sei.strip().upper())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"cdp_{numero.replace('/', '_')}.json"

    if usar_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("_cached_at"):
                delta = datetime.now() - datetime.fromisoformat(cached["_cached_at"])
                if delta.total_seconds() < 86400:
                    cached["_de_cache"] = True
                    return cached
        except Exception:
            pass

    async def _notificar(msg: str):
        if avisar:
            try:
                r = avisar(msg)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:
                pass

    if not await _chrome_disponivel():
        return {
            "numero": numero,
            "erro": "Chrome 9222 indisponível. Abra o Chrome debug (HERMES.bat passo 4) "
                    "e abra o portal SEI antes.",
        }

    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    resultado: dict = {"numero": numero, "documentos": [], "texto": "",
                       "captcha_resolvido": False}
    try:
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=30000)
        page = await _aba_sei(browser)
        if not page:
            resultado["erro"] = "Nenhuma aba encontrada no Chrome."
            return resultado

        # 1. Navega para a pesquisa pública
        try:
            await page.goto(SEI_PESQUISA_PUBLICA, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        except Exception as e:
            resultado["erro"] = f"falha ao abrir pesquisa SEI: {e}"
            return resultado

        # 2. Preenche o número e dispara a busca
        await page.evaluate(_JS_PREENCHE_BUSCA, numero)
        await asyncio.sleep(0.5)
        await page.evaluate(_JS_CLICA_PESQUISAR)
        await asyncio.sleep(2.5)

        # 3. CAPTCHA? — resolve por OCR (até N tentativas)
        captcha = await page.evaluate(_JS_DETECTA_CAPTCHA)
        if captcha.get("presente"):
            await _notificar(f"🔎 CAPTCHA detectado no SEI — resolvendo por OCR (`{numero}`)…")
            for tentativa in range(1, max_tentativas_captcha + 1):
                ok = await _resolver_captcha_ocr(page)
                res = await page.evaluate(_JS_TEM_RESULTADO)
                cap = await page.evaluate(_JS_DETECTA_CAPTCHA)
                if res.get("tem") or not cap.get("presente"):
                    resultado["captcha_resolvido"] = True
                    break
                if not ok:
                    # OCR não conseguiu nem preencher; tenta de novo recarregando
                    await asyncio.sleep(1)
            if not resultado["captcha_resolvido"]:
                resultado["erro"] = (
                    f"CAPTCHA não resolvido por OCR após {max_tentativas_captcha} tentativas. "
                    "A imagem pode estar muito distorcida; tente de novo."
                )
                return resultado
            await _notificar(f"✅ CAPTCHA resolvido (OCR) — lendo `{numero}`.")

        # 4. Abre o primeiro resultado (se a busca devolveu lista)
        await _abrir_primeiro_resultado(page)

        # 5. Lê a árvore de documentos + texto
        dump = await page.evaluate(_JS_LE_ARVORE_E_TEXTO)
        resultado.update({
            "url": dump.get("url", ""),
            "title": dump.get("title", ""),
            "documentos": dump.get("documentos", []),
            "texto": dump.get("texto", ""),
        })

        # 6. Lê o conteúdo de cada documento da árvore
        textos_docs = []
        for doc in resultado["documentos"][:8]:
            url = doc.get("url")
            if not url:
                continue
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.2)
                txt = await page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 6000) : ''"
                )
                if txt and len(txt) > 50:
                    textos_docs.append({"doc": doc.get("texto", "")[:80], "conteudo": txt})
            except Exception:
                continue

        resultado["conteudo_documentos"] = textos_docs
        texto_total = resultado["texto"] + "\n\n" + "\n\n".join(
            d["conteudo"] for d in textos_docs
        )

        # 7. Extrai CPFs, CNPJs, valores
        resultado["cpfs"] = sorted(set(re.findall(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", texto_total)))
        resultado["cnpjs"] = sorted(set(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", texto_total)))
        resultado["valores"] = sorted(set(re.findall(r"R\$\s*[\d.,]+", texto_total)))

        resultado["_cached_at"] = datetime.now().isoformat()
        try:
            cache_file.write_text(
                json.dumps(resultado, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

        return resultado

    except Exception as e:
        resultado["erro"] = f"{type(e).__name__}: {e}"
        return resultado
    finally:
        try:
            await p.stop()
        except Exception:
            pass


async def ler_processo_sei_launch(
    numero_sei: str,
    *,
    usar_cache: bool = True,
    max_tentativas_captcha: int = MAX_TENTATIVAS_CAPTCHA,
    headless: bool = True,
) -> dict:
    """Lê um processo SEI lançando o PRÓPRIO Chromium (Playwright launch), em vez de conectar no Chrome 9222.

    É o caminho para rodar onde NÃO há Chrome debug: **GitHub Actions (IPs Azure passam pelo WAF do SEI-RJ, como
    no SIAFE)** ou o desktop. Loga no SEI interno como `itkava` (env SEI_*) — sessão autenticada dispensa CAPTCHA.
    Reusa exatamente os mesmos extractors da leitura via CDP. Mesmo cache (data/sei_cache/cdp_*.json)."""
    numero = re.sub(r"\s+", "", numero_sei.strip().upper())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"cdp_{numero.replace('/', '_')}.json"
    if usar_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("_cached_at") and (
                datetime.now() - datetime.fromisoformat(cached["_cached_at"])
            ).total_seconds() < 86400:
                cached["_de_cache"] = True
                return cached
        except Exception:
            pass

    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    resultado: dict = {"numero": numero, "documentos": [], "texto": "", "captcha_resolvido": False}
    try:
        browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        if _tem_credenciais_sei():
            resultado["_login"] = await login_sei_interno(page)

        try:
            await page.goto(SEI_PESQUISA_PUBLICA, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        except Exception as e:
            resultado["erro"] = f"falha ao abrir pesquisa SEI: {e}"
            return resultado
        if any(m in (await page.inner_text("body")).lower() for m in _WAF_MARK):
            resultado["erro"] = "bloqueio de rede (WAF) na pesquisa — IP não autorizado (rodar no Actions/IP gov)"
            return resultado

        await page.evaluate(_JS_PREENCHE_BUSCA, numero)
        await asyncio.sleep(0.5)
        await page.evaluate(_JS_CLICA_PESQUISAR)
        await asyncio.sleep(2.5)

        if (await page.evaluate(_JS_DETECTA_CAPTCHA)).get("presente"):
            for _ in range(max_tentativas_captcha):
                await _resolver_captcha_ocr(page)
                if not (await page.evaluate(_JS_DETECTA_CAPTCHA)).get("presente"):
                    resultado["captcha_resolvido"] = True
                    break

        await _abrir_primeiro_resultado(page)
        dump = await page.evaluate(_JS_LE_ARVORE_E_TEXTO)
        resultado.update({"url": dump.get("url", ""), "title": dump.get("title", ""),
                          "documentos": dump.get("documentos", []), "texto": dump.get("texto", "")})

        textos_docs = []
        for doc in resultado["documentos"][:8]:
            url = doc.get("url")
            if not url:
                continue
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.0)
                txt = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 6000) : ''")
                if txt and len(txt) > 50:
                    textos_docs.append({"doc": doc.get("texto", "")[:80], "conteudo": txt})
            except Exception:
                continue
        resultado["conteudo_documentos"] = textos_docs
        tot = resultado["texto"] + "\n\n" + "\n\n".join(d["conteudo"] for d in textos_docs)
        resultado["cpfs"] = sorted(set(re.findall(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", tot)))
        resultado["cnpjs"] = sorted(set(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", tot)))
        resultado["valores"] = sorted(set(re.findall(r"R\$\s*[\d.,]+", tot)))
        resultado["_cached_at"] = datetime.now().isoformat()
        try:
            cache_file.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
        return resultado
    except Exception as e:
        resultado["erro"] = f"{type(e).__name__}: {e}"
        return resultado
    finally:
        try:
            await p.stop()
        except Exception:
            pass


async def _abrir_primeiro_resultado(page) -> bool:
    """Se a busca devolveu uma LISTA, abre o primeiro processo. Idempotente."""
    try:
        clicou = await page.evaluate(r"""
            () => {
                const a = document.querySelector(
                    'a[href*="procedimento_trabalhar"], a[href*="procedimento_visualizar"], '
                    + 'a[onclick*="procedimento"]'
                );
                if (a) { a.click(); return true; }
                return false;
            }
        """)
        if clicou:
            await asyncio.sleep(2.5)
        return bool(clicou)
    except Exception:
        return False


async def ler_processo_sei(numero_sei: str, **kwargs) -> dict:
    """
    Conveniência: lê o processo via Chrome (OCR no CAPTCHA), usando o Telegram
    como canal de aviso de progresso. Repassa kwargs para ler_processo_sei_via_chrome.
    """
    try:
        from compliance_agent.notifications.telegram import enviar_mensagem
        avisar = enviar_mensagem
    except Exception:
        avisar = None
    return await ler_processo_sei_via_chrome(numero_sei, avisar=avisar, **kwargs)


if __name__ == "__main__":
    import sys
    numero = sys.argv[1] if len(sys.argv) > 1 else "E-12/345/2026"
    res = asyncio.run(ler_processo_sei(numero))
    print(json.dumps({
        "numero": res.get("numero"),
        "erro": res.get("erro"),
        "captcha_resolvido": res.get("captcha_resolvido"),
        "n_documentos": len(res.get("documentos", [])),
        "n_cpfs": len(res.get("cpfs", [])),
        "n_cnpjs": len(res.get("cnpjs", [])),
        "n_valores": len(res.get("valores", [])),
    }, ensure_ascii=False, indent=2))
