"""
Loop 21 — /anomalias: filtrar transferências intra-governamentais/tributos do ranking.

Eram 12/20 das top anomalias entidades gov (Estado, Ministério da Fazenda) — ruído que
afoga o sinal de COMPRA. _eh_nao_fornecedor distingue não-fornecedor de fornecedor real.
"""
from compliance_agent.anomalias import _eh_nao_fornecedor


def test_exclui_intragov_e_tributos():
    for nome in ["Estado Do Rio De Janeiro", "MINISTÉRIO DA FAZENDA", "MINISTÉRIO DA ECONOMIA",
                 "Instituto Nacional De Seguro Social.", "SECRETARIA DE ESTADO DE FAZENDA",
                 "ENCARGOS GERAIS DO ESTADO - SUPERVISAO SEFAZ", "Tesouro Estadual",
                 "Tribunal de Contas do Estado do Rio de Janeiro"]:
        assert _eh_nao_fornecedor(nome), f"deveria excluir não-fornecedor: {nome}"


def test_mantem_fornecedores_reais():
    for nome in ["SCALLE CONSTRUCOES, REFORMAS E INSTALACOES LTDA", "MGS CLEAN SOLUCOES E SERVICOS LTDA",
                 "Enge Prat Engenharia E Serviços Ltda.", "DADY ILHA SOLUCOES INTEGRADAS LTDA.",
                 "CONSTRUTORA R2X LTDA ME", "Green Card S/a-refeicoes Com E Servicos"]:
        assert not _eh_nao_fornecedor(nome), f"NÃO podia excluir fornecedor real: {nome}"
