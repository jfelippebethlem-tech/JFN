# -*- coding: utf-8 -*-
"""A latência não cresce com o texto: ela desaba num precipício.

Medido no provedor, com o mesmo prompt e tamanhos crescentes:

| texto enviado | tempo | resposta |
|---|---:|---:|
| 40.000 chars | 1,6 s | 170 chars (JSON completo) |
| 60.000 chars | 18,1 s | 170 chars |
| 120.000 chars | **452,5 s** | 25 chars (amputada) |

Acima de ~100k o modelo degrada e devolve quase nada, então mandar o processo inteiro numa golada é
mais lento **e** pior — pagavam-se 9 minutos por uma resposta cortada. Ler em janelas de 40k levou o
processo de ~15 min para **48 s**.

Antes disso eu havia atribuído a lentidão ao PARALELISMO das duas fatias. Estava errado: a fatia
única sozinha continuou lenta, e a medição direta mostrou que a causa era o tamanho do prompt.
Palpite sobre causa não substitui medir a causa.
"""
from __future__ import annotations

import json

from tools.sei_leitura_dupla import _JANELA, extrair_interpretativo


def test_a_janela_fica_abaixo_do_precipicio():
    assert _JANELA <= 60_000, "acima disso a chamada passa de segundos para minutos"


def test_para_na_primeira_janela_que_responde_o_essencial():
    """Documento administrativo repete o cabeçalho: se o trecho 1 já traz os fatos, varrer o resto
    é pagar chamada de IA por nada."""
    chamadas = []

    def gerar(prompt, _sis):
        chamadas.append(prompt)
        return json.dumps({"contrato": "443/2025", "dispositivo": "art. 75, VIII",
                           "pregao": "NAO_CONSTA", "valor": "1,00", "favorecido": "NAO_CONSTA"})

    r = extrair_interpretativo("x" * (_JANELA * 4), "p", gerar=gerar)
    assert r["estado"] == "ok"
    assert len(chamadas) == 1, f"varreu {len(chamadas)} janelas tendo achado tudo na primeira"


def test_segue_para_a_proxima_janela_quando_o_trecho_nao_responde():
    """A guarda não pode virar desistência: trecho mudo tem de fazer o leitor avançar, senão o
    processo inteiro é julgado pelo seu cabeçalho."""
    respostas = ["{}", "{}", json.dumps({"contrato": "443/2025", "dispositivo": "art. 75",
                                         "pregao": "NAO_CONSTA"})]
    chamadas = []

    def gerar(prompt, _sis):
        chamadas.append(prompt)
        return respostas[min(len(chamadas) - 1, len(respostas) - 1)]

    r = extrair_interpretativo("x" * (_JANELA * 3), "p", gerar=gerar)
    assert len(chamadas) == 3
    assert r["fatos"]["contrato"] == "443/2025"
