"""T01 (three-way match) não pode AFASTAR o que não verificou.

AFASTADO significa "verifiquei e está ok". Quando o SIAFE 1 não expõe a liquidação (NL), o
teste só consegue olhar o elo RE↔PD — é 2-way, não 3-way. A versão anterior escrevia
"Integridade 3-way NÃO afirmável" na evidência **e devolvia AFASTADO**: texto e status se
contradiziam.

Medido em 31/08/2026 no acervo: 21.485 dos 31.017 itens do T01 (69,3%) caíam no ramo sem NL, e
6.385 deles (20,6% do total) tinham ZERO OBs com cadeia completa — nenhum ponto verificado.
"""
import pytest

from compliance_agent.auditoria_contrato import _t01_3way


def _ob(num, nl="", re="", pd="", status="Contabilizado", valor="100"):
    return {"numero_ob": num, "status": status, "valor": valor, "nl": nl, "re": re, "pd": pd}


def test_sem_nenhuma_liquidacao_e_INDISPONIVEL_nao_afastado():
    """O caso que motivou a correção: 6.385 itens do acervo voltavam AFASTADO sem ter
    verificado ponto algum do three-way."""
    r = _t01_3way({"obs": [_ob("1", re="RE1", pd="PD1"), _ob("2", re="RE2", pd="PD2")]})
    assert r["status"] == "INDISPONIVEL"
    assert "falta a liquidação" in r["evidencia"]
    assert "INDISPONÍVEL ≠ irregular" in r["evidencia"], "não pode virar 'irregular' também"


def test_cobertura_parcial_afasta_mas_declara_o_alcance():
    r = _t01_3way({"obs": [_ob("1", nl="NL1", re="RE1", pd="PD1"),
                           _ob("2", re="RE2", pd="PD2")]})
    assert r["status"] == "AFASTADO"
    assert r["cobertura_3way"] == pytest.approx(0.5)
    assert r["obs_sem_liquidacao"] == 1
    assert "NÃO foi verificado" in r["evidencia"]


def test_cadeia_integra_afasta_sem_ressalva():
    r = _t01_3way({"obs": [_ob("1", nl="NL1", re="RE1", pd="PD1"),
                           _ob("2", nl="NL2", re="RE2", pd="PD2")]})
    assert r["status"] == "AFASTADO"
    assert "íntegra" in r["evidencia"]
    assert "cobertura_3way" not in r, "sem lacuna não há cobertura parcial a declarar"


def test_ob_orfa_continua_indicio():
    """OB sem elo algum é pagamento sem liquidação rastreável — isso é achado, não lacuna."""
    r = _t01_3way({"obs": [_ob("1")]})
    assert r["status"] == "INDICIO" and "órfã" in r["evidencia"]


def test_sem_ob_contabilizada_e_indisponivel():
    """Só OB Contabilizado é pagamento (regra de ouro da casa)."""
    r = _t01_3way({"obs": [_ob("1", status="Anulado")]})
    assert r["status"] == "INDISPONIVEL"


def test_status_nunca_contradiz_a_evidencia():
    """A regressão que se trava aqui: evidência dizendo que não dá para afirmar, com status
    AFASTADO ao lado."""
    for obs in ([_ob("1", re="R", pd="P")],
                [_ob("1", nl="N", re="R", pd="P"), _ob("2", re="R2", pd="P2")],
                [_ob("1", nl="N", re="R", pd="P")]):
        r = _t01_3way({"obs": obs})
        ev = r["evidencia"]
        if "NÃO afirmável" in ev or "não roda" in ev:
            assert r["status"] == "INDISPONIVEL", f"evidência nega, status afirma: {r['status']}"
