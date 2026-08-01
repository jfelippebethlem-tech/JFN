# -*- coding: utf-8 -*-
"""processo_360 — contrato de saída, 3 baldes sob captura falha, suficiência do emissor."""
import json

import pytest

from compliance_agent import processo_360, sei_recomendacoes

CHAVES = {"numero_sei", "versao", "fases", "docs_chave", "achados", "lacunas_processo",
          "lacunas_captura", "score", "grau", "matriz_sv", "escalada", "cobertura", "llm"}


def _acervo(tmp_path, com_texto=True):
    pasta = tmp_path / "080002_001953_2026"
    (pasta / "texto").mkdir(parents=True)
    docs = [
        {"i": "0", "titulo": "Justificativa de Dispensa Emergencial (90000001)", "fase": "", "tipo": "outros",
         "texto": "texto/000_just_90000001.txt", "chars": 400, "ocr": False, "fotos": []},
        {"i": "1", "titulo": "Parecer Jurídico DIRJUR (90000002)", "fase": "", "tipo": "parecer_juridico",
         "texto": "texto/001_parecer_90000002.txt", "chars": 900, "ocr": False, "fotos": []},
        {"i": "2", "titulo": "Termo de Contrato 215/2024 (90000003)", "fase": "", "tipo": "contrato",
         "texto": "texto/002_contrato_90000003.txt", "chars": 900, "ocr": False, "fotos": []},
        {"i": "3", "titulo": "Nota de Empenho 2026NE00001 (90000004)", "fase": "", "tipo": "empenho",
         "texto": "texto/003_ne_90000004.txt", "chars": 200, "ocr": False, "fotos": []},
    ]
    man = {"processo": "SEI-080002/001953/2026", "origem": "cache", "modalidade": "dispensa",
           "docs": docs, "linha_do_tempo": {}, "lacunas": [], "fotos_total": 0}
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    if com_texto:
        (pasta / "texto" / "000_just_90000001.txt").write_text(
            "Justificativa: contratação emergencial por risco iminente.", encoding="utf-8")
        (pasta / "texto" / "001_parecer_90000002.txt").write_text(
            "Parecer da assessoria jurídica interna. Recomenda-se que seja sanada a pendência "
            "de pesquisa de preços antes da assinatura.", encoding="utf-8")
        (pasta / "texto" / "002_contrato_90000003.txt").write_text(
            "Termo de contrato emergencial. Valor inicial de R$ 1.000.000,00.", encoding="utf-8")
        (pasta / "texto" / "003_ne_90000004.txt").write_text("2026NE00001.", encoding="utf-8")
    return pasta


@pytest.fixture
def sem_motores(monkeypatch):
    """Isola os motores pesados (P/E/J, X, C) — o teste é do ORQUESTRADOR."""
    async def _pej(numero, **kw):
        return {"numero": numero, "status": "OK", "resultados": [], "confirmados": [],
                "nao_avaliaveis": [], "ctx_resumo": {}}
    monkeypatch.setattr(processo_360, "_analisar_pej", _pej)
    monkeypatch.setattr(processo_360, "_rodar_execucao", lambda *a, **k: [])
    monkeypatch.setattr(processo_360, "_rodar_fornecedor", lambda *a, **k: [])
    monkeypatch.setattr(processo_360, "_cnpj_vencedor", lambda *a, **k: None)


def test_contrato_de_saida(tmp_path, sem_motores):
    pasta = _acervo(tmp_path)
    out = processo_360.avaliar_pasta(pasta)
    assert CHAVES <= set(out)
    assert out["versao"] == "360.1"
    assert out["cobertura"]["captura_integra"] is True
    assert isinstance(out["score"], float)
    # dispensa emergencial com parecer só de assessoria interna → suficiência acusa (lição IDESI)
    assert out["acatamento"]["suficiencia"]["veredito"] == "PARECER_DE_EMISSOR_INSUFICIENTE"
    assert any(a.get("origem") == "suficiencia_emissor" for a in out["achados"])


def test_tres_baldes_sob_captura_falha(tmp_path, sem_motores):
    pasta = _acervo(tmp_path, com_texto=False)  # 0 txt no disco → captura NÃO íntegra
    out = processo_360.avaliar_pasta(pasta)
    assert out["cobertura"]["captura_integra"] is False
    assert out["lacunas_processo"] == []          # ausência NÃO vira vício do processo
    assert out["lacunas_captura"]                 # ela é declarada como trabalho NOSSO
    # sem captura íntegra, achados que dependem de ausência não entram no score
    assert all(a.get("origem") != "fases.lacunas" for a in out["achados"])


def test_processo_inexistente_indisponivel():
    out = processo_360.avaliar("SEI-999999/999999/2099")
    assert out["status"] == "INDISPONIVEL"


def test_suficiencia_pge_ok():
    docs = [{"ref": "Parecer", "tipo": "parecer",
             "texto": "Parecer da Procuradoria Geral do Estado — PGE. Aprovado."}]
    s = sei_recomendacoes.suficiencia_parecer(docs, "contratacao_direta")
    assert s["veredito"] == "SUFICIENTE" and s["max_nivel"] == 3


def test_suficiencia_interna_insuficiente_para_emergencia():
    docs = [{"ref": "Parecer", "tipo": "parecer",
             "texto": "Parecer jurídico da assessoria jurídica do órgão."},
            {"ref": "Auditoria", "tipo": "orgao_controle",
             "texto": "Relatório de auditoria interna 0793/2024."}]
    s = sei_recomendacoes.suficiencia_parecer(docs, "contratacao_direta")
    assert s["veredito"] == "PARECER_DE_EMISSOR_INSUFICIENTE"
    assert s["max_nivel"] == 2 and s["exigido"] == 3


def test_suficiencia_sem_parecer():
    s = sei_recomendacoes.suficiencia_parecer([{"ref": "Despacho", "tipo": "despacho",
                                                "texto": "Encaminhe-se."}], "geral")
    assert s["veredito"] == "SEM_PARECER_LOCALIZADO"


def test_score_processo_recebe_shape_valido(tmp_path, sem_motores, monkeypatch):
    """O agregador oficial (base.score_processo) é chamado com ResultadoDetector reais."""
    from compliance_agent.detectores.base import ResultadoDetector
    visto = {}
    orig = processo_360.score_processo

    def spy(resultados, pesos=None):
        visto["res"] = list(resultados)
        return orig(resultados, pesos)
    monkeypatch.setattr(processo_360, "score_processo", spy)
    processo_360.avaliar_pasta(_acervo(tmp_path))
    assert all(isinstance(r, ResultadoDetector) for r in visto["res"])
