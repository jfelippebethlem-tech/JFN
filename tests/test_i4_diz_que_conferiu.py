# -*- coding: utf-8 -*-
"""O I4 conferia a hipótese inocente — e continuava escrevendo que ela "precisa ser conferida".

Em 2026-08-04 o detector passou a checar, nos próprios autos, se existe aditivo anterior que não
prorrogou prazo (o que explicaria o ordinal sem vício): **14 dos 23 disparos (61%) caíram**, e
sobraram 6. Mas o texto do achado continuou dizendo *"salvo se houver aditivo anterior … precisa
ser conferida nos autos"* — transferindo ao fiscal um trabalho que o código já tinha feito, e
subestimando a própria conclusão.

Ressalva escrita não é ressalva testada — e o inverso também vale: **ressalva testada não pode
continuar escrita como pendência**.
"""
from __future__ import annotations

import re
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "compliance_agent" / "sei" / "instrumento_assinatura.py"


def test_o_texto_do_i4_declara_que_a_hipotese_foi_conferida():
    src = FONTE.read_text(encoding="utf-8")
    m = re.search(r'"o instrumento se declara \{n\}º termo aditivo(?:.|\n)*?\),', src)
    assert m, "não achei o texto do I4 — o teste precisa ser reescrito junto"
    texto = m.group(0)
    assert "FOI CONFERIDA" in texto
    assert "precisa ser conferida nos autos" not in texto, \
        "o código confere a hipótese; o texto não pode devolvê-la ao fiscal como pendência"
