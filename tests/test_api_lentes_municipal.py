"""A rota de lentes passa a servir a esfera MUNICIPAL sem alterar a estadual.

O que se trava aqui: (1) a esfera estadual continua idêntica; (2) a municipal vem sempre
acompanhada do denominador — contagem de lente municipal sem `universo_contratual` não se lê,
porque os R$ 89,62 bi brutos incluem folha, dívida e precatório.
"""
import json
from pathlib import Path

import pytest

from rotas.investigacao import api_lentes

ESTADO = Path("data/lentes_estado.json")


def _corpo(resp):
    return json.loads(resp.body)


@pytest.fixture(autouse=True)
def exige_estado():
    if not ESTADO.exists():
        pytest.skip("lentes não materializadas nesta máquina")


def test_estadual_e_o_padrao_e_nao_mudou():
    d = _corpo(api_lentes())
    assert d["ok"] and d["esfera"] == "estadual"
    assert "lentes" in d and "universo_contratual" not in d


def test_municipal_traz_o_denominador():
    d = _corpo(api_lentes(esfera="municipal"))
    assert d["esfera"] == "municipal"
    u = d["universo_contratual"]
    assert u["contratual"]["pago"] > 0
    assert 0 < u["fracao_do_bruto"] < 1, "o contratual é uma FRAÇÃO do bruto, nunca o bruto"
    assert u["contratual"]["pago"] < u["bruto"]["pago"]


def test_municipal_devolve_prevalencia_em_toda_lente():
    """Contagem sem denominador não diz se o sinal discrimina."""
    for nome, v in _corpo(api_lentes(esfera="municipal"))["lentes"].items():
        assert "prevalencia" in v, nome
        assert "universo" in v, nome
        if v.get("n") is None:
            assert v["prevalencia"] is None, f"{nome}: n nulo com prevalência numérica"


def test_ressalvados_e_inconclusivos_sao_contados_e_nao_somem():
    """O que foi qualificado continua na conta — sumir esconderia o caso que muda de figura."""
    lentes = _corpo(api_lentes(esfera="municipal"))["lentes"]
    assert lentes["fornecedor_quase_exclusivo"]["n_ressalvados"] > 0
    assert "n_inconclusivos" in lentes["sancao_de_efeito_amplo"]


def test_lente_municipal_desconhecida_devolve_404_com_a_lista():
    r = api_lentes(lente="nao_existe", esfera="municipal")
    assert r.status_code == 404
    assert _corpo(r)["disponiveis"], "404 tem de dizer o que existe"


def test_filtro_por_lente_municipal():
    d = _corpo(api_lentes(lente="me_epp_acima_do_teto", esfera="municipal"))
    assert list(d["lentes"]) == ["me_epp_acima_do_teto"]


def test_top_limita_o_topo_sem_mexer_no_n():
    d = _corpo(api_lentes(lente="liquidado_sem_pagamento", esfera="municipal", top=3))
    v = d["lentes"]["liquidado_sem_pagamento"]
    assert len(v["topo"]) <= 3
    assert v["n"] > 3, "`n` é o total apurado, não o tamanho da amostra devolvida"
