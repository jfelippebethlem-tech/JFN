"""
Querido Diário — API pública do DOERJ histórico.
Open Knowledge Brasil: https://queridodiario.ok.org.br

Permite buscar por palavra-chave em TODOS os diários oficiais do RJ
desde ~2019. Útil para:
  - Verificar se uma empresa já apareceu em publicações suspeitas no passado
  - Rastrear histórico de nomeações de uma pessoa
  - Ver em quantas licitações uma empresa participou
  - Detectar padrões ao longo do tempo

API: https://queridodiario.ok.org.br/api/gazettes
Sem autenticação, gratuita.
"""

import asyncio
from datetime import date, timedelta
from typing import Optional

import httpx

QD_API = "https://queridodiario.ok.org.br/api/gazettes"

# ID do município do Rio de Janeiro no Querido Diário
# Para diário ESTADUAL do RJ, usar territory_id do estado
RJ_TERRITORY = "3304557"   # município RJ (tem mais cobertura que o estadual)
RJ_ESTADO    = "33"         # estado RJ


async def buscar_historico(
    termo: str,
    desde: Optional[date] = None,
    ate: Optional[date] = None,
    max_resultados: int = 10,
) -> list[dict]:
    """
    Busca um termo no histórico completo do DOERJ via Querido Diário.
    Retorna lista de publicações encontradas.
    """
    params = {
        "querystring": termo,
        "territory_id": RJ_TERRITORY,
        "size": max_resultados,
        "offset": 0,
        "sort_by": "relevance",
    }
    if desde:
        params["since"] = desde.strftime("%Y-%m-%d")
    if ate:
        params["until"] = ate.strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(QD_API, params=params,
                                 headers={"User-Agent": "JFN-Compliance/1.0"})
            if r.status_code == 200:
                data = r.json()
                return data.get("gazettes", [])
    except Exception:
        pass
    return []


async def historico_empresa(cnpj_ou_nome: str, anos: int = 3) -> dict:
    """
    Busca o histórico completo de uma empresa no DOERJ.
    Retorna: total de aparições, tipos de publicação, primeiros resultados.
    """
    desde = date.today() - timedelta(days=365 * anos)
    resultados = await buscar_historico(cnpj_ou_nome, desde=desde, max_resultados=20)

    tipos: dict[str, int] = {}
    excerpts = []
    for r in resultados:
        for exc in r.get("excerpts", []):
            texto = exc.get("text", "").lower()
            # Classifica o tipo pelo conteúdo
            if any(w in texto for w in ["contrato", "contratação", "dispensa"]):
                tipos["contrato"] = tipos.get("contrato", 0) + 1
            elif any(w in texto for w in ["licitação", "pregão", "edital"]):
                tipos["licitacao"] = tipos.get("licitacao", 0) + 1
            elif any(w in texto for w in ["multa", "sanção", "penalidade", "rescisão"]):
                tipos["sancao"] = tipos.get("sancao", 0) + 1
            elif any(w in texto for w in ["nomeação", "nomeado", "cargo"]):
                tipos["nomeacao"] = tipos.get("nomeacao", 0) + 1
            else:
                tipos["outro"] = tipos.get("outro", 0) + 1
            excerpts.append({
                "data": r.get("date"),
                "url": r.get("url"),
                "trecho": exc.get("text", "")[:200],
            })

    return {
        "termo": cnpj_ou_nome,
        "total_publicacoes": len(resultados),
        "tipos": tipos,
        "tem_sancao_historica": tipos.get("sancao", 0) > 0,
        "excerpts": excerpts[:5],
    }


async def enriquecer_obs_com_historico(session, target_date: date = None) -> list[dict]:
    """
    Para OBs de alto valor do dia, busca histórico da empresa no Querido Diário.
    Alerta quando empresa tem histórico de sanções no DOERJ.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta

    target_date = target_date or date.today()
    VALOR_MINIMO = 100_000.0

    obs = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao == target_date,
            OrdemBancaria.valor >= VALOR_MINIMO,
            OrdemBancaria.favorecido_nome.isnot(None),
        )
        .all()
    )

    alertas = []
    verificados: set[str] = set()

    for ob in obs:
        nome = (ob.favorecido_nome or "").strip()
        if not nome or nome in verificados:
            continue
        verificados.add(nome)

        hist = await historico_empresa(nome)
        await asyncio.sleep(0.5)

        if hist["tem_sancao_historica"]:
            titulo = f"Histórico de sanções no DOERJ — {nome}"[:300]
            existe = session.query(Alerta).filter_by(titulo=titulo).first()
            if not existe:
                n_sancoes = hist["tipos"].get("sancao", 0)
                alerta = Alerta(
                    tipo="historico_sancao_doerj",
                    severidade="alta",
                    titulo=titulo,
                    descricao=(
                        f"'{nome}' recebeu OB de R$ {ob.valor:,.2f} (nº {ob.numero_ob}) "
                        f"e aparece {hist['total_publicacoes']} vez(es) no histórico do DOERJ "
                        f"nos últimos 3 anos, incluindo {n_sancoes} publicação(ões) de sanção. "
                        f"Verificar se as sanções anteriores foram regularizadas antes do pagamento."
                    ),
                    evidencias=str(hist),
                    data_referencia=target_date,
                    ordem_bancaria_id=ob.id,
                )
                session.add(alerta)
                alertas.append({
                    "ob": ob.numero_ob,
                    "favorecido": nome,
                    "valor": ob.valor,
                    "n_sancoes_historicas": n_sancoes,
                    "total_publicacoes": hist["total_publicacoes"],
                })

    session.commit()
    return alertas


async def buscar_pessoa(nome: str, anos: int = 5) -> dict:
    """Busca histórico de uma pessoa no DOERJ (nomeações, exonerações, etc.)."""
    return await historico_empresa(nome, anos=anos)
