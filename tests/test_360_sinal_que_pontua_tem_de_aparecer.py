# -*- coding: utf-8 -*-
"""Sinal que PONTUA tem de APARECER — senão a fila mostra processo vazio no topo.

Medido em 2026-08-03, depois de reavaliar o acervo: **14 processos com faixa EXTREMO e ZERO
achados**, um deles com score 93,6. Rastreando um: quem pontuava eram dois detectores de
FORNECEDOR (C9 com score 1,0 e C3/C5 com 0,85), que entram no `score_processo` mas nunca viravam
achado do processo. O fiscal abria o item mais alto da fila e não via nada escrito.

Pior efeito, medido na mesma passada: o processo que eu li à mão e cujos NOVE achados confirmei
um a um ficava em 99,3 — **abaixo** de processos com um único achado, porque o score era dominado
por sinais invisíveis. A fila não ordenava por gravidade.

Regra: todo resultado CONFIRMADO que entra no score entra também na lista de achados, com a
origem declarada. O que não aparece no entregável não existe.
"""
from compliance_agent import processo_360 as P
from compliance_agent.detectores.base import ResultadoDetector


def _rd(det, score, expl=""):
    return ResultadoDetector(detector=det, processo="X", score=score, valores={},
                             evidencia=[], explicacao_inocente=expl, status="confirmado")


def test_detector_de_fornecedor_confirmado_vira_achado():
    achados = P.achados_de_fornecedor([_rd("C9", 1.0, "97% do faturamento vem de TAC")])
    assert len(achados) == 1
    a = achados[0]
    assert a["origem"] == "fornecedor" and a["codigo"] == "C9"
    assert a["gravidade"] in ("media", "alta", "critica")
    assert a["diz"]


def test_detector_nao_confirmado_nao_vira_achado():
    r = _rd("C3", 0.9)
    r.status = "nao_avaliavel"
    assert P.achados_de_fornecedor([r]) == []


def test_detector_refutado_nao_vira_achado():
    r = _rd("C3", 0.9)
    r.refutada = True
    assert P.achados_de_fornecedor([r]) == []


def test_a_gravidade_acompanha_o_score_do_detector():
    fraco = P.achados_de_fornecedor([_rd("C1", 0.3)])[0]["gravidade"]
    forte = P.achados_de_fornecedor([_rd("C1", 1.0)])[0]["gravidade"]
    assert ("media", "critica") == (fraco, forte) or fraco != forte


def test_o_achado_diz_que_e_do_FORNECEDOR_nao_do_processo():
    """Perfil do contratado é indício sobre a EMPRESA; confundir com vício do processo seria
    imputar ao gestor o que é característica de quem ele contratou."""
    a = P.achados_de_fornecedor([_rd("C9", 1.0)])[0]
    assert "fornecedor" in a["diz"].lower() or "contratad" in a["diz"].lower()


def test_achado_de_fornecedor_nao_e_contado_duas_vezes_no_score():
    """O detector já está em `resultados`; virar sinal sintético também inflaria o score."""
    from pathlib import Path as _P
    src = _P(P.__file__).read_text(encoding="utf-8")
    assert 'if origem == "fornecedor":\n            continue' in src, (
        "o achado de fornecedor voltou a ser convertido em sinal sintético")


def test_explicacao_inocente_nao_vira_o_texto_do_achado():
    """Medido: o item saía escrito 'FALSO POSITIVO a descartar' — que é o CONTRA-argumento do
    detector, não a acusação. Ela fica em campo próprio, rotulada."""
    a = P.achados_de_fornecedor([_rd("C3/C5", 0.85, "FALSO POSITIVO a descartar (spread normal)")])[0]
    assert "FALSO POSITIVO" not in a["diz"]
    assert a["explicacao_inocente"] == "FALSO POSITIVO a descartar (spread normal)"
