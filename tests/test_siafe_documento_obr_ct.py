# -*- coding: utf-8 -*-
"""OB de Retenção e Contrato: cabeçalho e linha reais da sonda de 19/11/2026 entram nas tabelas certas."""
import sqlite3

from compliance_agent.siafe_documento import ingerir

H_OBR = ["Número", "UG Emitente", "UG Pagadora", "Data Emissão", "Status", "Tipo", "Finalidade", "Tipo de Retenção",
         "Credor", "Nome do Credor", "UG Liquidante", "Valor", "Competência", "Status de Envio", "GD", "Processo",
         "RE", "PD", "Tipo de Regularização", "Qtd. Impressões", "Assinatura Digital", "Vinculação de Pagamento"]
L_OBR = ["2026OB42387", "294200", "294200", "19/11/2026", "Contabilizado", "13", "3", "144 - IRRF TERCEIROS",
         "999900", "TESOURO DO ESTADO DO RIO DE JANEIRO", "294200", "5.592,00", "08/2026", "Enviado ao Banco", "",
         "SEI-080002/031570/2026", "2026RE03203", "2026PD42359", "", "0", "Não Solicitado", ""]
H_CT = ["Número Automático", "Número da Licitação", "Número Original", "Natureza", "Objeto", "Cód. Contratante",
        "Nome Contratante", "Cod. Contratado", "Modalidade de Licitação", "Nome do Contratado", "Situação",
        "Valor do Contrato", "Qtd. Aditivos", "Qtd. Reajustes", "Qtd. Anexos"]
L_CT = ["26049896", "", "", "Despesa", "Manutenção da frota", "261100", "SECRETARIA DE ESTADO DE POLÍCIA MILITAR",
        "48626534000154", "06 - Inexigibilidade", "48626534000154 - X", "Vigente", "1.234,56", "2", "0", "1"]


def test_obr(tmp_path):
    db = tmp_path / "t.db"
    assert ingerir(2026, H_OBR, [L_OBR], db=db, tipo="OBR")["ingeridas"] == 1
    r = sqlite3.connect(db).execute("SELECT ug_emitente, valor, pd, tipo_retencao, ano_ob FROM ob_retencao_siafe").fetchone()
    assert r == ("294200", 5592.0, "2026PD42359", "144 - IRRF TERCEIROS", 2026)


def test_contrato(tmp_path):
    db = tmp_path / "t.db"
    assert ingerir(2026, H_CT, [L_CT], db=db, tipo="CT")["ingeridas"] == 1
    r = sqlite3.connect(db).execute("SELECT ug_emitente, contratado, valor, qtd_aditivos FROM contrato_siafe").fetchone()
    assert r == ("261100", "48626534000154", 1234.56, "2")
