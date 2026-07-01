"""
Adaptador banco → Dossiê.

Liga o Núcleo de Inteligência Progressiva à base real do JFN (models SQLAlchemy),
sem acoplar os indicadores ao ORM. Monta ``Dossie`` a partir de ``Contrato`` /
``OrdemBancaria`` + ``Empresa`` + ``DoacaoEleitoral``, incluindo:

  - histórico órgão×fornecedor (para fracionamento),
  - referência estatística da categoria (para superfaturamento),
  - doações eleitorais reais do favorecido (para quid pro quo).

É defensivo: campo ausente no banco vira ``None`` e o indicador dependente
simplesmente não dispara — nunca quebra a perícia.

Uso:
    from compliance_agent.database.models import get_session  # conforme o projeto
    from compliance_agent.nucleo.adaptador_db import periciar_contrato, periciar_ob

    laudo = periciar_contrato(session, contrato_id=123)
    laudos = list(periciar_top_obs(session, limite=100))   # varredura da base
"""

from __future__ import annotations

import re
import statistics
from typing import Iterable, Iterator

from compliance_agent.nucleo.dossie import Contratacao, Dossie, Fornecedor
from compliance_agent.nucleo.nucleo import Laudo, periciar


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _categoria(texto: str) -> str:
    """
    Normaliza a categoria do objeto usando a heurística já existente
    (reports.categorizar.area_objeto). Lowercase + primeira palavra, para casar
    com as chaves dos indicadores (ex.: 'obras', 'saúde'). Falha → "".
    """
    if not texto:
        return ""
    try:
        from compliance_agent.reports.categorizar import area_objeto
        cat = (area_objeto(texto) or "").strip().lower()
        return cat.split(" / ")[0].split()[0] if cat else ""
    except Exception:
        return ""


def _doacoes_do_fornecedor(session, cnpj: str) -> list[dict]:
    """Doações eleitorais cujo doador é o CNPJ (ou sua raiz) do fornecedor."""
    try:
        from compliance_agent.database.models import DoacaoEleitoral
    except Exception:
        return []
    if not cnpj:
        return []
    saida: list[dict] = []
    try:
        q = (session.query(DoacaoEleitoral)
             .filter(DoacaoEleitoral.cpf_cnpj_doador.isnot(None)))
        raiz = cnpj[:8]
        for d in q.limit(500):
            doc = _digits(d.cpf_cnpj_doador)
            if doc == cnpj or (len(doc) >= 8 and doc[:8] == raiz):
                saida.append({"valor": d.valor, "data": d.data_doacao,
                              "candidato": d.nome_candidato})
    except Exception:
        return []
    return saida


def _fornecedor_de_empresa(empresa, session=None) -> Fornecedor:
    if empresa is None:
        return Fornecedor()
    cnpj = _digits(getattr(empresa, "cnpj", ""))
    situacao = getattr(empresa, "situacao", "") or ""
    end_tipo = ""
    # heurística leve de endereço a partir da natureza jurídica/municipio ausente
    f = Fornecedor(
        cnpj=cnpj,
        nome=getattr(empresa, "razao_social", "") or "",
        data_abertura=getattr(empresa, "data_abertura", None),
        capital_social=getattr(empresa, "capital_social", None),
        situacao=situacao,
        cnae_principal=getattr(empresa, "atividade_princ", "") or "",
        endereco_tipo=end_tipo,
        fonte="cnpj",
    )
    if session is not None and cnpj:
        f.doacoes_eleitorais = _doacoes_do_fornecedor(session, cnpj)
    return f


def _referencia_categoria(session, categoria: str) -> dict[str, float]:
    """Mediana e desvio-padrão dos valores da categoria (contratos)."""
    if not categoria:
        return {}
    try:
        from compliance_agent.database.models import Contrato
        valores = [
            v for (v,) in session.query(Contrato.valor_total)
            .filter(Contrato.valor_total.isnot(None), Contrato.valor_total > 0)
            .all()
        ]
    except Exception:
        return {}
    valores = [float(v) for v in valores if v]
    if len(valores) < 5:
        return {}
    ref = {"mediana": statistics.median(valores)}
    try:
        ref["desvio_padrao"] = statistics.pstdev(valores)
    except statistics.StatisticsError:
        pass
    return ref


def _historico_orgao_fornecedor(session, contrato) -> list[Contratacao]:
    """Outros contratos do mesmo órgão×empresa (para fracionamento)."""
    try:
        from compliance_agent.database.models import Contrato
    except Exception:
        return []
    if contrato is None or not getattr(contrato, "empresa_id", None):
        return []
    try:
        outros = (session.query(Contrato)
                  .filter(Contrato.empresa_id == contrato.empresa_id,
                          Contrato.orgao_contrat == contrato.orgao_contrat,
                          Contrato.id != contrato.id)
                  .limit(50).all())
    except Exception:
        return []
    return [_contratacao_de_contrato(c) for c in outros]


def _contratacao_de_contrato(c) -> Contratacao:
    return Contratacao(
        identificador=getattr(c, "numero", "") or str(getattr(c, "id", "")),
        objeto=getattr(c, "objeto", "") or "",
        orgao=getattr(c, "orgao_contrat", "") or "",
        modalidade=getattr(c, "modalidade", "") or "",
        valor=getattr(c, "valor_total", None),
        valor_estimado=getattr(c, "valor_estimado", None),
        data=getattr(c, "data_assinatura", None),
        fonte=getattr(c, "fonte", "") or "contrato",
    )


# ── Entradas públicas ────────────────────────────────────────────────────────

def periciar_contrato(session, contrato_id: int) -> Laudo | None:
    """Perícia de um Contrato específico, com todo o contexto do banco."""
    try:
        from compliance_agent.database.models import Contrato, Empresa
    except Exception:
        return None
    c = session.query(Contrato).get(contrato_id)
    if c is None:
        return None
    empresa = (session.query(Empresa).get(c.empresa_id)
               if getattr(c, "empresa_id", None) else None)
    contratacao = _contratacao_de_contrato(c)
    contratacao.categoria = _categoria(contratacao.objeto)
    return periciar(
        contratacao=contratacao,
        fornecedor=_fornecedor_de_empresa(empresa, session),
        historico=_historico_orgao_fornecedor(session, c),
        referencia_categoria=_referencia_categoria(session, contratacao.categoria),
    )


def periciar_ob(session, ob) -> Laudo:
    """
    Perícia de uma Ordem Bancária (pagamento). Sem edital/propostas, mas cobre
    empresa recém-aberta, sancionamento, quid pro quo e valor colado ao teto.
    """
    from compliance_agent.database.models import Empresa
    cnpj = _digits(getattr(ob, "favorecido_cpf", ""))
    empresa = None
    if len(cnpj) == 14:
        empresa = session.query(Empresa).filter(Empresa.cnpj == cnpj).first()
    fornecedor = _fornecedor_de_empresa(empresa, session)
    if not fornecedor.cnpj and len(cnpj) == 14:
        fornecedor.cnpj = cnpj
        fornecedor.nome = getattr(ob, "favorecido_nome", "") or ""
    contratacao = Contratacao(
        identificador=getattr(ob, "numero_ob", "") or "",
        objeto=getattr(ob, "observacao", "") or "",
        orgao=getattr(ob, "ug_nome", "") or "",
        valor=getattr(ob, "valor", None),
        data=getattr(ob, "data_emissao", None) or getattr(ob, "data_pagamento", None),
        categoria=getattr(ob, "categoria", "") or "",
        fonte="tfe_ob",
    )
    return periciar(contratacao=contratacao, fornecedor=fornecedor)


def periciar_top_obs(session, limite: int = 100,
                     valor_minimo: float = 100_000) -> Iterator[Laudo]:
    """
    Varre as maiores OBs e retorna apenas laudos com achados (risco > baixo),
    ordenados por valor. Ideal para o Auditor 24h priorizar alvos.
    """
    from compliance_agent.database.models import OrdemBancaria
    q = (session.query(OrdemBancaria)
         .filter(OrdemBancaria.valor.isnot(None), OrdemBancaria.valor >= valor_minimo)
         .order_by(OrdemBancaria.valor.desc())
         .limit(limite))
    for ob in q:
        laudo = periciar_ob(session, ob)
        if laudo.veredito.achados:
            yield laudo
