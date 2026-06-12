# -*- coding: utf-8 -*-
"""
Teste do P3.5 do QA: limpar bullets '- -' (dash duplo) na §9 (análise raciocinada) do relatório
de fornecedor. O LLM às vezes embute o marcador '- ' no próprio item (ou devolve JSON apesar de
pedirmos markdown), e o render re-prefixava '- ' → saía '- - texto'. _normaliza_raciocinio deve
deduplicar (idempotente), sem rede e determinístico.

Como rodar:
    cd ~/JFN && .venv/bin/python -m pytest tests/test_relatorio_raciocinio_bullets.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from compliance_agent.reporting.inteligencia import _normaliza_raciocinio as N  # noqa: E402


def _sem_dash_duplo(txt: str) -> bool:
    import re
    return not any(re.match(r"^\s*(?:[-*•]\s+){2,}", ln) for ln in txt.splitlines())


def test_json_com_dash_embutido_nao_duplica():
    # causa REAL do '- -': JSON cujos itens já começam com '- '
    out = N('["- A concentração de 100%", "- O rating MÉDIO parece subestimado"]')
    assert _sem_dash_duplo(out)
    assert out.splitlines()[0] == "- A concentração de 100%"


def test_texto_livre_com_dash_duplo_colapsa():
    out = N("- - A concentração\n- O rating\n- - Próximos passos")
    assert _sem_dash_duplo(out)
    assert out.splitlines()[0] == "- A concentração"
    assert out.splitlines()[2] == "- Próximos passos"


def test_bullet_unico_limpo_preservado():
    out = N("- A concentração\n- O rating")
    assert out == "- A concentração\n- O rating"


def test_json_dict_achata_sem_dash_duplo():
    out = N('{"merito": "- x relevante", "juridico": "y a verificar"}')
    assert _sem_dash_duplo(out)
    assert set(out.splitlines()) == {"- x relevante", "- y a verificar"}


def test_marcadores_mistos_asterisco_bullet():
    out = N("* * A\n• • B\n- * C")
    assert _sem_dash_duplo(out)
    for ln in out.splitlines():
        assert ln.startswith("- ")


def test_texto_normal_sem_bullets_intacto():
    txt = "Não há OBs na base para emitir parecer; recomenda-se coleta no SIAFE."
    assert N(txt) == txt
