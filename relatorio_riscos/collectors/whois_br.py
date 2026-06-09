"""
Consulta WHOIS/RDAP de domínios .br via Registro.br.

Fonte: https://rdap.registro.br/domain/{dominio}
Sem autenticação — API pública.
"""
from __future__ import annotations

import re
import logging
import unicodedata

import httpx

logger = logging.getLogger(__name__)

_RDAP_URL = "https://rdap.registro.br/domain/{dominio}"
_TIMEOUT = 15


def _slug(nome: str) -> str:
    """Converte nome para slug adequado para domínio."""
    nfkd = unicodedata.normalize("NFKD", nome.lower())
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_str)


def _extrair_contato(vcards: list) -> dict:
    """Extrai dados de contato de um array vCard."""
    dados: dict = {}
    for entry in vcards:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        tipo = entry[0]
        valor = entry[3]
        if tipo == "fn":
            dados["nome"] = valor if isinstance(valor, str) else ""
        elif tipo == "email":
            dados["email"] = valor if isinstance(valor, str) else ""
        elif tipo == "org":
            dados["organizacao"] = valor if isinstance(valor, str) else ""
        elif tipo == "tel":
            dados["telefone"] = valor if isinstance(valor, str) else ""
    return dados


def _extrair_registrante(data: dict) -> dict:
    """Extrai dados do registrante da resposta RDAP."""
    entidades = data.get("entities") or []
    for ent in entidades:
        roles = ent.get("roles") or []
        if "registrant" in roles:
            vcards = ent.get("vcardArray") or []
            contato = {}
            if vcards and len(vcards) > 1:
                contato = _extrair_contato(vcards[1])
            # CPF/CNPJ pode aparecer no publicIds
            cpf_cnpj = ""
            for pub in ent.get("publicIds") or []:
                if pub.get("type") in ("CPF", "CNPJ", "nic.br handle"):
                    cpf_cnpj = pub.get("identifier") or ""
                    break
            return {
                "nome": contato.get("nome") or ent.get("handle") or "",
                "cpf_cnpj": cpf_cnpj,
                "email": contato.get("email") or "",
                "organizacao": contato.get("organizacao") or "",
            }
    return {"nome": "", "cpf_cnpj": "", "email": "", "organizacao": ""}


def _extrair_data_evento(data: dict, tipo: str) -> str:
    """Extrai data de um evento RDAP pelo tipo."""
    for ev in data.get("events") or []:
        if ev.get("eventAction") == tipo:
            return (ev.get("eventDate") or "")[:10]
    return ""


def _extrair_nameservers(data: dict) -> list[str]:
    return [
        ns.get("ldhName") or ns.get("unicodeName") or ""
        for ns in data.get("nameservers") or []
        if ns.get("ldhName") or ns.get("unicodeName")
    ]


async def consultar_whois(dominio: str) -> dict:
    """
    Consulta RDAP do domínio via Registro.br.

    Parâmetro
    ---------
    dominio : ex. "cashpago.com.br" (com ou sem www)

    Retorno
    -------
    dict com "ok", "dominio", "registrado_em", "atualizado_em",
    "expira_em", "registrante", "nome_servidores".
    """
    dominio_limpo = dominio.lower().strip().lstrip("www.").strip("/")
    url = _RDAP_URL.format(dominio=dominio_limpo)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=_TIMEOUT, follow_redirects=True)

        if r.status_code == 404:
            return {
                "ok": True,
                "dominio": dominio_limpo,
                "encontrado": False,
                "motivo": "domínio não registrado ou não disponível no RDAP",
            }

        if r.status_code != 200:
            return {
                "ok": False,
                "dominio": dominio_limpo,
                "erro": f"RDAP retornou HTTP {r.status_code}",
            }

        data = r.json()
        registrante = _extrair_registrante(data)

        return {
            "ok": True,
            "dominio": dominio_limpo,
            "encontrado": True,
            "registrado_em": _extrair_data_evento(data, "registration"),
            "atualizado_em": _extrair_data_evento(data, "last changed"),
            "expira_em": _extrair_data_evento(data, "expiration"),
            "status": data.get("status") or [],
            "registrante": registrante,
            "nome_servidores": _extrair_nameservers(data),
        }

    except httpx.TimeoutException:
        return {
            "ok": False,
            "dominio": dominio_limpo,
            "erro": "Timeout ao consultar RDAP",
        }
    except Exception as exc:
        logger.exception("Erro RDAP para domínio %s", dominio_limpo)
        return {
            "ok": False,
            "dominio": dominio_limpo,
            "erro": str(exc),
        }


def _gerar_variacoes_dominio(nome: str) -> list[str]:
    """Gera variações de domínio .com.br a partir do nome da empresa."""
    slug = _slug(nome)
    if not slug:
        return []
    variacoes = [f"{slug}.com.br"]
    # Remove termos jurídicos comuns
    for termo in ("ltda", "sa", "eireli", "me", "epp", "solucoes", "servicos", "comercio"):
        if slug.endswith(termo) and len(slug) > len(termo) + 3:
            base = slug[: -len(termo)]
            variacoes.append(f"{base}.com.br")
            break
    return list(dict.fromkeys(variacoes))  # dedup mantendo ordem


async def buscar_dominios_grupo(lista_nomes: list[str]) -> list[dict]:
    """
    Tenta variações .com.br para cada nome da lista.

    Parâmetro
    ---------
    lista_nomes : nomes de empresas ou pessoas para tentar

    Retorno
    -------
    lista de resultados de consultar_whois (apenas os encontrados + erros)
    """
    dominios_unicos: list[str] = []
    for nome in lista_nomes:
        for d in _gerar_variacoes_dominio(nome):
            if d not in dominios_unicos:
                dominios_unicos.append(d)

    import asyncio

    tarefas = [consultar_whois(d) for d in dominios_unicos]
    resultados = await asyncio.gather(*tarefas, return_exceptions=False)

    # Filtra para retornar apenas os relevantes (encontrados ou erro)
    saida = []
    for res in resultados:
        if isinstance(res, dict):
            if res.get("ok") and res.get("encontrado"):
                saida.append(res)
            elif not res.get("ok"):
                saida.append(res)  # inclui erros para auditoria
    return saida
