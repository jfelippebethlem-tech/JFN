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


# ═════ os quatro achados restantes da leitura do original (seção 2 do confronto) ═════

# ── 2.3 · ordinal incoerente com o prazo total que o próprio instrumento declara ──

def test_ordinal_incoerente_com_o_prazo_total():
    """Achado real: '2º TERMO ADITIVO' que dá ao contrato 'prazo total de 24 meses'. Contrato de
    12 + esta prorrogação de 12 = 24 → é o 1º aditivo. O ordinal errado desalinha a contagem para
    todo aditivo futuro, e o art. 57, II da Lei 8.666/93 limita as prorrogações a 60 meses."""
    d = _doc("Termo Aditivo 75769317", "aditivo",
             "2º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. "
             "CLÁUSULA SEGUNDA (Da Prorrogação do Prazo): fica prorrogado o prazo de vigência do "
             "contrato por 12 (doze) meses, dando-se ao contrato o prazo total de 24 (vinte e "
             "quatro) meses.",
             [("Rachel Lopes da Silva", "Ordenadora", "03/06/2024", "14:00")])
    r = IA.ordinal_incoerente_com_prazo([d])
    assert r["achado"] is True and r["ordinal"] == 2 and r["total_meses"] == 24
    assert r["ordinal_implicado"] == 1


def test_ordinal_coerente_nao_e_achado():
    d = _doc("TA", "aditivo",
             "2º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. CLÁUSULA SEGUNDA: prorrogado por 12 meses, "
             "dando-se ao contrato o prazo total de 36 (trinta e seis) meses.", [])
    assert IA.ordinal_incoerente_com_prazo([d])["achado"] is False


def test_sem_prazo_total_declarado_nao_se_afirma_nada():
    d = _doc("TA", "aditivo", "2º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. Prorrogação de 12 meses.", [])
    assert IA.ordinal_incoerente_com_prazo([d])["achado"] is False


# ── 2.6 · declaração que atesta conformidade de OUTRO contrato ──

def test_declaracao_cita_contrato_de_outro_processo():
    """Achado real: 'a minuta da renovação do contrato 04/2022 segue a MINUTA-PADRÃO' num processo
    do Contrato 16/2023 — e é nessa declaração que o parecer se apoia."""
    docs = [
        _doc("Termo Aditivo", "aditivo",
             "1º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.",
             [("Ordenador", "Ordenador", "01/06/2024", "10:00")]),
        _doc("Declaração segue minuta padrão", "contrato",
             "DECLARAÇÃO. Declaro para devidos fins que a minuta da renovação do contrato 04/2022 "
             "segue a MINUTA-PADRÃO DE TERMO ADITIVO, de acordo com a RESOLUÇÃO PGE Nº 3887/2016.",
             [("Oficial", "Oficial", "16/05/2024", "16:00")]),
    ]
    r = IA.declaracao_de_outro_contrato(docs)
    assert r["achado"] is True
    assert r["contrato_do_processo"] == "16/2023" and "04/2022" in r["contrato_citado"]


def test_declaracao_do_contrato_certo_nao_e_achado():
    docs = [
        _doc("Termo Aditivo", "aditivo",
             "1º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA.", []),
        _doc("Declaração", "contrato",
             "DECLARAÇÃO. Declaro que a minuta da renovação do contrato 16/2023 segue a "
             "MINUTA-PADRÃO de termo aditivo.", []),
    ]
    assert IA.declaracao_de_outro_contrato(docs)["achado"] is False


# ── 2.7 · quantitativo do atesto diverge do objeto contratado ──

def test_quantitativo_do_atesto_diverge_do_objeto():
    """Achado real: o objeto são 03 aeronaves e o atesto do fiscal fala em 04."""
    docs = [
        _doc("Termo Aditivo", "aditivo",
             "1º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA (Do Objeto): prestação "
             "de serviços de guarda e reboque (hangaragem) para 03 (três) aeronaves operadas pelo "
             "GOA/CBMERJ.", []),
        _doc("Ofício - NA 99", "oficio",
             "Com relação à qualidade da prestação do serviço executado pela Contratada: a empresa "
             "apresenta prestação de serviço de guarda e reboque (hangaragem) para 04 (quatro) "
             "aeronaves operadas pelo GOA/CBMERJ, seguindo o Termo de Referência.", []),
    ]
    r = IA.quantitativo_divergente(docs)
    assert r["achado"] is True
    assert r["objeto"] == 3 and r["atesto"] == 4


def test_quantitativo_igual_nao_e_achado():
    docs = [
        _doc("TA", "aditivo", "1º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA (Do "
                              "Objeto): hangaragem para 03 (três) aeronaves.", []),
        _doc("Ofício", "oficio", "A contratada presta o serviço de hangaragem para 03 (três) "
                                 "aeronaves, a contento.", []),
    ]
    assert IA.quantitativo_divergente(docs)["achado"] is False


# ── 2.8 · quem o documento diz que aprovou não é quem assinou ──

def test_aprovador_nomeado_que_nao_assinou():
    """Achado real na Justificativa 74779736: nomeia 'Conferido por: RAFAEL BENVINDO FREITAS' e
    'Aprovado por: RODRIGO HINAGO', e quem assinou foram Renato e Vinicius."""
    d = _doc("Justificativa 74779736", "contrato",
             "JUSTIFICATIVA. Trata o presente processo de aditivo.\n\n"
             "Elaborado por:\nRENATO DE MELO CARDOSO - Cap BM\n\n"
             "Conferido por:\nRAFAEL BENVINDO FREITAS – Ten Cel BM\n\n"
             "Aprovado por:\nRODRIGO HINAGO - Cel BM",
             [("Renato de Melo Cardoso", "Oficial Administrativo", "16/05/2024", "16:06"),
              ("Vinicius Moncores Lopes", "Oficial Administrativo", "17/05/2024", "09:24")])
    r = IA.aprovador_nao_assinou([d])
    assert r["achado"] is True
    faltam = " ".join(r["nao_assinaram"]).upper()
    assert "RAFAEL" in faltam and "RODRIGO" in faltam


def test_aprovador_que_assinou_nao_e_achado():
    d = _doc("Justificativa", "contrato",
             "JUSTIFICATIVA.\n\nAprovado por:\nRODRIGO HINAGO - Cel BM",
             [("Rodrigo Hinago", "Coronel", "16/05/2024", "16:06")])
    assert IA.aprovador_nao_assinou([d])["achado"] is False


def test_documento_sem_bloco_de_aprovacao_fica_fora():
    d = _doc("Nota", "nota_fiscal", "Nota fiscal de serviços.",
             [("Alguém", "Cargo", "01/01/2024", "10:00")])
    assert IA.aprovador_nao_assinou([d])["achado"] is False


# ── integração: os SETE no formato de achado ──

def test_avaliar_reune_os_sete_codigos_possiveis():
    assert set(IA.CODIGOS) == {
        "I1_ORDINAL_DIVERGENTE", "I2_AUTORIZACAO_ANTES_DO_PARECER",
        "I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE", "I4_ORDINAL_INCOERENTE_COM_PRAZO",
        "I5_DECLARACAO_DE_OUTRO_CONTRATO", "I6_QUANTITATIVO_DIVERGENTE",
        "I7_APROVADOR_NAO_ASSINOU"}


def test_I6_ignora_unidade_de_TEMPO():
    """Falso positivo medido no processo real: '5 (cinco) dias' no objeto × '10 (dez) dias' no
    atesto viraram 'quantitativo divergente'. Prazo não é quantitativo do objeto."""
    docs = [
        _doc("TA", "aditivo", "1º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA (Do "
                              "Objeto): serviço a ser prestado em 5 (cinco) dias úteis.", []),
        _doc("Ofício", "oficio", "A contratada executou o serviço; atesto que o prazo foi de "
                                 "10 (dez) dias.", []),
    ]
    assert IA.quantitativo_divergente(docs)["achado"] is False


def test_I7_nao_confunde_de_acordo_com_bloco_de_aprovacao():
    """Falso positivo medido: 'de acordo com a legislação orçamentária' virou nome de aprovador."""
    d = _doc("Declaração", "autorizacao_despesa",
             "DECLARO que a despesa está de acordo com a LEGISLACAO ORCAMENTARIA vigente e com o "
             "Artigo 16 da Lei Complementar nº 101.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:04")])
    assert IA.aprovador_nao_assinou([d])["achado"] is False


def test_I6_ignora_meses_no_plural():
    """Falso positivo medido: 'objeto contratado é de 12 mese(s)' — 'meses' escapava do veto
    porque o normalizador tira só o 's' final ('meses' → 'mese')."""
    docs = [
        _doc("TA", "aditivo", "1º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. CLÁUSULA PRIMEIRA (Do "
                              "Objeto): vigência de 12 (doze) meses.", []),
        _doc("Ofício", "oficio", "Atesto a execução; o serviço correu por 6 (seis) meses.", []),
    ]
    assert IA.quantitativo_divergente(docs)["achado"] is False


def test_I7_exige_NOME_de_gente_no_bloco_de_aprovacao():
    """Falsos positivos medidos: 'meio do Processo Admi (autorizado por)' e 'este coordenador
    (conferido por)'. A casa já tem `agentes_publicos.nome_plausivel` — é dele o julgamento."""
    d = _doc("Despacho", "despacho",
             "DESPACHO. Autorizado por meio do Processo Administrativo nº 123.\n"
             "Conferido por este coordenador, na forma regimental.",
             [("Fulano de Tal", "Oficial", "01/01/2024", "10:00")])
    assert IA.aprovador_nao_assinou([d])["achado"] is False


# ───── validação caso a caso dos I1..I7 no acervo (2026-08-03) ─────

def test_I3_documento_intitulado_MINUTA_e_rascunho_nao_ato():
    """Falso positivo medido (270003/001666/2024): 'Anexo MINUTA AUTORIZAÇÃO DE DESPESAS' — o
    documento se declara MINUTA no título. Rascunho não é assinado pela autoridade por definição;
    acusar isso é cobrar assinatura de quem ainda não decidiu. O achado real (270131/000548/2023) é
    outro: documento que NÃO se intitula minuta e funciona como o ato, trazendo a marca interna."""
    d = _doc("Anexo MINUTA AUTORIZAÇÃO DE DESPESAS (79611222)", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS. Este Ordenador de Despesas, GUSTAVO SOARES, AUTORIZA.",
             [("Rafael Ribeiro", "Oficial", "01/03/2024", "10:00")])
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is False


def test_I3_ato_que_NAO_se_intitula_minuta_continua_sendo_achado():
    d = _doc("Declaração Autorizo (74780114)", "autorizacao_despesa",
             "ATO DO ORDENADOR DE DESPESAS\n* MINUTA DE DOCUMENTO\n"
             "Este Ordenador de Despesas, RACHEL LOPES DA SILVA, DECIDE, AUTORIZAR.",
             [("Renato de Melo Cardoso", "Oficial", "16/05/2024", "16:04")])
    assert IA.ato_sem_assinatura_da_autoridade([d])["achado"] is True


def test_I4_declara_a_hipotese_que_o_inocenta():
    """Aditivo anterior que NÃO prorrogou prazo (aditivo de valor, por exemplo) explica o ordinal
    sem vício. O achado tem de dizer isso — indício não pode se apresentar como certeza."""
    d = _doc("Termo Aditivo", "aditivo",
             "2º TERMO ADITIVO, QUE ENTRE SI CELEBRAM. CLÁUSULA SEGUNDA: fica prorrogado por "
             "12 (doze) meses, dando-se ao contrato o prazo total de 24 (vinte e quatro) meses.",
             [("Ordenador", "Ordenador", "01/06/2024", "10:00")])
    r = IA.ordinal_incoerente_com_prazo([d])
    assert r["achado"] is True
    assert "valor" in r["diz"].lower() or "não prorrog" in r["diz"].lower()


# ═══════════ Validação caso a caso dos disparos de I1 e I2 (2026-08-03) ═══════════
# Pendência declarada no handoff anterior: I1 e I2 eram os únicos códigos AMOSTRADOS, não abertos
# documento a documento. Abertos agora, sobre os 25 disparos do acervo real. I1 caiu de 10 para 3
# e I2 de 15 para 1 — e o caso que deu origem aos dois (270131/000548/2023) sobreviveu inteiro.
# Cada teste abaixo é um falso positivo LIDO no acervo, não uma hipótese.

def test_I1_ordinal_vem_da_formula_do_proprio_instrumento():
    """O Contrato 36/2023 do INEA cita "PRIMEIRO TERMO ADITIVO" numa cláusula e era contado como
    o 1º aditivo, colidindo com o aditivo verdadeiro (070002/006145/2024)."""
    contrato = _doc("Contrato 36/2023 - INEA", "contrato",
                    "CONTRATO N.º 36/2023 DE PRESTAÇÃO DE SERVIÇOS QUE ENTRE SI CELEBRAM o "
                    "Estado e a empresa. CLÁUSULA DÉCIMA: o PRIMEIRO TERMO ADITIVO poderá "
                    "prorrogar a vigência.", [("Ana", "Presidente", "01/03/2023", "10:00")])
    aditivo = _doc("Termo Aditivo 45/2024", "aditivo",
                   "PRIMEIRO TERMO ADITIVO AO CONTRATO INEA 36/2023, QUE ENTRE SI CELEBRAM O "
                   "INSTITUTO e a empresa.", [("Ana", "Presidente", "01/03/2024", "10:00")])
    r = IA.ordinal_divergente([contrato, aditivo])
    assert r["achado"] is False and r["duplicados"] == []


def test_I1_le_o_ordinal_por_extenso():
    """O SEI-RJ grafa "SEGUNDO TERMO ADITIVO" tanto quanto "2º" — sem extenso o aditivo caía no
    ordinal de outra passagem do texto."""
    d = _doc("Termo Aditivo 63/2024", "aditivo",
             "SEGUNDO TERMO ADITIVO AO CONTRATO INEA 36/2023, QUE ENTRE SI CELEBRAM.",
             [("Ana", "Presidente", "01/06/2024", "10:00")])
    assert IA._ordinal(d) == 2


@pytest.mark.parametrize("titulo", ["Publicação do 1º TA ao Contrato nº 016/2021",
                                    "Termo de Apostilamento", "Extrato do 1º Termo Aditivo"])
def test_I1_publicacao_e_apostilamento_nao_sao_o_instrumento(titulo):
    """O extrato publicado no D.O. e o apostilamento entravam como instrumento assinado e
    produziam ordinal duplicado (420001/004224/2024 e mais três)."""
    real = _doc("Termo Aditivo - 1º TA", "aditivo",
                "1º TERMO ADITIVO AO CONTRATO Nº 016/2021, QUE ENTRE SI CELEBRAM.",
                [("Ana", "Diretora", "01/06/2024", "10:00")])
    extrato = _doc(titulo, "contrato",
                   "1º TERMO ADITIVO AO CONTRATO Nº 016/2021 QUE ENTRE SI CELEBRAM. "
                   "CLÁUSULA PRIMEIRA DO OBJETO.", [("Ana", "Diretora", "02/06/2024", "10:00")])
    assert IA.ordinal_divergente([real, extrato])["achado"] is False


def test_I1_minuta_mais_recente_que_todo_assinado_e_processo_EM_CURSO():
    """Minuta do 2º aditivo depois do 1º assinado é instrução em andamento, não peça atropelada
    (070002/012954/2022)."""
    assinado = _doc("Termo Aditivo 90186554", "aditivo",
                    "1º TERMO ADITIVO AO CONTRATO Nº 5/2022, QUE ENTRE SI CELEBRAM.",
                    [("Adib", "Presidente", "27/12/2024", "10:00")])
    minuta = _doc("Minuta de Termo Aditivo (98441299)", "aditivo",
                  "MINUTA. 2º TERMO ADITIVO AO CONTRATO Nº 5/2022, QUE ENTRE SI CELEBRAM.",
                  [("Renato", "Oficial", "01/03/2025", "10:00")])
    assert IA.ordinal_divergente([assinado, minuta])["achado"] is False


def test_I1_minuta_corrigida_ANTES_da_assinatura_e_o_controle_funcionando():
    """Minuta do 2º em 06/06, minuta do 3º em 11/06, assina-se o 3º em 20/06: a correção veio
    antes da celebração (270131/000564/2023). Acusar aí é punir o processo que se corrigiu."""
    m2 = _doc("Minuta de Termo Aditivo 76079615", "aditivo",
              "MINUTA. 2º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM.",
              [("Renato", "Oficial", "06/06/2024", "10:00")])
    m3 = _doc("Minuta de Termo Aditivo 76516642", "aditivo",
              "MINUTA. 3º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM.",
              [("Renato", "Oficial", "11/06/2024", "10:00")])
    ass = _doc("Termo Aditivo 77050539", "aditivo",
               "3º TERMO ADITIVO AO CONTRATO Nº 9/2023, QUE ENTRE SI CELEBRAM.",
               [("Pedro", "Ordenador", "20/06/2024", "10:00")])
    assert IA.ordinal_divergente([m2, m3, ass])["achado"] is False


def test_I1_minuta_atropelada_continua_sendo_achado():
    """O caso que deu origem ao detector: minuta do 1º em 16/05, instrumento do 2º em 03/06, sem
    nenhuma minuta do 2º pelo meio (270131/000548/2023)."""
    m = _doc("Minuta de Termo Aditivo ao Contrato 74778400", "aditivo",
             "MINUTA. 1º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM.",
             [("Renato", "Oficial", "16/05/2024", "10:00")])
    a = _doc("Termo Aditivo 75769317", "aditivo",
             "2º TERMO ADITIVO AO CONTRATO Nº 16/2023, QUE ENTRE SI CELEBRAM.",
             [("Rachel", "Ordenadora", "03/06/2024", "10:00")])
    assert IA.ordinal_divergente([m, a])["achado"] is True


def test_I1_mesma_peca_anexada_duas_vezes_nao_sao_dois_instrumentos():
    """O 1º aditivo está na pasta como "Anexo SEI_…" e como "Anexo …_eDO", com as MESMAS
    assinaturas nas mesmas datas (270003/000382/2025)."""
    firmas = [("Luiz", "Secretário", "22/06/2023", "10:00"),
              ("Chrizantho", "Diretor", "23/06/2023", "11:00")]
    a = _doc("Anexo SEI_54299221_Termo_Aditivo", "aditivo",
             "1º TERMO ADITIVO AO CONTRATO N° 89/2022, QUE ENTRE SI CELEBRAM.", firmas)
    b = _doc("Anexo termo_aditivo_contrato_89.2022eDO", "aditivo",
             "1º TERMO ADITIVO AO CONTRATO N° 89/2022, QUE ENTRE SI CELEBRAM.", firmas)
    assert IA.ordinal_divergente([a, b])["achado"] is False


def test_I1_duplicata_com_assinante_a_mais_declara_a_hipotese_de_reemissao():
    """Duas cópias do 3º TA, a segunda com um assinante a mais: pode ser reemissão para colher
    assinatura faltante, e o achado tem de dizer isso (270003/000382/2025)."""
    a = _doc("Termo Aditivo 102859182", "aditivo",
             "3º TERMO ADITIVO AO CONTRATO N° 89/2022, QUE ENTRE SI CELEBRAM.",
             [("Luciano", "Diretor", "20/06/2025", "10:00")])
    b = _doc("Termo Aditivo 102996985", "aditivo",
             "3º TERMO ADITIVO AO CONTRATO N° 89/2022, QUE ENTRE SI CELEBRAM.",
             [("Luiz", "Secretário", "23/06/2025", "10:00"),
              ("Luciano", "Diretor", "23/06/2025", "11:00")])
    r = IA.ordinal_divergente([a, b])
    assert r["achado"] is True and "reemiss" in r["diz"]


@pytest.mark.parametrize("titulo,corpo", [
    ("Checklist 44733775", "CHECKLIST: PRORROGAÇÃO CONTRATUAL. Itens verificados."),
    ("Anexo Único - Resolução PGE/SEPLAG nº 187/2021",
     "DECLARAÇÃO DE CONFORMIDADE. DECLARO A CONFORMIDADE da minuta de edital com a "
     "minuta-padrão estabelecida pela Procuradoria Geral do Estado."),
    ("Ato de Designação de Servidor 53213796",
     "ATO DE DESIGNAÇÃO DE SERVIDOR. Designo a servidora para elaborar a minuta de edital."),
    ("Correspondência Interna - NA 1232",
     "CI Nº1232. Assunto: solicitação de troca de marca. A comissão possui parecer favorável."),
])
def test_I2_peca_que_nao_e_manifestacao_juridica_nao_serve_de_marco(titulo, corpo):
    """Quatro dos quinze disparos do I2 comparavam a autorização com peça que não é o controle
    prévio do art. 53 — checklist, declaração de conformidade da própria unidade, ato de
    designação e correspondência interna. Mesma doutrina que já derrubou 71 disparos do G3."""
    aut = _doc("Declaração do Ordenador de Despesas", "autorizacao_despesa",
               "DECLARAÇÃO DO ORDENADOR DE DESPESA. I - AUTORIZO a reserva orçamentária.",
               [("Rachel", "Ordenadora", "16/05/2024", "10:00")])
    falso = _doc(titulo, "parecer_juridico", corpo, [("Bruno", "Chefe", "22/05/2024", "10:00")])
    assert IA.autorizacao_antes_do_parecer([aut, falso])["achado"] is False


def test_I2_etiqueta_do_arquivo_nao_prova_que_o_documento_e_parecer():
    """O arquivo compacto prepõe "[título] (fase: … · tipo: parecer_juridico)" ao .txt. A palavra
    `juridico` entrava no texto e o documento provava a si mesmo — o "Parecer de Análise para
    Emissão DL" da Diretoria Administrativa Financeira passava por isso (080002/006705/2024)."""
    assert IA.e_controle_juridico(
        "Parecer de Análise para Emissão DL 83167512",
        "[Parecer de Análise para Emissão DL] (fase: controle · tipo: parecer_juridico)\n\n"
        "Fundação Saúde. Diretoria Administrativa Financeira.\n"
        "Procedida a Revisão do processo referente a indenização de serviços prestados.") is False


def test_I2_rotulo_de_campo_do_formulario_da_NAD_nao_e_o_ato():
    """Toda Nota de Autorização de Despesa traz impresso "39 - APROVO E AUTORIZO ORDENADOR /
    AUTORIDADE DELEGADA" como cabeçalho de campo. Cinco disparos vinham de ler o rótulo do
    formulário como a decisão do ordenador (080002/006705/2024 e outros quatro)."""
    nad = ("Apresentamos a dotação orçamentária solicitada conforme detalhamento da conta "
           "contábil 622110101.\n37 - MATRÍCULA\t38 - DATA\n"
           "39 - APROVO E AUTORIZO ORDENADOR / AUTORIDADE DELEGADA\t40 - ATO DE DELEGAÇÃO\n")
    assert IA.e_ato_de_autorizacao(nad) is False
    assert IA.e_ato_de_autorizacao("DECLARO: I - AUTORIZO a reserva orçamentária.") is True


def test_I2_parecer_sem_data_legivel_torna_a_comparacao_indisponivel():
    """A comparação é com o PRIMEIRO parecer. Havendo parecer cuja data não se lê — o rodapé de
    assinatura mora no fim, e 1.969 documentos do arquivo estão cortados em 20.000 caracteres —,
    o primeiro pode ser justamente ele. INDISPONÍVEL ≠ irregular."""
    aut = _doc("Declaração do Ordenador", "autorizacao_despesa",
               "ATO DO ORDENADOR DE DESPESAS. AUTORIZO a despesa.",
               [("Rachel", "Ordenadora", "15/03/2024", "10:00")])
    sem_data = _doc("Parecer 104 (67843319)", "parecer_juridico",
                    "PARECER Nº 104. Assessoria Jurídica. Opino pelo prosseguimento.")
    com_data = _doc("Parecer 639", "parecer_juridico",
                    "PARECER Nº 639. Assessoria Jurídica. Opino.",
                    [("Marcello", "Procurador", "28/08/2024", "10:00")])
    r = IA.autorizacao_antes_do_parecer([aut, sem_data, com_data])
    assert r["achado"] is False and r["indisponivel"] is True
    assert "Parecer 104" in r["motivo"]
