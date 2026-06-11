"""
Verificador de sanções nos cadastros públicos federais.

Fontes consultadas (requerem chave API do Portal da Transparência):
  - CEIS  — Cadastro de Empresas Inidôneas e Suspensas
  - CNEP  — Cadastro Nacional de Empresas Punidas
  - CEPIM — Cadastro de Entidades Privadas Sem Fins Lucrativos Impedidas

Sem chave API o módulo retorna verificado=False em vez de falhar.
Configure a variável de ambiente: TRANSPARENCIA_API_KEY
"""
from __future__ import annotations

import os
import re
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
_TIMEOUT = 20


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def _headers(chave: str) -> dict:
    return {"chave-api-dados": chave, "Accept": "application/json"}  # header correto do Portal (era "chave-api" = 401)


# Param de filtro por endpoint (varia!): CEIS/CNEP=codigoSancionado; CEPIM=cnpjSancionado. Verificado no swagger.
_PARAM_FILTRO = {"ceis": "codigoSancionado", "cnep": "codigoSancionado", "cepim": "cnpjSancionado"}


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


async def _consultar_endpoint(
    client: httpx.AsyncClient,
    endpoint: str,
    cnpj_limpo: str,
    chave: str,
) -> tuple[bool, list, Optional[str]]:
    """
    Consulta um endpoint de sanções.

    Retorna (sucesso, lista_sancoes, mensagem_erro).
    """
    url = f"{_BASE}/{endpoint}"
    params = {_PARAM_FILTRO.get(endpoint, "codigoSancionado"): cnpj_limpo, "pagina": 1, "tamanhoPagina": 10}
    try:
        r = await client.get(url, params=params, headers=_headers(chave), timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return True, data, None
            if isinstance(data, dict):
                itens = data.get("data") or data.get("content") or []
                return True, itens, None
            return True, [], None
        if r.status_code in (401, 403):
            return False, [], "Chave API inválida ou sem permissão"
        if r.status_code == 404:
            return True, [], None  # sem sanções
        return False, [], f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return False, [], "Timeout"
    except Exception as exc:
        logger.warning("Erro em %s: %s", endpoint, exc)
        return False, [], str(exc)


def _normalizar_sancao(s: dict, tipo: str) -> dict:
    return {
        "tipo": tipo,
        "nome_informado": s.get("nomeInformado") or s.get("razaoSocial") or "",
        "cpf_cnpj": s.get("cpfCnpj") or s.get("cnpjSancionado") or "",
        "orgao_sancionador": s.get("orgaoSancionador", {}).get("nome") if isinstance(s.get("orgaoSancionador"), dict) else s.get("orgaoSancionador") or "",
        "fundamentacao_legal": s.get("fundamentacaoLegal") or "",
        "data_inicio": s.get("dataInicioSancao") or s.get("dataPublicacao") or "",
        "data_fim": s.get("dataFimSancao") or s.get("dataReferencia") or "",
        "tipo_sancao": s.get("tipoSancao", {}).get("descricao") if isinstance(s.get("tipoSancao"), dict) else s.get("tipoSancao") or "",
        "numero_processo": s.get("numeroProcesso") or "",
        "valor_multa": s.get("valorMulta") or s.get("valorTotalMulta") or None,
    }


async def verificar_sancoes(cnpj: str) -> dict:
    """
    Verifica sanções nos cadastros públicos federais (CEIS, CNEP, CEPIM).

    Retorna dict com "ok", "verificado", "n_sancoes", "sancoes", e "motivo" se não verificado.
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {
            "ok": False,
            "erro": f"CNPJ inválido: {cnpj!r}",
            "verificado": False,
            "sancoes": [],
        }

    chave = (os.environ.get("PORTAL_TRANSPARENCIA_KEY", "") or os.environ.get("TRANSPARENCIA_API_KEY", "")).strip()
    if not chave:
        return {
            "ok": True,
            "cnpj": cnpj_limpo,
            "verificado": False,
            "motivo": "sem chave API — defina PORTAL_TRANSPARENCIA_KEY (ou TRANSPARENCIA_API_KEY)",
            "n_sancoes": 0,
            "sancoes": [],
        }

    todas: list[dict] = []
    erros: list[str] = []

    async with httpx.AsyncClient() as client:
        for endpoint, tipo in [
            ("ceis", "CEIS"),
            ("cnep", "CNEP"),
            ("cepim", "CEPIM"),
        ]:
            ok, lista, erro = await _consultar_endpoint(client, endpoint, cnpj_limpo, chave)
            if ok:
                for s in lista:
                    todas.append(_normalizar_sancao(s, tipo))
            else:
                erros.append(f"{tipo}: {erro}")
                logger.warning("Falha ao consultar %s: %s", tipo, erro)

    return {
        "ok": True,
        "cnpj": cnpj_limpo,
        "verificado": True,
        "n_sancoes": len(todas),
        "sancoes": todas,
        "erros_parciais": erros if erros else None,
    }
