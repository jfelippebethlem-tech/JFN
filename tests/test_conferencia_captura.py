# -*- coding: utf-8 -*-
"""O parecer LISTA os documentos dos autos — é conferência externa da nossa captura.

Achado na leitura integral do SEI-270131/000548/2023 (2026-08-03): o relatório do Parecer 462
enumera 31 documentos com o número SEI de cada um, e **4 não estavam no nosso arquivo** —
incluindo a documentação de habilitação (74889283) e a planilha de formação de preço (74889284),
que são justamente a prova de duas das condicionantes que o mesmo parecer impõe.

O valor disto é duplo e nenhum lado é opinião: (a) sabemos, documento a documento, o que falta
capturar — não "a captura parece incompleta", mas "faltam estes quatro, com número"; e (b) todo
veredito sobre condicionante nesses processos passa a ser lido com a lacuna declarada, porque
INDISPONÍVEL ≠ descumprido.

A conferência NUNCA é achado contra o processo: é achado contra a NOSSA coleta.
"""
from compliance_agent.sei import conferencia_captura as C

_PARECER = """
PARECER Nº 462/2024/SEDEC/ASSJUR. PROCESSO Nº SEI-270131/000548/2023.

I. RELATÓRIO
Os autos foram instruídos com os seguintes documentos:
Anexo Contrato_Hangaragem_escaneado (65334602);
Despacho de Encaminhamento de Processo 67955010;
Minuta de Termo Aditivo ao Contrato 74778400;
Checklist 74779798;
Anexo Gmail - RES_ documentação de habilitação (74889283);
Anexo PLANILHA DE FORMAÇÃO DE PREÇO - HANGARAGEM (74889284).

II. FUNDAMENTAÇÃO
O feito foi submetido a esta ASSJUR. Cita-se ainda o Parecer nº 02/2017 (12345678) a título de
precedente, que não integra estes autos.
"""


def _docs(*titulos):
    return [{"ref": t, "tipo": "outro", "texto": ""} for t in titulos]


def test_aponta_os_documentos_citados_que_nao_capturamos():
    capturados = _docs("Anexo Contrato_Hangaragem_escaneado (65334602)",
                       "Despacho de Encaminhamento de Processo 67955010",
                       "Minuta de Termo Aditivo ao Contrato 74778400")
    r = C.conferir(capturados + [{"ref": "Parecer 462", "tipo": "parecer", "texto": _PARECER}])
    assert r["ausentes"] == ["74779798", "74889283", "74889284"], r["ausentes"]
    assert r["n_citados"] == 6


def test_so_conta_o_que_o_parecer_lista_como_INSTRUCAO_dos_autos():
    """Precedente citado na fundamentação ('Parecer nº 02/2017 (12345678)') não é documento
    destes autos — cobrá-lo como lacuna de captura mandaria a fila atrás de coisa que não existe."""
    r = C.conferir([{"ref": "Parecer 462", "tipo": "parecer", "texto": _PARECER}])
    assert "12345678" not in r["ausentes"]


def test_captura_completa_nao_gera_achado():
    capturados = _docs("(65334602)", "67955010", "74778400", "74779798", "74889283", "74889284")
    r = C.conferir(capturados + [{"ref": "Parecer 462", "tipo": "parecer", "texto": _PARECER}])
    assert r["ausentes"] == [] and r["achado"] is False


def test_sem_parecer_nao_ha_conferencia_e_isso_e_dito():
    r = C.conferir(_docs("Nota fiscal 123"))
    assert r["achado"] is False and r["indisponivel"] is True


def test_gravidade_e_de_CAPTURA_nunca_do_processo():
    """A lacuna é da nossa coleta. Marcá-la como vício do processo seria imputar ao gestor um
    defeito nosso — o oposto do que esta casa existe para fazer."""
    r = C.conferir([{"ref": "Parecer", "tipo": "parecer", "texto": _PARECER}])
    assert r["achado"] is True
    assert r["gravidade"] == "captura"
    assert "captur" in r["diz"].lower()
    assert "INDISPON" in r["diz"].upper() or "indispon" in r["diz"].lower()


def test_saida_no_formato_de_achado_do_360():
    a = C.avaliar([{"ref": "Parecer", "tipo": "parecer", "texto": _PARECER}])
    assert len(a) == 1
    assert a[0]["codigo"] == "C1_DOCUMENTO_CITADO_NAO_CAPTURADO"
    assert a[0]["gravidade"] == "captura"
    assert a[0]["evidencia"]


def test_lista_para_a_fila_de_captura():
    """Quem consome isto é o sweep: precisa do número, não da prosa."""
    r = C.conferir([{"ref": "Parecer", "tipo": "parecer", "texto": _PARECER}])
    assert all(n.isdigit() and 7 <= len(n) <= 9 for n in r["ausentes"])


# ───── documento de OUTRO processo não é lacuna da nossa captura (medido 2026-08-03) ─────

_COM_OUTRO_PROCESSO = """
PARECER Nº 111/2025. PROCESSO Nº SEI-030001/044358/2025.
I. RELATÓRIO
Instruem os autos: Despacho (98967395); Minuta (99000111).
Consta ainda o Parecer PGE/PROCON/EXE/SUPOF nº 02/2023 nos autos administrativos
SEI-030029/005620/2023 sob index 51726816; e o Ofício (51000222) destes autos.
II. FUNDAMENTAÇÃO
"""


def test_documento_citado_como_de_OUTRO_processo_nao_entra_na_fila():
    """Medido no acervo: '…nos autos administrativos SEI-030029/005620/2023 sob index 51726816'.
    Cobrar esse número mandaria o sweep capturar documento de processo alheio."""
    r = C.conferir([{"ref": "Parecer 111", "tipo": "parecer", "texto": _COM_OUTRO_PROCESSO}])
    assert "51726816" not in r["ausentes"], r["ausentes"]
    assert set(r["ausentes"]) == {"98967395", "99000111", "51000222"}


def test_o_numero_do_processo_e_lido_do_cabecalho_do_parecer():
    assert C.numero_do_processo(_COM_OUTRO_PROCESSO) == "030001/044358/2025"


def test_sem_numero_no_cabecalho_a_conferencia_segue_sem_o_filtro():
    """Sem saber qual é o processo, não se pode dizer que a citação é alheia — e calar a
    conferência inteira seria pior: perde-se a lista toda por causa de um filtro."""
    texto = "PARECER Nº 9. I. RELATÓRIO. Instruem: Despacho (98967395). II. FUNDAMENTAÇÃO"
    r = C.conferir([{"ref": "P", "tipo": "parecer", "texto": texto}])
    assert r["ausentes"] == ["98967395"]


def test_numero_com_zero_a_esquerda_nao_e_documento_do_sei():
    """Medido no acervo (070002/012954/2022): '00159075' entrou na fila. Documento do SEI-RJ nunca
    começa com zero — aquilo era fragmento de CNPJ/valor no corpo do relatório."""
    txt = ("PARECER Nº 5. PROCESSO Nº SEI-070002/012954/2022. I. RELATÓRIO. Instruem os autos: "
           "Ofício (73055430); consta o valor 00159075 na planilha. II. FUNDAMENTAÇÃO")
    r = C.conferir([{"ref": "P", "tipo": "parecer", "texto": txt}])
    assert r["ausentes"] == ["73055430"]


# ───── validação caso a caso (2026-08-03): três falsos positivos medidos ─────

def test_numero_de_TELEFONE_nao_e_documento():
    """Medido: 'Telefone: 23809230' entrava na fila de captura. O rodapé do SEI traz o telefone
    da unidade, e ele tem 8 dígitos como um número de documento."""
    txt = ("PARECER Nº 1. PROCESSO Nº SEI-030001/004949/2026. I. RELATÓRIO. Instruem: Ofício "
           "(98967395). Rua Joaquim Palhares, 40, Rio de Janeiro/RJ. Telefone: 23809230 - "
           "www.rj.gov.br. II. FUNDAMENTAÇÃO")
    r = C.conferir([{"ref": "P", "tipo": "parecer", "texto": txt}])
    assert r["ausentes"] == ["98967395"], r["ausentes"]


def test_documento_capturado_conta_mesmo_que_o_ID_nao_esteja_no_TITULO():
    """Medido: o parecer cita 'Relatório de Fiscalização (121178482)' e o documento ESTÁ na pasta,
    mas com título sem o número. Cobrar a recaptura dele manda o sweep buscar o que já temos."""
    txt = ("PARECER Nº 2. PROCESSO Nº SEI-030001/111011/2025. I. RELATÓRIO. Considerando o "
           "Relatório de Fiscalização (121178482). II. FUNDAMENTAÇÃO")
    docs = [{"ref": "P", "tipo": "parecer", "texto": txt},
            {"ref": "Relatório de Fiscalização", "tipo": "outro",
             "texto": "[Relatório de Fiscalização (121178482)] conteúdo."}]
    assert C.conferir(docs)["ausentes"] == []


def test_o_que_falta_DE_VERDADE_continua_sendo_cobrado():
    txt = ("PARECER Nº 3. PROCESSO Nº SEI-X/1/2026. I. RELATÓRIO. Instruem: Habilitação "
           "(74889283); Planilha (74889284). II. FUNDAMENTAÇÃO")
    r = C.conferir([{"ref": "P", "tipo": "parecer", "texto": txt}])
    assert set(r["ausentes"]) == {"74889283", "74889284"}
