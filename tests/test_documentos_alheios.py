# -*- coding: utf-8 -*-
"""Documento de OUTRO processo não entra na pasta deste — e o manifest já sabia de quem é.

Achado em 2026-07-29 lendo o dossiê de `080001_000744_2024` (R$ 51,6 milhões, repasse do Fundo
Estadual de Saúde para nove Fundos Municipais). O dossiê trazia assinaturas de **merendeira,
Subtenente PM e Vice-Diretora do ILE/UERJ**, e um despacho da Secretaria de **Educação** sobre
controle de frequência de um colégio.

O rastro fechou assim:

    cache CDP (a leitura da árvore) .......... 10 documentos — TODOS do processo
    pasta arquivada .......................... 35 documentos
    manifest da íntegra ...................... 37 documentos, e o campo `contexto` diz
                                               de QUEM é cada um:
        080001/000744/2024 .... 10   ← o processo
        270006/014930/2026 ....  2
        270007/028772/2026 ....  2
        030001/006436/2026 ....  1   (o despacho da Educação)
        + outros 11 processos

A captura estava certa. O ARQUIVAMENTO é que juntou documentos de 15 processos numa pasta só —
e o dado para separar já estava no manifest, sem uso.

O dano não é estético: o dossiê atribui fatos e RESPONSÁVEIS a um processo que não é o deles, e
`agente_processo` (que responde "quem responde por este processo") herda o erro.

REGRA: documento sem número no contexto FICA. Ausência de dado não é prova de que o documento é
alheio — descartá-lo seria trocar contaminação por perda silenciosa.
"""
from compliance_agent.sei.documentos_alheios import numero_do_contexto, separar_alheios

MANIFEST = [
    {"i": 0, "titulo": "Programação de Desembolso - PD 2025PD04651 ITAPERUNA",
     "contexto": "Administrativo: Elaboração de Correspondência Nº SEI-080001/000744/2024"},
    {"i": 1, "titulo": "Programação de Desembolso - PD 2025PD04650",
     "contexto": "Administrativo: Elaboração de Correspondência Nº SEI-080001/000744/2024"},
    {"i": 12, "titulo": "Despacho de Encaminhamento de Processo",
     "contexto": "Recursos Humanos: Controle de Frequência Nº SEI-030001/006436/2026"},
    {"i": 13, "titulo": "Correspondência Interna - NA 1354", "contexto": "sem número aqui"},
]


def test_le_o_numero_do_processo_no_contexto():
    assert numero_do_contexto("Recursos Humanos: Controle de Frequência Nº SEI-030001/006436/2026") \
        == "030001/006436/2026"
    assert numero_do_contexto("Administrativo: Elaboração Nº SEI-080001/000744/2024") \
        == "080001/000744/2024"


def test_contexto_sem_numero_devolve_none():
    assert numero_do_contexto("sem número aqui") is None
    assert numero_do_contexto("") is None
    assert numero_do_contexto(None) is None


def test_separa_os_documentos_de_outro_processo():
    r = separar_alheios(MANIFEST, "080001/000744/2024")
    assert [d["i"] for d in r["proprios"]] == [0, 1, 13], "o sem-número FICA"
    assert [d["i"] for d in r["alheios"]] == [12]


def test_documento_sem_numero_NAO_e_descartado():
    """Ausência de dado não prova que o documento é de outro — descartar seria perder."""
    r = separar_alheios([{"i": 9, "contexto": "nada"}], "080001/000744/2024")
    assert r["alheios"] == []
    assert len(r["proprios"]) == 1
    assert r["sem_numero"] == 1


def test_o_relatorio_diz_de_quem_sao_os_alheios():
    """Saber que sobrou lixo não basta: para recuperar, é preciso saber de qual processo."""
    r = separar_alheios(MANIFEST, "080001/000744/2024")
    assert r["por_processo_alheio"] == {"030001/006436/2026": 1}


def test_numero_com_ponto_em_vez_de_barra_tambem_casa():
    """O SEI escreve o número dos dois jeitos conforme a tela."""
    assert numero_do_contexto("Nº SEI-080001.000744.2024") == "080001/000744/2024"


def test_pasta_toda_do_processo_nao_perde_nada():
    todos = [{"i": i, "contexto": "Nº SEI-080001/000744/2024"} for i in range(5)]
    r = separar_alheios(todos, "080001/000744/2024")
    assert len(r["proprios"]) == 5 and r["alheios"] == []
