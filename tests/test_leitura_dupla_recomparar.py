# -*- coding: utf-8 -*-
"""As RÉGUAS MUDAM E AS LEITURAS NÃO.

Cada conserto do comparador feito nesta sessão — ausência concorde, dispositivo por pertinência,
`SEM CONTRATO` = `NAO_CONSTA` — só valia para os processos lidos DEPOIS dele. A tabela virava um
mosaico: 133 linhas medidas por réguas diferentes, somadas no mesmo KPI do painel, que é o vício de
somar o que não se soma.

As duas leituras já estão gravadas (`deterministico` e `ia`). Recomparar custa **zero chamada de
IA** — só reprocessa o que está no banco. Rodado no acervo: **44 das 133 mudaram de veredito**.

Por isso a comparação vive numa função à parte de quem lê: `comparar()` não abre processo, não
chama modelo, não toca a rede.
"""
from __future__ import annotations

import inspect

from tools.sei_leitura_dupla import comparar


def test_comparar_nao_le_nem_chama_ia():
    """Se a comparação voltar a depender de leitura, o `--recomparar` deixa de ser barato e a
    tabela volta ao mosaico."""
    fonte = inspect.getsource(comparar)
    for proibido in ("texto_do_processo", "gerar", "extrair_interpretativo", "extrair_deterministico"):
        assert proibido not in fonte, f"`comparar` passou a depender de {proibido}"


def test_recompara_a_partir_do_que_esta_gravado():
    det = {"contrato": {"valor": "443/2025"}, "dispositivo": {"valor": "art. 75, VIII",
                                                              "alternativas": []}}
    ia = {"estado": "ok", "fatos": {"contrato": "443/2025", "dispositivo": "Lei 14.133/2021, Art. 75º, VIII",
                                    "pregao": "NAO_CONSTA", "valor": "", "favorecido": ""}}
    r = comparar(det, ia, {"tem_ob": False})
    assert set(r["acordo"]) == {"contrato", "dispositivo"}
    assert not r["discordancia"]
    assert "pregao" in r["ausencia_concorde"]
