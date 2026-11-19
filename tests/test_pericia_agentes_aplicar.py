"""Perícia de agente só sobe 🔴 com conferência na fonte primária registrada pela sessão principal."""
from tools import pericia_agentes_aplicar as A

NOMES = ("juridico", "economicidade")


def _laudo(grau, nota, veredito=None):
    d = {"processo": "SEI-1/1/2025", "eixos": {"juridico": {"grau": grau}, "economicidade": {"grau": 1}},
         "lex": {"execucao_comprovada": "parcial", "nota_risco_execucao": nota, "duvidas": []}}
    if veredito:
        d["conferencia_principal"] = {"veredito": veredito}
    return d


def test_vermelho_sem_conferencia_vira_amarelo_com_motivo():
    e = A.eixos_com_teto(_laudo(3, 8), NOMES)
    assert e["juridico"]["grau"] == 2 and e["juridico"]["grau_agente"] == 3 and "teto" in e["juridico"]
    assert e["economicidade"]["grau"] == 1 and "teto" not in e["economicidade"]
    assert A.lex_com_teto(_laudo(3, 8))["nota_risco_execucao"] == 6


def test_vermelho_conferido_na_fonte_fica():
    d = _laudo(3, 8, "confirmado")
    assert A.eixos_com_teto(d, NOMES)["juridico"]["grau"] == 3
    assert A.lex_com_teto(d)["nota_risco_execucao"] == 8


def test_indicio_forte_e_rebaixado_nao_sobem_vermelho():
    for v in ("indicio_forte", "rebaixado_para_amarelo", "parcial"):
        assert A.eixos_com_teto(_laudo(3, 9, v), NOMES)["juridico"]["grau"] == 2


def test_eixo_ausente_vira_indeterminado_e_tem_descartados():
    e = A.eixos_com_teto({"processo": "x", "eixos": {}}, NOMES)
    assert e["juridico"]["grau"] is None and e["juridico"]["descartados"] == []
