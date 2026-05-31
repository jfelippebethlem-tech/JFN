"""
Coletor do Diário Oficial do Estado do Rio de Janeiro (DOERJ).

Fontes:
  - IOERJ (Imprensa Oficial do Estado do RJ): https://www.ioerj.com.br
  - JusBrasil mirror: https://www.jusbrasil.com.br/diarios/DOERJ

Extrai automaticamente: nomeações, exonerações, contratos, licitações,
publicações de pensão/aposentadoria, atos normativos.
"""

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup


# Regex para extrair CPFs e CNPJs de texto
_RE_CPF  = re.compile(r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b")
_RE_CNPJ = re.compile(r"\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\.\s]?\d{4}[-\.\s]?\d{2}\b")

# Palavras-chave para classificar o tipo de ato
_TIPO_KEYWORDS = {
    "nomeação":          ["nomear", "nomeação", "nomeado", "nomeada", "designar", "designação"],
    "exoneração":        ["exonerar", "exoneração", "exonerado", "dispensar", "dispensa"],
    "aposentadoria":     ["aposentar", "aposentadoria", "aposentado"],
    "contrato":          ["contrato n°", "contrato nº", "celebração de contrato", "rescisão contratual"],
    "licitação":         ["pregão", "concorrência", "licitação", "edital", "tomada de preço", "dispensa"],
    "pensão":            ["pensão por morte", "pensionista", "beneficiário de pensão"],
    "cessão":            ["ceder", "cessão", "cedido"],
    "gratificação":      ["gratificação", "adicional", "vantagem"],
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

JUSBRASIL_SEARCH = "https://www.jusbrasil.com.br/diarios/busca/?q={query}&o=relevance&s=doerj&startDate={start}&endDate={end}"
IOERJ_BASE = "https://www.ioerj.com.br"


def classificar_tipo_ato(texto: str) -> str:
    """Classifica o tipo de ato a partir do texto."""
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


class DOERJCollector:
    """
    Coleta publicações do DOERJ via IOERJ e JusBrasil.
    Salva resultados no banco de dados de compliance.
    """

    def __init__(self, session=None):
        self._session = session

    async def coletar_data(self, data: date) -> list[dict]:
        """
        Coleta todas as publicações de uma data específica.
        Tenta IOERJ primeiro, cai para JusBrasil se necessário.
        """
        publicacoes = []

        # Tenta IOERJ (fonte oficial)
        try:
            pubs = await self._coletar_ioerj(data)
            publicacoes.extend(pubs)
        except Exception as e:
            print(f"[DOERJ] IOERJ falhou ({e}), tentando JusBrasil...")

        # Complementa com JusBrasil se não encontrou nada
        if not publicacoes:
            try:
                pubs = await self._coletar_jusbrasil(data)
                publicacoes.extend(pubs)
            except Exception as e:
                print(f"[DOERJ] JusBrasil também falhou: {e}")

        return publicacoes

    async def coletar_periodo(
        self,
        data_inicio: date,
        data_fim: Optional[date] = None,
        delay: float = 1.0,
    ) -> list[dict]:
        """Coleta publicações de um período, um dia por vez."""
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

    async def coletar_hoje(self) -> list[dict]:
        return await self.coletar_data(date.today())

    # ── Fonte 1: IOERJ ───────────────────────────────────────────────────────

    async def _coletar_ioerj(self, data: date) -> list[dict]:
        """
        Acessa o IOERJ para a data especificada.
        O IOERJ disponibiliza o DO em PDF; tentamos via índice HTML.
        """
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
            # Formato da URL do índice diário no IOERJ
            data_str = data.strftime("%d/%m/%Y")
            urls_to_try = [
                f"{IOERJ_BASE}/pages/DiarioOficial/search?data={data_str}",
                f"{IOERJ_BASE}/diario/{data.strftime('%Y%m%d')}",
            ]

            for url in urls_to_try:
                try:
                    r = await client.get(url)
                    if r.status_code == 200 and len(r.text) > 500:
                        return self._parse_ioerj_html(r.text, data, url)
                except Exception:
                    continue
        return []

    def _parse_ioerj_html(self, html: str, data: date, fonte_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        publicacoes = []

        # IOERJ usa estrutura variável — tentamos extrair blocos de texto por órgão
        for el in soup.find_all(["article", "div", "section", "p"], limit=500):
            texto = el.get_text(separator=" ", strip=True)
            if len(texto) < 80:
                continue
            tipo = classificar_tipo_ato(texto)
            if tipo == "outros" and len(texto) < 200:
                continue

            publicacoes.append({
                "data_publicacao": data.isoformat(),
                "secao":           "1",
                "tipo_ato":        tipo,
                "titulo":          texto[:200],
                "texto":           texto[:3000],
                "cpfs_extraidos":  json.dumps(extrair_cpfs(texto)),
                "cnpjs_extraidos": json.dumps(extrair_cnpjs(texto)),
                "url_fonte":       fonte_url,
            })

        return publicacoes

    # ── Fonte 2: JusBrasil ───────────────────────────────────────────────────

    async def _coletar_jusbrasil(self, data: date) -> list[dict]:
        """
        Busca publicações no mirror do JusBrasil.
        Gratuito para consulta pública.
        """
        data_str = data.strftime("%Y-%m-%d")
        url = JUSBRASIL_SEARCH.format(
            query="nomeação+OR+contrato+OR+licitação",
            start=data_str,
            end=data_str,
        )

        async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                raise Exception(f"JusBrasil retornou {r.status_code}")
            return self._parse_jusbrasil_html(r.text, data, url)

    def _parse_jusbrasil_html(self, html: str, data: date, fonte_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        publicacoes = []

        # JusBrasil usa cards com classe "result-item" ou similar
        for card in soup.find_all(["div", "article"], class_=re.compile(r"result|item|card|hit")):
            titulo_el = card.find(["h2", "h3", "strong", "a"])
            titulo = titulo_el.get_text(strip=True) if titulo_el else ""
            texto  = card.get_text(separator=" ", strip=True)

            if len(texto) < 50:
                continue

            url_el = card.find("a", href=True)
            item_url = url_el["href"] if url_el else fonte_url

            publicacoes.append({
                "data_publicacao": data.isoformat(),
                "secao":           "1",
                "tipo_ato":        classificar_tipo_ato(texto),
                "titulo":          titulo[:200] or texto[:200],
                "texto":           texto[:3000],
                "cpfs_extraidos":  json.dumps(extrair_cpfs(texto)),
                "cnpjs_extraidos": json.dumps(extrair_cnpjs(texto)),
                "url_fonte":       item_url if item_url.startswith("http") else f"https://www.jusbrasil.com.br{item_url}",
            })

        return publicacoes

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
                print(f"[DOERJ] Erro ao salvar publicação: {e}")
        self._session.commit()
