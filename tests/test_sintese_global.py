# -*- coding: utf-8 -*-
"""O olhar de CONJUNTO sobre o processo — o que uma lista de achados não mostra.

Pedido do dono (2026-08-03): "analisar tudo com completude e olhar global sobre cada processo".
Nenhum modelo lê os 3 milhões de caracteres do processo do Jacarezinho de uma vez; a resposta não
é ler menos, é ler em três tempos — ficha por documento, redução por fase, confronto do conjunto.
A síntese lê as FICHAS, nunca o texto cru: é isso que faz um processo de 484 documentos caber em
qualquer janela.
"""
from compliance_agent.sei import sintese_global as S

_RODAPE = "\n\nDocumento assinado eletronicamente por {n}, Cargo, em {d}, às 10:00, conforme."


def _doc(i, ref, tipo, fase, corpo="", assina=None, data="01/01/2024"):
    txt = corpo + (_RODAPE.format(n=assina, d=data) if assina else "")
    return {"i": i, "ref": ref, "tipo": tipo, "fase": fase, "texto": txt}


def test_ficha_extrai_o_essencial_de_cada_documento():
    f = S.fichas([_doc(1, "Contrato 10", "contrato", "contratacao",
                       "CONTRATO Nº 10/2024. Valor de R$ 1.234.567,89.", "Maria Souza",
                       "05/03/2024")])[0]
    assert f["fase"] == "contratacao" and f["valor"] == 1234567.89
    assert f["assinantes"] == ["Maria Souza"] and f["data"] == "05/03/2024"
    assert f["contratos_citados"] == ["10/2024"]


def test_reducao_por_fase_monta_o_esqueleto():
    fs = S.fichas([
        _doc(1, "ETP", "etp", "planejamento", "Estudo.", "Ana", "01/02/2024"),
        _doc(2, "Contrato", "contrato", "contratacao", "R$ 100,00", "Bruno", "01/04/2024"),
        _doc(3, "Aditivo", "aditivo", "contratacao", "R$ 200,00", "Bruno", "01/05/2024"),
    ])
    r = S.por_fase(fs)
    assert r["planejamento"]["n_docs"] == 1
    assert r["contratacao"]["n_docs"] == 2 and r["contratacao"]["maior_valor"] == 200.0
    assert r["contratacao"]["de"] == "01/04/2024" and r["contratacao"]["ate"] == "01/05/2024"


def test_G1_REMOVIDO_sobreposicao_de_fases_nao_e_defeito():
    """Validado caso a caso no acervo (2026-08-03): 202 ocorrências, e os pares mais frequentes
    eram `despesa × controle` (94×), `execucao × despesa` (31×) e `contratacao × despesa` (25×).
    Paga-se ENQUANTO se executa; o controle atravessa o processo. A inversão que importa já é
    apurada por MARCO (cadeia_processo e I2_AUTORIZACAO_ANTES_DO_PARECER)."""
    fs = S.fichas([
        _doc(1, "Contrato", "contrato", "contratacao", "x", "Ana", "01/09/2024"),
        _doc(2, "OB", "ordem_bancaria", "despesa", "x", "Ana", "01/07/2024"),
    ])
    assert not [c for c in S.contradicoes(fs) if c["codigo"] == "G1_FASES_SOBREPOSTAS"]


def test_G2_REMOVIDO_citar_outro_contrato_nao_e_defeito():
    """305 ocorrências e o achado chegou a dizer 'cita o contrato 010/2024 enquanto o processo
    discute o 1/2024' — sendo que o documento ERA o 'Contrato Nº 010/2024'. O caso real (declaração
    que atesta conformidade de OUTRO ajuste) é o I5_DECLARACAO_DE_OUTRO_CONTRATO, com 2 disparos."""
    fs = S.fichas([
        _doc(1, "Contrato Nº 010/2024", "contrato", "contratacao", "CONTRATO Nº 010/2024."),
        _doc(2, "Publicação DOERJ", "anexo", "contratacao", "extrato do contrato 37/2024."),
    ])
    assert not [c for c in S.contradicoes(fs)
                if c["codigo"] in ("G1_FASES_SOBREPOSTAS", "G2_CONTRATO_ALHEIO_NO_DOCUMENTO")]


def _removido_test_confronto_acha_fase_que_termina_depois_da_seguinte():
    fs = S.fichas([
        _doc(1, "ETP", "etp", "planejamento", "x", "Ana", "01/06/2024"),
        _doc(2, "ETP2", "etp", "planejamento", "x", "Ana", "01/09/2024"),
        _doc(3, "Contrato", "contrato", "contratacao", "x", "Bruno", "01/07/2024"),
    ])
    cods = {c["codigo"] for c in S.contradicoes(fs)}
    assert "G1_FASES_SOBREPOSTAS" in cods


def _removido_test_confronto_acha_documento_de_contrato_alheio():
    fs = S.fichas([
        _doc(1, "TA", "aditivo", "contratacao", "1º TERMO ADITIVO AO CONTRATO Nº 16/2023."),
        _doc(2, "TA2", "aditivo", "contratacao", "CONTRATO Nº 16/2023 prorrogado."),
        _doc(3, "Declaração", "contrato", "contratacao", "minuta do contrato 04/2022 padrão."),
    ])
    c = [x for x in S.contradicoes(fs) if x["codigo"] == "G2_CONTRATO_ALHEIO_NO_DOCUMENTO"]
    assert c and "04/2022" in c[0]["diz"]


def test_confronto_acha_quem_controla_e_decide():
    fs = S.fichas([
        _doc(1, "Parecer Jurídico 5 - PGE", "parecer", "controle", "Opino.", "Carlos Lima",
             "01/03/2024"),
        _doc(2, "Contrato", "contrato", "contratacao", "Ajuste.", "Carlos Lima", "05/03/2024"),
    ])
    c = [x for x in S.contradicoes(fs) if x["codigo"] == "G3_MESMA_PESSOA_CONTROLA_E_DECIDE"]
    assert c and "Carlos Lima" in c[0]["diz"]


def test_sintese_declara_leitura_parcial_quando_falta_documento():
    fs = S.fichas([_doc(1, "X", "outro", "tramitacao", "y")])
    assert "PARCIAL" in S.sintetizar(fs, lacunas_captura=3)["leitura"]
    assert "todos os documentos citados" in S.sintetizar(fs, lacunas_captura=0)["leitura"]


def test_a_prosa_le_o_ESQUELETO_e_nunca_o_texto_cru():
    """É o que faz um processo de 3 milhões de caracteres caber em qualquer janela."""
    visto = {}

    def gerar(prompt, sistema=""):
        visto["p"] = prompt
        return "leitura do conjunto"

    fs = S.fichas([_doc(1, "Segredo", "outro", "tramitacao", "TEXTO CRU QUE NAO PODE VAZAR")])
    r = S.sintetizar(fs, gerar=gerar)
    assert r["prosa"] == "leitura do conjunto"
    assert "TEXTO CRU" not in visto["p"]


def test_LLM_fora_do_ar_nao_derruba_a_sintese():
    def quebra(*a, **k):
        raise RuntimeError("provedor fora")
    fs = S.fichas([_doc(1, "X", "outro", "tramitacao", "y")])
    r = S.sintetizar(fs, gerar=quebra)
    assert r["leitura"] and "indisponível" in r["prosa"]


def test_data_ordena_por_ANO_e_nao_por_dia():
    """Bug meu, achado na primeira execução real: a fase saía 'de 08/12/2025 a 28/11/2025' — o
    início DEPOIS do fim. Ordenar 'dd/mm/aaaa' como texto ordena pelo DIA, que é a mesma armadilha
    já registrada no acervo para o `data_emissao` do SIAFE."""
    fs = S.fichas([
        _doc(1, "A", "outro", "despesa", "x", "Ana", "28/11/2025"),
        _doc(2, "B", "outro", "despesa", "x", "Ana", "08/12/2025"),
        _doc(3, "C", "outro", "despesa", "x", "Ana", "04/09/2024"),
    ])
    r = S.por_fase(fs)["despesa"]
    assert r["de"] == "04/09/2024" and r["ate"] == "08/12/2025", r


def _removido_test_zero_a_esquerda_nao_faz_do_mesmo_contrato_dois():
    """Falso positivo medido ao ligar a síntese ao 360: '016/2023' e '16/2023' são o MESMO
    contrato, e a contradição saía dizendo que o documento falava de contrato alheio."""
    fs = S.fichas([
        _doc(1, "TA", "aditivo", "contratacao", "1º TERMO ADITIVO AO CONTRATO Nº 16/2023."),
        _doc(2, "TA2", "aditivo", "contratacao", "CONTRATO Nº 16/2023 prorrogado."),
        _doc(3, "Decl", "contrato", "contratacao", "conforme o contrato 016/2023 desta pasta."),
    ])
    assert not [c for c in S.contradicoes(fs) if c["codigo"] == "G2_CONTRATO_ALHEIO_NO_DOCUMENTO"]


# ───── G3 estreitado: controle JURÍDICO × ato DECISÓRIO (medido 2026-08-03) ─────
# 73 casos e 25 pessoas acusadas. Amostrando o mais frequente (35×): o servidor assinava um
# "Parecer de Análise para Emissão DL" (fase controle) e um "Despacho de Formalização de
# Liquidação de Despesa" (fase despesa). Nenhum dos dois é o que o achado diz: o primeiro não é o
# controle prévio do art. 53, e o segundo não é ato discricionário — é o mesmo servidor tocando o
# expediente. Acusar perda de independência aí é imputar quebra a quem cumpriu rotina.

def test_G3_nao_acusa_parecer_de_rotina_com_liquidacao():
    fs = S.fichas([
        _doc(1, "Parecer de Análise para Emissão DL 84035046", "parecer", "controle",
             "Análise para emissão.", "Raphael Caserta", "01/03/2024"),
        _doc(2, "Despacho de Formalização de Liquidação de Despesa 84", "nota_liquidacao",
             "despesa", "Formalizo a liquidação.", "Raphael Caserta", "05/03/2024"),
    ])
    assert not [c for c in S.contradicoes(fs)
                if c["codigo"] == "G3_MESMA_PESSOA_CONTROLA_E_DECIDE"]


def test_G3_acusa_parecer_JURIDICO_com_ato_que_DECIDE():
    fs = S.fichas([
        _doc(1, "Parecer Jurídico 12 (PGE)", "parecer", "controle",
             "PARECER Nº 12. Procuradoria Geral do Estado. Opino.", "Carlos Lima", "01/03/2024"),
        _doc(2, "Ato do Ordenador de Despesas", "autorizacao_despesa", "despesa",
             "ATO DO ORDENADOR DE DESPESAS. AUTORIZO.", "Carlos Lima", "05/03/2024"),
    ])
    c = [x for x in S.contradicoes(fs) if x["codigo"] == "G3_MESMA_PESSOA_CONTROLA_E_DECIDE"]
    assert c and "Carlos Lima" in c[0]["diz"]


def test_G3_nao_confunde_CHECKLIST_com_parecer():
    """Segundo falso positivo do G3, medido no acervo (080002/004433/2026): 'Checklist Consolidado
    PGE' é tipado `parecer` e traz 'PGE' no título, mas checklist é formulário de conformidade —
    quem o preenche não exerce o controle prévio do art. 53."""
    fs = S.fichas([
        _doc(1, "Checklist Checklist Consolidado PGE (126279494)", "parecer", "controle",
             "Itens verificados.", "Bernard Mothe", "01/03/2026"),
        _doc(2, "Nota de Autorização de Despesa - NAD 1519", "autorizacao_despesa", "despesa",
             "AUTORIZO.", "Bernard Mothe", "05/03/2026"),
    ])
    assert not [c for c in S.contradicoes(fs)
                if c["codigo"] == "G3_MESMA_PESSOA_CONTROLA_E_DECIDE"]


# ═══ G1 e G2 REFEITOS: a pergunta certa, não a grosseira (2026-08-03) ═══
# A validação caso a caso derrubou as versões antigas — mas o sinal existia, estava mal perguntado.
# G1 virou "pagou ANTES de contratar", que é defeito de verdade; G2 virou "documento de OUTRO
# processo dentro da pasta", reusando a doutrina do `sei/documentos_alheios`.

def test_G1_pagamento_ANTES_do_contrato_e_achado():
    fs = S.fichas([
        _doc(1, "Contrato 5/2024", "contrato", "contratacao",
             "CONTRATO Nº 5/2024, QUE ENTRE SI CELEBRAM.", "Ana", "01/09/2024"),
        _doc(2, "OB 2024OB1", "ordem_bancaria", "despesa", "Ordem Bancária.", "Bruno",
             "01/07/2024"),
    ])
    c = [x for x in S.contradicoes(fs) if x["codigo"] == "G1_PAGAMENTO_ANTES_DO_CONTRATO"]
    assert c and "01/07/2024" in c[0]["diz"] and "01/09/2024" in c[0]["diz"]


def test_G1_pagamento_DEPOIS_do_contrato_e_o_fluxo_normal():
    fs = S.fichas([
        _doc(1, "Contrato", "contrato", "contratacao", "CONTRATO Nº 5/2024, QUE ENTRE SI CELEBRAM.",
             "Ana", "01/07/2024"),
        _doc(2, "OB", "ordem_bancaria", "despesa", "Ordem Bancária.", "Bruno", "01/09/2024"),
    ])
    assert not [x for x in S.contradicoes(fs) if x["codigo"] == "G1_PAGAMENTO_ANTES_DO_CONTRATO"]


def test_G1_execucao_e_despesa_sobrepostas_NAO_sao_achado():
    """O que derrubou a versão antiga: paga-se ENQUANTO se executa."""
    fs = S.fichas([
        _doc(1, "Medição", "medicao", "execucao", "x", "Ana", "01/09/2024"),
        _doc(2, "OB", "ordem_bancaria", "despesa", "x", "Bruno", "01/07/2024"),
    ])
    assert not [x for x in S.contradicoes(fs) if x["codigo"].startswith("G1")]


def test_G2_documento_de_OUTRO_processo_na_pasta():
    fs = S.fichas([
        _doc(1, "Despacho", "despacho", "tramitacao",
             "[Despacho] corpo. Referência: Processo nº SEI-070002/001289/2022"),
        _doc(2, "Ofício alheio", "oficio", "tramitacao",
             "[Ofício] corpo. Referência: Processo nº SEI-030001/999999/2020"),
        _doc(3, "Parecer", "parecer", "controle",
             "[Parecer] corpo. Referência: Processo nº SEI-070002/001289/2022"),
    ])
    c = [x for x in S.contradicoes(fs) if x["codigo"] == "G2_DOCUMENTO_DE_OUTRO_PROCESSO"]
    assert c and "030001/999999/2020" in c[0]["diz"]


def test_G2_pasta_limpa_nao_gera_achado():
    fs = S.fichas([
        _doc(1, "A", "despacho", "tramitacao", "[A] c. Referência: Processo nº SEI-070002/001289/2022"),
        _doc(2, "B", "despacho", "tramitacao", "[B] c. Referência: Processo nº SEI-070002/001289/2022"),
    ])
    assert not [x for x in S.contradicoes(fs) if x["codigo"] == "G2_DOCUMENTO_DE_OUTRO_PROCESSO"]


def test_G1_EMPENHO_antes_do_contrato_NAO_e_pagamento():
    """Regra absoluta da casa: Empenho ≠ Liquidação ≠ OB — só a Ordem Bancária é 'pago'. Reservar
    dotação ANTES de assinar é o fluxo correto; acusar isso seria inverter a doutrina."""
    fs = S.fichas([
        _doc(1, "Contrato", "contrato", "contratacao", "CONTRATO Nº 5/2024, QUE ENTRE SI CELEBRAM.",
             "Ana", "01/09/2024"),
        _doc(2, "NE 2024NE1", "nota_empenho", "despesa", "Nota de Empenho.", "Bruno", "01/07/2024"),
        _doc(3, "NL 2024NL1", "nota_liquidacao", "despesa", "Nota de Liquidação.", "Bruno",
             "15/07/2024"),
    ])
    assert not [x for x in S.contradicoes(fs) if x["codigo"] == "G1_PAGAMENTO_ANTES_DO_CONTRATO"]


def test_G2_usa_o_numero_REAL_do_processo_nao_a_frequencia():
    """Bug medido: com o dono adivinhado por frequência, o achado chegou a listar o PRÓPRIO
    processo (030001/004933/2026) como alheio. O número está no manifesto — não se adivinha."""
    fs = S.fichas([
        _doc(1, "A", "despacho", "tramitacao",
             "[A] corpo. Referência: Processo nº SEI-030001/004933/2026"),
        _doc(2, "B", "despacho", "tramitacao",
             "[B] corpo. Referência: Processo nº SEI-030001/005382/2026"),
    ])
    c = [x for x in S.contradicoes(fs, numero="030001/004933/2026")
         if x["codigo"] == "G2_DOCUMENTO_DE_OUTRO_PROCESSO"]
    assert c and "005382" in c[0]["evidencia"] and "004933" not in c[0]["evidencia"], c
