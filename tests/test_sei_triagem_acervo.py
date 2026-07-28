# -*- coding: utf-8 -*-
"""Quando a queixa é de lacuna, a pergunta seguinte é: o documento falta MESMO?

`sei_triagem_flags.encaminhamento` já separa a queixa de captura do achado substantivo e
manda "recapturar" quem só tem lacuna. Falta o segundo passo, e ele é caro: o processo
SEI-070002/006145/2024 tem **294 documentos capturados no disco, 30 deles Ordens
Bancárias** — e a ficha diz "não inclui comprovante de pagamento (Ordem Bancária)". A
leitura viu 36 de 791 documentos da árvore e citou 2.

Recapturar esse processo é gastar browser e sessão SEI para trazer o que já está em disco,
e a ficha voltaria idêntica enquanto a análise continuar lendo 2 documentos. O
encaminhamento correto é REANALISAR sobre o acervo que já existe.
"""
from compliance_agent.sei_triagem_flags import encaminhamento, encaminhamento_com_acervo

LACUNA = ["Ausência de comprovante de pagamento (Ordem Bancária)"]
ACHADO = ["Pagamento de R$ 5,2 mi sem pesquisa de preços nos autos"]


def test_lacuna_com_acervo_nao_lido_manda_reanalisar_nao_recapturar():
    assert encaminhamento(LACUNA) == "recapturar"          # o que a régua antiga diz
    assert encaminhamento_com_acervo(LACUNA, docs_no_acervo=294, docs_lidos=2) == "reanalisar"


def test_lacuna_sem_acervo_continua_recapturar():
    """Sem material em disco, a queixa é verdadeira e o destino é mesmo o coletor."""
    assert encaminhamento_com_acervo(LACUNA, docs_no_acervo=0, docs_lidos=0) == "recapturar"


def test_lacuna_com_acervo_ja_todo_lido_continua_recapturar():
    """Tudo que havia foi lido e o documento não apareceu: a lacuna é do processo."""
    assert encaminhamento_com_acervo(LACUNA, docs_no_acervo=12, docs_lidos=12) == "recapturar"


def test_achado_substantivo_continua_indo_para_apuracao():
    """Acervo não lido não rebaixa achado — só reclassifica queixa de captura."""
    assert encaminhamento_com_acervo(ACHADO, docs_no_acervo=294, docs_lidos=2) == "apurar"
    assert encaminhamento_com_acervo(ACHADO + LACUNA, docs_no_acervo=294, docs_lidos=2) == "apurar"


def test_sem_flag_nenhuma_continua_sem_sinal():
    assert encaminhamento_com_acervo([], docs_no_acervo=294, docs_lidos=2) == "sem_sinal"


def test_sem_saber_o_acervo_devolve_o_mesmo_que_a_regua_antiga():
    """Chamador que não tem o número do acervo não pode ser penalizado com veredito novo."""
    for fl in (LACUNA, ACHADO, []):
        assert encaminhamento_com_acervo(fl) == encaminhamento(fl)
