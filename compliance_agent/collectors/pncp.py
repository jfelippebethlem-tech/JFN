"""
Coletor do PNCP — Portal Nacional de Contratações Públicas.
API pública, sem autenticação.

Usos:
  1. Verificar se OBs acima de R$30k têm contrato publicado no PNCP
     (obrigatório desde Lei 14.133/21 art. 94)
  2. Buscar contratos de um fornecedor específico (CNPJ)
  3. Coletar licitações abertas de órgãos do RJ para monitoramento

Endpoint principal:
  https://pncp.gov.br/api/pncp/v1/contratos
  Parâmetros: cnpjOrgao, dataInicial, dataFinal, pagina, tamanhoPagina
"""

import asyncio
import re
from datetime import date, timedelta
from typing import Optional

import httpx

PNCP_BASE = "https://pncp.gov.br/api/pncp/v1"

# CNPJs dos principais órgãos do Estado do RJ para monitoramento
ORGAOS_RJ = {
    "SECRETARIA DE FAZENDA RJ":          "30636722000105",
    "GOVERNO DO ESTADO RJ":              "42498600000148",
    "SECRETARIA DE SAUDE RJ":            "08739068000103",
    "SECRETARIA DE EDUCACAO RJ":         "08739068000104",
    "DETRAN RJ":                         "09176466000109",
    "INEA":                              "10736572000109",
}


async def _get_pncp(endpoint: str, params: dict) -> Optional[dict]:
    url = f"{PNCP_BASE}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, params=params,
                                 headers={"User-Agent": "JFN-Compliance/1.0"})
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def buscar_contratos_fornecedor(
    cnpj_fornecedor: str,
    data_inicial: date,
    data_final: date,
) -> list[dict]:
    """Retorna contratos de um fornecedor (por CNPJ) em um período."""
    cnpj = re.sub(r"\D", "", cnpj_fornecedor)
    if len(cnpj) != 14:
        return []

    params = {
        "cnpjFornecedor": cnpj,
        "dataInicial": data_inicial.strftime("%Y%m%d"),
        "dataFinal": data_final.strftime("%Y%m%d"),
        "pagina": 1,
        "tamanhoPagina": 50,
    }
    result = await _get_pncp("/contratos", params)
    if not result:
        return []
    return result.get("data", []) or (result if isinstance(result, list) else [])


async def buscar_licitacoes_orgao(
    cnpj_orgao: str,
    data_inicial: date,
    data_final: date,
) -> list[dict]:
    """Retorna licitações de um órgão em um período."""
    cnpj = re.sub(r"\D", "", cnpj_orgao)
    params = {
        "cnpjOrgao": cnpj,
        "dataInicial": data_inicial.strftime("%Y%m%d"),
        "dataFinal": data_final.strftime("%Y%m%d"),
        "pagina": 1,
        "tamanhoPagina": 100,
    }
    result = await _get_pncp("/contratacoes/publicacao", params)
    if not result:
        return []
    return result.get("data", []) or (result if isinstance(result, list) else [])


async def verificar_obs_sem_pncp(session, target_date: date = None) -> list[dict]:
    """
    Para cada OB acima de R$30k do dia, verifica se há contrato publicado
    no PNCP para o mesmo CNPJ favorecido. Gera alertas para os que não têm.

    Lei 14.133/21 art. 94: contratos devem ser publicados no PNCP.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta

    target_date = target_date or date.today()
    MINIMO = 30_000.0
    JANELA_DIAS = 365  # contrato pode ter sido assinado até 1 ano antes da OB

    obs = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao == target_date,
            OrdemBancaria.valor >= MINIMO,
            OrdemBancaria.favorecido_cpf.isnot(None),
        )
        .all()
    )

    alertas = []
    verificados = set()  # evita checar mesmo CNPJ múltiplas vezes

    for ob in obs:
        cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))
        if len(cnpj) != 14 or cnpj in verificados:
            continue
        verificados.add(cnpj)

        data_ini = target_date - timedelta(days=JANELA_DIAS)
        contratos = await buscar_contratos_fornecedor(cnpj, data_ini, target_date)
        await asyncio.sleep(0.3)

        if not contratos:
            # Sem contrato publicado no PNCP para este CNPJ
            titulo = f"OB sem contrato no PNCP — {ob.favorecido_nome or cnpj}"[:300]
            existe = session.query(Alerta).filter_by(titulo=titulo).first()
            if not existe:
                alerta = Alerta(
                    tipo="pncp_sem_contrato",
                    severidade="alta",
                    titulo=titulo,
                    descricao=(
                        f"OB nº {ob.numero_ob} (R$ {ob.valor:,.2f}) paga a "
                        f"'{ob.favorecido_nome}' (CNPJ {cnpj}) em {target_date}. "
                        f"Nenhum contrato encontrado no PNCP para este fornecedor "
                        f"nos últimos {JANELA_DIAS} dias. Pagamento sem amparo contratual "
                        f"publicado — possível irregularidade à luz da Lei 14.133/21 art. 94."
                    ),
                    evidencias=str({
                        "numero_ob": ob.numero_ob,
                        "cnpj": cnpj,
                        "favorecido": ob.favorecido_nome,
                        "valor": ob.valor,
                        "pncp_contratos_encontrados": 0,
                    }),
                    data_referencia=target_date,
                    ordem_bancaria_id=ob.id,
                )
                session.add(alerta)
                alertas.append({"ob": ob.numero_ob, "cnpj": cnpj, "valor": ob.valor})

    session.commit()
    return alertas


async def monitorar_licitacoes_rj() -> list[dict]:
    """
    Coleta licitações recentes de todos os órgãos RJ monitorados.
    Útil para alertas proativos antes de contratos suspeitos serem assinados.
    """
    hoje = date.today()
    semana_passada = hoje - timedelta(days=7)
    todas = []

    for nome, cnpj in ORGAOS_RJ.items():
        licitacoes = await buscar_licitacoes_orgao(cnpj, semana_passada, hoje)
        for lic in licitacoes:
            lic["orgao_nome"] = nome
            todas.append(lic)
        await asyncio.sleep(0.5)

    return todas
