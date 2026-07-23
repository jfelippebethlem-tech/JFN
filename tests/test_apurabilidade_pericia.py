"""INDISPONÍVEL ≠ 0 na perícia (regra da casa).

Uma OB do TFE traz valor/objeto/órgão e nada de licitação: modalidade, propostas,
prazo de edital e aditivos NÃO EXISTEM nessa fonte. Os indicadores que dependem
desses campos ficam calados — e o laudo saía "risco 0/100, nenhum indicador
disparou", que o humano lê como "auditado e limpo".

Caso real que motivou (2026-07-23): CPASC (ONG do caso Con-tato), OB de
R$ 16,4 milhões por *Termo de Cooperação*, 31 perícias, todas "🟢 BAIXO 0/100".
O 0 não era ausência de risco: era ausência de medição.
"""
from compliance_agent.nucleo.dossie import Contratacao, Dossie, Fornecedor
from compliance_agent.nucleo.indicadores import apurabilidade


def _dossie_ob_tfe() -> Dossie:
    """Exatamente o que o adaptador monta a partir de uma OB do TFE."""
    return Dossie(
        contratacao=Contratacao(
            identificador="ob:3504334", objeto="Termo Coop. — pesquisa de campo",
            orgao="Secretaria de Estado de Cidades", valor=16_400_000.0,
            data="2020-03-13", categoria="saúde", fonte="tfe_ob"),
        fornecedor=Fornecedor(
            cnpj="03686998000118", nome="CPASC", data_abertura="2000-03-02",
            situacao="ATIVA", cnae_principal="associações de defesa de direitos", fonte="cnpj"),
        referencia_categoria={"mediana": 50_486_144.6, "n": 47.0, "desvio_padrao": 42_279_883.47},
    )


def test_ob_tfe_declara_indisponivel_o_que_nao_mediu():
    ap = apurabilidade(_dossie_ob_tfe())
    indisp = {i["indicador"] for i in ap["indisponiveis"]}
    # sem edital/contrato não há como afirmar nada sobre estes:
    assert {"IND-DIR-01", "IND-DIR-02", "IND-ADT-01", "IND-LIM-01"} <= indisp
    assert ap["cobertura"] < 1.0
    assert ap["n_apuraveis"] + len(ap["indisponiveis"]) == ap["n_total"]


def test_o_que_a_fonte_sustenta_continua_apuravel():
    ap = apurabilidade(_dossie_ob_tfe())
    apur = set(ap["apuraveis"])
    # tem CNPJ (sanção/doação consultáveis), situação cadastral, abertura e mediana
    assert {"IND-SAN-01", "IND-SIT-01", "IND-EMP-01", "IND-SUP-01"} <= apur


def test_dossie_completo_tem_cobertura_total():
    d = _dossie_ob_tfe()
    d.contratacao.modalidade = "dispensa"
    d.contratacao.propostas_validas = 1
    d.contratacao.prazo_edital_dias = 8
    d.contratacao.fonte = "pncp"
    d.historico_orgao_fornecedor = [Contratacao(valor=1000.0, data="2020-01-01")]
    ap = apurabilidade(d)
    assert ap["indisponiveis"] == []
    assert ap["cobertura"] == 1.0
