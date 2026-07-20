# -*- coding: utf-8 -*-
"""Catálogo canônico de vícios — knowledge/catalogo_vicios.py.

O valor do catálogo é a INTEGRIDADE dos ponteiros: cada vício aponta para detector, red flag do Lex,
padrão de fraude, cláusula do E7 e súmula que EXISTEM de verdade. `validar()` confere tudo; aqui o
teste falha listando os ponteiros quebrados (mensagem completa, não só o count).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_catalogo_vicios.py -q
"""
from __future__ import annotations

from compliance_agent.knowledge import catalogo_vicios as cv


def test_catalogo_integro_todo_ponteiro_resolve():
    problemas = cv.validar()
    assert not problemas, "ponteiros quebrados no catálogo:\n" + "\n".join(problemas)


def test_cobre_as_cinco_fases():
    r = cv.resumo()
    assert r["total"] >= 35
    for fase in cv.FASES:
        assert r["por_fase"][fase] >= 3, f"fase '{fase}' com cobertura magra no catálogo"


def test_lacunas_sao_declaradas_nao_escondidas():
    # a honestidade do catálogo: o que não roda sozinho está DECLARADO como lacuna/parcial
    ids_lacuna = {v.id for v in cv.lacunas()}
    # deserto_fracassado_dirigido saiu das lacunas em 2026-07-20 (detector E8)
    assert "deserto_fracassado_dirigido" not in ids_lacuna
    assert cv.obter("deserto_fracassado_dirigido").detectores == ("E8",)
    assert "proposta_dia_nao_util" in ids_lacuna  # segue lacuna: falta timestamp de envio
    assert all(v.descricao for v in cv.lacunas())


def test_apis_de_consulta():
    assert cv.obter("fracionamento_despesa").detectores == ("P4",)
    assert {v.id for v in cv.por_detector("E7")} >= {"clausula_restritiva_combinada", "vigencia_excessiva"}
    assert cv.por_clausula("faturamento_minimo")[0].id == "faturamento_minimo_exigido"
    assert cv.obter("nao_existe") is None


def test_vicios_novos_da_pesquisa_2026_07_20_presentes():
    # incorporações do redflags.eu/ALICE (2026-07-20): homologado acima do estimado (art. 59 III),
    # faturamento mínimo (rol do art. 69), vigência excessiva (arts. 106-111)
    for vid in ("homologado_acima_estimado", "faturamento_minimo_exigido", "vigencia_excessiva"):
        v = cv.obter(vid)
        assert v is not None and v.status == "coberto", f"{vid} deveria estar coberto"
        assert v.teste_objetivo, f"{vid} deveria ter teste objetivo"
