# -*- coding: utf-8 -*-
"""O I4 nomeava a hipótese inocente e não a conferia — tendo os documentos à mão.

`ordinal_incoerente_com_prazo` acusa quando o ordinal declarado ("2º termo aditivo") não bate com
o prazo total que o próprio instrumento anuncia. O texto do achado já dizia *"salvo se houver
aditivo anterior que NÃO prorrogou prazo (aditivo de valor, por exemplo), hipótese que explica o
ordinal sem vício e precisa ser conferida nos autos"* — e os autos estavam ali, no mesmo `docs`.

Medido em 2026-08-04: **14 dos 23 disparos (61%)** tinham no MESMO processo um aditivo cujo objeto
se anuncia "ALTERAÇÃO QUANTITATIVA E QUALITATIVA DO OBJETO", e o instrumento acusado era a
PRIMEIRA prorrogação. Exemplo lido inteiro: SEI-070002/006145/2024 — TA 45/2024 (alteração) e TA
63/2024 (prorrogação), com o 63 acusado de "2º aditivo com prazo de 1º".

Depois da conferência: 23 → 6, e os 6 restantes têm só aditivos de PRORROGAÇÃO nos autos.
"""
from compliance_agent.sei import instrumento_assinatura as IA

_CABECA = ("TERMO ADITIVO QUE ENTRE SI CELEBRAM O ESTADO DO RIO DE JANEIRO E A EMPRESA X, "
           "NA FORMA ABAIXO:\n")


def _aditivo(ref, ordinal_txt, objeto, prazo=""):
    return {"ref": ref, "tipo": "aditivo",
            "texto": f"{ordinal_txt} TERMO ADITIVO AO CONTRATO 36/2023\nOBJETO A {objeto}, "
                     f"NA FORMA ABAIXO:\n{_CABECA}{prazo}"}


def test_aditivo_de_ALTERACAO_no_mesmo_processo_explica_o_ordinal():
    """O caso real do SEI-070002/006145/2024."""
    docs = [
        _aditivo("Termo Aditivo 45/2024", "PRIMEIRO", "ALTERAÇÃO QUANTITATIVA E QUALITATIVA DO OBJETO"),
        _aditivo("Termo Aditivo 63/2024", "SEGUNDO", "PRORROGAÇÃO DO PRAZO CONTRATUAL",
                 "prazo total de 30 (trinta) meses, prorrogado por 15 (quinze) meses"),
    ]
    assert IA.ordinal_incoerente_com_prazo(docs)["achado"] is False


def test_so_com_aditivos_de_PRORROGACAO_o_achado_permanece():
    """É o caso dos 6 que sobraram: nada nos autos explica o descompasso."""
    docs = [
        _aditivo("Termo Aditivo 1", "PRIMEIRO", "PRORROGAÇÃO DE PRAZO CONTRATUAL"),
        _aditivo("Termo Aditivo 2", "TERCEIRO", "PRORROGAÇÃO DO PRAZO CONTRATUAL",
                 "prazo total de 36 (trinta e seis) meses, prorrogado por 12 (doze) meses"),
    ]
    r = IA.ordinal_incoerente_com_prazo(docs)
    assert r["achado"] is True and r["ordinal"] == 3 and r["ordinal_implicado"] == 2


def test_a_conferencia_olha_o_OBJETO_declarado_nao_o_titulo():
    """O título mente nos dois sentidos; o termo aditivo declara o próprio objeto no cabeçalho."""
    docs = [
        {"ref": "Anexo qualquer", "tipo": "aditivo",
         "texto": "TERMO ADITIVO\nOBJETO A SUPRESSÃO DE ITENS, NA FORMA ABAIXO:\n" + _CABECA},
        _aditivo("Termo Aditivo 2", "SEGUNDO", "PRORROGAÇÃO DO PRAZO CONTRATUAL",
                 "prazo total de 24 (vinte e quatro) meses, prorrogado por 12 (doze) meses"),
    ]
    assert IA.ordinal_incoerente_com_prazo(docs)["achado"] is False


def test_aditivo_sem_objeto_declarado_nao_serve_de_desculpa():
    """Ausência de objeto declarado não é prova de que o aditivo foi de valor — não explica nada,
    e o achado continua para o fiscal conferir."""
    docs = [
        {"ref": "Termo Aditivo 1", "tipo": "aditivo",
         "texto": "TERMO ADITIVO AO CONTRATO 36/2023\n" + _CABECA},
        _aditivo("Termo Aditivo 2", "SEGUNDO", "PRORROGAÇÃO DO PRAZO CONTRATUAL",
                 "prazo total de 24 (vinte e quatro) meses, prorrogado por 12 (doze) meses"),
    ]
    assert IA.ordinal_incoerente_com_prazo(docs)["achado"] is True
