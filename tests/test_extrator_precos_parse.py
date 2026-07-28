# -*- coding: utf-8 -*-
"""A tabela de preços não pode ser descartada por causa da embalagem da resposta.

`_camada_llm_texto` desembrulhava a resposta do modelo à mão — `removeprefix("```json")`,
`removesuffix("```")` — e caía no `except` genérico devolvendo `[]` sempre que a forma fugia
disso: cerca no meio da prosa, uma frase antes do JSON, vírgula sobrando, resposta cortada
pelo limite de tokens.

`[]` aqui não é "documento sem tabela de preços": é a tabela existindo e sendo jogada fora
depois de paga. E preço unitário é a matéria-prima do sobrepreço — o achado morre na
embalagem.

O parse único da casa (`llm/json_resposta`) já resolve todas essas formas, com teste de
paridade próprio. Aqui só se liga um sítio que ficou de fora.
"""
from compliance_agent.sei.extrator_precos import _camada_llm_texto

ITEM = '[{"item":"1","descricao":"Cimento CP-II","unidade":"sc","quantidade":"100","valor_unitario":"32,50"}]'


def _gerar(resposta):
    return lambda _prompt: resposta


def test_json_puro_continua_funcionando():
    assert _camada_llm_texto("texto", _gerar(ITEM))[0]["descricao"] == "Cimento CP-II"


def test_cerca_simples_continua_funcionando():
    assert len(_camada_llm_texto("texto", _gerar(f"```json\n{ITEM}\n```"))) == 1


def test_prosa_antes_e_depois_da_cerca_nao_descarta_a_tabela():
    resposta = f"Claro! Segue a tabela extraída:\n\n```json\n{ITEM}\n```\n\nQualquer dúvida, avise."
    assert len(_camada_llm_texto("texto", _gerar(resposta))) == 1


def test_virgula_sobrando_nao_descarta_a_tabela():
    resposta = '[{"item":"1","descricao":"Cimento CP-II","valor_unitario":"32,50"},]'
    assert len(_camada_llm_texto("texto", _gerar(resposta))) == 1


def test_lista_vazia_continua_significando_sem_tabela():
    """O modelo dizendo `[]` é resposta legítima — não pode virar erro."""
    assert _camada_llm_texto("texto", _gerar("[]")) == []


def test_resposta_sem_json_nenhum_devolve_vazio():
    assert _camada_llm_texto("texto", _gerar("Não há tabela de preços neste documento.")) == []


def test_gerador_que_levanta_nao_derruba_a_extracao():
    """O ramo de erro tem de EXISTIR de verdade: a 1ª versão logava com um `logger` que o
    módulo não definia, trocando a falha do gerador por um NameError — a mesma doença que
    esta casa já pegou (régua que some porque o erro foi engolido)."""
    def gerar_quebrado(_prompt):
        raise TypeError("gerador quebrado")

    assert _camada_llm_texto("texto", gerar_quebrado) == []


def test_sem_pdfplumber_a_camada_de_tabela_degrada_para_vazio(monkeypatch):
    """Dependência opcional ausente é [] honesto — e o `except` diz qual erro espera."""
    import builtins

    real = builtins.__import__

    def sem_pdfplumber(nome, *a, **k):
        if nome == "pdfplumber":
            raise ImportError("no module named pdfplumber")
        return real(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sem_pdfplumber)
    from compliance_agent.sei.extrator_precos import _camada_tabela_pdf, _texto_pdf

    assert _camada_tabela_pdf(b"%PDF-1.4 falso") == []
    assert _texto_pdf(b"%PDF-1.4 falso") == ""


def test_pdf_corrompido_nao_derruba_a_extracao():
    from compliance_agent.sei.extrator_precos import _camada_tabela_pdf, _texto_pdf

    assert _camada_tabela_pdf(b"isto nao e um PDF") == []
    assert _texto_pdf(b"isto nao e um PDF") == ""


def test_objeto_solto_em_vez_de_lista_nao_vira_item_falso():
    """Contrato é LISTA de itens; um dict avulso não é tabela e não pode ser inventado."""
    assert _camada_llm_texto("texto", _gerar('{"erro":"nao consegui"}')) == []
