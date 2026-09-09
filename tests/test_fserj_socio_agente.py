# -*- coding: utf-8 -*-
"""Graduação do sócio-agente (FSERJ direto / SES vinculado / outro) e peso do nome (homônimo)."""
from __future__ import annotations

from tools.fserj_socio_agente import graduar, peso_nome


def test_graduacao_por_ente():
    assert graduar("FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO", "DIRETOR ASSISTENCIAL", "CARGO COMISSAO") == "🔴"
    assert graduar("SECRETARIA DE ESTADO DE SAUDE", "MÉDICO LEI 7946'18", "EFETIVO") == "🟡"
    assert graduar("SECRETARIA DE ESTADO DE POLICIA MILITAR", "SUBTENENTE PM", "EFETIVO") == "⚪"
    assert graduar(None, None, None) == "⚪"
    assert graduar("PREFEITURA DO RIO — RioSaúde (RS/PRE)", "", "PCRJ") == "⚪"   # saúde MUNICIPAL não é SES


def test_peso_do_nome_separa_homonimo_provavel():
    assert peso_nome("VANESSA TAVARES MANHAES") == "forte"
    assert peso_nome("WALTER CHAMOSCHINE FERNANDES") == "forte"
    assert peso_nome("JOSE CARLOS DOS SANTOS") == "forte"   # 3 tokens distintivos
    assert peso_nome("MARCOS RIBEIRO") == "fraco"
