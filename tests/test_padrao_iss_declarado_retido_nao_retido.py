# -*- coding: utf-8 -*-
"""Padrão iss_declarado_retido_nao_retido — controle positivo e negativo (unitários puros; não varre o acervo).

Positivo: trecho REAL da NFS-e de Magé 1001711 (FAETEC × Scalle, SEI-260005/007167/2024) e a OB 2024OB05071 =
bruto − IRRF. Negativo: a mesma nota com OB = bruto − IRRF − ISS (retido certo), e nota com "ISSQN RETIDO Não"."""
from __future__ import annotations

from compliance_agent import detector_iss_retido as D
from compliance_agent.padroes import iss_declarado_retido_nao_retido as P

MAGE_1001711 = """PREFEITURA MUNICIPAL DE MAGE
SECRETARIA MUNICIPAL DA FAZENDA
NOTA FISCAL DE SERVIÇOS ELETRÔNICA - NFS-e
Número da Nota:
1001711
PRESTADOR DE SERVIÇOS
CPF/CNPJ:
 19.024.253/0001-23
Município: Rio de Janeiro - ISS (3%) – Base de Cálculo (já considerando a dedução de material - valor de R$ 4.270.377,95): R$ 128.111,34
VALOR TOTAL DA NOTA: R$ 8.540.755,89
Nota
Fiscal
VALOR SERVIÇOS:
R$ 8.540.755,89
VALOR
DEDUÇÃO:
R$ 4.270.377,95
DESC. INCOND:
R$ 0,00
BASE DE
CÁLCULO:
R$ 4.270.377,94
ALÍQUOTA:
3%
VALOR ISS:
R$ 0,00
VALOR ISS
RETIDO:
R$ 128.111,34
DESC. COND:
R$ 0,00
____________________________________________________________________
VALOR PIS:
R$ 0,00
VALOR COFINS:
R$ 0,00
VALOR IR:
R$ 102.489,07
VALOR INSS:
R$ 0,00
VALOR CSLL:
R$ 0,00
OUTRAS RETENÇÕES:
R$ 0,00
VALOR LÍQUIDO:
R$ 8.310.155,48
DADOS COMPLEMENTARES
OUTRAS INFORMAÇÕES / CRITICAS
ISSQN RETIDO
Sim
"""


def _ob(valor, numero="2024OB05071"):
    return {"numero_ob": numero, "ug_emitente": "404400", "data_emissao": "11/07/2024", "nl": "2024NL02665",
            "credor": "19024253000123", "nome_credor": "SCALLE CONSTRUCOES", "valor": valor}


def test_mage_lido_e_conta_fechada():
    [n] = D.extrair_nfs(MAGE_1001711)
    assert (n["formato"], n["numero"], n["bruto"], n["iss"], n["iss_retido_tomador"]) == \
        ("mage", "1001711", 8540755.89, 128111.34, True)
    assert n["componentes"] == {"IRRF": 102489.07}


def test_mage_conta_que_nao_fecha_nao_entra():
    assert D.extrair_nfs(MAGE_1001711.replace("R$ 8.310.155,48", "R$ 8.310.155,98")) == []


def test_mage_bandeira_nao_contra_valor_retido_nao_entra():
    assert D.extrair_nfs(MAGE_1001711.replace("ISSQN RETIDO\nSim", "ISSQN RETIDO\nNão")) == []


def test_positivo_scalle_ob_sem_iss_acende_forte():
    nfs = D.extrair_nfs(MAGE_1001711)
    [r] = D.avaliar_processo("SEI-260005/007167/2024", nfs, [_ob(8438266.82)])
    a = P.achado_nf_x_ob(r)
    assert a and a["grau"] == "forte" and a["valor_pago_ob"] == 8438266.82 and a["iss_nao_retido"] == 128111.34


def test_negativo_ob_com_iss_retido_nao_acende():
    nfs = D.extrair_nfs(MAGE_1001711)
    [r] = D.avaliar_processo("SEI-260005/007167/2024", nfs, [_ob(round(8540755.89 - 102489.07 - 128111.34, 2))])
    assert r["classe"] == "RETIDO" and P.achado_nf_x_ob(r) is None


# ─────────────── sub-sinal: OB de retenção de ISS devolvida sem reemissão ───────────────
# Trecho REAL da impressão SIAFE nos autos de SEI-070002/019996/2025 (doc 275, INEA × Lytoranea).
OB_LYTORANEA = """Governo do Estado do Rio de Janeiro
Ordem Bancária de Retenção
TIPO 13
Identificação
UG Emitente
Documento
Emissão
243200 - INEA
2026OB02539
26/06/26
Valor por Extenso
Valor
H u m m i l h ã o e v i n t e e u m m i l e t r e z e n t o s e d e z e s s e i s r e a i s e s e t e n t a e c i n c o 
centavos
1.021.316,75
Detalhamento
Tipo de Retenção
ISS
Credor da Retenção
Prefeitura Municipal De Belford Roxo
Tipo de Retenção
ISS - 25
Credor da Retenção
39485438000142 - Prefeitura Municipal De Belford Roxo
Status de 
Envio
Erro no Pagamento
Data de retorno
30/06/26
Guia de Devolução
2026GD00114
"""


def _lido(**k):
    o = P.ler_ob_retencao(OB_LYTORANEA)
    o.update(k)
    return o


def test_ob_retencao_lida():
    o = P.ler_ob_retencao(OB_LYTORANEA)
    assert (o["numero"], o["ug"], o["emissao"], o["valor"], o["tipo"], o["cnpj_retencao"], o["status_envio"], o["gd"]) \
        == ("2026OB02539", "243200", "26/06/2026", 1021316.75, "ISS", "39485438000142", "Erro no Pagamento",
            "2026GD00114")


def test_positivo_devolvida_sem_reemissao_acende():
    from datetime import date
    ob = _lido()
    a = P.achado_devolvida("SEI-070002/019996/2025", ob, P.reemitida(ob, []), "doc 275", None, date(2026, 11, 10))
    assert a and a["grau"] == "medio" and a["valor_retencao_devolvida"] == 1021316.75


def test_negativo_reemitida_depois_nao_acende():
    ob = _lido()
    reem = _lido(numero="2026OB02900", emissao="10/07/2026", status_envio="Processado e Pago")
    assert P.reemitida(ob, [ob, reem]) == reem
    assert P.achado_devolvida("SEI-x", ob, reem, "doc 275") is None


def test_reemissao_anterior_ou_tambem_devolvida_nao_conta():
    ob = _lido()
    assert P.reemitida(ob, [_lido(numero="2026OB01000", emissao="01/05/2026", status_envio="Processado e Pago")]) is None
    assert P.reemitida(ob, [_lido(numero="2026OB02900", emissao="10/07/2026")]) is None   # também "Erro"


def test_retencao_paga_ou_de_outro_tributo_nao_acende():
    assert P.achado_devolvida("SEI-x", _lido(status_envio="Processado e Pago"), None, "doc 1") is None
    assert P.achado_devolvida("SEI-x", _lido(tipo="IRRF"), None, "doc 1") is None
    assert P.ler_ob_retencao(OB_LYTORANEA.replace("Ordem Bancária de Retenção", "Ordem Bancária")) is None


def test_erro_recente_e_fraco():
    from datetime import date
    assert P.achado_devolvida("SEI-x", _lido(), None, "doc 275", None, date(2026, 7, 10))["grau"] == "fraco"


def test_retorno_do_banco_nao_corta_o_segmento():
    t = OB_LYTORANEA.replace("Data de retorno", "Retorno\nOrdem bancária paga e liberada com sucesso.\nData de retorno")
    [o] = P.ler_obs_retencao(t)
    assert o["gd"] == "2026GD00114"


def test_negativo_real_barra_do_pirai_devolvida_e_reemitida():
    """SEI-330002/049435/2025 doc 2: 2026OB01115 (ISS, Barra do Piraí, R$ 39.999,21) 'Erro no Pagamento' — "O código
    de barras apresentou erro" — e 2026OB01290 de 26/03/2026, mesmo credor e valor, 'Processado e Pago'."""
    base = {"ug": "044100", "valor": 39999.21, "tipo": "ISS", "cnpj_retencao": "28576080000147",
            "credor_retencao": "Prefeitura Municipal de Barra do Pirai"}
    dev = {**base, "numero": "2026OB01115", "emissao": "20/03/2026", "status_envio": "Erro no Pagamento"}
    reem = {**base, "numero": "2026OB01290", "emissao": "26/03/2026", "status_envio": "Processado e Pago"}
    assert P.achado_devolvida("SEI-330002/049435/2025", dev, P.reemitida(dev, [reem, dev]), "doc 2") is None


def test_negativo_nf_declara_prestador_recolhe_por_decisao_judicial_vira_pendente():
    """FP medido em 18/11/2026: Scalle × EMOP (330003/002539/2024 e mais 9) — a NFS-e de Magé marca "ISSQN RETIDO
    Sim", mas o corpo diz que o PRESTADOR recolhe por decisão judicial. Não pode ser forte."""
    corpo = ("Município: Rio de Janeiro - ISS (3%) – Base de Cálculo (dedução do material no v alor de R$ 7.021.053,46): "
             "R$ 210.631,60 (ISS a ser recolhido no município de\nexecução das obras pelo Prestador dev ido a Decisão "
             "Judicial)")
    provas = D.provas_de_recolhimento([("texto/011_nota_fiscal.txt", "Nota Fiscal - NF (87905704)", corpo)])
    assert provas
    nfs = D.extrair_nfs(MAGE_1001711)
    [r] = D.avaliar_processo("SEI-330003/002539/2024", nfs, [_ob(8438266.82)], provas=provas)
    assert r["estado"] == "PENDENTE" and P.achado_nf_x_ob(r)["grau"] == "medio"
