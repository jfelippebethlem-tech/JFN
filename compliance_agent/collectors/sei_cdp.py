"""
Leitura de processos SEI-RJ via Chrome debug (porta 9222) — HUMANO-NO-LOOP.

Por que este módulo existe
──────────────────────────
O Portal de Pesquisa Pública do SEI-RJ protege a consulta com CAPTCHA. Esse
CAPTCHA existe DE PROPÓSITO para impedir acesso automatizado em massa. Este
módulo NÃO quebra, NÃO resolve e NÃO contorna o CAPTCHA — em vez disso ele
mantém um HUMANO no circuito:

  1. O agente navega até a consulta do SEI na janela do Chrome que VOCÊ já tem
     aberta e logada (porta 9222).
  2. Preenche o número do processo automaticamente.
  3. Se aparecer um CAPTCHA, o agente PAUSA e te avisa (painel + Telegram):
     "resolva o CAPTCHA na janela do Chrome".
  4. VOCÊ resolve o desafio UMA vez, na janela real.
  5. O agente detecta que a página avançou e então lê o processo na íntegra,
     reaproveitando a sessão validada para os próximos documentos.

Isso satisfaz o controle de segurança de forma legítima (um humano de fato
resolveu o desafio) e ainda automatiza praticamente todo o resto do trabalho:
navegação, preenchimento, extração da árvore de documentos, leitura do texto,
cache e cruzamento com SIAFE.

Uso (standalone):
    python -m compliance_agent.collectors.sei_cdp "E-12/345/2026"
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

CDP_URL = "http://127.0.0.1:9222"
SEI_PESQUISA_PUBLICA = (
    "https://portalsei.rj.gov.br/sei/modulos/pesquisa/"
    "md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar"
    "&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=0"
)

CACHE_DIR = Path("data/sei_cache")

# Espera máxima (segundos) para o humano resolver o CAPTCHA na janela do Chrome.
TIMEOUT_CAPTCHA = int(__import__("os").environ.get("SEI_CAPTCHA_TIMEOUT", "300"))


# ── Detecção de CAPTCHA (NÃO resolve — apenas reconhece que existe) ────────────

_JS_DETECTA_CAPTCHA = r"""
() => {
    // reCAPTCHA / hCaptcha por iframe ou container
    const temRecaptcha = !!document.querySelector(
        'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], '
        + '.g-recaptcha, #g-recaptcha, [class*="recaptcha"], [id*="captcha"]'
    );
    // CAPTCHA de imagem clássico do SEI (campo + imagem)
    const imgCaptcha = document.querySelector(
        'img[src*="captcha"], img[src*="Captcha"], img[id*="aptcha"]'
    );
    const campoCaptcha = document.querySelector(
        'input[id*="aptcha"], input[name*="aptcha"], input[id*="Captcha"]'
    );
    const temImgCaptcha = !!(imgCaptcha || campoCaptcha);

    // Texto da página sugerindo desafio
    const txt = (document.body ? document.body.innerText : '').toLowerCase();
    const mencionaCaptcha = txt.includes('captcha')
        || txt.includes('não sou um robô')
        || txt.includes('digite os caracteres')
        || txt.includes('código da imagem');

    return {
        presente: temRecaptcha || temImgCaptcha || mencionaCaptcha,
        tipo: temRecaptcha ? 'recaptcha' : (temImgCaptcha ? 'imagem' : (mencionaCaptcha ? 'texto' : '')),
    };
}
"""

# Heurística: a página de RESULTADO já passou do CAPTCHA quando aparece a
# tabela de processos / link de visualização da árvore.
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
    // Campo de número de protocolo na pesquisa pública do SEI
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
    // Coleta links de documentos da árvore do processo + texto visível
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


async def ler_processo_sei_via_chrome(
    numero_sei: str,
    *,
    avisar: Optional[Callable] = None,
    timeout_captcha: int = TIMEOUT_CAPTCHA,
    usar_cache: bool = True,
) -> dict:
    """
    Lê um processo SEI na íntegra usando a janela do Chrome (porta 9222),
    com HUMANO-NO-LOOP para o CAPTCHA.

    Args:
        numero_sei: número do processo (ex.: "E-12/345/2026" ou "SEI-123/2026").
        avisar:     callback async opcional para notificar o humano
                    (ex.: enviar_mensagem do Telegram). Recebe (texto: str).
        timeout_captcha: segundos a esperar o humano resolver o desafio.
        usar_cache: se True, devolve cache de até 24h.

    Returns:
        dict com: numero, url, documentos[], texto, cpfs, cnpjs, valores,
        captcha_resolvido (bool), aguardou_humano (bool), erro (se houver).
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
                    "e faça login/abra o portal SEI antes.",
        }

    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    resultado: dict = {"numero": numero, "documentos": [], "texto": "",
                       "captcha_resolvido": False, "aguardou_humano": False}
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

        # 3. CAPTCHA? — humano-no-loop
        captcha = await page.evaluate(_JS_DETECTA_CAPTCHA)
        if captcha.get("presente"):
            resultado["aguardou_humano"] = True
            await _notificar(
                "🔐 *CAPTCHA no SEI*\n\n"
                f"Para ler o processo `{numero}` preciso que você resolva o CAPTCHA "
                "na janela do Chrome (a que está aberta na porta 9222).\n\n"
                f"Tipo: {captcha.get('tipo','?')}. "
                f"Tenho {timeout_captcha//60} min de espera. Assim que você resolver, "
                "eu continuo a leitura sozinho."
            )

            # Aguarda o humano resolver: a página avança (resultado aparece) ou
            # o CAPTCHA some. Faz polling leve até timeout.
            resolvido = await _esperar_humano_resolver(page, timeout_captcha)
            resultado["captcha_resolvido"] = resolvido
            if not resolvido:
                resultado["erro"] = (
                    f"CAPTCHA não foi resolvido dentro de {timeout_captcha//60} min. "
                    "Resolva na janela do Chrome e rode de novo."
                )
                return resultado
            await _notificar(f"✅ CAPTCHA resolvido — lendo o processo `{numero}` na íntegra.")

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

        # 6. Lê o conteúdo de cada documento da árvore (na mesma sessão validada)
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


async def _esperar_humano_resolver(page, timeout: int) -> bool:
    """
    Faz polling leve até o humano resolver o CAPTCHA. Considera resolvido quando:
      - a página passa a mostrar resultado (links/tabela de processo), OU
      - o CAPTCHA desaparece da página.
    NÃO toca no desafio — só observa.
    """
    intervalo = 3
    tentativas = max(1, timeout // intervalo)
    for _ in range(tentativas):
        await asyncio.sleep(intervalo)
        try:
            res = await page.evaluate(_JS_TEM_RESULTADO)
            if res.get("tem"):
                return True
            cap = await page.evaluate(_JS_DETECTA_CAPTCHA)
            if not cap.get("presente"):
                # CAPTCHA sumiu — provavelmente resolvido/aceito
                await asyncio.sleep(2)
                return True
        except Exception:
            continue
    return False


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


# ── Atalho que já notifica via Telegram ───────────────────────────────────────

async def ler_processo_sei(numero_sei: str, **kwargs) -> dict:
    """
    Conveniência: lê o processo via Chrome usando o Telegram como canal de aviso
    do CAPTCHA. Repassa kwargs para ler_processo_sei_via_chrome.
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
        "aguardou_humano": res.get("aguardou_humano"),
        "captcha_resolvido": res.get("captcha_resolvido"),
        "n_documentos": len(res.get("documentos", [])),
        "n_cpfs": len(res.get("cpfs", [])),
        "n_cnpjs": len(res.get("cnpjs", [])),
        "n_valores": len(res.get("valores", [])),
    }, ensure_ascii=False, indent=2))
