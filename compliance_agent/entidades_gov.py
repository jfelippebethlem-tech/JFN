"""
Classificador leve de "não-fornecedor": entidades que recebem OB mas NÃO são fornecedores de
contratação — transferências intra-governamentais, tributos e encargos (o Estado paga a si mesmo
ou à União: ISS/INSS/FGTS/encargos, repasses a Ministérios/Tesouro). Poluem os rankings de COMPRA
(anomalias, cartel/captura) porque são pagamentos obrigatórios, não licitação.

Módulo SEM dependências pesadas (só `re`) para ser importável por qualquer detector.
Usado por: compliance_agent/anomalias.py, compliance_agent/grafo_cartel.py.
"""
import re

# Leading \b evita falso-match no meio de palavra; sem \b final (prefixos como "previd" pegam "previdência").
_NAO_FORNECEDOR = re.compile(
    r"\b(estado do rio|munic[ií]pio d|prefeitura|uni[ãa]o\b|minist[ée]rio|secretaria de estado|"
    r"tesouro|receita federal|fazenda nacional|procuradoria|inss\b|instituto nacional do seguro|"
    r"seguro social|fgts|pasep|\bpis\b|caixa econ[oô]mica|banco central|tribunal de|"
    r"c[âa]mara municipal|assembleia legislativa|defensoria|encargos gerais|"
    r"fundo (municipal|estadual|nacional)|fundo (de|da|do) sa[úu]de|previd[êe]ncia)", re.I)


def eh_nao_fornecedor(nome: str) -> bool:
    """True se `nome` é uma entidade intra-governamental/tributo (não um fornecedor de compra)."""
    return bool(_NAO_FORNECEDOR.search(nome or ""))
