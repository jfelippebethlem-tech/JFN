"""Um nível de risco só, escrito de um jeito só.

Nasceu de um defeito de DADO medido no acervo (25/07/2026): `sei_ficha` e `sei_arvore`
guardavam 2.465 `medio` e 566 `médio` — a mesma categoria em duas grafias, porque o prompt
pede `baixo|medio|alto` mas o modelo acentua em 15% das vezes e ninguém normalizava na
entrada. Dois consumidores contornavam (`correlacao_sei`, `inteligencia_orgao`); outros
quatro não, e para eles 566 processos nao existiam.
"""
import pytest

from tools.sei_depurar_db import nivel_risco_norm


@pytest.mark.parametrize("entrada,esperado", [
    ("medio", "medio"), ("médio", "medio"), ("MÉDIO", "medio"), ("  Médio  ", "medio"),
    ("media", "medio"), ("média", "medio"), ("moderado", "medio"), ("medium", "medio"),
    ("baixo", "baixo"), ("Baixa", "baixo"), ("LOW", "baixo"),
    ("alto", "alto"), ("ALTA", "alto"), ("elevado", "alto"), ("high", "alto"),
])
def test_sinonimos_colapsam_num_nivel_so(entrada, esperado):
    assert nivel_risco_norm(entrada) == esperado


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_vazio_continua_vazio(vazio):
    """Ausência não vira nível — INDISPONÍVEL ≠ baixo."""
    assert nivel_risco_norm(vazio) == ""


def test_desconhecido_nao_vira_palpite():
    """Sinônimo que não conhecemos passa adiante limpo, sem ser chutado para uma categoria."""
    assert nivel_risco_norm("  CRÍTICO ") == "crítico"
    assert nivel_risco_norm("indeterminado") == "indeterminado"


def test_as_tres_categorias_sao_fechadas_entre_si():
    """Nenhum sinônimo cai na categoria errada — o teste que pega uma tabela mal editada."""
    vistos = {nivel_risco_norm(x) for x in ("baixo", "baixa", "low")}
    assert vistos == {"baixo"}
    vistos = {nivel_risco_norm(x) for x in ("medio", "médio", "media", "média", "medium", "moderado")}
    assert vistos == {"medio"}
    vistos = {nivel_risco_norm(x) for x in ("alto", "alta", "high", "elevado")}
    assert vistos == {"alto"}
