"""cronologia_do_ato — a data escrita DENTRO da peça (casos reais lidos em 25/09/2026, reduzidos)."""
from compliance_agent.cronologia_do_ato import analisar

NL_31_12 = {"titulo": "Nota de Liquidação - NL 2024NL26909 (91016913)", "tipo": "nota_liquidacao",
            "texto": "Nota de Liquidação\nDocumento\nEmissão\n180100 - SEEDUC\n2024NL26909\n31/12/24\nValor Bruto"}
NP_31_12 = {"titulo": "Nota Patrimonial - NP 2024NP006998 Registro Garantia (91016939)", "tipo": "outro",
            "texto": "Nota Patrimonial\n2024NP006998\n31/12/24\nProcesso\nSEI-030001/000071/2025\n"}
OF_08_01 = {"titulo": "Anexo Ordem de Fornecimento (90902958)", "tipo": "ordem_inicio",
            "texto": "Ordem de fornecimento\nDe\nFulano\nData Qua, 08/01/2025 12:57\nPara Comercial"}
NF_08_01 = {"titulo": "Nota Fiscal - NF 1.780 (90442592)", "tipo": "nota_fiscal",
            "texto": "DATA DA EMISSÃO\n08/01/2025\nVALOR TOTAL"}
REC_08_01 = {"titulo": "Relatório de Fiscalização 90902746", "tipo": "fiscalizacao",
             "texto": "Data de Conferência: 08/01/2025 Data aceite: 08/01/2025"}
EUREKA_39 = [NL_31_12, NP_31_12, OF_08_01, NF_08_01, REC_08_01]


def test_eureka_liquidou_antes_da_ordem_e_com_data_retroativa():
    r = analisar(EUREKA_39, numero_processo="SEI-030001/000071/2025")
    tipos = {a["tipo"]: a for a in r["achados"]}
    assert r["grau"] == "vermelho"
    assert "8 dia(s) ANTES da ordem" in tipos["liquidacao_antes_da_ordem"]["diz"]
    assert tipos["ato_anterior_ao_processo"]["grau"] == "vermelho"      # retroativo + fato de 2025
    assert "entrega_no_dia_da_ordem" in tipos


def test_servico_continuo_faturado_em_janeiro_e_conferir_nao_acusar():
    """SEGOV × PRIME (420001/000112/2025): consumo de dezembro, NF em janeiro, NL de 31/12 no encerramento."""
    nl = {"titulo": "Nota de Liquidação - NL 2024NL02875 (91008772)", "tipo": "liquidacao",
          "texto": "2024NL02875\n31/12/24\nProcesso SEI-420001/000112/2025"}
    nf = {"titulo": "Nota Fiscal - NF ADM (90913028)", "tipo": "outros", "texto": "Data de Emissão\n08/01/2025 10:00"}
    r = analisar([nl, nf], numero_processo="SEI-420001/000112/2025")
    assert r["grau"] == "amarelo"
    assert {a["tipo"] for a in r["achados"]} == {"liquidacao_antes_da_nf", "ato_anterior_ao_processo"}
    assert all(a["grau"] == "amarelo" for a in r["achados"])


def test_varias_nls_mensais_nao_viram_inversao():
    """030002/000307/2025: a NF do 1º mês sem data lida; a 1ª NL não pode ser comparada à NF do 2º mês."""
    docs = [{"titulo": "Nota de Liquidação - NL (92640758)", "tipo": "liquidacao", "texto": "2025NL00100\n04/02/25"},
            {"titulo": "Nota de Liquidação - NL (94631865)", "tipo": "liquidacao", "texto": "2025NL00300\n20/03/25"},
            {"titulo": "Nota Fiscal - NF e Acompanhamentos (94574396)", "tipo": "outros",
             "texto": "Data de Emissão\n06/03/2025"}]
    assert analisar(docs)["grau"] == "verde"


def test_conferencia_antes_da_ordem_e_amarelo():
    of2 = {"titulo": "Ordem _de_Fornecimento Cont nº 02-2025 - OF nº 02 (94574483)", "tipo": "tr",
           "texto": "Ordem de Fornecimento de Materiais nº 02 | Data da Emissão | 2025-03-06 00:00:00 | Contrato"}
    rec = {"titulo": "Relatório de Fiscalização 94573672", "tipo": "tramitacao",
           "texto": "Data de Conferência: 03/02/2025\tData aceite: 07/03/2025"}
    r = analisar([of2, rec])
    assert [a["tipo"] for a in r["achados"]] == ["conferencia_antes_da_ordem"] and r["grau"] == "amarelo"


def test_ano_impossivel_do_ocr_nao_vira_cronologia():
    nl = {"titulo": "Nota de Liquidação - NL 13148 (84377547)", "tipo": "liquidacao", "texto": "2024NL13148\n01/10/24"}
    of = {"titulo": "Ordem de Fornecimento (1)", "tipo": "ordem_inicio", "texto": "Data Qua, 27/08/7024 10:00"}
    assert analisar([nl, of])["grau"] == "verde"


def test_sem_datas_e_nao_aplicavel():
    assert analisar([{"titulo": "Despacho", "tipo": "despacho", "texto": "encaminho"}])["grau"] == "nao_aplicavel"
