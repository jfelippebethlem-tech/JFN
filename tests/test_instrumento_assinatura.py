# -*- coding: utf-8 -*-
"""Três achados que só aparecem quando se lê o TEXTO dos autos, não os títulos.

Nasceram da leitura integral do SEI-270131/000548/2023 (2026-08-03), confrontada com o que o
sistema tinha concluído. Os três eram invisíveis para a casa:

  1. **Ordinal divergente** — a minuta que a assessoria jurídica examinou é do "1º TERMO ADITIVO";
     os instrumentos assinados dizem "2º". O art. 38, parágrafo único, da Lei 8.666/93 (art. 53
     da 14.133) exige exame prévio DA MINUTA QUE SE CELEBRA. E havia DOIS instrumentos com o
     mesmo ordinal e o mesmo objeto, assinados com 8 dias de diferença.
  2. **Autorização antes do parecer** — o ato do ordenador é de 16/05/2024 e o parecer, de
     22/05/2024. A casa já detecta "contrato antes do parecer" (A1); a autorização, não.
  3. **Ato decisório sem a assinatura de quem decide** — o "ATO DO ORDENADOR DE DESPESAS" trazia
     "* MINUTA DE DOCUMENTO" no topo e só a assinatura do oficial que o redigiu; a ordenadora que
     o próprio texto nomeia não assinou.

Todos são INDÍCIO, nunca acusação: documento pode ter sido assinado fora do SEI, e a captura
pode estar incompleta — por isso cada achado declara o que viu e o que não pode ver.
"""
import pytest

from compliance_agent.sei import instrumento_assinatura as IA

_RODAPE = ("\n\nDocumento assinado eletronicamente por {nome}, {cargo}, em {data}, às {hora}, "
           "conforme horário oficial de Brasília, com fundamento nos art. 28º e 29º do Decreto "
           "nº 48.209, de 19 de setembro de 2022.\n")


def _doc(ref, tipo, corpo, assinaturas=()):
    txt = corpo + "".join(_RODAPE.format(nome=n, cargo=c, data=d, hora=h)
                          for n, c, d, h in assinaturas)
    return {"ref": ref, "tipo": tipo, "texto": txt}


# ───────────────────────── 0. o extrator de assinaturas ─────────────────────────

def test_le_as_assinaturas_do_rodape_do_sei():
    d = _doc("X", "contrato", "corpo",
             [("Renato de Melo Cardoso", "Oficial Administrativo", "16/05/2024", "16:06"),
              ("Vinicius Moncores Lopes", "Oficial Administrativo", "17/05/2024", "09:24")])
    ass = IA.assinaturas(d["texto"])
    assert [a["nome"] for a in ass] == ["Renato de Melo Cardoso", "Vinicius Moncores Lopes"]
    assert ass[0]["data"] == "16/05/2024"


def test_documento_sem_rodape_devolve_lista_vazia_sem_quebrar():
    assert IA.assinaturas("texto qualquer sem rodapé") == []


# ───────────────────────── 1. ordinal divergente ─────────────────────────

def test_minuta_aprovada_que_nao_corresponde_a_instrumento_assinado():
    docs = [
        _doc("Minuta de Termo Aditivo 74778400", "aditivo",
             "MINUTA. 1º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM o Estado e a empresa. CLÁUSULA PRIMEIRA (Do Objeto): prorrogação.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:00")]),
        _doc("Termo Aditivo 75769317", "aditivo",
             "2º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM o Estado e a empresa. CLÁUSULA PRIMEIRA (Do Objeto): prorrogação de prazo.",
             [("Rachel Lopes da Silva", "Ordenadora", "03/06/2024", "14:00")]),
    ]
    r = IA.ordinal_divergente(docs)
    assert r["achado"] is True
    assert r["ordinal_minuta"] == 1 and 2 in r["ordinais_assinados"]
    assert "38" in r["fundamento"] or "53" in r["fundamento"]


def test_dois_instrumentos_com_o_mesmo_ordinal():
    docs = [
        _doc("Termo Aditivo 75769317", "aditivo", "2º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Rachel Lopes da Silva", "Ordenadora", "03/06/2024", "14:00")]),
        _doc("Termo Aditivo 76563176", "aditivo", "2º TERMO ADITIVO DO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Rachel Lopes da Silva", "Ordenadora", "11/06/2024", "17:40")]),
    ]
    r = IA.ordinal_divergente(docs)
    assert r["achado"] is True and r["duplicados"] == [2]


def test_minuta_e_instrumento_no_mesmo_ordinal_nao_e_achado():
    docs = [
        _doc("Minuta", "aditivo", "MINUTA. 1º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Fulano", "Oficial", "01/03/2024", "10:00")]),
        _doc("Termo Aditivo", "aditivo", "1º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Autoridade", "Ordenador", "10/03/2024", "10:00")]),
    ]
    assert IA.ordinal_divergente(docs)["achado"] is False


def test_processo_com_1o_e_2o_aditivos_legitimos_nao_e_achado():
    """Dois aditivos de ordinais DIFERENTES, cada um com sua minuta, é o fluxo normal."""
    docs = [
        _doc("M1", "aditivo", "MINUTA. 1º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.", []),
        _doc("A1", "aditivo", "1º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Autoridade", "Ordenador", "10/03/2024", "10:00")]),
        _doc("M2", "aditivo", "MINUTA. 2º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.", []),
        _doc("A2", "aditivo", "2º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Autoridade", "Ordenador", "10/03/2025", "10:00")]),
    ]
    assert IA.ordinal_divergente(docs)["achado"] is False


def test_sem_aditivo_nenhum_nao_ha_o_que_dizer():
    assert IA.ordinal_divergente([_doc("NF", "nota_fiscal", "Nota fiscal.")])["achado"] is False


# ───────────────────────── 2. autorização antes do parecer ─────────────────────────

def test_autorizacao_assinada_antes_do_parecer():
    docs = [
        _doc("Declaração Autorizo 74780114", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. AUTORIZAR a prorrogação do Contrato nº 16/2023.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:04")]),
        _doc("Parecer 462", "parecer",
             "PARECER Nº 462/2024. Assessoria Jurídica. Opino condicionado.",
             [("Marcello Cinelli de Paula Freitas", "Procurador", "22/05/2024", "21:50")]),
    ]
    r = IA.autorizacao_antes_do_parecer(docs)
    assert r["achado"] is True
    assert r["data_autorizacao"] == "16/05/2024" and r["data_parecer"] == "22/05/2024"


def test_autorizacao_depois_do_parecer_e_o_fluxo_correto():
    docs = [
        _doc("Parecer", "parecer", "PARECER Nº 1. Opino.",
             [("Procurador", "Procurador", "01/05/2024", "10:00")]),
        _doc("Autorizo", "autorizacao_despesa", "ATO DO ORDENADOR. AUTORIZAR a despesa.",
             [("Ordenador", "Ordenador", "05/05/2024", "10:00")]),
    ]
    assert IA.autorizacao_antes_do_parecer(docs)["achado"] is False


def test_sem_data_em_um_dos_dois_o_veredito_e_indisponivel():
    """Sem as duas datas não se afirma inversão — INDISPONÍVEL ≠ regular e ≠ irregular."""
    docs = [
        _doc("Autorizo", "autorizacao_despesa", "ATO DO ORDENADOR. AUTORIZAR a despesa."),
        _doc("Parecer", "parecer", "PARECER Nº 1. Opino.",
             [("Procurador", "Procurador", "01/05/2024", "10:00")]),
    ]
    r = IA.autorizacao_antes_do_parecer(docs)
    assert r["achado"] is False and r["indisponivel"] is True


# ───────────────────────── 3. ato decisório sem a assinatura de quem decide ─────────────────────────

def test_ato_marcado_como_minuta_e_sem_assinatura_da_autoridade():
    d = _doc("Declaração Autorizo 74780114", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS\n\n* MINUTA DE DOCUMENTO\n\n"
             "Este Ordenador de Despesas, RACHEL LOPES DA SILVA, Ten Cel BM, DECIDE, AUTORIZAR a "
             "prorrogação do Contrato nº 16/2023.\n\nRACHEL LOPES DA SILVA – TEN CEL BM\n"
             "Ordenadora de Despesa\n\nConfeccionado por:\nRENATO DE MELO CARDOSO - CAP BM",
             [("Renato de Melo Cardoso", "Oficial Administrativo", "16/05/2024", "16:04")])
    r = IA.ato_sem_assinatura_da_autoridade([d])
    assert r["achado"] is True
    assert r["marcado_minuta"] is True
    assert "RACHEL" in r["autoridade"].upper()
    assert "Renato" in " ".join(r["quem_assinou"])


def test_ato_assinado_pela_propria_autoridade_nao_e_achado():
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS\n\nEste Ordenador de Despesas, RACHEL LOPES DA SILVA, "
             "DECIDE, AUTORIZAR a despesa.\n\nRACHEL LOPES DA SILVA\nOrdenadora de Despesa",
             [("Rachel Lopes da Silva", "Ordenadora", "16/05/2024", "16:04")])
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is False


def test_ato_sem_assinatura_nenhuma_e_indisponivel_nao_achado():
    """Documento pode ter sido assinado fora do SEI — ausência de rodapé não prova ausência de ato."""
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, FULANO DE TAL, AUTORIZA.")
    r = IA.ato_sem_assinatura_da_autoridade([d])
    assert r["achado"] is False and r["indisponivel"] is True


@pytest.mark.parametrize("tipo", ["nota_fiscal", "despacho", "parecer"])
def test_documento_que_nao_e_ato_de_autorizacao_fica_fora(tipo):
    d = _doc("X", tipo, "Texto qualquer com MINUTA DE DOCUMENTO no meio.")
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is False


# ───────────────────────── integração: os três viram achados do 360 ─────────────────────────

def test_avaliar_devolve_os_tres_no_formato_de_achado():
    docs = [
        _doc("Minuta 74778400", "aditivo", "MINUTA. 1º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM o Estado e a empresa. CLÁUSULA PRIMEIRA (Do Objeto): prorrogação.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:00")]),
        _doc("Termo Aditivo 75769317", "aditivo", "2º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Rachel Lopes da Silva", "Ordenadora", "03/06/2024", "14:00")]),
        _doc("Declaração Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS\n* MINUTA DE DOCUMENTO\n"
             "Este Ordenador de Despesas, RACHEL LOPES DA SILVA, DECIDE, AUTORIZAR.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:04")]),
        _doc("Parecer 462", "parecer", "PARECER Nº 462/2024. Opino condicionado.",
             [("Marcello Cinelli", "Procurador", "22/05/2024", "21:50")]),
    ]
    achados = IA.avaliar(docs)
    codigos = {a["codigo"] for a in achados}
    assert codigos == {"I1_ORDINAL_DIVERGENTE", "I2_AUTORIZACAO_ANTES_DO_PARECER",
                       "I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE"}
    for a in achados:
        assert a["gravidade"] in ("media", "alta", "critica")
        assert a["diz"] and a["evidencia"], "achado sem prova literal não entra no dossiê"


def test_processo_limpo_nao_gera_achado():
    docs = [_doc("Parecer", "parecer", "PARECER Nº 1. Opino favoravelmente.",
                 [("Procurador", "Procurador", "01/05/2024", "10:00")]),
            _doc("Autorizo", "autorizacao_despesa",
                 "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, MARIA SOUZA, AUTORIZA.",
                 [("Maria Souza", "Ordenadora", "05/05/2024", "10:00")])]
    assert IA.avaliar(docs) == []


def test_peca_que_apenas_CITA_o_ordinal_nao_conta_como_instrumento():
    """Falso positivo medido no acervo real (2026-08-03): a Justificativa ("Trata o presente
    processo de formalização do 1º Termo Aditivo…") e o próprio parecer citam o ordinal, e eram
    contados como instrumentos assinados — o achado saía dizendo que havia 1º E 2º duplicados."""
    docs = [
        _doc("Justificativa 74779736", "contrato",
             "JUSTIFICATIVA. Trata o presente processo de formalização do 1º Termo Aditivo ao "
             "Contrato nº 16/2023, celebrado com a empresa LÍDER TÁXI AÉREO.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:06")]),
        _doc("Parecer 462", "parecer",
             "PARECER Nº 462/2024. 1º TERMO ADITIVO AO CONTRATO Nº 16/2023 - PRORROGAÇÃO.",
             [("Procurador", "Procurador", "22/05/2024", "21:50")]),
        _doc("Termo Aditivo 75769317", "aditivo",
             "2º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Rachel Lopes da Silva", "Ordenadora", "03/06/2024", "14:00")]),
    ]
    r = IA.ordinal_divergente(docs)
    assert r["ordinais_assinados"] == [2], f"peça que só cita virou instrumento: {r}"
    assert r["duplicados"] == []


def test_assinatura_no_fim_de_documento_longo_e_encontrada():
    """O Parecer 462 tem 54.900 caracteres e a assinatura mora no RODAPÉ. Lendo só os 20.000
    primeiros — o teto padrão do 360 — a data sumia e o I2 nunca disparava."""
    longo = _doc("Parecer 462", "parecer", "PARECER Nº 462/2024. " + "Fundamentação. " * 4000,
                 [("Marcello Cinelli de Paula Freitas", "Procurador", "22/05/2024", "21:50")])
    assert len(longo["texto"]) > 50000
    assert IA.assinaturas(longo["texto"])[0]["data"] == "22/05/2024"


def test_erro_de_digitacao_no_nome_nao_vira_acusacao():
    """Falso positivo medido no acervo (270006/020276/2024 e 020299/2024): o corpo do ato grafa
    'ALINE DE OLIVEIRA NASCXIMENTO' e a assinatura é de 'Aline de Oliveira Nascimento' — a MESMA
    pessoa. Comparação literal transformava um typo em 'a autoridade não assinou'."""
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, ALINE DE OLIVEIRA "
             "NASCXIMENTO, AUTORIZA a despesa.",
             [("Aline de Oliveira Nascimento", "Ordenadora", "10/04/2024", "10:00")])
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is False


def test_homonimo_parcial_continua_sendo_achado():
    """A tolerância a typo não pode engolir pessoa diferente: nomes distintos seguem divergentes."""
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, ALINE DE OLIVEIRA "
             "NASCIMENTO, AUTORIZA a despesa.",
             [("Carlos Eduardo Pereira", "Oficial", "10/04/2024", "10:00")])
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is True


def test_primeiro_nome_diferente_nao_casa_mesmo_com_sobrenome_igual():
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, MARIA DE OLIVEIRA "
             "NASCIMENTO, AUTORIZA.",
             [("Aline de Oliveira Nascimento", "Ordenadora", "10/04/2024", "10:00")])
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is True


# ───── dedup por IDENTIFICADOR (CPF / Id funcional), não por semelhança de nome ─────
# Pedido do dono em 2026-08-03: "dedup com CPF essa dúvida". Semelhança de nome é chute — dois
# servidores podem ter nomes quase iguais, e a mesma pessoa aparece grafada de três jeitos. O
# documento do SEI traz o identificador ao lado do nome, e a casa já tem a doutrina certa em
# `agentes_publicos.chave()`: "ID funcional manda; sem ele, nome normalizado".

def test_mesma_pessoa_provada_por_cpf_apesar_do_nome_divergente():
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, ALINE DE OLIVEIRA "
             "NASCXIMENTO, Id Funcional nº 613973-6, CPF 022.318.157-96, AUTORIZA.\n"
             "Assinado por: Aline de O. Nascimento, CPF 022.318.157-96.",
             [("Aline de O. Nascimento", "Ordenadora", "10/04/2024", "10:00")])
    r = IA.ato_sem_assinatura_da_autoridade([d])
    assert r["achado"] is False
    assert r["base_da_comparacao"] == "cpf"


def test_pessoas_DIFERENTES_provadas_por_cpf_viram_achado_certo():
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, RACHEL LOPES DA SILVA, "
             "CPF 022.318.157-96, DECIDE AUTORIZAR.\n"
             "Confeccionado por: RENATO DE MELO CARDOSO, CPF 111.222.333-44.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:04")])
    r = IA.ato_sem_assinatura_da_autoridade([d])
    assert r["achado"] is True and r["base_da_comparacao"] == "cpf"


def test_id_funcional_serve_quando_nao_ha_cpf():
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, RAFAEL PAIVA VIERA, "
             "Id Funcional nº 613973-6, DECIDE AUTORIZAR.\n"
             "Confeccionado por: IGOR LIBERATO CALIXTO, Id. Funcional: 4405356-8.",
             [("Igor Liberato Calixto", "Oficial", "16/05/2024", "16:04")])
    r = IA.ato_sem_assinatura_da_autoridade([d])
    assert r["achado"] is True and r["base_da_comparacao"] == "id_funcional"


def test_sem_identificador_cai_no_nome_e_DIZ_que_caiu():
    """Sem CPF nem Id, o veredito continua saindo — mas declarando que a base é o nome."""
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, MARIA SOUZA, AUTORIZA.",
             [("Carlos Pereira", "Oficial", "10/04/2024", "10:00")])
    r = IA.ato_sem_assinatura_da_autoridade([d])
    assert r["achado"] is True and r["base_da_comparacao"] == "nome"


def test_cpf_nunca_sai_inteiro_na_saida():
    """LGPD: a base interna compara o CPF íntegro; o entregável mostra mascarado."""
    d = _doc("Autorizo", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, RACHEL LOPES DA SILVA, "
             "CPF 022.318.157-96, DECIDE AUTORIZAR.\n"
             "Confeccionado por: RENATO DE MELO CARDOSO, CPF 111.222.333-44.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:04")])
    saida = " ".join(str(v) for v in IA.ato_sem_assinatura_da_autoridade([d]).values())
    assert "022.318.157-96" not in saida and "111.222.333-44" not in saida
