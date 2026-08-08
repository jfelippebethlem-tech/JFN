# -*- coding: utf-8 -*-
"""A fila de recaptura tem de ordenar pelo BURACO MEDIDO — o slot é escasso demais para sorteio.

O CUSTO REAL DA ORDEM. A recaptura roda ~1 vez a cada 3 horas e cabe em 2 processos por passada,
porque o custo é do login e da carga da árvore, não do número de documentos. São ~16 processos por
dia sobre uma fila de 1.516. Nessa cadência, a ORDEM não é detalhe de apresentação: é o que decide
se a passada fecha dois processos ou se queima o slot num gigante que estoura e não entrega nada
(medido: o de 956 documentos fez exatamente isso e travou a passada inteira).

O DEFEITO, medido em 2026-08-07. Enquanto o arquivo não sabia o tamanho da árvore, o teto de coleta
entrava com `faltam: 0` — um MARCADOR de ignorância, não uma medida — e a fila ordenava por
`faltam` crescente. Resultado: processos a 39 de 55 e 40 de 45 documentos encabeçavam a fila
empatados em zero, junto com 26 pastas VAZIAS cujo tamanho ninguém conhecia, enquanto casos a UM
documento do fim esperavam atrás. Depois que `docs_na_arvore` passou a existir, manter o zero seria
jogar fora o número que acabara de ser conquistado.

Duas regras, e as duas nasceram de medição:
1. Buraco medido ordena pelo tamanho — menor primeiro, porque é onde o slot rende.
2. Tamanho DESCONHECIDO vai para o fim. Zero por ignorância não é "quase pronto": arquivo vazio
   pode esconder 3 documentos ou 900, e tratá-lo como o menor é convidar o gigante para a frente.
"""
from __future__ import annotations

import pytest

from tools import sweep_recaptura_integral as R


def _fila(itens):
    """Aplica a mesma ordenação da ferramenta a uma lista construída à mão."""
    return sorted(itens, key=lambda x: (bool(x.get("faltam_desconhecido")), x["faltam"]))


def test_menor_buraco_medido_vem_primeiro():
    fila = _fila([
        {"numero": "grande", "faltam": 667, "faltam_desconhecido": False},
        {"numero": "quase", "faltam": 1, "faltam_desconhecido": False},
        {"numero": "medio", "faltam": 16, "faltam_desconhecido": False},
    ])
    assert [x["numero"] for x in fila] == ["quase", "medio", "grande"]


def test_tamanho_desconhecido_vai_para_o_fim():
    """Zero por ignorância não pode competir com zero por medição."""
    fila = _fila([
        {"numero": "vazio", "faltam": 0, "faltam_desconhecido": True},
        {"numero": "quase", "faltam": 1, "faltam_desconhecido": False},
        {"numero": "grande", "faltam": 667, "faltam_desconhecido": False},
    ])
    assert fila[0]["numero"] == "quase"
    assert fila[-1]["numero"] == "vazio", (
        "arquivo de tamanho desconhecido voltou a encabeçar a fila — é o convite para o gigante "
        "que estoura o slot e não entrega nada")


def test_a_ferramenta_usa_essa_ordem():
    """Prova de que a regra acima é a da ferramenta, não uma reescrita do teste."""
    fonte = R.__file__
    with open(fonte, encoding="utf-8") as f:
        texto = f.read()
    assert 'key=lambda x: (bool(x.get("faltam_desconhecido")), x["faltam"])' in texto, (
        "a ordenação da fila mudou sem que este teste mudasse junto — se foi deliberado, reescreva "
        "a regra aqui com o motivo")


def test_arquivo_vazio_e_declarado_desconhecido():
    """`n_docs == 0` produzia `faltam = 0 - 0 = 0`: verdadeiro e inútil.

    26 pastas sem um único documento encabeçavam a fila como quase-completas.
    """
    with open(R.__file__, encoding="utf-8") as f:
        texto = f.read()
    assert "incerto = teto or n_docs == 0" in texto, (
        "arquivo vazio voltou a ser tratado como buraco de tamanho zero")


def test_o_buraco_real_substitui_o_marcador_quando_conhecido():
    """Com `faltam_capturar` no gate, a fila não pode mais usar o zero de ignorância."""
    with open(R.__file__, encoding="utf-8") as f:
        texto = f.read()
    assert 'ev.get("faltam_capturar")' in texto, (
        "a fila voltou a ignorar o tamanho da árvore que o manifesto agora declara")


@pytest.mark.parametrize("faltam,esperado", [(0, True), (5, False)])
def test_fila_real_nao_poe_desconhecido_na_frente(faltam, esperado):
    """Controle sobre a fila DE VERDADE: nenhum item de tamanho desconhecido antes de um medido."""
    itens = R.fila()
    if not itens:
        pytest.skip("acervo vazio neste ambiente")
    primeiro_medido = next((i for i, x in enumerate(itens)
                            if not x.get("faltam_desconhecido")), None)
    primeiro_incerto = next((i for i, x in enumerate(itens)
                             if x.get("faltam_desconhecido")), None)
    if primeiro_medido is None or primeiro_incerto is None:
        pytest.skip("fila sem os dois tipos neste ambiente")
    assert primeiro_medido < primeiro_incerto
