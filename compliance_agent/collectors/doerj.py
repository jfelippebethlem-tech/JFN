"""
Coletor do Diário Oficial do Estado do Rio de Janeiro (DOERJ).

Fonte primária: IOERJ — Imprensa Oficial do Estado do RJ
  https://www.ioerj.com.br

Estratégia de coleta:
  1. Acessa a listagem de edições do ano corrente para descobrir o número
     da edição correspondente à data desejada.
  2. Baixa o HTML completo da edição encontrada.
  3. Fallback: busca textual no próprio site da IOERJ.

O bot aprende: sempre que uma coleta falha, registra os erros e tenta
variações de URL/estrutura na próxima execução (estado persistido em
data/doerj_learning.json).
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

# Padrões de URL da IOERJ a tentar (em ordem de preferência)
# Serão testados e o resultado bem-sucedido é guardado em doerj_learning.json
_IOERJ_URL_PATTERNS = [
    # 1. Listagem do ano — para descobrir número da edição
    "{base}/portal/modules/conteudoonline/listaConteudo.php?e=01&a={year}",
    # 2. Busca por data diretamente
    "{base}/portal/modules/conteudoonline/listaConteudo.php?e=01&a={year}&data={dd}/{mm}/{yyyy}",
    # 3. Página principal de DO
    "{base}/portal/modules/conteudoonline/mostraConteudo.php?e=01&a={year}&d={dd}{mm}{yyyy}",
    # 4. Raiz do site (para inferir estrutura atual)
    "{base}/",
]


def _load_learning() -> dict:
    """Load the learning state (successful URL patterns, edition map)."""
    try:
        if _LEARN_FILE.exists():
            return json.loads(_LEARN_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"working_patterns": [], "edition_map": {}, "errors": []}


def _save_learning(state: dict):
    """Persist learning state."""
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


class DOERJCollector:
    """
    Coleta publicações do DOERJ direto da Imprensa Oficial do Estado do RJ (IOERJ).
    Aprende automaticamente os padrões de URL que funcionam e persiste esse
    conhecimento em data/doerj_learning.json para execuções futuras.
    """

    def __init__(self, session=None):
        self._session = session
        self._state = _load_learning()

    async def coletar_hoje(self) -> list:
        return await self.coletar_data(date.today())

    async def coletar_data(self, data: date) -> list:
        """
        Coleta todas as publicações de uma data específica.
        Tenta múltiplas estratégias na IOERJ; persiste o que funcionou.
        """
        publicacoes = []
        erros = []

        async with httpx.AsyncClient(
            timeout=25,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:

            # 1. Tentar padrão aprendido anteriormente (mais rápido)
            for pattern_info in self._state.get("working_patterns", []):
                try:
                    url = self._fmt_url(pattern_info["url"], data)
                    pubs = await self._fetch_and_parse(client, url, data)
                    if pubs:
                        print(f"[DOERJ] {len(pubs)} publicações via padrão salvo ({url[:60]}...)")
                        publicacoes.extend(pubs)
                        break
                except Exception as e:
                    erros.append(f"padrão salvo: {e}")

            # 2. Se não achou nada, tentar listagem do ano para descobrir edição
            if not publicacoes:
                try:
                    pubs = await self._coletar_via_listagem(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} publicações via listagem anual")
                except Exception as e:
                    erros.append(f"listagem: {type(e).__name__}: {e}")

            # 3. Fallback: busca direta por texto no site da IOERJ
            if not publicacoes:
                try:
                    pubs = await self._coletar_via_busca(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} publicações via busca IOERJ")
                except Exception as e:
                    erros.append(f"busca IOERJ: {type(e).__name__}: {e}")

            # 4. Fallback: página raiz para mapear estrutura atual
            if not publicacoes:
                try:
                    pubs = await self._aprender_estrutura(client, data)
                    if pubs:
                        publicacoes.extend(pubs)
                        print(f"[DOERJ] {len(pubs)} publicações via aprendizado de estrutura")
                except Exception as e:
                    erros.append(f"aprendizado: {type(e).__name__}: {e}")

        if erros:
            print(f"[DOERJ] Erros na coleta de {data}: {erros}")
            self._state.setdefault("errors", []).append({
                "data": data.isoformat(),
                "erros": erros,
                "ts": datetime.now().isoformat(),
            })
            # Keep only last 20 errors
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

    # ── Estratégia 1: listagem anual para descobrir número de edição ──────────

    async def _coletar_via_listagem(self, client: httpx.AsyncClient, data: date) -> list:
        """
        Acessa a lista de edições do ano corrente, encontra a edição da data
        alvo e baixa seu conteúdo completo.
        """
        year = data.year
        list_url = f"{IOERJ_BASE}/portal/modules/conteudoonline/listaConteudo.php?e=01&a={year}"

        resp = await client.get(list_url)
        if resp.status_code != 200:
            raise Exception(f"listagem retornou HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Procura links de edições com a data alvo
        data_str_br = data.strftime("%d/%m/%Y")
        data_str_iso = data.isoformat()

        edition_url = None
        edition_n = None

        for a in soup.find_all("a", href=True):
            href = a["href"]
            link_text = a.get_text(strip=True)
            # A data pode aparecer no texto do link ou em elemento próximo
            parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
            if data_str_br in parent_text or data_str_iso in parent_text:
                edition_url = href if href.startswith("http") else f"{IOERJ_BASE}{href}"
                # Extract edition number from URL if possible
                m = re.search(r"[?&]n=(\d+)", href)
                if m:
                    edition_n = m.group(1)
                break

        if not edition_url and edition_n is None:
            # Parse the table/list looking for the date in a TD or LI
            for row in soup.find_all(["tr", "li", "div"]):
                row_text = row.get_text(" ", strip=True)
                if data_str_br in row_text:
                    a_tag = row.find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        edition_url = href if href.startswith("http") else f"{IOERJ_BASE}{href}"
                        m = re.search(r"[?&]n=(\d+)", href)
                        if m:
                            edition_n = m.group(1)
                        break

        if not edition_url and not edition_n:
            raise Exception(f"edição de {data_str_br} não encontrada na listagem anual")

        # If we found an edition number, build the content URL
        if edition_n and not edition_url:
            edition_url = (
                f"{IOERJ_BASE}/portal/modules/conteudoonline/"
                f"mostraConteudo.php?n={edition_n}&e=01&a={year}"
            )

        resp2 = await client.get(edition_url)
        if resp2.status_code != 200:
            raise Exception(f"edição URL {edition_url} retornou {resp2.status_code}")

        pubs = self._parse_html_ioerj(resp2.text, data, edition_url)
        if pubs:
            # Salvar padrão que funcionou
            self._state.setdefault("working_patterns", []).insert(0, {
                "strategy": "listagem_anual",
                "url": list_url,
                "ts": datetime.now().isoformat(),
            })
            self._state["working_patterns"] = self._state["working_patterns"][:5]
            _save_learning(self._state)
        return pubs

    # ── Estratégia 2: busca direta no site da IOERJ ───────────────────────────

    async def _coletar_via_busca(self, client: httpx.AsyncClient, data: date) -> list:
        """Usa a busca do portal da IOERJ por data."""
        termos = ["nomeação", "contrato", "licitação"]
        pubs = []
        for termo in termos:
            try:
                url = (
                    f"{IOERJ_BASE}/portal/modules/conteudoonline/busca.php"
                    f"?q={termo}&e=01&a={data.year}"
                    f"&di={data.strftime('%d/%m/%Y')}"
                    f"&df={data.strftime('%d/%m/%Y')}"
                )
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.text) > 500:
                    p = self._parse_html_ioerj(resp.text, data, url)
                    pubs.extend(p)
                    if p:
                        self._state.setdefault("working_patterns", []).insert(0, {
                            "strategy": "busca_ioerj",
                            "url": url,
                            "ts": datetime.now().isoformat(),
                        })
                        self._state["working_patterns"] = self._state["working_patterns"][:5]
                        _save_learning(self._state)
                        break
            except Exception:
                continue
        return pubs

    # ── Estratégia 3: aprender estrutura atual do site ────────────────────────

    async def _aprender_estrutura(self, client: httpx.AsyncClient, data: date) -> list:
        """
        Acessa a página raiz da IOERJ e mapeia todos os links de conteúdo
        disponíveis, procurando um que corresponda à data alvo.
        Persiste os resultados no arquivo de aprendizado para uso futuro.
        """
        resp = await client.get(IOERJ_BASE + "/")
        if resp.status_code != 200:
            raise Exception(f"raiz IOERJ retornou {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extrair todos os links relevantes
        links_encontrados = []
        data_str_br = data.strftime("%d/%m/%Y")
        data_str_iso = data.isoformat()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = a.get_text(strip=True)
            if not href or href.startswith("#"):
                continue
            full = href if href.startswith("http") else f"{IOERJ_BASE}{href}"
            links_encontrados.append({"text": txt, "url": full})

            # Se o link ou texto referencia a data alvo, tentar acessar
            if data_str_br in txt or data_str_iso in txt or data_str_br in href:
                try:
                    r2 = await client.get(full)
                    if r2.status_code == 200:
                        pubs = self._parse_html_ioerj(r2.text, data, full)
                        if pubs:
                            self._state.setdefault("working_patterns", []).insert(0, {
                                "strategy": "aprendido_raiz",
                                "url": full,
                                "ts": datetime.now().isoformat(),
                            })
                            _save_learning(self._state)
                            return pubs
                except Exception:
                    pass

        # Persistir mapa de links para análise manual futura
        self._state["site_links_aprendidos"] = {
            "ts": datetime.now().isoformat(),
            "links": links_encontrados[:50],
        }
        _save_learning(self._state)

        raise Exception(
            f"Estrutura do site IOERJ mapeada ({len(links_encontrados)} links), "
            f"mas data {data_str_br} não encontrada. "
            f"Verifique data/doerj_learning.json para ver os links disponíveis."
        )

    # ── Parser de HTML da IOERJ ───────────────────────────────────────────────

    def _parse_html_ioerj(self, html: str, data: date, fonte_url: str) -> list[dict]:
        """
        Extrai publicações do HTML retornado pela IOERJ.
        Tenta múltiplos seletores CSS pois a estrutura varia entre seções.
        """
        soup = BeautifulSoup(html, "html.parser")
        publicacoes = []
        seen_texts: set[str] = set()

        # Seletores em ordem de especificidade — da mais específica pra mais genérica
        seletores = [
            "article",
            ".publicacao", ".ato", ".materia", ".conteudo",
            "div.conteudo", "div.texto", "div.ato",
            "p.ato", "div > p",
        ]

        for sel in seletores:
            elementos = soup.select(sel)
            if not elementos:
                continue
            for el in elementos[:200]:
                texto = el.get_text(separator=" ", strip=True)
                if len(texto) < 80:
                    continue
                chave = texto[:60]
                if chave in seen_texts:
                    continue
                seen_texts.add(chave)
                tipo = classificar_tipo_ato(texto)
                # Skip generic blocks if classification is "outros" and text is short
                if tipo == "outros" and len(texto) < 200:
                    continue
                publicacoes.append(_pub_dict(texto, data, fonte_url))
            if publicacoes:
                break

        # Generic fallback: all <p> tags with enough text
        if not publicacoes:
            for p in soup.find_all("p"):
                texto = p.get_text(separator=" ", strip=True)
                if len(texto) < 100:
                    continue
                chave = texto[:60]
                if chave in seen_texts:
                    continue
                seen_texts.add(chave)
                publicacoes.append(_pub_dict(texto, data, fonte_url))

        return publicacoes

    def _fmt_url(self, url_template: str, data: date) -> str:
        return (
            url_template
            .replace("{year}", str(data.year))
            .replace("{dd}", data.strftime("%d"))
            .replace("{mm}", data.strftime("%m"))
            .replace("{yyyy}", str(data.year))
        )

    # ── Salvar no banco ───────────────────────────────────────────────────────

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
