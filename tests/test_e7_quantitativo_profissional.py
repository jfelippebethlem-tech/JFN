"""E7 + coletor: cláusula em PARÁGRAFO e quantitativo mínimo exigido do PROFISSIONAL (PE 24/2023 do INEA, 25/09/2026)."""
from compliance_agent.detectores import coletor_edital as CE
from compliance_agent.detectores import e7_clausula_restritiva as E7

ANEXO_9 = """ANEXO 9
PARCELAS DE MAIOR RELEVÂNCIA TÉCNICA
A qualificação técnica da empresa será comprovada através de no mínimo 1 (um) atestado técnico ou
Certidão de Acervo Técnico (CAT) fornecidos por pessoas jurídicas de direito público ou privado em nome
dos profissionais responsáveis técnicos com vínculos comprovados com a empresa licitante, averbados
pelas entidades profissionais competentes, correspondente aos serviços especificados conforme figura
abaixo, equivalentes a 25% dos quantitativos previstos para cada lote, ainda que de diferentes contratos.
"""


def _clausulas(texto):
    return CE.montar_ctx_de_sei({"conteudo_documentos": [
        {"doc": "Anexo 09 - Parcela de Maior Relevância Técnica (52375493)", "conteudo": "qualificação técnica\n" + texto}]}
    ).get("clausulas_edital") or []


def test_clausula_em_tres_linhas_e_capturada_e_exigida_do_profissional():
    cl = [c for c in _clausulas(ANEXO_9) if c["tipo"] == "atestado_quantitativo"]
    assert cl and cl[0]["pct"] == 0.25 and cl[0]["exige_do_profissional"] is True
    grau, motivo = E7._teste_atestado(cl[0], None)
    assert grau == "forte" and "art. 30 §1º I" in motivo


def test_atestado_da_empresa_segue_a_regra_dos_50_por_cento():
    txt = ("Outrossim, a empresa deverá possuir atestado(s) de capacidade técnica de execução de serviços semelhantes,\n"
           "no percentual de 25% do quantitativo previsto.")
    cl = [c for c in _clausulas(txt) if c["tipo"] == "atestado_quantitativo"]
    assert cl and cl[0]["exige_do_profissional"] is False
    assert E7._teste_atestado(cl[0], None)[0] == "medio"


def test_formulario_de_pontuacao_da_fiscalizacao_nao_vira_pontuacao_dirigida():
    txt = ("Retardar, intencionalmente, a solução de requerimento, andamento de\nPontuação obtida\n"
           "Ciente do Preposto da Empresa\nFiscal Setorial (Elaborador)\n")
    assert not [c for c in _clausulas(txt) if c["tipo"] == "pontuacao_dirigida"]
