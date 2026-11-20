"""
Coletor do Portal de Transparência do Estado do Rio de Janeiro.
URL base: https://www.transparencia.rj.gov.br

Coleta:
  - Folha de pagamento de servidores ativos, inativos e pensionistas
  - Contratos celebrados
  - Licitações abertas e homologadas
"""

import csv
import io
import re

import logging

import httpx
from bs4 import BeautifulSoup

from compliance_agent.collectors.formato import valor_br


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


logger = logging.getLogger(__name__)


def _valor_ou_zero(v) -> float:
    # valor ilegível grava 0.0 — comportamento histórico, não régua: ver docs/untangle/collectors.md
    return valor_br(v) or 0.0


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

    # ── Parsers ──────────────────────────────────────────────────────────────

    def _parse_servidores(self, response: httpx.Response) -> list[dict]:
        """Tenta parsear JSON ou HTML da resposta de servidores."""
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = response.json()
                items = data if isinstance(data, list) else data.get("dados", data.get("items", data.get("resultado", [])))
                return [self._normalizar_servidor(i) for i in items if isinstance(i, dict)]
            except Exception as exc:  # noqa: BLE001 — fallback de formato; segue p/ o próximo parser
                logger.debug("transparency: parse JSON falhou (%s) — tentando próximo formato", exc)

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
            "remuneracao_bruta":  _valor_ou_zero(item.get("remuneracaoBruta") or item.get("bruto", 0)),
            "remuneracao_liquida": _valor_ou_zero(item.get("remuneracaoLiquida") or item.get("liquido", 0)),
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
                    "remuneracao_bruta": _valor_ou_zero(row.get("REMUNERAÇÃO BRUTA", 0)),
                    "remuneracao_liquida": _valor_ou_zero(row.get("REMUNERAÇÃO LÍQUIDA", 0)),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("transparency: parse CSV incompleto (%s) — retorna o que leu", exc)
        return registros

    def _parse_contratos(self, response: httpx.Response) -> list[dict]:
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = response.json()
                items = data if isinstance(data, list) else data.get("dados", data.get("items", []))
                return [self._normalizar_contrato(i) for i in items if isinstance(i, dict)]
            except Exception as exc:  # noqa: BLE001 — fallback de formato; segue p/ o próximo parser
                logger.debug("transparency: parse JSON falhou (%s) — tentando próximo formato", exc)
        return self._parse_html_tabela(response.text, tipo="contrato")

    def _normalizar_contrato(self, item: dict) -> dict:
        return {
            "numero":          item.get("numeroContrato") or item.get("numero", ""),
            "objeto":          item.get("objeto") or item.get("descricaoObjeto", ""),
            "cnpj":            re.sub(r"\D", "", item.get("cnpj", "") or ""),
            "empresa":         item.get("nomeEmpresa") or item.get("fornecedor", ""),
            "orgao":           item.get("nomeOrgao") or item.get("orgao", ""),
            "modalidade":      item.get("modalidade", ""),
            "valor_total":     _valor_ou_zero(item.get("valorTotal") or item.get("valor", 0)),
            "data_assinatura": item.get("dataAssinatura", ""),
            "data_inicio":     item.get("dataInicio", ""),
            "data_fim":        item.get("dataTermino") or item.get("dataFim", ""),
        }

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

    # ── Persistência ─────────────────────────────────────────────────────────
