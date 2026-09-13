# -*- coding: utf-8 -*-
"""O que o texto cala, a Ordem Bancária já disse.

**46 casos — a maior categoria da fila** — eram `so_regra` no campo `favorecido`. Só que ali o lado
da "regra" não é regex: é a ORDEM BANCÁRIA, que pela regra nº 2 da casa é a verdade sobre quem
recebeu. A IA apenas não achou o CNPJ escrito no processo, e muitos processos não o escrevem.

Mandar isso para a fila de leitura humana é pedir que alguém confira o que a fonte canônica já
confirmou. Não é divergência entre leitores sobre um fato: é o texto sendo silencioso sobre um fato
que está resolvido noutro lugar.

A guarda importa nos dois sentidos — sem OB vinculada, o achado da regra volta a ser `so_regra` e
merece o olho humano, porque aí ninguém confirmou nada.
"""
from __future__ import annotations

from tools.sei_leitura_dupla import comparar

_DET = {"cnpjs": {"valor": "00.801.512/0001-57", "fonte": "ordem bancária", "alternativas": []}}
_IA = {"estado": "ok", "fatos": {"favorecido": "NAO_CONSTA", "contrato": "", "dispositivo": "",
                                 "pregao": "", "valor": ""}}


def test_com_OB_vinculada_o_fato_sai_da_fila_humana():
    r = comparar(_DET, _IA, {"tem_ob": True, "favorecidos": {"00801512000157"}})
    assert "favorecido" not in r["discordancia"]
    assert r["ausencia_concorde"]["favorecido"]["estado"] == "so_fonte_canonica"


def test_SEM_OB_vinculada_continua_pedindo_olho_humano():
    """Sem fonte canônica ninguém confirmou nada — o achado solitário da regra é sinal, não ruído."""
    r = comparar(_DET, _IA, {"tem_ob": False})
    assert r["discordancia"]["favorecido"]["estado"] == "so_regra"
