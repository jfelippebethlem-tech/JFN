# -*- coding: utf-8 -*-
"""O portão de pre-push prometia uma catraca que não estava na lista.

O cabeçalho de `tools/pre_push_gate.sh` diz, sobre as catracas: que pegam captura genérica de
exceção nova, R$ no formato americano e **inventário de rotas fora do golden**. A variável
`CATRACAS` tinha só as duas primeiras.

(A frase acima evita escrever a expressão literal que a catraca de captura genérica procura: ela
conta ocorrências de TEXTO no repositório inteiro, comentários e docstrings inclusive. Este arquivo
citando a expressão duas vezes bastou para bloquear o próprio push que o criou — o que é, em si, a
prova de que a catraca funciona, e um lembrete de que ela mede texto, não código.)

O preço saiu em 2026-08-11: liguei uma rota nova (`/api/fiscal/emergencia_recorrente`), o portão
aprovou o push, e o CI ficou vermelho em `test_inventario_de_rotas_identico_ao_golden` — que é
exatamente o e-mail para o dono que este portão existe para evitar.

E não é caso de "o critério de casamento pegaria": o portão casa testes pelo NOME do arquivo e por
QUEM IMPORTA o módulo tocado, e `test_server_snapshot` não importa `rotas/vinculos`. Rota nova é
justamente onde o critério de import não alcança — por isso ela tem de ser transversal.

Custo medido: 6,6 s. O portão inteiro roda em ~110 s.
"""
from __future__ import annotations

import re
from pathlib import Path

_GATE = Path(__file__).resolve().parent.parent / "tools" / "pre_push_gate.sh"


def _catracas() -> list[str]:
    m = re.search(r'^CATRACAS="([^"]*)"', _GATE.read_text(encoding="utf-8"), re.M)
    assert m, "a variável CATRACAS sumiu do portão"
    return m.group(1).split()


def test_as_catracas_prometidas_no_cabecalho_estao_na_lista():
    c = _catracas()
    assert "tests/test_catraca_excepts.py" in c          # captura genérica de exceção
    assert "tests/test_moeda_padrao_brasileiro.py" in c  # R$ no formato americano
    assert "tests/test_server_snapshot.py" in c          # inventário de rotas fora do golden


def test_toda_catraca_listada_existe():
    """Portão que aponta para arquivo inexistente falha por motivo errado — e o pytest devolve
    erro de coleta, que numa saída longa passa por ruído."""
    raiz = _GATE.resolve().parent.parent
    faltando = [c for c in _catracas() if not (raiz / c).exists()]
    assert not faltando, f"catraca inexistente: {faltando}"
