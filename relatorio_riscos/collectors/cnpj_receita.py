"""
Coletor de dados cadastrais da Receita Federal via APIs públicas.

Fontes:
  - BrasilAPI (primária):  https://brasilapi.com.br/api/cnpj/v1/{cnpj}
  - ReceitaWS  (fallback): https://www.receitaws.com.br/v1/cnpj/{cnpj}
"""
from __future__ import annotations

import re
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
_RECEITAWS_URL = "https://www.receitaws.com.br/v1/cnpj/{cnpj}"
_TIMEOUT = 20


def _limpar_cnpj(cnpj: str) -> str:
    """Remove pontuação do CNPJ."""
    return re.sub(r"\D", "", cnpj)


def _mascarar_cpf(cpf_cnpj: str) -> str:
    """
    Mascara CPF/CNPJ de sócio pessoa-física:
    mantém 3 primeiros e 2 últimos dígitos visíveis → ***361705**.
    CNPJs (14 dígitos) são deixados sem máscara.
    """
    digitos = re.sub(r"\D", "", cpf_cnpj or "")
    if len(digitos) == 11:
        return f"***{digitos[3:9]}**"
    return cpf_cnpj  # CNPJ ou vazio: devolve original


def _normalizar_socios_brasilapi(raw: list) -> list[dict]:
    socios = []
    for s in raw or []:
        socios.append({
            "nome": s.get("nome_socio") or s.get("nome") or "",
            "cpf_cnpj_socio": _mascarar_cpf(s.get("cnpj_cpf_do_socio") or s.get("cpf_cnpj_socio") or ""),
            "qualificacao": s.get("qualificacao_socio") or s.get("qualificacao") or "",
            "data_entrada": s.get("data_entrada_sociedade") or s.get("data_entrada") or "",
        })
    return socios


def _normalizar_socios_receitaws(raw: list) -> list[dict]:
    socios = []
    for s in raw or []:
        socios.append({
            "nome": s.get("nome") or "",
            "cpf_cnpj_socio": _mascarar_cpf(s.get("cpf_cnpj_socio") or ""),
            "qualificacao": s.get("qual") or "",
            "data_entrada": s.get("pais_origem") or "",  # receitaws não expõe data_entrada
        })
    return socios


def _montar_endereco_brasilapi(data: dict) -> str:
    partes = [
        data.get("logradouro", ""),
        data.get("numero", ""),
        data.get("complemento", ""),
        data.get("bairro", ""),
        data.get("municipio", ""),
        data.get("uf", ""),
        data.get("cep", ""),
    ]
    return ", ".join(p for p in partes if p)


def _montar_endereco_receitaws(data: dict) -> str:
    partes = [
        data.get("logradouro", ""),
        data.get("numero", ""),
        data.get("complemento", ""),
        data.get("bairro", ""),
        data.get("municipio", ""),
        data.get("uf", ""),
        data.get("cep", ""),
    ]
    return ", ".join(p for p in partes if p)


def _extrair_cnae_brasilapi(data: dict) -> str:
    cnae = data.get("cnae_fiscal_descricao") or ""
    codigo = data.get("cnae_fiscal") or ""
    if codigo:
        return f"{codigo} - {cnae}" if cnae else str(codigo)
    return cnae


def _extrair_cnae_receitaws(data: dict) -> str:
    atividade = (data.get("atividade_principal") or [{}])[0]
    codigo = atividade.get("code", "")
    texto = atividade.get("text", "")
    if codigo:
        return f"{codigo} - {texto}" if texto else codigo
    return texto


async def _buscar_brasilapi(cnpj_limpo: str, client: httpx.AsyncClient) -> Optional[dict]:
    url = _BRASILAPI_URL.format(cnpj=cnpj_limpo)
    try:
        r = await client.get(url, timeout=_TIMEOUT)
        if r.status_code != 200:
            logger.warning("BrasilAPI retornou %d para CNPJ %s", r.status_code, cnpj_limpo)
            return None
        data = r.json()
        capital = 0.0
        try:
            capital = float(data.get("capital_social") or 0)
        except (TypeError, ValueError):
            pass

        simples = False
        mei = False
        opcoes = data.get("opcao_pelo_simples") or data.get("simples") or {}
        if isinstance(opcoes, bool):
            simples = opcoes
        elif isinstance(opcoes, dict):
            simples = bool(opcoes.get("opcao_pelo_simples") or opcoes.get("simples"))
            mei = bool(opcoes.get("opcao_pelo_mei") or opcoes.get("mei"))

        return {
            "ok": True,
            "fonte": "brasilapi",
            "razao_social": data.get("razao_social") or "",
            "nome_fantasia": data.get("nome_fantasia") or "",
            "cnpj": cnpj_limpo,
            "situacao": data.get("descricao_situacao_cadastral") or data.get("situacao") or "",
            "data_abertura": data.get("data_inicio_atividade") or data.get("abertura") or "",
            "capital_social": capital,
            "porte": data.get("porte") or data.get("descricao_porte") or "",
            "natureza_juridica": data.get("natureza_juridica") or data.get("descricao_natureza_juridica") or "",
            "cnae_principal": _extrair_cnae_brasilapi(data),
            "endereco": _montar_endereco_brasilapi(data),
            "email": data.get("email") or "",
            "telefone": data.get("ddd_telefone_1") or data.get("telefone") or "",
            "socios": _normalizar_socios_brasilapi(data.get("qsa") or []),
            "simples": simples,
            "mei": mei,
        }
    except Exception as exc:
        logger.warning("BrasilAPI erro: %s", exc)
        return None


async def _buscar_receitaws(cnpj_limpo: str, client: httpx.AsyncClient) -> Optional[dict]:
    url = _RECEITAWS_URL.format(cnpj=cnpj_limpo)
    try:
        r = await client.get(url, timeout=_TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            logger.warning("ReceitaWS retornou %d para CNPJ %s", r.status_code, cnpj_limpo)
            return None
        data = r.json()
        if data.get("status") == "ERROR":
            return None

        capital = 0.0
        try:
            capital_str = (data.get("capital_social") or "0").replace(".", "").replace(",", ".")
            capital = float(capital_str)
        except (TypeError, ValueError):
            pass

        return {
            "ok": True,
            "fonte": "receitaws",
            "razao_social": data.get("nome") or "",
            "nome_fantasia": data.get("fantasia") or "",
            "cnpj": cnpj_limpo,
            "situacao": data.get("situacao") or "",
            "data_abertura": data.get("abertura") or "",
            "capital_social": capital,
            "porte": data.get("porte") or "",
            "natureza_juridica": data.get("natureza_juridica") or "",
            "cnae_principal": _extrair_cnae_receitaws(data),
            "endereco": _montar_endereco_receitaws(data),
            "email": data.get("email") or "",
            "telefone": data.get("telefone") or "",
            "socios": _normalizar_socios_receitaws(data.get("qsa") or []),
            "simples": data.get("simples") == "Sim",
            "mei": data.get("mei") == "Sim",
        }
    except Exception as exc:
        logger.warning("ReceitaWS erro: %s", exc)
        return None


async def buscar_cnpj(cnpj: str) -> dict:
    """
    Busca dados cadastrais de um CNPJ.

    Tenta BrasilAPI primeiro; se falhar, tenta ReceitaWS.
    Retorna dict com chave "ok" indicando sucesso.
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {"ok": False, "erro": f"CNPJ inválido: {cnpj!r} (esperado 14 dígitos)"}

    async with httpx.AsyncClient() as client:
        resultado = await _buscar_brasilapi(cnpj_limpo, client)
        if resultado is None:
            logger.info("Tentando fallback ReceitaWS para CNPJ %s", cnpj_limpo)
            resultado = await _buscar_receitaws(cnpj_limpo, client)

    if resultado is None:
        return {
            "ok": False,
            "erro": "Todas as fontes falharam (BrasilAPI e ReceitaWS)",
            "cnpj": cnpj_limpo,
            "razao_social": "",
            "nome_fantasia": "",
            "situacao": "",
            "data_abertura": "",
            "capital_social": 0.0,
            "porte": "",
            "natureza_juridica": "",
            "cnae_principal": "",
            "endereco": "",
            "email": "",
            "telefone": "",
            "socios": [],
            "simples": False,
            "mei": False,
        }

    return resultado
