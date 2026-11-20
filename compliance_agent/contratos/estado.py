# -*- coding: utf-8 -*-
"""Os SEIS órgãos do governo do estado do RJ na câmara de contratos.

POR QUE não vem do PNCP: o executivo estadual do RJ tem baixa adesão ao PNCP
(verificado ao vivo: só o TJRJ publica). A fonte real dos contratos estaduais é
o TCE-RJ (dados abertos → contratos_tcerj/compras_diretas_tcerj), e os pagamentos
vêm do SIAFE (ob_orcamentaria_siafe/ordens_bancarias). Este adaptador monta o
MESMO dossiê que a câmara municipal usa, para os detectores/parecer serem reusados.

Limites honestos do dado estadual (ausente ≠ 0):
  • TCE-RJ não traz TERMOS ADITIVOS → dimensão aditivo fica nao_avaliavel.
  • valor_unitario das dispensas às vezes é o total do item → sobrepreço via
    compras_diretas é best-effort (o parecer declara).
Apoio principal do parecer estadual: sinais cruzados, Lex e prorrogação (vigência).
"""
from __future__ import annotations

from compliance_agent.cpf_cnpj import digitos as _digitos
from compliance_agent.contratos.dossie import sinais_fornecedor, tem_tabela
from compliance_agent.cruzamentos_intel import _ob_paga

# os SEIS → padrões de unidade no TCE-RJ (uma família pode ter várias unidades)
ORGAOS_ESTADO = {
    "SAUDE":    ("FSERJ", "FES ", "FUNDO ESTADUAL DE SAUDE", "FUNDO ESTADUAL DE SAÚDE",
                 "SES ", "SECRET ESTADO  SAUDE", "SECRETARIA DE ESTADO DE SAUDE", "SAÚDE"),
    "EDUCACAO": ("SEEDUC", "EDUCAÇÃO", "EDUCACAO"),
    "FAZENDA":  ("SEFAZ", "FAZENDA"),
    "DETRAN":   ("DETRAN",),
    "INEA":     ("INEA",),
    "GOVERNO":  ("SEGOV", "SECC", "CASA CIVIL", "SECRETARIA DE ESTADO DE GOVERNO"),
}


def orgao_de_unidade(unidade: str) -> str | None:
    """Mapeia o nome da unidade do TCE-RJ para um dos seis órgãos canônicos."""
    U = (unidade or "").upper()
    for orgao, padroes in ORGAOS_ESTADO.items():
        if any(p.upper() in U for p in padroes):
            return orgao
    return None


def _pagamentos_por_processo(con, processo: str) -> dict:
    """Soma paga no SIAFE ligada ao MESMO processo do contrato (empenho≠pago).

    Só OB paga (`_ob_paga`: anulada/excluída e a devolvida pelo banco ficam fora). 19/11/2026: a ligação é a de
    `ob_processo` — nº exato e normalizado ("…/23", sem "SEI-") e NL/PD/OB juntadas nos autos —, com a devolução
    (GD) descontada; o `processo=?` literal subcontava a outra grafia e somava a OB devolvida e a reemitida.
    Um dossiê por vez: autos=True. `por_via`/`piso` dizem de onde vem cada real e se o total é piso."""
    if not processo or not tem_tabela(con, "ob_orcamentaria_siafe"):
        return {}
    from compliance_agent.ob_processo import chave_processo, obs_por_processo
    if chave_processo(processo) is None:
        # nº fora do padrão SEI (processo "E-02/000934/2024" do papel): sem chave normalizada, vale o literal
        r = con.execute(f"select coalesce(sum(valor),0) from ob_orcamentaria_siafe where processo=? and {_ob_paga(con)}",
                        (processo,)).fetchone()
        return {"pago": r[0], "empenhado": None, "liquidado": None} if r and r[0] else {}
    d = obs_por_processo(con, [processo], autos=True, so_pagos=True).get(chave_processo(processo))
    if not d or not d["total"]:
        return {}
    return {"pago": d["total"], "empenhado": None, "liquidado": None, "n_obs": d["n"], "por_via": d["por_via"],
            "piso": d["piso"], "candidatas": d["candidatas"]}


def _itens_dispensa(con, processo: str) -> list[dict]:
    """Itens/preços da compra direta ligada ao processo (best-effort p/ sobrepreço)."""
    if not processo or not tem_tabela(con, "compras_diretas_tcerj"):
        return []
    rows = con.execute(
        "select item, objeto, valor_unitario, quantidade from compras_diretas_tcerj where processo=?",
        (processo,)).fetchall()
    return [{"descricao": (r[0] or r[1] or ""), "valor_unitario": r[2], "quantidade": r[3]}
            for r in rows]


def montar_dossie_tcerj(con, contrato_row) -> dict:
    """Dossiê no MESMO formato de contratos.dossie.montar_dossie, para a câmara."""
    c = dict(contrato_row) if not isinstance(contrato_row, dict) else contrato_row
    doc = _digitos(c.get("cnpj"))
    processo = c.get("processo") or c.get("sei_norm")
    contrato = {
        "numero_controle_pncp": f"tcerj:{c.get('id')}",
        "orgao_nome": c.get("unidade"),
        "orgao": orgao_de_unidade(c.get("unidade")),
        "fornecedor_documento": doc,
        "fornecedor_nome": c.get("fornecedor"),
        "objeto": c.get("objeto"),
        "valor_inicial": c.get("valor_contrato"),
        "valor_global": c.get("valor_contrato"),
        "vigencia_ini": c.get("vig_inicio"),
        "vigencia_fim": c.get("vig_fim"),
        "processo": processo,
    }
    return {
        "contrato": contrato,
        "aditivos": [],                              # TCE-RJ não traz termos → aditivo nao_avaliavel
        "pagamentos": _pagamentos_por_processo(con, processo),
        "itens": _itens_dispensa(con, processo),
        "sinais_fornecedor": sinais_fornecedor(con, doc, com_rede=True),
        "proveniencia": {"contrato": "TCE-RJ contratos_tcerj", "pagamentos": "SIAFE por processo",
                         "itens": "TCE-RJ compras_diretas", "sinais_fornecedor": "CEIS/emendas/rede"},
    }


def contratos_dos_seis(con, limite_por_orgao: int = 50) -> list:
    """Retorna linhas de contratos_tcerj dos seis órgãos, maior valor primeiro."""
    if not tem_tabela(con, "contratos_tcerj"):
        return []
    padroes = [p for ps in ORGAOS_ESTADO.values() for p in ps]
    like = " or ".join("upper(unidade) like ?" for _ in padroes)
    args = [f"%{p.upper()}%" for p in padroes]
    rows = con.execute(
        f"""select * from contratos_tcerj where ({like}) and valor_contrato > 0
            order by valor_contrato desc limit ?""", (*args, limite_por_orgao * 6)).fetchall()
    return rows
