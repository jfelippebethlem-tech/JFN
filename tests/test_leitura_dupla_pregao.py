# -*- coding: utf-8 -*-
"""A régua perdia o certame por três detalhes de grafia — e todos vieram do texto.

47 casos de `so_ia` no campo `pregao` (a IA acha, a regra não). Abrindo os processos, a régua é que
era estreita, em três pontos que o documento ensina e nenhum palpite alcançaria:

| o que o documento escreve | o que a régua exigia |
|---|---|
| `PREGÃO ELETRÔNICO N.º` (caixa alta) | `[Pp]reg[ãa]o` — resto minúsculo |
| `nº **PE** 008/23`, `nº **SRP** 068/2019` | dígito logo depois do `nº` |
| `008/**23**` | ano de quatro dígitos |

O ano curto só é aceito com a palavra "Pregão" a até 30 caracteres — sem essa âncora, `008/23`
casaria com qualquer fração escrita no processo.

Conferido no acervo depois do conserto: os achados novos são números plausíveis de certame
(`068/2019` é `Pregão Eletrônico SRP nº 068/2019`, lido na fonte), não ruído.
"""
from __future__ import annotations

import pytest

from tools.sei_leitura_dupla import extrair_deterministico

CASOS = [
    ("Ref.: PREGÃO ELETRÔNICO N.º PE 008/23\n", "008/23"),
    ("aquisição via Pregão Eletrônico SRP nº 068/2019, conforme\n", "068/2019"),
    ("Pregão Eletrônico nº 01/2023 homologado\n", "01/2023"),
    ("PREGÃO PRESENCIAL Nº 12/2021 da unidade\n", "12/2021"),
]


@pytest.mark.parametrize("texto,esperado", CASOS)
def test_acha_o_certame_nas_grafias_que_o_documento_usa(texto, esperado):
    assert extrair_deterministico(texto)["pregao"]["valor"] == esperado


def test_ano_curto_sem_a_palavra_pregao_NAO_entra():
    """Sem a âncora, `008/23` casaria com fração, item de tabela ou numeração qualquer."""
    assert not extrair_deterministico("Item 008/23 da planilha de custos.\n")["pregao"]["valor"]


def test_sigla_de_QUATRO_letras_e_sem_o_marcador_de_numero():
    """`EDITAL DE PREGÃO ELETRÔNICO PERP 02/2020` — Pregão Eletrônico para Registro de Preços.

    Dois detalhes de uma vez: a sigla tem QUATRO letras (a régua aceitava 2 ou 3, `PE` e `SRP`) e o
    `nº` NÃO aparece — a sigla vem direto depois do nome da modalidade. Cada um sozinho já custava o
    certame inteiro.
    """
    assert extrair_deterministico(
        "EDITAL DE PREGÃO ELETRÔNICO PERP 02/2020\n")["pregao"]["valor"] == "02/2020"


def test_afrouxar_o_marcador_nao_pode_criar_falso_positivo():
    """Tornar o `nº` opcional aumenta o alcance — e o teste de fronteira continua valendo: sem a
    palavra "Pregão" por perto, número solto não vira certame."""
    assert not extrair_deterministico("Item 008/23 da planilha de custos.\n")["pregao"]["valor"]
