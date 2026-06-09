"""
Análise de rede societária a partir de um CNPJ raiz.

Limitação conhecida: APIs públicas brasileiras (BrasilAPI, ReceitaWS) não
expõem busca por CPF/sócio. Por isso a expansão automática além do N0 requer
que os CNPJs adicionais sejam fornecidos manualmente via `cnpjs_adicionais`.

Quando cnpjs_adicionais for fornecido, os CNPJs são agrupados por nível com
base na presença de sócios comuns com o CNPJ raiz.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..collectors.cnpj_receita import buscar_cnpj, _limpar_cnpj  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


def _socios_cpfs(empresa: dict) -> set[str]:
    """Retorna conjunto de CPFs/CNPJs mascarados dos sócios."""
    return {s.get("cpf_cnpj_socio", "") for s in empresa.get("socios", []) if s.get("cpf_cnpj_socio")}


def _socios_nomes(empresa: dict) -> set[str]:
    """Retorna conjunto de nomes dos sócios (uppercase)."""
    return {s.get("nome", "").upper() for s in empresa.get("socios", []) if s.get("nome")}


def _tem_socio_comum(empresa_a: dict, empresa_b: dict) -> bool:
    """Verifica se duas empresas compartilham sócio (por nome)."""
    nomes_a = _socios_nomes(empresa_a)
    nomes_b = _socios_nomes(empresa_b)
    return bool(nomes_a & nomes_b)


async def _buscar_varios(cnpjs: list[str]) -> dict[str, dict]:
    """Busca dados de vários CNPJs em paralelo."""
    tarefas = {cnpj: buscar_cnpj(cnpj) for cnpj in cnpjs}
    resultados = await asyncio.gather(*tarefas.values(), return_exceptions=True)
    saida: dict[str, dict] = {}
    for cnpj, res in zip(tarefas.keys(), resultados):
        if isinstance(res, Exception):
            saida[cnpj] = {"ok": False, "erro": str(res), "cnpj": cnpj, "razao_social": "", "socios": [], "situacao": "ERRO"}
        else:
            saida[cnpj] = res
    return saida


def _resumo_no(empresa: dict) -> dict:
    """Cria resumo de um nó da rede."""
    cnpj = empresa.get("cnpj") or ""
    razao = empresa.get("razao_social") or ""
    status = empresa.get("situacao") or ""
    socios = empresa.get("socios") or []
    return {
        "cnpj": cnpj,
        "razao_social": razao,
        "status": status,
        "capital_social": empresa.get("capital_social") or 0.0,
        "data_abertura": empresa.get("data_abertura") or "",
        "natureza_juridica": empresa.get("natureza_juridica") or "",
        "socios": [
            {
                "nome": s.get("nome", ""),
                "cpf_cnpj_socio": s.get("cpf_cnpj_socio", ""),
                "qualificacao": s.get("qualificacao", ""),
            }
            for s in socios
        ],
    }


def _calcular_pessoas_chave(todos_nos: list[dict]) -> list[dict]:
    """
    Identifica sócios que aparecem em ≥2 empresas.
    Agrupa por nome (uppercase) já que CPF fica mascarado.
    """
    contagem: dict[str, dict] = {}  # nome → {cpf, empresas: [cnpj]}
    for no in todos_nos:
        cnpj = no.get("cnpj", "")
        for s in no.get("socios", []):
            nome = (s.get("nome") or "").upper().strip()
            if not nome:
                continue
            if nome not in contagem:
                contagem[nome] = {
                    "nome": s.get("nome") or nome,
                    "cpf": s.get("cpf_cnpj_socio") or "",
                    "empresas": [],
                }
            if cnpj and cnpj not in contagem[nome]["empresas"]:
                contagem[nome]["empresas"].append(cnpj)

    pessoas_chave = []
    for info in contagem.values():
        n = len(info["empresas"])
        if n >= 2:
            pessoas_chave.append({
                "nome": info["nome"],
                "cpf": info["cpf"],
                "n_empresas": n,
                "empresas": info["empresas"],
            })

    pessoas_chave.sort(key=lambda x: x["n_empresas"], reverse=True)
    return pessoas_chave


async def expandir_rede(
    cnpj_raiz: str,
    max_nivel: int = 3,
    cnpjs_adicionais: Optional[list[str]] = None,
) -> dict:
    """
    Expande a rede societária a partir de um CNPJ raiz.

    Parâmetros
    ----------
    cnpj_raiz         : CNPJ da empresa âncora
    max_nivel         : profundidade máxima (1–3, padrão 3)
    cnpjs_adicionais  : lista de CNPJs extras para incluir na análise
                        (expansão manual — APIs públicas não permitem busca por CPF)

    Retorno
    -------
    dict com nos (N0..N3), pessoas_chave, totais e percentuais de baixadas
    """
    cnpj_raiz_limpo = _limpar_cnpj(cnpj_raiz)
    cnpjs_adicionais = [_limpar_cnpj(c) for c in (cnpjs_adicionais or [])]

    # --- N0: empresa raiz ---
    empresa_raiz = await buscar_cnpj(cnpj_raiz_limpo)
    nos_por_nivel: dict[str, list[dict]] = {"N0": [], "N1": [], "N2": [], "N3": []}
    cnpjs_vistos: set[str] = {cnpj_raiz_limpo}

    if not empresa_raiz.get("ok"):
        return {
            "ok": False,
            "erro": f"Falha ao buscar CNPJ raiz: {empresa_raiz.get('erro')}",
            "cnpj_raiz": cnpj_raiz_limpo,
            "empresa_raiz": "",
            "nos": nos_por_nivel,
            "pessoas_chave": [],
            "total_cnpjs": 0,
            "baixadas_inaptas": 0,
            "pct_baixadas": 0.0,
        }

    nos_por_nivel["N0"].append(_resumo_no(empresa_raiz))

    # --- N1..N3: expansão com CNPJs adicionais ---
    if cnpjs_adicionais and max_nivel >= 1:
        # Busca todos os CNPJs adicionais
        todos_adicionais = [c for c in cnpjs_adicionais if c != cnpj_raiz_limpo]
        dados_adicionais = await _buscar_varios(todos_adicionais)

        for cnpj_add, dados in dados_adicionais.items():
            if cnpj_add in cnpjs_vistos:
                continue
            cnpjs_vistos.add(cnpj_add)
            resumo = _resumo_no(dados)

            # Determina nível pelo grau de conexão
            if _tem_socio_comum(empresa_raiz, dados):
                nivel = "N1"
            else:
                # Verifica se tem sócio comum com algum N1
                tem_n1 = any(
                    _tem_socio_comum(no_n1, dados)
                    for no_n1 in nos_por_nivel.get("N1", [])
                )
                if tem_n1 and max_nivel >= 2:
                    nivel = "N2"
                else:
                    nivel = "N3" if max_nivel >= 3 else "N2"

            if nivel in nos_por_nivel:
                nos_por_nivel[nivel].append(resumo)

    # --- Estatísticas ---
    todos_nos = [
        no
        for nivel in nos_por_nivel.values()
        for no in nivel
    ]
    total_cnpjs = len(todos_nos)

    situacoes_baixadas = {"BAIXADA", "INAPTA", "CANCELADA", "NULA", "SUSPENSA"}
    baixadas = sum(
        1 for no in todos_nos
        if (no.get("status") or "").upper() in situacoes_baixadas
    )
    pct = round(baixadas / total_cnpjs * 100, 1) if total_cnpjs else 0.0

    pessoas_chave = _calcular_pessoas_chave(todos_nos)

    return {
        "ok": True,
        "cnpj_raiz": cnpj_raiz_limpo,
        "empresa_raiz": empresa_raiz.get("razao_social") or "",
        "nos": nos_por_nivel,
        "pessoas_chave": pessoas_chave,
        "total_cnpjs": total_cnpjs,
        "baixadas_inaptas": baixadas,
        "pct_baixadas": pct,
        "aviso": (
            "Expansão automática limitada: APIs públicas não permitem busca por CPF. "
            "Forneça cnpjs_adicionais para análise de rede completa."
        ) if not cnpjs_adicionais else None,
    }
