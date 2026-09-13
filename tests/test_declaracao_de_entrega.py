# -*- coding: utf-8 -*-
"""A prova de entrega mora no TEXTO, não no título — e o modo verbal decide qual é prova.

`fases.classificar` decide a fase pelo TÍTULO, e o título destes documentos não anuncia execução
nenhuma: "Ofício - NI 196/2024", "Correspondência Interna - NA 163", "Anexo ANS". Medido em
2026-08-05 sobre os **319 processos** com `F_EXECUCAO_SEM_EVIDENCIA` — o maior achado do acervo,
quase metade dos 667 — **69 (21,6%) trazem no TEXTO a afirmação de que o objeto foi entregue**.

O caminho errado estava à mão: uma primeira medida deu **93% de "atesto"** numa amostra de 60, e
quase todo esse 93% era *"ATESTO e CERTIFICO a regularidade da **liquidação da despesa**"* — o
servidor certificando o ATO financeiro, não que a coisa chegou. Tratar os dois como o mesmo
esvaziaria o maior achado do acervo com prova que não é prova.
"""
from __future__ import annotations

from compliance_agent.processo_360 import (_RX_ENTREGA_AFIRMADA as SIM,
                                           _RX_ENTREGA_NAO_AFIRMADA as NAO)


def _declara(texto: str) -> bool:
    m = SIM.search(texto)
    if not m:
        return False
    janela = texto[max(0, m.start() - 130):m.end() + 130]
    return not NAO.search(janela)


AFIRMAM = [
    # atesto de recebimento de bem, na unidade que recebeu
    "Atestamos o recebimento, em 04/2024, dos kit material escolar conforme quantidades e "
    "especificações contratadas.",
    # a PGE LENDO os autos: a NF atestada por dois servidores (art. 90, §3º, Lei Est. 287/79)
    "na Nota Fiscal nº 894 (101360976), assinada por dois servidores, em conformidade com a "
    "exigência do art. 90, §3º, da Lei Estadual nº 287/79, que confirma que o serviço foi "
    "prestado a contento.",
    "ATESTAMOS, que os serviços foram prestados a contento e cumpre informar que não foi "
    "identificada glosa no período.",
    "Considerando que os serviços foram prestados a contento, tendo sido analisada toda a "
    "documentação juntada aos autos.",
]

NAO_AFIRMAM = [
    # atesto do ATO financeiro — 93% da primeira amostra, e não diz nada sobre a entrega
    "Em prosseguimento, face da análise precedida, ATESTO e CERTIFICO a regularidade da "
    "liquidação da despesa, em favor de Fundo Municipal de Saúde.",
    # a PGE PERGUNTANDO, logo antes de registrar a ausência
    "deve ser informado se o serviço foi prestado adequadamente, uma vez que, a despeito da "
    "ausência de cobertura contratual, houve execução.",
    # doutrina do TAC no Parecer 1994: descreve o que o atesto SERIA
    "atesto na nota fiscal e/ou fatura correspondente, por representante da Administração "
    "Pública, da(s) parcela(s) executada(s), reconhecendo que um determinado serviço foi "
    "prestado ou algum bem foi entregue, ainda que sem cobertura contratual válida.",
    # checklist: a exigência, não o cumprimento dela
    "atestação na nota fiscal e/ou fatura correspondente, por fiscal do contrato, da(s) "
    "parcela(s) executada(s), reconhecendo que o serviço foi prestado ou o bem foi entregue.",
]


def test_declaracao_de_entrega_afirmada_e_reconhecida():
    for texto in AFIRMAM:
        assert _declara(texto), f"deveria reconhecer a entrega: {texto[:70]}"


def test_atesto_do_ato_financeiro_e_norma_nao_valem_como_entrega():
    for texto in NAO_AFIRMAM:
        assert not _declara(texto), f"não afirma entrega, mas passou: {texto[:70]}"
