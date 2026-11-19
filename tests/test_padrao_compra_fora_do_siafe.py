# -*- coding: utf-8 -*-
"""compra_fora_do_siafe — SEI-270118/001445/2021 e 270098/000603/2022 (positivos) × NE juntada / verba da unidade."""
from compliance_agent.padroes.compra_fora_do_siafe import (chave_ok, classificar, cnpj_ok, explicacao, extrair_nf,
                                                           formas_pagamento, irmas, valor_nf)

DANFE_IMPRESSISTEM = (
    "RECEBEMOS DE IMPRESSISTEM COMERCIO E REPRESENTAÇÕES LTDA\nVALOR DA NOTA\nR$ 469,50\n"
    "3322.0410,5582.9500.0170.5500.1000,0083.4711.6401.8557\nTELEFONE: (22)3853-1486 - FAX: (22)3853-1486\n"
    "233220070153497 13/04/22 14:20:27\n10558295000170\nDATA DE EMISSÃO 13/04/22\n28176998000441\nPED./FAT: 14.967\n")
DANFE_MOVEMAQ = ("MOVEMAQ MOVEIS E MAQUINAS LTDA\nTELEFONE: (22)98111-0579 - FAX: (22)39853-1486\n37640716000163\n"
                 "28176998000441\nVALOR TOTAL DOS PRODUTOS VALOR TOTAL DA NOTA\n0,00 0,00 2.950,00\nPED./FAT: 14.968\n")


def test_validadores():
    assert cnpj_ok("28176998000441") and cnpj_ok("10558295000170")
    assert not cnpj_ok("28176998000442")
    assert not chave_ok("3" * 44)


def test_positivo_nf_contra_orgao_e_valor_tabular():
    nf = extrair_nf(DANFE_MOVEMAQ)
    assert nf["contra_orgao_cnpj"] and nf["emitentes"] == ["37640716000163"]
    assert nf["valor"] == 2950.0
    assert valor_nf("VALOR DO FRETE VALOR TOTAL DA NOTA |\nÉ. 0,00 | 0,90 0,00! 1.019,16!") == 1019.16
    assert valor_nf("3GBM.-NTTEROI Valor Total: 1.113,00") == 1113.0
    # SEI-270063/000216/2022: OCR zera o total do DANFE; o valor fica na fatura
    assert valor_nf("VALOR TOTAL DOS PRONTOS.\n0.00\n/Num.: VENCIMENTO: 18/10/ V. Orig.: 874,43/V. Liq.: 874,43") == 874.43


def test_positivo_emitentes_irmaos_por_telefone():
    a = extrair_nf(DANFE_IMPRESSISTEM) | {"doc": 2}
    b = extrair_nf(DANFE_MOVEMAQ) | {"doc": 4}
    a["emitentes"] = ["10558295000170"]
    a["fones_receita"] = ["2238531486"]          # Receita: telefone da IMPRESSISTEM
    par = irmas([a, b])
    assert par and any("telefone" in m for m in par[0]["motivos"])


def test_negativo_mesma_raiz_e_telefone_zerado_nao_sao_irmas():
    a = {"emitentes": ["47960950089785"], "fones": ["0000000000"], "doc": 1}
    b = {"emitentes": ["47960950166607"], "fones": ["0000000000"], "doc": 1}
    assert irmas([a, b]) == []
    assert extrair_nf("FONE (21) 0000-0000")["fones"] == []


def test_classificacao_e_explicacao():
    assert formas_pagamento("Forma de Pagamento: Transferencia Bancaria - PIX") == ["pix", "deposito_transferencia"]
    assert "faturado" not in formas_pagamento("FATURA\nVENCIMENTO: 18/10/22 TOTAL FATURADO 2.420,00")
    assert "faturado" in formas_pagamento("DADOS BANCÁRIOS: BANCO DO BRASIL, AGÊNCIA 0459-6")
    cl, tr = explicacao("orienta-se ao gestor da Unidade que utilize a verba de operacionalização da mesma")
    assert cl == "verba_operacionalizacao" and "operacionaliza" in tr
    assert explicacao("Termo de incorporação de bens móveis")[0] is None
    assert classificar(False, False, None) == "fora_do_siafe_sem_explicacao"
    assert classificar(True, False, None) == "dentro_do_siafe"          # negativo: NE juntada
    assert classificar(False, True, "doacao") == "dentro_do_siafe"     # negativo: OB da SEDEC ao emitente
    assert classificar(False, False, "verba_operacionalizacao") == "verba_operacionalizacao"


def test_aapat_so_secao_incorporacao():
    from compliance_agent.padroes.compra_fora_do_siafe import secoes_aapat
    t = ("INCORPORAÇÃO\n PROCESSO:\nSEI-270089/000911/2023\n1601108\n3º DESTACAMENTO\nSEI-270089/000453/2023\n"
         "FUNDO ESPECIAL DO CBMERJ\n\nDESFAZIMENTO\n PROCESSO:\nSEI-270028/000872/2023\n1601002\n")
    assert set(secoes_aapat(t)) == {"270089_000911_2023", "270089_000453_2023"}


def test_negativo_telefone_fora_da_receita_nao_e_vinculo():
    """SEI-270056/000133/2022: transportadora e vendedora imprimem o celular do destinatário."""
    a = {"emitentes": ["20147617002608"], "fones": ["21964288189"], "fones_receita": ["2125801992"], "doc": 1}
    b = {"emitentes": ["39893680000236"], "fones": ["21964288189"], "fones_receita": [], "doc": 1}
    assert irmas([a, b]) == []


def test_negativo_telefone_do_comprador_em_varias_nf():
    """SEI-270007/051741/2025: (21) 2633-6910 sai em NF de 6 emitentes — é a unidade compradora, não vínculo."""
    nfs = [{"emitentes": [c], "fones": ["2126336910"], "doc": i}
           for i, c in enumerate(["05654516000173", "52618139002817", "07921382000135", "59531283000140"])]
    assert irmas(nfs) == []
