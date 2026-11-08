"""Trava a causa-raiz de 2026-09-02: a pesquisa pública do SEI municipal é AJAX.

O resultado é injetado em `.retorno-ajax` e a página NUNCA navega, então o `body` devolve o
formulário de novo — que sempre contém a palavra "captcha" e nunca contém o resultado. Medir o
captcha pela PRESENÇA do widget dava `captcha_resolvido=False` mesmo com o OCR correto, e o texto
devolvido era o formulário, o que fazia toda busca parecer "não encontrou".
"""
from compliance_agent.collectors.sei_cdp import _captcha_recusado, _is_captcha_page

FORMULARIO = "Pesquisa Pública ... Digite os caracteres da imagem (captcha) ..."
RECUSA = "Código de confirmação inválido 1."
SEM_ORGAO = "Informe o código de confirmação."
ACHOU = "SERVIÇOS PRESTADOS AO CIDADÃO: CADASTRO ... nº000100.000300/2026"
VAZIO = "Sua pesquisa pelo termo 004900000300202643 não encontrou nenhum protocolo correspondente."


def test_formulario_nao_e_recusa():
    """O formulário em tela não significa código errado — foi esse o falso negativo."""
    assert _is_captcha_page(FORMULARIO)      # a página REALMENTE tem widget de captcha…
    assert not _captcha_recusado(FORMULARIO)  # …mas o servidor não recusou nada.


def test_recusa_do_servidor_e_detectada():
    assert _captcha_recusado(RECUSA)
    assert _captcha_recusado(SEM_ORGAO)


def test_resultado_real_nao_e_recusa():
    """Busca que ACHOU e busca que veio VAZIA são as duas sucesso de captcha."""
    assert not _captcha_recusado(ACHOU)
    assert not _captcha_recusado(VAZIO)
