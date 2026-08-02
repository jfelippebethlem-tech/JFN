# -*- coding: utf-8 -*-
"""A fila do 360 tem de seguir a rubrica VIGENTE, não uma versão fixada no shell.

Em 2026-08-02 o `sweep_360.sh` filtrava `rubrica_versao='2'` hardcoded. Quando a rubrica virou
v3 (ressalva de competência ≠ esquiva), o sweep passou a considerar "já julgado" quem só tinha
veredito da rubrica velha — 389 processos ficariam de fora do re-julgamento, em silêncio. Este
teste falha se alguém voltar a cravar o número.
"""
import re
from pathlib import Path

from compliance_agent.sei.doc_juizo import RUBRICA_VERSAO

SWEEP = Path(__file__).resolve().parents[1] / "tools" / "sweep_360.sh"


def test_sweep_nao_crava_versao_de_rubrica_no_sql():
    txt = SWEEP.read_text(encoding="utf-8")
    cravado = re.search(r"rubrica_versao\s*=\s*'(\d+)'", txt)
    assert not cravado, (
        f"versão de rubrica cravada no sweep ('{cravado.group(1) if cravado else ''}') — "
        "usar a constante RUBRICA_VERSAO do doc_juizo")


def test_sweep_importa_a_constante_vigente():
    txt = SWEEP.read_text(encoding="utf-8")
    assert "RUBRICA_VERSAO" in txt, "o sweep precisa ler a rubrica vigente do módulo"
    assert "from compliance_agent.sei.doc_juizo import RUBRICA_VERSAO" in txt


def test_constante_e_string_simples_para_casar_com_a_coluna():
    """A coluna `rubrica_versao` é TEXT: a constante tem de ser str, senão o filtro casa vazio."""
    assert isinstance(RUBRICA_VERSAO, str) and RUBRICA_VERSAO.isdigit()
