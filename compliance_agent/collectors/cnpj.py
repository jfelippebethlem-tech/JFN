"""
CNPJ lookup via BrasilAPI (gratuita, sem autenticação).
Retorna dados da empresa + sócios da Receita Federal.
"""

import asyncio
import json
import logging
import re
from datetime import date
from typing import Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:  # só p/ anotação (o import real é lazy dentro da função) — resolve F821
    from compliance_agent.database.models import Empresa


BRASILAPI_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
_HEADERS = {"User-Agent": "JFN-Compliance-Agent/1.0 (transparencia publica)"}


logger = logging.getLogger(__name__)


def _clean_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


async def buscar_cnpj(cnpj: str, client: Optional[httpx.AsyncClient] = None) -> dict:
    """
    Consulta dados de um CNPJ na BrasilAPI.

    Returns a dict with keys:
        razao_social, nome_fantasia, situacao_cadastral, data_abertura,
        capital_social, natureza_juridica, atividade_principal,
        municipio, uf, qsa (lista de sócios), raw
    """
    cnpj_clean = _clean_cnpj(cnpj)
    if len(cnpj_clean) != 14:
        return {"error": f"CNPJ inválido: {cnpj}"}

    url = BRASILAPI_URL.format(cnpj=cnpj_clean)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=15, headers=_HEADERS)

    try:
        r = await client.get(url)
        if r.status_code == 404:
            return {"error": "CNPJ não encontrado"}
        r.raise_for_status()
        data = r.json()

        socios = []
        for s in data.get("qsa", []):
            socios.append({
                "nome":           s.get("nome_socio", ""),
                "cpf_cnpj":       s.get("cnpj_cpf_do_socio", ""),
                "qualificacao":   s.get("qualificacao_socio", ""),
                "data_entrada":   s.get("data_entrada_sociedade", ""),
            })

        atividade = ""
        ativs = data.get("cnae_fiscal_descricao") or ""
        if isinstance(ativs, list) and ativs:
            atividade = ativs[0].get("descricao", "")
        elif isinstance(ativs, str):
            atividade = ativs

        return {
            "cnpj":           cnpj_clean,
            "razao_social":   data.get("razao_social", ""),
            "nome_fantasia":  data.get("nome_fantasia", ""),
            "situacao":       data.get("descricao_situacao_cadastral", ""),
            "data_abertura":  data.get("data_inicio_atividade", ""),
            "capital_social": data.get("capital_social", 0),
            "natureza_jur":   data.get("natureza_juridica", ""),
            "atividade":      atividade,
            "municipio":      data.get("municipio", ""),
            "uf":             data.get("uf", ""),
            "cep":            re.sub(r"\D", "", data.get("cep", "") or ""),
            "socios":         socios,
            "raw":            data,
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if owns_client:
            await client.aclose()


async def buscar_varios_cnpjs(cnpjs: list[str], delay: float = 0.5) -> list[dict]:
    """Busca múltiplos CNPJs respeitando rate limit da BrasilAPI."""
    results = []
    async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
        for cnpj in cnpjs:
            result = await buscar_cnpj(cnpj, client=client)
            results.append(result)
            await asyncio.sleep(delay)
    return results


def salvar_empresa(dados: dict, session) -> "Empresa":
    """Persiste dados da BrasilAPI no banco de dados."""
    from compliance_agent.database.models import Empresa, EmpresaSocio, Pessoa

    if "error" in dados:
        return None

    empresa = session.query(Empresa).filter_by(cnpj=dados["cnpj"]).first()
    if not empresa:
        empresa = Empresa(cnpj=dados["cnpj"])
        session.add(empresa)

    empresa.razao_social    = dados["razao_social"]
    empresa.nome_fantasia   = dados.get("nome_fantasia", "")
    empresa.situacao        = dados.get("situacao", "")
    empresa.natureza_jur    = dados.get("natureza_jur", "")
    empresa.atividade_princ = dados.get("atividade", "")
    empresa.municipio       = dados.get("municipio", "")
    empresa.uf              = dados.get("uf", "")
    empresa.cep             = dados.get("cep", "")
    empresa.capital_social  = dados.get("capital_social", 0)
    empresa.raw_json        = json.dumps(dados.get("raw", {}), ensure_ascii=False)

    try:
        da = dados.get("data_abertura", "")
        if da:
            empresa.data_abertura = date.fromisoformat(da[:10])
    except Exception as exc:
        logger.debug("data_abertura ilegível (%r): %s", da, exc)

    session.flush()

    # Sócios
    for s in dados.get("socios", []):
        cpf_cnpj = re.sub(r"\D", "", s.get("cpf_cnpj", ""))
        socio_db = session.query(EmpresaSocio).filter_by(
            empresa_id=empresa.id, cpf_cnpj=cpf_cnpj, nome=s["nome"]
        ).first()
        if not socio_db:
            socio_db = EmpresaSocio(
                empresa_id = empresa.id,
                cpf_cnpj   = cpf_cnpj,
                nome       = s["nome"],
                qualific   = s.get("qualificacao", ""),
            )
            try:
                if s.get("data_entrada"):
                    socio_db.data_entrada = date.fromisoformat(s["data_entrada"][:10])
            except Exception as exc:
                logger.debug("data_entrada de sócio ilegível: %s", exc)
            session.add(socio_db)

            # Se CPF de 11 dígitos, tenta vincular à Pessoa
            if len(cpf_cnpj) == 11:
                pessoa = session.query(Pessoa).filter_by(cpf=cpf_cnpj).first()
                if pessoa:
                    socio_db.pessoa_id = pessoa.id

    session.commit()
    return empresa
