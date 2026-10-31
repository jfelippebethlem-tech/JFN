# -*- coding: utf-8 -*-
"""Fiscalização atesto a atesto: casos reais do acervo (30/10/2026) viram teste."""
from compliance_agent.sei import fiscalizacao as F

_RODAPE = "Documento assinado eletronicamente por {n}, Coordenador, em {d}, às 10:00, conforme horário oficial"


def _atesto(corpo, *datas, ref="Atestado de Realização de Serviços 88615942"):
    return {"ref": ref, "tipo": "contrato",
            "texto": corpo + " " + " ".join(_RODAPE.format(n=f"Fiscal {i}", d=d) for i, d in enumerate(datas))}


def test_mes_atestado_antes_de_acabar_acende_fz1():
    """Elevadores Atlas Schindler/UERJ: dezembro/2024 atestado em 03/12/2024."""
    a = F.avaliar([_atesto("Atestamos que os serviços do mês de dezembro de 2024, Nota Fiscal 451360, "
                           "referente ao Contrato nº 02/2022 ... foram executados", "03/12/2024", "03/12/2024")])
    assert [x["codigo"] for x in a] == ["FZ1_ATESTO_ANTES_DO_FIM_DO_PERIODO"]
    assert "28 dia(s)" in a[0]["diz"] and "fim do exercício" in a[0]["diz"] and a[0]["ressalva"]


def test_vale_a_ultima_assinatura_da_comissao():
    """Comissão: o atesto só se completa quando o último membro assina (aqui, depois do fim do mês)."""
    a = F.avaliar([_atesto("Atestamos que os serviços do mês de outubro/2024 foram executados",
                           "24/10/2024", "04/11/2024")])
    assert a == []


def test_periodo_que_termina_muito_depois_e_erro_material_fz2():
    """CBMERJ/ENGE PRAT: 'período de 29/11/2022 até 28/12/2023' assinado em 13/02/2023."""
    a = F.avaliar([_atesto("Atestamos que os serviços referentes a Ordem de Serviços 031/2022, realizados no "
                           "período de 29/11/2022 até 28/12/2023, foram executados", "13/02/2023")])
    assert [x["codigo"] for x in a] == ["FZ2_DATA_INCOERENTE_NO_ATESTO"] and "318 dias" in a[0]["diz"]


def test_concessionaria_fica_fora():
    """CEG: o 'mês' é o do ciclo de leitura da fatura, não o do serviço."""
    a = F.avaliar([_atesto("Atestamos que os serviços do mês de Outubro/2025, referentes ao fornecimento de gás "
                           "natural encanado ... Companhia Distribuidora de Gás do Rio de Janeiro - CEG",
                           "09/10/2025")])
    assert a == []


def test_so_peca_de_atesto_e_so_com_assinatura_e_periodo():
    corpo = "Atestamos que os serviços do mês de dezembro de 2024 foram executados"
    assert F.avaliar([_atesto(corpo, "03/12/2024", ref="Despacho de Encaminhamento 1")]) == []
    assert F.avaliar([_atesto(corpo, "03/12/2024", ref="Atestado de Realização de Serviços - CANCELADO (1)")]) == []
    assert F.avaliar([{"ref": "Atestado de Realização de Serviços 1", "texto": corpo}]) == []   # sem rodapé
    assert F.avaliar([_atesto("Atestamos que os serviços foram executados", "03/12/2024")]) == []  # sem período
