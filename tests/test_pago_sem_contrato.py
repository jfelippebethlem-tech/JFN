# -*- coding: utf-8 -*-
"""Pago sem contrato — a lente que lê a INTERPRETAÇÃO da IA, não uma tabela.

O que estes testes protegem: o filtro `_LEGITIMO`. Pagar sem contrato é lícito para folha, tarifa,
tributo, repasse e precatório — despesas que nunca tiveram instrumento por natureza. Sem esse
corte, a primeira medição trazia no topo R$ 123,5 mi de "apoio financeiro" a um Fundo Municipal de
Saúde, que é repasse, e o número inflava de R$ 146,6 mi para R$ 326,4 mi.
"""
import json
import sqlite3


def _banco(o_que_e, ponto="Nota de Empenho: 'Contrato 00000000 - SEM CONTRATO'"):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sei_leitura_dupla (numero_sei TEXT, ia TEXT)")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, valor REAL, status TEXT,"
                " nome_credor TEXT)")
    ia = json.dumps({"interpretacao": {"o_que_e": o_que_e,
                                       "chama_atencao": [{"ponto": ponto}]}})
    con.execute("INSERT INTO sei_leitura_dupla VALUES ('030001/000001/2025', ?)", (ia,))
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('SEI-030001/000001/2025',1e6,"
                "'Contabilizado','FORNECEDOR X')")
    return con


def test_compra_sem_contrato_ENTRA():
    from tools.pago_sem_contrato import sem_contrato
    r = sem_contrato(_banco("Processo de aquisição de medicamentos para a rede estadual."))
    assert len(r) == 1 and r[0]["pago"] == 1e6


def test_repasse_a_municipio_NAO_entra():
    """Foi o que inflava o topo: R$ 123,5 mi de 'apoio financeiro' a Fundo Municipal de Saúde."""
    from tools.pago_sem_contrato import sem_contrato
    assert sem_contrato(_banco("Apoio financeiro do Estado ao município para custeio de "
                               "serviços de diagnóstico.")) == []


def test_folha_tarifa_tributo_NAO_entram():
    from tools.pago_sem_contrato import sem_contrato
    for oq in ("Liquidação de despesas de folha de pagamento e encargos previdenciários.",
               "Pagamento de faturas de fornecimento de energia elétrica para escolas.",
               "Recolhimento de tributo federal retido na fonte.",
               "Pagamento de precatório por decisão judicial transitada em julgado."):
        assert sem_contrato(_banco(oq)) == [], f"entrou indevidamente: {oq[:40]}"


def test_sem_apontamento_de_contrato_nao_entra():
    """A lente não marca processo só por ser compra — precisa do apontamento da IA."""
    from tools.pago_sem_contrato import sem_contrato
    assert sem_contrato(_banco("Aquisição de medicamentos.",
                               ponto="Divergência de centavos na nota fiscal.")) == []


def test_com_legitimos_mostra_tudo():
    """O modo de conferência existe — e NÃO é a fila."""
    from tools.pago_sem_contrato import sem_contrato
    assert len(sem_contrato(_banco("Repasse fundo a fundo."), com_legitimos=True)) == 1


def test_ob_nao_contabilizada_nao_soma():
    from tools.pago_sem_contrato import sem_contrato
    con = _banco("Aquisição de material.")
    con.execute("UPDATE ob_orcamentaria_siafe SET status='Anulado'")
    r = sem_contrato(con)
    assert len(r) == 1 and r[0]["pago"] == 0.0, "OB anulada não é pagamento"
