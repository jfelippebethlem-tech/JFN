"""
Coletor do Portal de Transparência do Estado do Rio de Janeiro.
URL base: https://www.transparencia.rj.gov.br

Coleta:
  - Folha de pagamento de servidores ativos, inativos e pensionistas
  - Contratos celebrados
  - Licitações abertas e homologadas
"""

import asyncio
import csv
import io
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup


BASE_URL = "https://www.transparencia.rj.gov.br"

# Endpoints conhecidos do portal de transparência RJ
ENDPOINTS = {
    "servidores_ativos":   f"{BASE_URL}/pessoal/ServidoresAtivos",
    "servidores_inativos": f"{BASE_URL}/pessoal/ServidoresInativos",
    "pensionistas":        f"{BASE_URL}/pessoal/Pensionistas",
    "contratos":           f"{BASE_URL}/compras/Contratos",
    "licitacoes":          f"{BASE_URL}/compras/Licitacoes",
    "despesas":            f"{BASE_URL}/despesas/Despesas",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


class TransparenciaRJCollector:
    """Coleta e estrutura dados públicos do portal de transparência RJ."""

    def __init__(self, session=None):
        self._session = session

    async def buscar_servidor_por_nome(self, nome: str) -> list[dict]:
        """Busca servidor pelo nome no portal de transparência."""
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
            # Tenta endpoint de busca
            params = {"nome": nome, "pagina": 1, "tamanhoPagina": 50}
            try:
                r = await client.get(ENDPOINTS["servidores_ativos"], params=params)
                return self._parse_servidores(r)
            except Exception as e:
                return [{"error": str(e)}]

    async def buscar_servidor_por_cpf(self, cpf: str) -> list[dict]:
        """Busca servidor pelo CPF (mascarado nos portais, mas às vezes disponível)."""
        cpf_clean = re.sub(r"\D", "", cpf)
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
            params = {"cpf": cpf_clean}
            try:
                r = await client.get(ENDPOINTS["servidores_ativos"], params=params)
                return self._parse_servidores(r)
            except Exception as e:
                return [{"error": str(e)}]

    async def buscar_folha_orgao(
        self,
        orgao_codigo: str,
        competencia: str,   # formato AAAA-MM
    ) -> list[dict]:
        """Busca folha de pagamento de um órgão em uma competência."""
        async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
            params = {
                "orgao": orgao_codigo,
                "competencia": competencia.replace("-", ""),
                "pagina": 1,
                "tamanhoPagina": 500,
            }
            registros = []
            while True:
                try:
                    r = await client.get(ENDPOINTS["servidores_ativos"], params=params)
                    page_data = self._parse_servidores(r)
                    if not page_data:
                        break
                    registros.extend(page_data)
                    params["pagina"] += 1
                    if len(page_data) < params["tamanhoPagina"]:
                        break
                    await asyncio.sleep(0.5)
                except Exception:
                    break
        return registros

    async def buscar_contratos_empresa(self, cnpj: str) -> list[dict]:
        """Busca contratos celebrados com uma empresa pelo CNPJ."""
        cnpj_clean = re.sub(r"\D", "", cnpj)
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
            params = {"cnpj": cnpj_clean, "pagina": 1, "tamanhoPagina": 100}
            try:
                r = await client.get(ENDPOINTS["contratos"], params=params)
                return self._parse_contratos(r)
            except Exception as e:
                return [{"error": str(e)}]

    async def buscar_licitacoes(
        self,
        orgao: Optional[str] = None,
        ano: Optional[int] = None,
        modalidade: Optional[str] = None,
    ) -> list[dict]:
        """Busca licitações com filtros opcionais."""
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
            params = {"pagina": 1, "tamanhoPagina": 100}
            if orgao:
                params["orgao"] = orgao
            if ano:
                params["ano"] = str(ano)
            if modalidade:
                params["modalidade"] = modalidade
            try:
                r = await client.get(ENDPOINTS["licitacoes"], params=params)
                return self._parse_licitacoes(r)
            except Exception as e:
                return [{"error": str(e)}]

    # ── Parsers ──────────────────────────────────────────────────────────────

    def _parse_servidores(self, response: httpx.Response) -> list[dict]:
        """Tenta parsear JSON ou HTML da resposta de servidores."""
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = response.json()
                items = data if isinstance(data, list) else data.get("dados", data.get("items", data.get("resultado", [])))
                return [self._normalizar_servidor(i) for i in items if isinstance(i, dict)]
            except Exception:
                pass

        # Tenta CSV
        if "csv" in ct or response.text.startswith('"') or response.text.startswith("nome"):
            return self._parse_csv_servidores(response.text)

        # HTML fallback
        return self._parse_html_tabela(response.text, tipo="servidor")

    def _normalizar_servidor(self, item: dict) -> dict:
        """Normaliza campos de servidor para formato padrão."""
        return {
            "nome":               item.get("nome") or item.get("nomeServidor", ""),
            "cpf":                re.sub(r"\D", "", item.get("cpf", "") or ""),
            "orgao_codigo":       item.get("codigoOrgao") or item.get("orgaoCodigo", ""),
            "orgao_nome":         item.get("nomeOrgao") or item.get("orgaoNome", ""),
            "cargo":              item.get("cargo") or item.get("descricaoCargo", ""),
            "vinculo":            item.get("tipoVinculo") or item.get("vinculo", ""),
            "remuneracao_bruta":  self._parse_valor(item.get("remuneracaoBruta") or item.get("bruto", 0)),
            "remuneracao_liquida": self._parse_valor(item.get("remuneracaoLiquida") or item.get("liquido", 0)),
            "competencia":        item.get("competencia", ""),
        }

    def _parse_csv_servidores(self, texto: str) -> list[dict]:
        registros = []
        try:
            reader = csv.DictReader(io.StringIO(texto), delimiter=";")
            for row in reader:
                registros.append({
                    "nome":              row.get("NOME", ""),
                    "cpf":               re.sub(r"\D", "", row.get("CPF", "") or ""),
                    "orgao_nome":        row.get("ÓRGÃO", "") or row.get("ORGAO", ""),
                    "cargo":             row.get("CARGO", ""),
                    "vinculo":           row.get("VÍNCULO", "") or row.get("VINCULO", ""),
                    "remuneracao_bruta": self._parse_valor(row.get("REMUNERAÇÃO BRUTA", 0)),
                    "remuneracao_liquida": self._parse_valor(row.get("REMUNERAÇÃO LÍQUIDA", 0)),
                })
        except Exception:
            pass
        return registros

    def _parse_contratos(self, response: httpx.Response) -> list[dict]:
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = response.json()
                items = data if isinstance(data, list) else data.get("dados", data.get("items", []))
                return [self._normalizar_contrato(i) for i in items if isinstance(i, dict)]
            except Exception:
                pass
        return self._parse_html_tabela(response.text, tipo="contrato")

    def _normalizar_contrato(self, item: dict) -> dict:
        return {
            "numero":          item.get("numeroContrato") or item.get("numero", ""),
            "objeto":          item.get("objeto") or item.get("descricaoObjeto", ""),
            "cnpj":            re.sub(r"\D", "", item.get("cnpj", "") or ""),
            "empresa":         item.get("nomeEmpresa") or item.get("fornecedor", ""),
            "orgao":           item.get("nomeOrgao") or item.get("orgao", ""),
            "modalidade":      item.get("modalidade", ""),
            "valor_total":     self._parse_valor(item.get("valorTotal") or item.get("valor", 0)),
            "data_assinatura": item.get("dataAssinatura", ""),
            "data_inicio":     item.get("dataInicio", ""),
            "data_fim":        item.get("dataTermino") or item.get("dataFim", ""),
        }

    def _parse_licitacoes(self, response: httpx.Response) -> list[dict]:
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = response.json()
                items = data if isinstance(data, list) else data.get("dados", data.get("items", []))
                return items
            except Exception:
                pass
        return []

    def _parse_html_tabela(self, html: str, tipo: str) -> list[dict]:
        """Extrai dados de tabela HTML genérica."""
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        results = []
        for table in tables:
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if not headers:
                continue
            for row in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if cells:
                    results.append(dict(zip(headers, cells)))
        return results

    @staticmethod
    def _parse_valor(val) -> float:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        val = str(val).replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(val)
        except Exception:
            return 0.0

    # ── Persistência ─────────────────────────────────────────────────────────

    def salvar_servidores(self, registros: list[dict], competencia: str):
        from compliance_agent.database.models import Pessoa, RegistroFolha
        for r in registros:
            if not r.get("nome"):
                continue
            cpf = r.get("cpf", "")

            # Upsert Pessoa
            pessoa = None
            if cpf and len(cpf) == 11:
                pessoa = self._session.query(Pessoa).filter_by(cpf=cpf).first()
                if not pessoa:
                    pessoa = Pessoa(cpf=cpf, nome=r["nome"], tipo="servidor")
                    self._session.add(pessoa)
                    self._session.flush()
                elif pessoa.nome != r["nome"]:
                    pessoa.nome = r["nome"]

            # Upsert RegistroFolha
            existe = self._session.query(RegistroFolha).filter_by(
                cpf=cpf, competencia=competencia
            ).first() if cpf else None

            if not existe:
                reg = RegistroFolha(
                    pessoa_id          = pessoa.id if pessoa else None,
                    cpf                = cpf,
                    nome               = r["nome"],
                    orgao_codigo       = r.get("orgao_codigo", ""),
                    orgao_nome         = r.get("orgao_nome", ""),
                    cargo              = r.get("cargo", ""),
                    vinculo            = r.get("vinculo", ""),
                    competencia        = competencia,
                    remuneracao_bruta  = r.get("remuneracao_bruta", 0),
                    remuneracao_liquida= r.get("remuneracao_liquida", 0),
                    fonte              = "transparencia_rj",
                )
                self._session.add(reg)

        self._session.commit()
