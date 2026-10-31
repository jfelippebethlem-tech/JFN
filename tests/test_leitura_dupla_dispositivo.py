# -*- coding: utf-8 -*-
"""Mesma resposta escrita diferente não é briga entre leitores.

`art. 75, VIII` e `Lei nº 14.133/2021, Art. 75º, VIII` são O MESMO dispositivo, e caíam como
discordância porque o `º` vira `O` na normalização e quebra a comparação por substring. Eram **19
das 23 brigas** acumuladas — a maior fonte de ruído na fila de leitura humana.

A comparação certa é por peça (lei, artigo, inciso). E a LEI é o que impede o conserto de virar um
defeito pior: art. 75 da 14.133 e art. 75 da 8.666 são dispositivos DIFERENTES — o primeiro é
dispensa por emergência, o segundo nem existe na mesma matéria. Casar os dois seria fabricar acordo.
"""
from __future__ import annotations

import pytest

from tools.sei_leitura_dupla import _mesmo_dispositivo

IGUAIS = [
    ("art. 75, VIII", "Lei nº 14.133/2021, Art. 75º, VIII"),
    ("art. 79, II", "art. 79, inciso II, da Lei nº 8.666, de 1993"),
    ("art. 75", "Art. 75º da Lei 14.133/2021"),
]
DIFERENTES = [
    ("art. 5, § 2", "Lei nº 14.133/2021 art. 74"),
    ("art. 27", "Art. 65, inciso I, alíneas “a” e “b”, da Lei 8.666"),
    ("art. 42", "art. 57, II da Lei 8.666/1993"),
    ("Lei 8.666, art. 75", "Lei 14.133, art. 75"),          # mesmo artigo, LEI diferente
]


@pytest.mark.parametrize("a,b", IGUAIS)
def test_o_mesmo_dispositivo_escrito_de_dois_jeitos_e_acordo(a, b):
    assert _mesmo_dispositivo(a, b)


@pytest.mark.parametrize("a,b", DIFERENTES)
def test_dispositivos_distintos_continuam_briga(a, b):
    assert not _mesmo_dispositivo(a, b), "casar dispositivos diferentes fabrica acordo — pior que o defeito"
