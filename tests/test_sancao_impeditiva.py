# -*- coding: utf-8 -*-
"""A régua única do que VEDA contratar — e o SQL equivalente, para não voltarem a divergir."""
from __future__ import annotations

import pytest

from compliance_agent.sancao_impeditiva import (RADICAIS_IMPEDITIVOS, SQL_IMPEDITIVA,
                                                e_impeditiva)


@pytest.mark.parametrize("cat", [
    "Impedimento/proibição de contratar com prazo determinado",
    "Suspensão", "suspensao temporaria",
    "Declaração de Inidoneidade sem prazo determinado", "inidônea",
    "Proibição de contratar com o Poder Público",
])
def test_impeditivas(cat):
    assert e_impeditiva(cat) is True


@pytest.mark.parametrize("cat", [
    "Multa", "multa administrativa",
    "Publicação extraordinária da decisão condenatória",
    "Perdimento de bens", None, "", "   ",
])
def test_nao_impeditivas(cat):
    assert e_impeditiva(cat) is False


def test_desconhecida_nao_presume_gravidade():
    """Sem saber qual é a sanção, a casa não afirma que ela impede."""
    assert e_impeditiva("categoria que ninguém viu antes") is False


def test_sql_cobre_os_mesmos_radicais():
    for r in RADICAIS_IMPEDITIVOS:
        assert f"'%{r}%'" in SQL_IMPEDITIVA
    assert SQL_IMPEDITIVA.startswith("(") and SQL_IMPEDITIVA.endswith(")")


def test_os_consumidores_usam_a_regua_unica():
    """cruzamentos_intel e nucleo/adaptador_db tinham cópias idênticas em SQL. O teste existe para
    que a próxima edição em um não passe sem o outro."""
    from compliance_agent.cruzamentos_intel import _SQL_IMPEDITIVA
    assert _SQL_IMPEDITIVA == SQL_IMPEDITIVA
