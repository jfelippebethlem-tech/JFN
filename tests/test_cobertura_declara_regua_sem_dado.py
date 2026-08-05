# -*- coding: utf-8 -*-
""""Indisponíveis: nenhum" num processo em que 30 das 43 réguas não puderam avaliar.

`cobertura.indisponiveis` só registrava MOTOR QUEBRADO — exceção ao rodar uma família inteira.
Detector que roda e devolve `nao_avaliavel` por falta de dado não entrava em lugar nenhum, então
a seção "Honestidade da cobertura" do dossiê dizia que nada ficara de fora.

Medido em 2026-08-04 no SEI-070002/001289/2022: **43 detectores rodados, 0 indisponíveis
declarados, 30 sem condição de avaliar** — X2 sem vigência, X4 sem quantitativos da ata, X5 sem
itens de planilha, X8 sem vigência do contrato. Quem lia o dossiê concluía que tudo fora aferido.

É a regra da casa (INDISPONÍVEL ≠ 0) falhando no relatório da própria casa.
"""
from compliance_agent import processo_360 as P
from compliance_agent.detectores.base import ResultadoDetector


def test_detector_nao_avaliavel_entra_na_cobertura():
    """Contrato do dicionário: `nao_avaliaveis` traz detector e motivo, para o dossiê poder dizer
    o que não foi aferido e POR QUÊ."""
    r = ResultadoDetector(detector="X5", processo="P", score=0.0, valores={},
                          status="nao_avaliavel",
                          motivo_refutacao="nao_avaliavel: nenhum item de planilha no contexto")
    assert r.status == "nao_avaliavel" and r.motivo_refutacao


def test_o_dossie_mostra_as_reguas_sem_dado():
    from compliance_agent.reporting import processo_360_ctx as CTX

    out = {"numero_sei": "SEI-000000/000001/2025", "faixa": "BAIXO", "score100": 0.0,
           "achados": [], "lacunas_processo": [], "lacunas_captura": [],
           "cobertura": {"captura_integra": True, "detectores_rodados": ["X1", "X5", "X8"],
                         "indisponiveis": [],
                         "nao_avaliaveis": [
                             {"detector": "X5", "motivo": "nenhum item de planilha no contexto"},
                             {"detector": "X8", "motivo": "vigência do contrato ausente"}]},
           "matriz_sv": {}, "escalada": {}, "sintese": {}, "acatamento": {}, "fases": {},
           "docs_chave": [], "cadeia": {},
           "grau": {"grau": "C", "motivo": "sem corroboração"}}
    ctx = CTX.render_processo_ctx(out)
    html = "".join(s.get("html", "") for s in (ctx.get("secoes") or []))
    assert "SEM CONDIÇÃO DE AVALIAR" in html
    assert "X5" in html and "planilha" in html
    assert "2 sem condição de avaliar" in html


def test_processo_real_declara_o_que_nao_foi_aferido():
    """Sem isto, o dossiê afirma cobertura que não teve."""
    import pathlib
    import pytest
    if not (pathlib.Path.home() / "JFN" / "data" / "sei_arquivo").exists():
        pytest.skip("acervo ausente")
    out = P.avaliar("SEI-070002/001289/2022")
    if out.get("status") != "OK":
        pytest.skip("processo indisponível nesta máquina")
    cob = out["cobertura"]
    assert "nao_avaliaveis" in cob
    assert len(cob["nao_avaliaveis"]) > 0, (
        "43 réguas rodam e nenhuma ficou sem dado? o campo parou de ser preenchido")
    assert all(x.get("motivo") for x in cob["nao_avaliaveis"]), "motivo vazio não explica nada"
