"""Aditivo lido POR DOCUMENTO e prorrogação que renova valor (casos lidos em 25/09/2026, reduzidos)."""
from compliance_agent.execucao_fatos import (_natureza, aditivos_por_documento, declara_continuo,
                                             prorrogacao_renova_valor)


def _ad(n, objeto, valor, total, extra=""):
    return {"titulo": f"Termo Aditivo {n} (1)", "tipo": "contrato",
            "texto": (f"TERMO ADITIVO N° {n} – INEA\nSEGUNDO TERMO ADITIVO AO CONTRATO INEA\n34/2023, QUE TEM POR\n"
                      f"OBJETO {objeto}, NA FORMA ABAIXO: {extra}\nCLÁUSULA QUARTA: Dá-se ao termo aditivo o valor de "
                      f"R$ {valor}, totalizando o contrato o valor de R$ {total}.")}


INEA = [_ad("59/2024", "A ALTERAÇÃO QUANTITATIVA E QUALITATIVA DO OBJETO", "8.520.610,08", "57.011.710,08"),
        _ad("71/2024", "A PRORROGAÇÃO DO PRAZO CONTRATUAL SEM RENÚNCIA DE REAJUSTE", "57.011.710,08", "114.023.420,16",
            "relativo à prestação de serviços contínuos de desassoreamento"),
        _ad("80/2025", "A PRORROGAÇÃO DO PRAZO CONTRATUAL SEM RENÚNCIA DE REAJUSTE", "60.083.291,82", "177.178.293,72")]


def test_sem_renuncia_de_reajuste_e_prorrogacao_nao_reajuste():
    assert _natureza("OBJETO A PRORROGAÇÃO DO PRAZO CONTRATUAL SEM RENÚNCIA DE REAJUSTE") == "prazo"
    assert _natureza("OBJETO A ALTERAÇÃO QUANTITATIVA E QUALITATIVA DO OBJETO") == "valor"


def test_le_numero_contrato_valor_e_total_de_cada_aditivo():
    ads = aditivos_por_documento(INEA)
    assert [(a["numero"], a["contrato"], a["tipo"]) for a in ads] == [
        ("59/2024", "34/2023", "valor"), ("71/2024", "34/2023", "prazo"), ("80/2025", "34/2023", "prazo")]
    assert ads[1]["valor"] == 57011710.08 and ads[2]["total_apos"] == 177178293.72


def test_multiplicador_parte_do_valor_inicial_real():
    r = prorrogacao_renova_valor(aditivos_por_documento(INEA))
    assert r["valor_inicial"] == 48491100.0 and r["multiplicador"] == 3.65


def test_declarado_continuo_e_atributo_nao_achado():
    """O INEA enquadrou como 'serviços contínuos' — formalmente lícito; o juízo vai para o parecer."""
    assert prorrogacao_renova_valor(aditivos_por_documento(INEA))["grau"] == "verde"


def test_sem_declaracao_e_amarelo():
    sem = [_ad("1/2024", "A ALTERAÇÃO QUANTITATIVA DO OBJETO", "100.000,00", "1.100.000,00"),
           _ad("2/2024", "A PRORROGAÇÃO DO PRAZO CONTRATUAL", "1.100.000,00", "2.200.000,00")]
    r = prorrogacao_renova_valor(aditivos_por_documento(sem))
    assert r["grau"] == "amarelo" and "NÃO declara" in r["diz"]


def test_locacao_de_veiculos_e_continua_por_natureza():
    contrato = {"titulo": "Contrato SEGOV nº 001/2020", "texto": "OBJETO: a prestação de serviços de locação, com "
                "manutenção, de 165 (cento e sessenta e cinco) veículos tipo motocicleta"}
    assert declara_continuo([contrato]) is True                   # vírgulas entre "locação", "com manutenção" e "de"
    contrato2 = {"titulo": "Contrato nº 2", "texto": "prestação de serviços de locação de 202 veículos de duas rodas"}
    assert declara_continuo([contrato2]) is True
