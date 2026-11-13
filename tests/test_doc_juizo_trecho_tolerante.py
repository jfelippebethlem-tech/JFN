from compliance_agent.sei.doc_juizo import _trecho_confere

TEXTO = ('AUTORIZO a despesa referente ao "Termo de Ajuste de Contas" — valor de R$ 1.234,56, '
         'conforme Nota Fiscal nº 58044, dotação 2026 33903900.')


def test_aspas_curvas_e_travessao_nao_reprovam():
    assert _trecho_confere("referente ao “Termo de Ajuste de Contas” - valor de R$ 1.234,56", TEXTO)


def test_reticencias_aceitam_pedacos_na_ordem():
    assert _trecho_confere("AUTORIZO a despesa ... conforme Nota Fiscal nº 58044", TEXTO)
    assert not _trecho_confere("conforme Nota Fiscal nº 58044 ... AUTORIZO a despesa", TEXTO)   # fora de ordem


def test_palavra_que_nao_esta_no_documento_continua_reprovando():
    assert not _trecho_confere("AUTORIZO a despesa referente ao contrato emergencial", TEXTO)
    assert not _trecho_confere("AUTORIZO ... 58", TEXTO)        # pedaço curto demais não prova nada
    assert not _trecho_confere("", TEXTO)
