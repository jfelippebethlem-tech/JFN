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
     edições extras). Seguimos os links para extrair o conteúdo.

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

_RE_CPF  = re.compile(r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b")
_RE_CNPJ = re.compile(r"\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\.\s]?\d{4}[-\.\s]?\d{2}\b")

_TIPO_KEYWORDS = {
    "nomeação":      ["nomear", "nomeação", "nomeado", "nomeada", "designar", "designação"],
    "exoneração":    ["exonerar", "exoneração", "exonerado", "dispensar", "dispensa"],
    "aposentadoria": ["aposentar", "aposentadoria", "aposentado"],
    "contrato":      ["contrato n", "celebração de contrato", "rescisão contratual", "termo aditivo"],
    "licitação":     ["pregão", "concorrência", "licitação", "edital", "tomada de preço"],
    "pensão":        ["pensão por morte", "pensionista", "beneficiário de pensão"],
    "cessão":        ["cessão", "cedido"],
    "gratificação":  ["gratificação", "adicional", "vantagem"],
}

_EXTRA_KEYWORDS = ["extra", "suplemento", "suplementar", "extraordin", "especial"]


def _b64_data(d: date) -> str:
    return base64.b64encode(d.strftime("%Y%m%d").encode()).decode()


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
        _LEARN_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


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


def _pub_dict(texto: str, data: date, url: str, edicao: str = "", titulo: str = "") -> dict:
    return {
        "data_publicacao": data.isoformat(),
        "edicao":          edicao,
        "secao":           "1",
        "tipo_ato":        classificar_tipo_ato(texto),
        "titulo":          (titulo or texto[:200])[:500],
        "texto":           texto[:5000],
        "cpfs_extraidos":  json.dumps(extrair_cpfs(texto)),
        "cnpjs_extraidos": json.dumps(extrair_cnpjs(texto)),
        "url_fonte":       url,
    }


# JS genérico: extrai links + texto da página atual ───────────────────────────
_JS_EXTRACT = r"""
() => {
    const links = [];
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        const txt = (a.textContent || '').trim();
        if (!href || href.startsWith('#') || href.startsWith('javascript')) continue;
        links.push({text: txt.substring(0, 120), href: href});
    }
    return {
        url: location.href,
        title: document.title,
        text: (document.body ? document.body.innerText : '').substring(0, 60000),
        links: links.slice(0, 300),
    };
}
"""


class DOERJCollector:
    """Coleta o DOERJ pelo Chrome aberto (CDP), sem esbarrar no 403."""

    def __init__(self, session=None):
        self._session = session
        self._state = _load_learning()

    async def coletar_hoje(self) -> list:
        return await self.coletar_data(date.today())

    async def coletar_data(self, data: date) -> list:
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
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()

            b64 = _b64_data(data)
            url = _EDICAO_URL.format(b64=b64)
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                erros.append(f"goto edicao: {type(e).__name__}: {e}")
            await asyncio.sleep(2.5)

            dump = await page.evaluate(_JS_EXTRACT)
            self._salvar_diagnostico(data, dump)

            edicoes = self._filtrar_links_edicao(dump.get("links", []))
            if not edicoes:
                # Pode não haver edição nesse dia (fim de semana/feriado)
                txt = dump.get("text", "")
                if "não há" in txt.lower() or "nao ha" in txt.lower() or len(txt) < 200:
                    print(f"[DOERJ] {data}: nenhuma edição encontrada (dia sem publicação?)")
                else:
                    erros.append(f"nenhum link de edição reconhecido em {url}")
                    # ainda assim extrai CPFs/CNPJs do que tiver
                    if dump.get("text"):
                        publicacoes.append(_pub_dict(dump["text"], data, url, titulo="Página de edição"))

            # Segue cada edição (limitado) e extrai o conteúdo
            for ed in edicoes[:12]:
                ed_url = self._abs(ed["href"])
                is_extra = any(k in ed["text"].lower() for k in _EXTRA_KEYWORDS)
                try:
                    await page.goto(ed_url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(2)
                    ed_dump = await page.evaluate(_JS_EXTRACT)
                    texto = ed_dump.get("text", "")
                    if len(texto) >= 100:
                        pubs = self._fatiar_atos(texto, data, ed_url,
                                                 edicao="extra" if is_extra else "normal",
                                                 titulo=ed["text"])
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {data}: edição '{ed['text'][:40]}' "
                              f"-> {len(pubs)} atos ({'EXTRA' if is_extra else 'normal'})")
                except Exception as e:
                    erros.append(f"edição {ed_url[:60]}: {type(e).__name__}: {e}")

            # Registra no aprendizado quantas edições teve nesse dia
            self._state.setdefault("edicoes_por_data", {})[data.isoformat()] = {
                "n_edicoes": len(edicoes),
                "titulos": [e["text"][:60] for e in edicoes],
                "ts": datetime.now().isoformat(),
            }
            _save_learning(self._state)

        except Exception as e:
            erros.append(f"geral: {type(e).__name__}: {e}")
        finally:
            try:
                if page:
                    await page.close()
            except Exception:
                pass
            try:
                await p.stop()
            except Exception:
                pass

        if erros:
            print(f"[DOERJ] Avisos em {data}: {erros}")
            self._registrar_erros(data, erros)

        if self._session and publicacoes:
            self._salvar_publicacoes(publicacoes)

        return publicacoes

    async def coletar_periodo(self, data_inicio: date,
                              data_fim: Optional[date] = None,
                              delay: float = 2.0) -> list:
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _abs(self, href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return IOERJ + href
        return f"{IOERJ}/portal/modules/conteudoonline/{href.lstrip('/')}"

    def _filtrar_links_edicao(self, links: list[dict]) -> list[dict]:
        """
        Filtra os links que apontam para edições/conteúdo do DO, descartando
        navegação (calendário, menu, redes sociais, login).
        """
        out = []
        seen = set()
        for l in links:
            href = l.get("href", "")
            txt = l.get("text", "")
            low = href.lower()
            # descartar navegação conhecida
            if any(x in low for x in [
                "do_seleciona_data", "do_seleciona_edicao",  # calendário/dias
                "facebook", "instagram", "linkedin", "login", "admin",
                "user.php", "busca_do", "index.php?id=", "portal.ioerj",
            ]):
                continue
            # candidatos a edição/conteúdo
            if any(x in low for x in [
                "conteudoonline", "mostraconteudo", "do_", ".pdf", "edicao", "caderno", "parte"
            ]):
                if href not in seen:
                    seen.add(href)
                    out.append({"text": txt, "href": href})
        return out

    def _fatiar_atos(self, texto: str, data: date, url: str,
                     edicao: str, titulo: str) -> list[dict]:
        """
        Divide o texto da edição em 'atos' por marcadores comuns do DO.
        Se não houver marcadores claros, salva como uma publicação única.
        """
        # Marcadores típicos de início de ato
        partes = re.split(
            r"(?=\b(?:PORTARIA|RESOLUÇÃO|DECRETO|ATO|EDITAL|EXTRATO|AVISO|"
            r"DESPACHO|ORDEM DE SERVIÇO|DELIBERAÇÃO)\b)",
            texto,
        )
        pubs = []
        ed_nome = (titulo or "")[:40]
        for i, parte in enumerate(partes):
            t = parte.strip()
            if len(t) < 120:
                continue
            # Título único por ato (senão a deduplicação data+titulo colapsa
            # todos os atos da mesma edição em um só registro).
            primeira = " ".join(t[:90].split())
            titulo_ato = f"{ed_nome} | {primeira}" if ed_nome else primeira
            pubs.append(_pub_dict(t, data, url, edicao=edicao, titulo=titulo_ato))
        if not pubs:
            primeira = " ".join(texto[:90].split())
            titulo_ato = f"{ed_nome} | {primeira}" if ed_nome else primeira
            pubs.append(_pub_dict(texto, data, url, edicao=edicao, titulo=titulo_ato))
        return pubs[:500]

    def _salvar_diagnostico(self, data: date, dump: dict):
        try:
            _DIAG_DIR.mkdir(parents=True, exist_ok=True)
            f = _DIAG_DIR / f"doerj_edicao_{data.isoformat()}.json"
            f.write_text(json.dumps({
                "url": dump.get("url"),
                "title": dump.get("title"),
                "n_links": len(dump.get("links", [])),
                "links": dump.get("links", [])[:80],
                "text_head": dump.get("text", "")[:1000],
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
                    data_publicacao=d, titulo=pub["titulo"][:500],
                ).first()
                if not existe:
                    self._session.add(PublicacaoDOERJ(
                        data_publicacao=d,
                        edicao=pub.get("edicao", ""),
                        secao=pub.get("secao", "1"),
                        tipo_ato=pub.get("tipo_ato", "outros"),
                        titulo=pub.get("titulo", "")[:500],
                        texto=pub.get("texto", ""),
                        cpfs_extraidos=pub.get("cpfs_extraidos", "[]"),
                        cnpjs_extraidos=pub.get("cnpjs_extraidos", "[]"),
                        url_fonte=pub.get("url_fonte", ""),
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
    alvo = date.today()
    if len(sys.argv) > 1:
        alvo = date.fromisoformat(sys.argv[1])
    pubs = asyncio.run(c.coletar_data(alvo))
    print(f"DOERJ {alvo}: {len(pubs)} publicações")
