"""
Entry point principal do módulo Relatório de Riscos Corporativos.

Uso rápido
----------
    import asyncio
    from relatorio_riscos import gerar_relatorio_risco

    resultado = asyncio.run(gerar_relatorio_risco("28.584.601/0001-08"))
    print(resultado["risco"])          # "ALTO" / "MÉDIO" / "BAIXO"
    print(resultado["relatorio_path"]) # caminho do arquivo .md salvo
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Optional

from .collectors.cnpj_receita import buscar_cnpj
from .collectors.contratos_pncp import buscar_contratos_por_cnpj
from .collectors.sancoes import verificar_sancoes
from .collectors.whois_br import buscar_dominios_grupo
from .collectors.cache import limpar_expirados
from .analise.rede_societaria import expandir_rede
from .analise.sinais_risco import calcular_sinais
from .relatorio.gerador import gerar_md, gerar_txt, salvar_relatorio

logger = logging.getLogger(__name__)


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


async def _coletar_paralelo(cnpj: str) -> tuple[dict, dict, dict]:
    """Executa coletores de dados em paralelo."""
    resultados = await asyncio.gather(
        buscar_cnpj(cnpj),
        buscar_contratos_por_cnpj(cnpj),
        verificar_sancoes(cnpj),
        return_exceptions=True,
    )

    empresa = resultados[0] if not isinstance(resultados[0], Exception) else {
        "ok": False, "erro": str(resultados[0]), "razao_social": "", "cnpj": cnpj,
        "socios": [], "situacao": "", "data_abertura": "", "capital_social": 0.0,
        "porte": "", "natureza_juridica": "", "email": "", "mei": False, "simples": False,
    }
    contratos = resultados[1] if not isinstance(resultados[1], Exception) else {
        "ok": False, "erro": str(resultados[1]), "total": 0, "contratos": [],
    }
    sancoes = resultados[2] if not isinstance(resultados[2], Exception) else {
        "ok": False, "erro": str(resultados[2]), "verificado": False, "sancoes": [],
    }

    return empresa, contratos, sancoes


async def gerar_relatorio_risco(
    cnpj: str,
    formato: str = "md",
    cnpjs_adicionais: Optional[list[str]] = None,
    salvar: bool = True,
) -> dict:
    """
    Gera relatório de riscos corporativos para o CNPJ informado.

    Parâmetros
    ----------
    cnpj              : CNPJ da empresa (com ou sem pontuação)
    formato           : "md" (Markdown), "txt" (texto simples) ou "json" (dados brutos)
    cnpjs_adicionais  : CNPJs extras para expandir a rede societária
    salvar            : se True, salva o relatório em /reports/

    Retorno
    -------
    dict com:
        ok             : bool
        cnpj           : str (sem pontuação)
        empresa        : str (razão social)
        risco          : "ALTO" / "MÉDIO" / "BAIXO"
        sinais         : lista de dicts {nivel, descricao, detalhe}
        relatorio_md   : str (conteúdo Markdown)
        relatorio_path : str (caminho do arquivo salvo, ou "" se salvar=False)
        dados          : dict com subchaves empresa/rede/contratos/sancoes/sinais
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {
            "ok": False,
            "erro": f"CNPJ inválido: {cnpj!r} (esperado 14 dígitos)",
            "cnpj": cnpj_limpo,
            "empresa": "",
            "risco": "—",
            "sinais": [],
            "relatorio_md": "",
            "relatorio_path": "",
        }

    data_analise = date.today().isoformat()
    logger.info("Iniciando análise de risco para CNPJ %s", cnpj_limpo)

    # 1. Coleta em paralelo
    empresa, contratos, sancoes = await _coletar_paralelo(cnpj_limpo)

    # 2. Rede societária (depende dos dados da empresa)
    rede = await expandir_rede(cnpj_limpo, max_nivel=3, cnpjs_adicionais=cnpjs_adicionais)

    # 3. WHOIS de domínios (best-effort, não bloqueia o relatório)
    dominios_whois: list[dict] = []
    nome_empresa = empresa.get("razao_social") or ""
    if nome_empresa:
        try:
            dominios_whois = await buscar_dominios_grupo([nome_empresa])
        except Exception as exc:
            logger.warning("WHOIS falhou: %s", exc)

    # 4. Sinais de risco
    sinais = calcular_sinais(empresa, rede, contratos, sancoes)

    # 5. Geração do relatório
    relatorio_md = gerar_md(empresa, rede, contratos, sancoes, sinais, data_analise)

    relatorio_path = ""
    if formato == "pdf":
        from .relatorio.pdf import salvar_pdf
        if salvar:
            try:
                relatorio_path = salvar_pdf(empresa, rede, contratos, sancoes, sinais, data_analise, relatorio_md)
                logger.info("PDF salvo em: %s", relatorio_path)
            except Exception as exc:
                logger.error("Erro ao gerar PDF: %s", exc)
        conteudo_salvar = ""
        ext = "pdf"
    elif formato == "txt":
        conteudo_salvar = gerar_txt(empresa, rede, contratos, sancoes, sinais, data_analise)
        ext = "txt"
    elif formato == "json":
        conteudo_salvar = ""
        ext = "json"
    else:
        conteudo_salvar = relatorio_md
        ext = "md"

    limpar_expirados()

    if salvar and conteudo_salvar and formato != "pdf":
        try:
            relatorio_path = salvar_relatorio(conteudo_salvar, cnpj_limpo, data_analise, ext)
            logger.info("Relatório salvo em: %s", relatorio_path)
        except Exception as exc:
            logger.error("Erro ao salvar relatório: %s", exc)

    todos_sinais = (
        sinais.get("sinais_alto", [])
        + sinais.get("sinais_medio", [])
        + sinais.get("sinais_baixo", [])
    )

    return {
        "ok": True,
        "cnpj": cnpj_limpo,
        "empresa": nome_empresa,
        "risco": sinais.get("nivel_geral") or "BAIXO",
        "score": sinais.get("score") or 0,
        "sinais": todos_sinais,
        "relatorio_md": relatorio_md,
        "relatorio_path": relatorio_path,
        "dados": {
            "empresa": empresa,
            "rede": rede,
            "contratos": contratos,
            "sancoes": sancoes,
            "sinais": sinais,
            "whois": dominios_whois,
        },
    }
