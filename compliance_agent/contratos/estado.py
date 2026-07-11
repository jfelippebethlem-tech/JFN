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

import re

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


def _digitos(doc: str) -> str:
    return re.sub(r"\D", "", doc or "")


def _tem_tabela(con, nome: str) -> bool:
    return bool(con.execute("select 1 from sqlite_master where type='table' and name=?",
                            (nome,)).fetchone())


def _sinais_fornecedor(con, doc: str) -> list[str]:
    sinais = []
    if not doc:
        return sinais
    if _tem_tabela(con, "sancoes_federais") and con.execute(
            "select 1 from sancoes_federais where cpf_cnpj=? limit 1", (doc,)).fetchone():
        sinais.append("fornecedor sancionado (CEIS)")
    if _tem_tabela(con, "emenda_favorecidos") and con.execute(
            "select 1 from emenda_favorecidos where documento_favorecido=? limit 1", (doc,)).fetchone():
        sinais.append("favorecido de emenda federal")
    if _tem_tabela(con, "rede_socios_fornecedores"):
        try:
            if con.execute("select 1 from rede_socios_fornecedores where raiz=? limit 1",
                           (doc[:8],)).fetchone():
                sinais.append("sócio liga ≥2 fornecedores (rede)")
        except Exception:
            pass
    return sinais


def _pagamentos_por_processo(con, processo: str) -> dict:
    """Soma paga no SIAFE ligada ao MESMO processo do contrato (empenho≠pago)."""
    if not processo or not _tem_tabela(con, "ob_orcamentaria_siafe"):
        return {}
    r = con.execute(
        "select coalesce(sum(valor),0) from ob_orcamentaria_siafe where processo=?",
        (processo,)).fetchone()
    return {"pago": r[0], "empenhado": None, "liquidado": None} if r and r[0] else {}


def _itens_dispensa(con, processo: str) -> list[dict]:
    """Itens/preços da compra direta ligada ao processo (best-effort p/ sobrepreço)."""
    if not processo or not _tem_tabela(con, "compras_diretas_tcerj"):
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
        "sinais_fornecedor": _sinais_fornecedor(con, doc),
        "proveniencia": {"contrato": "TCE-RJ contratos_tcerj", "pagamentos": "SIAFE por processo",
                         "itens": "TCE-RJ compras_diretas", "sinais_fornecedor": "CEIS/emendas/rede"},
    }


def contratos_dos_seis(con, limite_por_orgao: int = 50) -> list:
    """Retorna linhas de contratos_tcerj dos seis órgãos, maior valor primeiro."""
    if not _tem_tabela(con, "contratos_tcerj"):
        return []
    padroes = [p for ps in ORGAOS_ESTADO.values() for p in ps]
    like = " or ".join("upper(unidade) like ?" for _ in padroes)
    args = [f"%{p.upper()}%" for p in padroes]
    rows = con.execute(
        f"""select * from contratos_tcerj where ({like}) and valor_contrato > 0
            order by valor_contrato desc limit ?""", (*args, limite_por_orgao * 6)).fetchall()
    return rows
