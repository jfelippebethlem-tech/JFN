"""
Coletor do Diário Oficial do Estado do Rio de Janeiro (DOERJ).

Fonte primária: IOERJ — Imprensa Oficial do Estado do RJ
  https://www.ioerj.com.br/portal/modules/content/index.php?id=61

Estratégia de coleta (em ordem):
  1. Página oficial de busca do DOERJ (?id=61): envia o formulário com a data.
  2. Listagem anual de edições para descobrir URL da edição da data.
  3. Busca textual no site da IOERJ.
  4. Mapeamento autônomo da estrutura do site (aprendizado).

O bot aprende: padrões que funcionam são salvos em data/doerj_learning.json.
"""

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup


# ── Regex utilitários ─────────────────────────────────────────────────────────
_RE_CPF  = re.compile(r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b")
_RE_CNPJ = re.compile(r"\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\.\s]?\d{4}[-\.\s]?\d{2}\b")

_TIPO_KEYWORDS = {
    "nomeação":      ["nomear", "nomeação", "nomeado", "nomeada", "designar", "designação"],
    "exoneração":    ["exonerar", "exoneração", "exonerado", "dispensar", "dispensa"],
    "aposentadoria": ["aposentar", "aposentadoria", "aposentado"],
    "contrato":      ["contrato n°", "contrato nº", "celebração de contrato", "rescisão contratual"],
    "licitação":     ["pregão", "concorrência", "licitação", "edital", "tomada de preço", "dispensa"],
    "pensão":        ["pensão por morte", "pensionista", "beneficiário de pensão"],
    "cessão":        ["ceder", "cessão", "cedido"],
    "gratificação":  ["gratificação", "adicional", "vantagem"],
}

_LEARN_FILE = Path(__file__).parent.parent.parent / "data" / "doerj_learning.json"

# ── Headers que imitam um navegador real ─────────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.ioerj.com.br/",
}

IOERJ_BASE = "https://www.ioerj.com.br"
IOERJ_HTTP = "http://www.ioerj.com.br"   # fallback sem SSL

# Página oficial de busca do DOERJ (fornecida pelo usuário)
IOERJ_BUSCA_URL = "{base}/portal/modules/content/index.php?id=61"


def _load_learning() -> dict:
    try:
        if _LEARN_FILE.exists():
            return json.loads(_LEARN_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"working_patterns": [], "edition_map": {}, "errors": []}


def _save_learning(state: dict):
    try:
        _LEARN_FILE.parent.mkdir(exist_ok=True)
        _LEARN_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def classificar_tipo_ato(texto: str) -> str:
    texto_lower = texto.lower()
    for tipo, keywords in _TIPO_KEYWORDS.items():
        if any(kw in texto_lower for kw in keywords):
            return tipo
    return "outros"


def extrair_cpfs(texto: str) -> list[str]:
    matches = _RE_CPF.findall(texto)
    return [re.sub(r"\D", "", m) for m in matches if len(re.sub(r"\D", "", m)) == 11]


def extrair_cnpjs(texto: str) -> list[str]:
    matches = _RE_CNPJ.findall(texto)
    return [re.sub(r"\D", "", m) for m in matches if len(re.sub(r"\D", "", m)) == 14]


def _pub_dict(texto: str, data: date, url: str, secao: str = "1") -> dict:
    return {
        "data_publicacao": data.isoformat(),
        "secao":           secao,
        "tipo_ato":        classificar_tipo_ato(texto),
        "titulo":          texto[:200],
        "texto":           texto[:3000],
        "cpfs_extraidos":  json.dumps(extrair_cpfs(texto)),
        "cnpjs_extraidos": json.dumps(extrair_cnpjs(texto)),
        "url_fonte":       url,
    }


async def _detect_base(timeout: float = 6.0) -> str:
    """Descobre se HTTPS funciona; retorna IOERJ_BASE ou IOERJ_HTTP."""
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as c:
            r = await c.get(IOERJ_BASE + "/")
            if r.status_code < 500:
                return IOERJ_BASE
    except Exception as e:
        cause = getattr(e, "__cause__", None) or e
        print(f"[DOERJ] HTTPS falhou ({type(cause).__name__}), tentando HTTP...")
    return IOERJ_HTTP


class DOERJCollector:
    """
    Coleta publicações do DOERJ direto da Imprensa Oficial (IOERJ).
    Estratégias em ordem: página de busca oficial → listagem anual →
    busca textual → mapeamento autônomo do site.
    """

    def __init__(self, session=None):
        self._session = session
        self._state = _load_learning()
        self._base: Optional[str] = None   # definido em coletar_data após probe

    async def coletar_hoje(self) -> list:
        return await self.coletar_data(date.today())

    async def coletar_data(self, data: date) -> list:
        publicacoes = []
        erros = []

        self._base = await _detect_base()

        async with httpx.AsyncClient(
            timeout=30,
            headers=_HEADERS,
            follow_redirects=True,
            verify=False,
        ) as client:

            # 0. Padrão aprendido em sessão anterior (mais rápido)
            for pattern_info in self._state.get("working_patterns", []):
                try:
                    url = self._fmt_url(pattern_info["url"], data)
                    pubs = await self._get_and_parse(client, url, data)
                    if pubs:
                        print(f"[DOERJ] {len(pubs)} pub via padrão salvo")
                        publicacoes.extend(pubs)
                        break
                except Exception as e:
                    erros.append(f"padrão salvo: {type(e).__name__}: {e}")

            # 1. Página oficial de busca (id=61)
            if not publicacoes:
                try:
                    pubs = await self._coletar_via_busca_oficial(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} pub via busca oficial (id=61)")
                except Exception as e:
                    erros.append(f"busca_oficial: {type(e).__name__}: {e}")

            # 2. Listagem anual → número de edição → conteúdo
            if not publicacoes:
                try:
                    pubs = await self._coletar_via_listagem(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} pub via listagem anual")
                except Exception as e:
                    erros.append(f"listagem: {type(e).__name__}: {e}")

            # 3. Busca textual
            if not publicacoes:
                try:
                    pubs = await self._coletar_via_busca_texto(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} pub via busca textual")
                except Exception as e:
                    erros.append(f"busca_texto: {type(e).__name__}: {e}")

            # 4. Mapeamento autônomo (aprende estrutura do site)
            if not publicacoes:
                try:
                    pubs = await self._aprender_estrutura(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} pub via aprendizado")
                except Exception as e:
                    erros.append(f"aprendizado: {type(e).__name__}: {e}")

        if erros:
            print(f"[DOERJ] Erros na coleta de {data}: {erros}")
            self._state.setdefault("errors", []).append({
                "data": data.isoformat(),
                "erros": erros,
                "ts": datetime.now().isoformat(),
            })
            self._state["errors"] = self._state["errors"][-20:]
            _save_learning(self._state)

        return publicacoes

    async def coletar_periodo(
        self,
        data_inicio: date,
        data_fim: Optional[date] = None,
        delay: float = 2.0,
    ) -> list:
        if data_fim is None:
            data_fim = date.today()
        todas = []
        current = data_inicio
        while current <= data_fim:
            print(f"[DOERJ] Coletando {current.isoformat()}...")
            pubs = await self.coletar_data(current)
            todas.extend(pubs)
            if self._session:
                self._salvar_publicacoes(pubs)
            current += timedelta(days=1)
            await asyncio.sleep(delay)
        return todas

    # ── Estratégia 1: página oficial de busca (id=61) ─────────────────────────

    async def _coletar_via_busca_oficial(
        self, client: httpx.AsyncClient, data: date
    ) -> list:
        """
        Usa a página oficial de busca do DOERJ:
        https://www.ioerj.com.br/portal/modules/content/index.php?id=61
        Carrega o formulário, descobre os campos de data e envia.
        """
        busca_url = IOERJ_BUSCA_URL.format(base=self._base)

        # Carrega a página de busca para inspecionar o formulário
        resp = await client.get(busca_url)
        if resp.status_code != 200:
            raise Exception(f"busca_oficial retornou HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")

        pubs = []

        if form:
            # Monta os dados do formulário com a data alvo
            form_data: dict = {}
            action = form.get("action", busca_url)
            if action and not action.startswith("http"):
                action = f"{self._base}/{action.lstrip('/')}"

            for inp in form.find_all(["input", "select", "textarea"]):
                name = inp.get("name")
                if not name:
                    continue
                val = inp.get("value", "")
                # Detectar campos de data pelo nome ou label próximo
                name_lower = name.lower()
                if any(k in name_lower for k in ["dat", "inicio", "fim", "de", "ate", "data"]):
                    # Tentar inferir se é data início ou fim
                    if any(k in name_lower for k in ["fim", "ate", "final", "f_"]):
                        val = data.strftime("%d/%m/%Y")
                    else:
                        val = data.strftime("%d/%m/%Y")
                form_data[name] = val

            method = (form.get("method") or "get").lower()
            try:
                if method == "post":
                    resp2 = await client.post(action, data=form_data)
                else:
                    resp2 = await client.get(action, params=form_data)

                if resp2.status_code == 200 and len(resp2.text) > 300:
                    pubs = self._parse_html_ioerj(resp2.text, data, resp2.url.__str__())
                    if pubs:
                        self._salvar_padrao(IOERJ_BUSCA_URL, "busca_oficial")
            except Exception as e:
                raise Exception(f"submit form: {e}") from e

        # Mesmo sem form, pode haver conteúdo direto na página
        if not pubs:
            pubs = self._parse_html_ioerj(resp.text, data, busca_url)

        # Procurar links de edição na resposta que correspondam à data
        if not pubs:
            pubs = await self._seguir_links_data(client, resp.text, data, busca_url)

        return pubs

    async def _seguir_links_data(
        self,
        client: httpx.AsyncClient,
        html: str,
        data: date,
        base_url: str,
    ) -> list:
        """Procura na página links que correspondam à data e tenta acessá-los."""
        soup = BeautifulSoup(html, "html.parser")
        data_br = data.strftime("%d/%m/%Y")
        data_iso = data.isoformat()
        pubs = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            ctx = (a.get_text(" ", strip=True) + " " +
                   (a.parent.get_text(" ", strip=True) if a.parent else ""))
            if data_br in ctx or data_iso in ctx or data_br.replace("/", "") in href:
                full = href if href.startswith("http") else f"{self._base}/{href.lstrip('/')}"
                try:
                    r = await client.get(full)
                    if r.status_code == 200:
                        p = self._parse_html_ioerj(r.text, data, full)
                        if p:
                            pubs.extend(p)
                            self._salvar_padrao(full, "link_data")
                except Exception:
                    pass
        return pubs

    # ── Estratégia 2: listagem anual → número de edição ──────────────────────

    async def _coletar_via_listagem(self, client: httpx.AsyncClient, data: date) -> list:
        year = data.year
        list_url = f"{self._base}/portal/modules/conteudoonline/listaConteudo.php?e=01&a={year}"

        resp = await client.get(list_url)
        if resp.status_code != 200:
            raise Exception(f"listagem HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")
        data_str_br = data.strftime("%d/%m/%Y")

        edition_url = None
        for row in soup.find_all(["tr", "li", "div", "a"]):
            row_text = row.get_text(" ", strip=True)
            if data_str_br in row_text:
                a_tag = row.find("a", href=True) if row.name != "a" else row
                if a_tag and a_tag.get("href"):
                    href = a_tag["href"]
                    edition_url = href if href.startswith("http") else f"{self._base}{href}"
                    break

        if not edition_url:
            raise Exception(f"edição de {data_str_br} não encontrada na listagem")

        resp2 = await client.get(edition_url)
        if resp2.status_code != 200:
            raise Exception(f"edição URL retornou {resp2.status_code}")

        pubs = self._parse_html_ioerj(resp2.text, data, edition_url)
        if pubs:
            self._salvar_padrao(edition_url, "listagem_anual")
        return pubs

    # ── Estratégia 3: busca textual ────────────────────────────────────────────

    async def _coletar_via_busca_texto(self, client: httpx.AsyncClient, data: date) -> list:
        termos = ["nomeação", "contrato", "licitação"]
        pubs = []
        for termo in termos:
            try:
                url = (
                    f"{self._base}/portal/modules/conteudoonline/busca.php"
                    f"?q={termo}&e=01&a={data.year}"
                    f"&di={data.strftime('%d/%m/%Y')}"
                    f"&df={data.strftime('%d/%m/%Y')}"
                )
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.text) > 500:
                    p = self._parse_html_ioerj(resp.text, data, url)
                    if p:
                        pubs.extend(p)
                        self._salvar_padrao(url, "busca_texto")
                        break
            except Exception:
                continue
        return pubs

    # ── Estratégia 4: mapeamento autônomo ─────────────────────────────────────

    async def _aprender_estrutura(self, client: httpx.AsyncClient, data: date) -> list:
        resp = await client.get(self._base + "/")
        if resp.status_code != 200:
            raise Exception(f"raiz IOERJ HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")
        data_str_br = data.strftime("%d/%m/%Y")
        links_encontrados = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = a.get_text(strip=True)
            if not href or href.startswith("#"):
                continue
            full = href if href.startswith("http") else f"{self._base}{href}"
            links_encontrados.append({"text": txt, "url": full})

            if data_str_br in txt or data_str_br in href:
                try:
                    r2 = await client.get(full)
                    if r2.status_code == 200:
                        pubs = self._parse_html_ioerj(r2.text, data, full)
                        if pubs:
                            self._salvar_padrao(full, "aprendido_raiz")
                            return pubs
                except Exception:
                    pass

        self._state["site_links_aprendidos"] = {
            "ts": datetime.now().isoformat(),
            "links": links_encontrados[:50],
        }
        _save_learning(self._state)

        raise Exception(
            f"Estrutura mapeada ({len(links_encontrados)} links), "
            f"{data_str_br} não encontrada. Veja data/doerj_learning.json."
        )

    # ── Parser HTML ───────────────────────────────────────────────────────────

    def _parse_html_ioerj(self, html: str, data: date, fonte_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        publicacoes = []
        seen: set[str] = set()

        seletores = [
            "article", ".publicacao", ".ato", ".materia", ".conteudo",
            "div.conteudo", "div.texto", "div.ato", "p.ato", "div > p",
        ]
        for sel in seletores:
            for el in soup.select(sel)[:200]:
                texto = el.get_text(separator=" ", strip=True)
                if len(texto) < 80:
                    continue
                chave = texto[:60]
                if chave in seen:
                    continue
                seen.add(chave)
                tipo = classificar_tipo_ato(texto)
                if tipo == "outros" and len(texto) < 200:
                    continue
                publicacoes.append(_pub_dict(texto, data, fonte_url))
            if publicacoes:
                break

        if not publicacoes:
            for p in soup.find_all("p"):
                texto = p.get_text(separator=" ", strip=True)
                if len(texto) < 100:
                    continue
                chave = texto[:60]
                if chave in seen:
                    continue
                seen.add(chave)
                publicacoes.append(_pub_dict(texto, data, fonte_url))

        return publicacoes

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt_url(self, url_template: str, data: date) -> str:
        return (
            url_template
            .replace("{base}", self._base or IOERJ_BASE)
            .replace("{year}", str(data.year))
            .replace("{dd}", data.strftime("%d"))
            .replace("{mm}", data.strftime("%m"))
            .replace("{yyyy}", str(data.year))
        )

    def _salvar_padrao(self, url: str, strategy: str):
        patterns = self._state.setdefault("working_patterns", [])
        patterns.insert(0, {
            "strategy": strategy,
            "url": url,
            "ts": datetime.now().isoformat(),
        })
        self._state["working_patterns"] = patterns[:5]
        _save_learning(self._state)

    def _get_and_parse(self, client, url, data):
        return self._fetch_and_parse(client, url, data)

    async def _fetch_and_parse(
        self, client: httpx.AsyncClient, url: str, data: date
    ) -> list[dict]:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")
        return self._parse_html_ioerj(resp.text, data, url)

    def _salvar_publicacoes(self, publicacoes: list[dict]):
        from compliance_agent.database.models import PublicacaoDOERJ
        for pub in publicacoes:
            try:
                data = date.fromisoformat(pub["data_publicacao"])
                existe = self._session.query(PublicacaoDOERJ).filter_by(
                    data_publicacao=data,
                    titulo=pub["titulo"][:500],
                ).first()
                if not existe:
                    obj = PublicacaoDOERJ(
                        data_publicacao = data,
                        secao           = pub.get("secao", "1"),
                        tipo_ato        = pub.get("tipo_ato", "outros"),
                        titulo          = pub.get("titulo", "")[:500],
                        texto           = pub.get("texto", ""),
                        cpfs_extraidos  = pub.get("cpfs_extraidos", "[]"),
                        cnpjs_extraidos = pub.get("cnpjs_extraidos", "[]"),
                        url_fonte       = pub.get("url_fonte", ""),
                    )
                    self._session.add(obj)
            except Exception as e:
                print(f"[DOERJ] Erro ao salvar: {e}")
        self._session.commit()
