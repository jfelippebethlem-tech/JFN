# -*- coding: utf-8 -*-
"""Testes da §1-I (PAINEL DE DETECTORES do spec de licitações) do relatório de órgão. SEM DuckDB/LLM e SEM
rodar o orquestrador real: `detectores.rodar_orgao` é STUBADO via monkeypatch com uma lista de
`ResultadoDetector` (1 confirmado + 1 descartado + 1 nao_avaliavel). O teste exercita o render, a contagem
honesta dos afastados/indisponíveis, a entrada do confirmado no raciocínio (_fatos_orgao) e a degradação
honesta para INDISPONÍVEL quando o orquestrador quebra (a seção NÃO some)."""
from compliance_agent.detectores.base import ResultadoDetector
from compliance_agent.reporting import inteligencia_orgao as io


def _stub_resultados():
    """1 confirmado (J1, com evidência + defesa inocente) + 1 descartado (refutado pela exculpatória) +
    1 nao_avaliavel (LLM/dado ausente)."""
    confirmado = ResultadoDetector(
        detector="J1", processo="133100", score=0.85, status="confirmado",
        valores={"share": 57.0}, explicacao_inocente="Mercado restrito de obras explica parte da concentração.",
    )
    confirmado.add_evidencia("grafo_cartel", "Grupo ALFA concentra 57% do valor pago pela UG")
    descartado = ResultadoDetector(
        detector="J2", processo="133100", score=0.6, status="descartado", refutada=True,
        motivo_refutacao="checagem inversa refutou: dispersão de preços compatível com mercado",
    )
    nao_avaliavel = ResultadoDetector(
        detector="P4", processo="133100", status="nao_avaliavel",
        motivo_refutacao="nao_avaliavel: dado de fracionamento indisponível",
    )
    return [confirmado, descartado, nao_avaliavel]


def _render(ctx):
    L = []
    io._secao_painel_detectores_md(L.append, ctx)
    return "\n".join(L)


def test_helper_usa_orquestrador_stubado(monkeypatch):
    """O helper _painel_detectores_orgao NÃO toca DuckDB/LLM: usa rodar_orgao stubado e normaliza a saída."""
    monkeypatch.setattr("compliance_agent.detectores.rodar_orgao",
                        lambda ug, **kw: _stub_resultados())
    pd = io._painel_detectores_orgao("133100")
    assert pd["ok"] is True
    assert pd["n_total"] == 3
    assert pd["n_confirmados"] == 1
    assert pd["n_descartados"] == 1
    assert pd["n_nao_avaliaveis"] == 1
    assert pd["confirmados"][0]["detector"] == "J1"


def test_secao_surfa_confirmado_e_conta_afastados_indisponiveis(monkeypatch):
    monkeypatch.setattr("compliance_agent.detectores.rodar_orgao",
                        lambda ug, **kw: _stub_resultados())
    pd = io._painel_detectores_orgao("133100")
    md = _render({"painel_detectores": pd})
    # cabeçalho da seção
    assert "## 1-I." in md and "PAINEL DE DETECTORES" in md
    # confirmado surfado no topo (detector + evidência + defesa visível)
    assert "J1" in md
    assert "Grupo ALFA concentra 57%" in md
    assert "Mercado restrito de obras" in md  # defesa inocente VISÍVEL
    # contagem honesta dos afastados/indisponíveis em 1 linha
    assert "1** afastado" in md  # n_descartados
    assert "1** indisponível" in md  # n_nao_avaliaveis
    assert "INDISPONÍVEL ≠ ausência de indício" in md
    # detectores descartado/nao_avaliavel NÃO viram alarme no topo
    assert "🔴 descartado" not in md


def test_fato_confirmado_entra_no_raciocinio(monkeypatch):
    monkeypatch.setattr("compliance_agent.detectores.rodar_orgao",
                        lambda ug, **kw: _stub_resultados())
    pd = io._painel_detectores_orgao("133100")
    ctx = {"nome": "ITERJ — UG X", "ug": "133100",
           "pagamentos": {"tem_dados": True, "total_geral": 10_000_000.0, "n_geral": 30,
                          "n_fornecedores": 1,  # nº de CNPJs distintos (off-by-one §1/§3 — cont.30 306518f)
                          "por_favorecido_geral": {"ALFA": 5_700_000.0},
                          "hhi": {"indice": 1200.0, "nivel": "ALTO", "top_share": 57.0},
                          "anos": [], "por_ano": {}},
           "painel_detectores": pd}
    fatos = io._fatos_orgao(ctx)
    assert "Painel de detectores" in fatos
    assert "J1" in fatos and "CONFIRMADO" in fatos
    # não duplica a tabela de concentração-grupo da §1-H: referencia, não repete
    assert "sem" in fatos.lower() and "duplica" in fatos.lower()


def test_indisponivel_honesto_secao_nao_some(monkeypatch):
    """rodar_orgao quebrando → painel INDISPONÍVEL honesto; a seção NÃO some (mantém cabeçalho + ressalva)."""
    def _boom(ug, **kw):
        raise RuntimeError("DuckDB offline")
    monkeypatch.setattr("compliance_agent.detectores.rodar_orgao", _boom)
    pd = io._painel_detectores_orgao("133100")
    assert pd["ok"] is False
    md = _render({"painel_detectores": pd})
    # a seção continua existindo (cabeçalho) e informa INDISPONÍVEL — não some
    assert "## 1-I." in md and "PAINEL DE DETECTORES" in md
    assert "INDISPONÍVEL" in md
    assert "INDISPONÍVEL não é prova de ausência de indício" in md
