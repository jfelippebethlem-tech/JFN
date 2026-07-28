# -*- coding: utf-8 -*-
"""Quais 40 documentos ler quando o processo tem 791.

`SEI_MAX_DOCS=40` limita a leitura por uma razão boa (tempo de browser). O que estava errado
era a ESCOLHA: `documentos[:40]` pega os primeiros da árvore, que são os despachos de
abertura. Medido no SEI-070002/006145/2024 (791 documentos):

    dos 40 primeiros da árvore .... 32 de valor baixo, 4 médio, 4 alto
    no processo inteiro ........... 38 de valor ALTO (33 pareceres jurídicos, 4 contratos, 1 TR)

Cabem todos os 38 no mesmo orçamento. A ficha desse processo concluiu "não inclui documentação
da licitação nem comprovante de pagamento" — com 33 pareceres e 30 Ordens Bancárias no processo,
nenhum deles alcançado.

E as Ordens Bancárias caíam em `outros` (valor baixo, texto descartado) porque o classificador
central não as conhecia, embora `cadeia_processo` já as reconheça como marco de pagamento.
"""
from compliance_agent.sei.classificador_doc import (classificar_doc, deve_guardar_texto,
                                                    ordenar_para_leitura, valor_doc)


# ── a Ordem Bancária entra na taxonomia ──────────────────────────────────────────────────────

def test_ordem_bancaria_e_reconhecida():
    assert classificar_doc("Ordem Bancária Orçamentaria (136295444)") == "ordem_bancaria"
    assert classificar_doc("OB 2026OB00123") == "ordem_bancaria"


def test_ordem_bancaria_vale_como_documento_de_despesa():
    """Mesma família de empenho e liquidação — é a peça que prova o PAGAMENTO."""
    assert valor_doc("ordem_bancaria") == "medio"
    assert deve_guardar_texto("ordem_bancaria") is True


def test_despacho_continua_tramitacao():
    """A regra nova não pode capturar o que já estava certo."""
    assert classificar_doc("Despacho de Encaminhamento de Processo 136511168") == "tramitacao"


# ── a escolha dos documentos a ler ───────────────────────────────────────────────────────────

def _docs(*titulos):
    return [{"titulo": t} for t in titulos]


def test_le_o_de_maior_valor_antes_do_que_veio_primeiro_na_arvore():
    docs = _docs("Despacho de Encaminhamento de Processo", "Parecer Jurídico PGE nº 12")
    assert [d["titulo"] for d in ordenar_para_leitura(docs, limite=1)] == ["Parecer Jurídico PGE nº 12"]


def test_respeita_o_orcamento_de_leitura():
    docs = _docs(*[f"Despacho {i}" for i in range(100)])
    assert len(ordenar_para_leitura(docs, limite=40)) == 40


def test_ordem_da_arvore_e_preservada_dentro_do_mesmo_valor():
    """A árvore é cronológica: entre documentos igualmente decisivos, a ordem dos atos importa."""
    docs = _docs("Parecer Jurídico A", "Parecer Jurídico B", "Parecer Jurídico C")
    assert [d["titulo"] for d in ordenar_para_leitura(docs, limite=3)] == \
        ["Parecer Jurídico A", "Parecer Jurídico B", "Parecer Jurídico C"]


def test_medio_vem_antes_de_baixo():
    docs = _docs("Despacho de Encaminhamento", "Nota de Empenho - NE 2026NE01331")
    assert [d["titulo"] for d in ordenar_para_leitura(docs, limite=1)] == \
        ["Nota de Empenho - NE 2026NE01331"]


def test_sem_limite_devolve_tudo_reordenado():
    docs = _docs("Despacho", "Contrato nº 36/2023")
    assert len(ordenar_para_leitura(docs, limite=None)) == 2


def test_lista_vazia_nao_quebra():
    assert ordenar_para_leitura([], limite=40) == []


def test_documento_sem_titulo_nao_quebra_e_vai_para_o_fim():
    docs = [{"titulo": ""}, {"titulo": "Contrato nº 36/2023"}]
    assert ordenar_para_leitura(docs, limite=1)[0]["titulo"] == "Contrato nº 36/2023"
