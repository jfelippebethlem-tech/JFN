"""
Coletor do Diário Oficial do Estado do RJ (DOERJ) — via Chrome (CDP).

POR QUE CDP E NÃO httpx:
  O site da IOERJ (www.ioerj.com.br) responde 403 Forbidden a requisições
  automatizadas (httpx/requests). Só o Chrome real, já aberto, consegue
  acessar. Por isso este coletor usa o mesmo Chrome (porta 9222) que o
  coletor do SIAFE2 usa.

FLUXO REAL (confirmado por diagnóstico):
  1. A busca por data fica em do_seleciona_data.php (um calendário).
  2. Cada dia aponta para:
       do_seleciona_edicao.php?data=<BASE64(YYYYMMDD)>
     ex.: 01/06/2026 -> data=MjAyNjA2MDE=  (base64 de "20260601")
  3. Essa página lista as edições do dia (Parte I, II, suplementos,
     edições extras) com links para mostra_edicao.php?session=<TOKEN>.
  4. Cada página de edição serve o texto do DO (às vezes via iframe).

Aprendizado: a estrutura da página de edição é salva em
data/diagnostics/ e em data/doerj_learning.json para refino futuro.
"""

import asyncio
import base64
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

CDP_URL = "http://127.0.0.1:9222"
IOERJ = "http://www.ioerj.com.br"
_EDICAO_URL = IOERJ + "/portal/modules/conteudoonline/do_seleciona_edicao.php?data={b64}"

_LEARN_FILE = Path(__file__).parent.parent.parent / "data" / "doerj_learning.json"
_DIAG_DIR = Path(__file__).parent.parent.parent / "data" / "diagnostics"

# ── Regexes de extração ───────────────────────────────────────────────────────

_RE_CPF  = re.compile(r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b")
_RE_CNPJ = re.compile(r"\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\.\s]?\d{4}[-\.\s]?\d{2}\b")
_RE_VALOR = re.compile(r"R\$\s*[\d.,]+(?:\s*(?:mil|milh[õo]es|bilh[õo]es))?")
_RE_SEI_PROC = re.compile(
    r"\b(?:SEI[-\s]*\d|E[-/]\d{1,4}[-/]\d{3,6}[-/]\d{4})\b", re.IGNORECASE
)
_RE_ORGAO = re.compile(
    r"(?m)^[ \t]*(?:SECRETARIA|FUNDA[ÇC][ÃA]O|AUTARQUIA|AG[ÊEẼE]NCIA|INSTITUTO"
    r"|DEPARTAMENTO|COORDENADORIA|SUPERINTEND[ÊEẼE]NCIA|SUBSECRETARIA"
    r"|DIRETORIA|EMPRESA|COMPANHIA)(?:\s+(?:DE|DO|DA|DOS|DAS|ESTADO(?:\s+DO)?))?"
    r"\s+[A-ZÁÉÍÓÚÃÕÇÂÊÎÔÛ].{5,100}",
    re.IGNORECASE,
)
_RE_NUMERO_ATO = re.compile(
    r"(?:PORTARIA|DECRETO|RESOLU[ÇC][ÃA]O|ATO\b|INSTRU[ÇC][ÃA]O\s+NORMATIVA"
    r"|EDITAL|DELIBERA[ÇC][ÃA]O|DESPACHO)\s*N[ºOo°]?\s*[\d.\-/]+(?:/\d{2,4})?",
    re.IGNORECASE,
)
# Lookahead que identifica o início de um novo ato pelo tipo + "Nº"
_RE_ACT_START = re.compile(
    r"(?m)(?=^[ \t]*(?:PORTARIA|RESOLU[ÇC][ÃA]O|DECRETO|ATO\b|EDITAL|EXTRATO"
    r"|AVISO\b|DESPACHO|DELIBERA[ÇC][ÃA]O|INSTRU[ÇC][ÃA]O\s+NORMATIVA"
    r"|LEI\b|CONTRATO\b|CHAMAMENTO|INEXIGIBILIDADE|DISPENSA\b|HOMOLOGA[ÇC][ÃA]O"
    r"|RATIFICA[ÇC][ÃA]O|ANULA[ÇC][ÃA]O|RESULTADO\b|TERMO\b|CONCURSO\b"
    r"|AUTORIZA[ÇC][ÃA]O\b)\s+N[ºOo°]?\s*\d)",
    re.IGNORECASE,
)

_TIPO_KEYWORDS = {
    "nomeação":      ["nomear", "nomeação", "nomeado", "nomeada", "designar", "designação"],
    "exoneração":    ["exonerar", "exoneração", "exonerado", "dispensar", "dispensa"],
    "aposentadoria": ["aposentar", "aposentadoria", "aposentado"],
    "contrato":      ["contrato n", "celebração de contrato", "rescisão contratual", "termo aditivo"],
    "licitação":     ["pregão", "concorrência", "licitação", "edital", "tomada de preço",
                      "dispensa", "inexigibilidade"],
    "pensão":        ["pensão por morte", "pensionista", "beneficiário de pensão"],
    "cessão":        ["cessão", "cedido"],
    "gratificação":  ["gratificação", "adicional", "vantagem"],
    "decreto":       ["decreto nº", "decreto n."],
    "portaria":      ["portaria nº", "portaria n."],
    "resolução":     ["resolução nº", "resolução n."],
}

_EXTRA_KEYWORDS = ["extra", "suplemento", "suplementar", "extraordin", "especial"]


# ── Helpers de extração ───────────────────────────────────────────────────────

def _b64_data(d: date) -> str:
    return base64.b64encode(d.strftime("%Y%m%d").encode()).decode()


def classificar_tipo_ato(texto: str) -> str:
    t = texto.lower()
    for tipo, kws in _TIPO_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return tipo
    return "outros"


def extrair_cpfs(texto: str) -> list[str]:
    return [re.sub(r"\D", "", m) for m in _RE_CPF.findall(texto)
            if len(re.sub(r"\D", "", m)) == 11]


def extrair_cnpjs(texto: str) -> list[str]:
    return [re.sub(r"\D", "", m) for m in _RE_CNPJ.findall(texto)
            if len(re.sub(r"\D", "", m)) == 14]


def extrair_valores(texto: str) -> list[str]:
    return list(dict.fromkeys(_RE_VALOR.findall(texto)))[:30]


def extrair_processos_sei(texto: str) -> list[str]:
    return list(dict.fromkeys(_RE_SEI_PROC.findall(texto)))[:20]


def _extrair_orgao(texto: str) -> str:
    m = _RE_ORGAO.search(texto[:600])
    return m.group(0).strip()[:200] if m else ""


def _extrair_numero_ato(texto: str) -> str:
    m = _RE_NUMERO_ATO.search(texto[:300])
    return m.group(0).strip()[:150] if m else ""


def _inferir_secao(edicao: str, titulo: str) -> str:
    s = (edicao + " " + titulo).lower()
    if "parte i" in s or "seção i" in s or "secao i" in s:
        return "I"
    if "parte ii" in s or "seção ii" in s:
        return "II"
    if "parte iii" in s:
        return "III"
    if "extra" in s or "suplemento" in s or "supl" in s:
        return "E"
    return "I"


def _pub_dict(texto: str, data: date, url: str,
              edicao: str = "", titulo: str = "") -> dict:
    return {
        "data_publicacao":         data.isoformat(),
        "edicao":                  edicao,
        "secao":                   _inferir_secao(edicao, titulo),
        "orgao":                   _extrair_orgao(texto),
        "tipo_ato":                classificar_tipo_ato(texto),
        "numero_ato":              _extrair_numero_ato(texto),
        "titulo":                  (titulo or texto[:200])[:500],
        "texto":                   texto[:8000],
        "cpfs_extraidos":          json.dumps(extrair_cpfs(texto)),
        "cnpjs_extraidos":         json.dumps(extrair_cnpjs(texto)),
        "valores_extraidos":       json.dumps(extrair_valores(texto)),
        "processos_sei_extraidos": json.dumps(extrair_processos_sei(texto)),
        "url_fonte":               url,
    }


def _load_learning() -> dict:
    try:
        if _LEARN_FILE.exists():
            return json.loads(_LEARN_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"edicoes_por_data": {}, "errors": []}


def _save_learning(state: dict):
    try:
        _LEARN_FILE.parent.mkdir(exist_ok=True)
        _LEARN_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ── JavaScript injetado no Chrome ────────────────────────────────────────────

_JS_EXTRACT = r"""
() => {
    // Tenta o painel de conteúdo específico do IOERJ; fallback para body
    const painel = document.querySelector(
        '#conteudo_diario, .diario-conteudo, .conteudo_edicao, '
        + '#txtConteudo, .texto-edicao, '
        + 'div[class*="conteudo"], div[id*="conteudo"], '
        + 'div[class*="diario"], div[id*="diario"]'
    );
    const corpo = painel
        ? painel.innerText
        : (document.body ? document.body.innerText : '');
    const links = [];
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        const txt  = (a.textContent || '').trim();
        if (!href || href.startsWith('#') || href.startsWith('javascript')) continue;
        links.push({text: txt.substring(0, 120), href: href});
    }
    return {
        url:        location.href,
        title:      document.title,
        text:       corpo.substring(0, 120000),
        links:      links.slice(0, 400),
        has_iframe: !!document.querySelector('iframe'),
    };
}
"""

_JS_LE_IFRAME = r"""
() => {
    for (const f of document.querySelectorAll('iframe')) {
        try {
            const doc = f.contentDocument || (f.contentWindow && f.contentWindow.document);
            if (doc && doc.body) {
                const txt = doc.body.innerText || '';
                if (txt.length > 300) {
                    return {
                        source: 'iframe',
                        src:    f.src || f.getAttribute('src') || '',
                        text:   txt.substring(0, 120000),
                    };
                }
            }
        } catch(e) {}
    }
    return null;
}
"""


class DOERJCollector:
    """Coleta o DOERJ pelo Chrome aberto (CDP), sem esbarrar no 403."""

    def __init__(self, session=None):
        self._session = session
        self._state = _load_learning()

    # ── API pública ───────────────────────────────────────────────────────────

    async def coletar_hoje(self) -> list:
        return await self.coletar_data(date.today())

    async def coletar_data(self, data: date) -> list:
        """Coleta todas as edições de um dia específico."""
        from playwright.async_api import async_playwright

        publicacoes: list[dict] = []
        erros: list[str] = []

        p = await async_playwright().start()
        browser = None
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"[DOERJ] Chrome não acessível via CDP: {e}")
            await p.stop()
            self._registrar_erros(data, [f"CDP: {e}"])
            return publicacoes

        page = None
        try:
            ctx  = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()

            b64 = _b64_data(data)
            url = _EDICAO_URL.format(b64=b64)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                erros.append(f"goto edicao: {type(e).__name__}: {e}")
            await asyncio.sleep(2.5)

            dump = await page.evaluate(_JS_EXTRACT)
            self._salvar_diagnostico(data, dump)

            edicoes = self._filtrar_links_edicao(dump.get("links", []))
            if not edicoes:
                txt = dump.get("text", "")
                if "não há" in txt.lower() or "nao ha" in txt.lower() or len(txt) < 200:
                    print(f"[DOERJ] {data}: nenhuma edição encontrada (dia sem publicação?)")
                else:
                    erros.append(f"nenhum link de edição reconhecido em {url}")
                    if txt:
                        publicacoes.append(_pub_dict(txt, data, url, titulo="Página de edição"))

            for ed in edicoes[:12]:
                ed_url = self._abs(ed["href"])
                is_extra = any(k in ed["text"].lower() for k in _EXTRA_KEYWORDS)
                try:
                    pubs = await self._ler_pagina_edicao(
                        page, ed_url, data,
                        edicao="extra" if is_extra else "normal",
                        titulo=ed["text"],
                    )
                    publicacoes.extend(pubs)
                    print(f"[DOERJ] {data}: '{ed['text'][:40]}' "
                          f"→ {len(pubs)} atos ({'EXTRA' if is_extra else 'normal'})")
                except Exception as e:
                    erros.append(f"edição {ed_url[:60]}: {type(e).__name__}: {e}")

            self._state.setdefault("edicoes_por_data", {})[data.isoformat()] = {
                "n_edicoes": len(edicoes),
                "titulos":   [e["text"][:60] for e in edicoes],
                "ts":        datetime.now().isoformat(),
            }
            _save_learning(self._state)

        except Exception as e:
            erros.append(f"geral: {type(e).__name__}: {e}")
        finally:
            if page:
                try: await page.close()
                except Exception: pass
            try: await p.stop()
            except Exception: pass

        if erros:
            print(f"[DOERJ] Avisos em {data}: {erros}")
            self._registrar_erros(data, erros)

        if self._session and publicacoes:
            self._salvar_publicacoes(publicacoes)
        return publicacoes

    async def coletar_edicao_url(
        self,
        url_edicao: str,
        data: Optional[date] = None,
        edicao: str = "normal",
        titulo: str = "",
    ) -> list[dict]:
        """
        Lê uma edição específica diretamente pelo URL completo.
        Aceita URLs do tipo mostra_edicao.php?session=... ou qualquer
        página do IOERJ que contenha o texto do DO.
        """
        from playwright.async_api import async_playwright

        p = await async_playwright().start()
        pubs: list[dict] = []
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            ctx  = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()
            d = data or date.today()

            pubs = await self._ler_pagina_edicao(page, url_edicao, d,
                                                  edicao=edicao, titulo=titulo)
            print(f"[DOERJ] coletar_edicao_url: {len(pubs)} atos de {url_edicao[:60]}")
            try: await page.close()
            except Exception: pass
        except Exception as e:
            print(f"[DOERJ] Erro em coletar_edicao_url: {e}")
        finally:
            try: await p.stop()
            except Exception: pass

        if self._session and pubs:
            self._salvar_publicacoes(pubs)
        return pubs

    async def coletar_periodo(
        self,
        data_inicio: date,
        data_fim: Optional[date] = None,
        delay: float = 2.0,
    ) -> list:
        if data_fim is None:
            data_fim = date.today()
        todas = []
        atual = data_inicio
        while atual <= data_fim:
            print(f"[DOERJ] Coletando {atual.isoformat()}...")
            todas.extend(await self.coletar_data(atual))
            atual += timedelta(days=1)
            await asyncio.sleep(delay)
        return todas

    # ── Leitura de uma página de edição ───────────────────────────────────────

    async def _ler_pagina_edicao(
        self,
        page,
        url: str,
        data: date,
        edicao: str,
        titulo: str,
    ) -> list[dict]:
        """Navega para url, extrai texto (incluindo iframe se necessário), fatia atos."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[DOERJ] goto {url[:60]}: {e}")
            return []
        await asyncio.sleep(2.5)

        dump = await page.evaluate(_JS_EXTRACT)
        texto = dump.get("text", "")

        # Se a página está vazia, tenta iframe (padrão antigo do IOERJ)
        if len(texto) < 300 and dump.get("has_iframe"):
            iframe_info = await page.evaluate(_JS_LE_IFRAME)
            if iframe_info:
                texto = iframe_info.get("text", texto)
                # Se o iframe tem src próprio, navega para ter mais contexto
                src = iframe_info.get("src", "")
                if src and len(src) > 5:
                    abs_src = self._abs(src)
                    try:
                        await page.goto(abs_src, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(2)
                        dump2 = await page.evaluate(_JS_EXTRACT)
                        if len(dump2.get("text", "")) > len(texto):
                            texto = dump2["text"]
                    except Exception:
                        pass

        self._salvar_diagnostico(data, {**dump, "text_head": texto[:1500], "url_edicao": url})

        if len(texto) < 80:
            return []

        titulo_efetivo = titulo or dump.get("title", "")
        return self._fatiar_atos(texto, data, url, edicao=edicao, titulo=titulo_efetivo)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _abs(self, href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return IOERJ + href
        return f"{IOERJ}/portal/modules/conteudoonline/{href.lstrip('/')}"

    def _filtrar_links_edicao(self, links: list[dict]) -> list[dict]:
        """Filtra os links que apontam para edições do DO, descarta navegação."""
        out, seen = [], set()
        for lk in links:
            href = lk.get("href", "")
            low  = href.lower()
            # Descarta navegação conhecida
            if any(x in low for x in [
                "do_seleciona_data", "do_seleciona_edicao",
                "facebook", "instagram", "linkedin", "login", "admin",
                "user.php", "busca_do", "index.php?id=",
            ]):
                continue
            # Candidatos a conteúdo de edição
            if any(x in low for x in [
                "mostra_edicao", "conteudoonline", "mostraconteudo", "do_",
                ".pdf", "edicao", "caderno", "parte", "session=",
            ]):
                if href not in seen:
                    seen.add(href)
                    out.append({"text": lk.get("text", ""), "href": href})
        return out

    def _fatiar_atos(
        self, texto: str, data: date, url: str, edicao: str, titulo: str
    ) -> list[dict]:
        """
        Divide o texto da edição em atos individuais.

        Estratégia em cascata:
          1. Lookahead nos tipos de ato + "Nº" (mais preciso)
          2. Parágrafos separados por 3+ quebras de linha
          3. Parágrafos separados por 2 quebras de linha
          4. Fallback: publicação única com o texto inteiro
        """
        partes = _RE_ACT_START.split(texto)
        if len(partes) <= 2:
            partes = re.split(r"\n[ \t]*\n[ \t]*\n", texto)
        if len(partes) <= 2:
            partes = re.split(r"\n[ \t]*\n", texto)

        ed_nome = (titulo or "")[:40]
        pubs = []

        for parte in partes:
            t = parte.strip()
            if len(t) < 80:
                continue
            numero   = _extrair_numero_ato(t)
            primeira = " ".join(t[:90].split())
            if numero:
                titulo_ato = numero + (f" — {ed_nome}" if ed_nome else "")
            else:
                titulo_ato = f"{ed_nome} | {primeira}" if ed_nome else primeira
            pub = _pub_dict(t, data, url, edicao=edicao, titulo=titulo_ato)
            pubs.append(pub)

        if not pubs:
            primeira   = " ".join(texto[:90].split())
            titulo_ato = f"{ed_nome} | {primeira}" if ed_nome else primeira
            pubs.append(_pub_dict(texto, data, url, edicao=edicao, titulo=titulo_ato))

        return pubs[:500]

    def _salvar_diagnostico(self, data: date, dump: dict):
        try:
            _DIAG_DIR.mkdir(parents=True, exist_ok=True)
            f = _DIAG_DIR / f"doerj_edicao_{data.isoformat()}.json"
            f.write_text(json.dumps({
                "url":       dump.get("url"),
                "title":     dump.get("title"),
                "n_links":   len(dump.get("links", [])),
                "links":     dump.get("links", [])[:80],
                "text_head": dump.get("text_head") or dump.get("text", "")[:1500],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _registrar_erros(self, data: date, erros: list[str]):
        self._state.setdefault("errors", []).append({
            "data": data.isoformat(), "erros": erros, "ts": datetime.now().isoformat(),
        })
        self._state["errors"] = self._state["errors"][-30:]
        _save_learning(self._state)

    def _salvar_publicacoes(self, publicacoes: list[dict]):
        from compliance_agent.database.models import PublicacaoDOERJ
        novos = 0
        for pub in publicacoes:
            try:
                d = date.fromisoformat(pub["data_publicacao"])
                existe = self._session.query(PublicacaoDOERJ).filter_by(
                    data_publicacao=d,
                    titulo=pub["titulo"][:500],
                ).first()
                if not existe:
                    self._session.add(PublicacaoDOERJ(
                        data_publicacao         = d,
                        edicao                  = pub.get("edicao", ""),
                        secao                   = pub.get("secao", "I"),
                        orgao                   = pub.get("orgao", "")[:200],
                        tipo_ato                = pub.get("tipo_ato", "outros"),
                        numero_ato              = (pub.get("numero_ato") or "")[:150],
                        titulo                  = pub.get("titulo", "")[:500],
                        texto                   = pub.get("texto", ""),
                        cpfs_extraidos          = pub.get("cpfs_extraidos", "[]"),
                        cnpjs_extraidos         = pub.get("cnpjs_extraidos", "[]"),
                        valores_extraidos       = pub.get("valores_extraidos", "[]"),
                        processos_sei_extraidos = pub.get("processos_sei_extraidos", "[]"),
                        url_fonte               = pub.get("url_fonte", ""),
                    ))
                    novos += 1
            except Exception as e:
                print(f"[DOERJ] Erro ao salvar: {e}")
        self._session.commit()
        if novos:
            print(f"[DOERJ] {novos} publicações novas salvas no banco")


if __name__ == "__main__":
    import sys
    from compliance_agent.database.models import get_session, init_db
    init_db()
    s = get_session()
    c = DOERJCollector(s)

    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg.startswith("http"):
        # Ler edição diretamente por URL
        pubs = asyncio.run(c.coletar_edicao_url(arg))
        print(f"DOERJ (URL direto): {len(pubs)} atos")
        for p in pubs[:5]:
            print(f"  [{p['tipo_ato']}] {p['titulo'][:80]}")
            if p.get('cpfs_extraidos') and p['cpfs_extraidos'] != '[]':
                print(f"    CPFs: {p['cpfs_extraidos']}")
            if p.get('valores_extraidos') and p['valores_extraidos'] != '[]':
                print(f"    Valores: {p['valores_extraidos']}")
    else:
        alvo = date.today()
        if arg:
            try:
                alvo = date.fromisoformat(arg)
            except ValueError:
                pass
        pubs = asyncio.run(c.coletar_data(alvo))
        print(f"DOERJ {alvo}: {len(pubs)} publicações")
        for p in pubs[:5]:
            print(f"  [{p['tipo_ato']}] {p['titulo'][:80]}")
