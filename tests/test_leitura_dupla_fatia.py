# -*- coding: utf-8 -*-
"""Rodar em paralelo sem ler o mesmo processo duas vezes.

A leitura dupla é presa a REDE (a chamada de IA), não a CPU: com um lote só a VM fica em load 1,5 e
o acervo de 2.357 processos levaria ~4 dias. O caminho óbvio — abrir dois lotes — tem uma armadilha
silenciosa: os dois chamam `_pendentes` e recebem A MESMA lista, gastando chamada de IA em dobro
pelo mesmo processo e gravando um por cima do outro.

A fatia `i/n` reparte de forma determinística. **As fatias têm de partir juntas**: cada processo
calcula a fila no seu próprio início, então uma fatia lançada depois já veria a fila sem o que a
outra gravou, e as bordas deslocariam.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools.sei_leitura_dupla import _pendentes


@pytest.fixture
def acervo(tmp_path, monkeypatch):
    for i in range(1, 13):
        d = tmp_path / f"030001_{i:06d}_2024" / "texto"
        d.mkdir(parents=True)
        (d / "a.txt").write_text("x" * (2000 - i), encoding="utf-8")   # tamanhos distintos
    monkeypatch.setattr("tools.sei_leitura_dupla._ARQ", tmp_path)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sei_leitura_dupla (numero_sei TEXT PRIMARY KEY, ia TEXT)")
    return con


def test_as_fatias_nao_se_sobrepoem_e_cobrem_a_fila(acervo):
    fila = _pendentes(acervo, 12)
    a, b = fila[0::2], fila[1::2]
    assert not set(a) & set(b), "duas fatias lendo o mesmo processo = chamada de IA em dobro"
    assert set(a) | set(b) == set(fila), "fatia que perde processo deixa buraco no acervo"


def test_a_fila_e_estavel_entre_chamadas(acervo):
    """Se a ordem variasse entre as duas chamadas, as fatias se cruzariam mesmo sem sobreposição
    aparente — a repartição depende de `_pendentes` devolver sempre a mesma sequência."""
    assert _pendentes(acervo, 12) == _pendentes(acervo, 12)
