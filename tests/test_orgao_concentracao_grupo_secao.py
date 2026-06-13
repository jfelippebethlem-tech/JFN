# -*- coding: utf-8 -*-
"""Testes da seção 1-H (concentração OCULTA por grupo econômico = cartel/concorrência fictícia) do
relatório de órgão. SEM rede/DB e SEM rodar o detector real (DuckDB na DB de 1,2GB): o detector
`grafo_cartel.concentracao_por_grupo` é STUBADO via monkeypatch; o teste exercita o render e a entrada
do sinal no raciocínio (_fatos_orgao)."""
from compliance_agent.reporting import inteligencia_orgao as io


# Stub do retorno de concentracao_por_grupo: 1 grupo multi-CNPJ de 10 CNPJs (8 raízes) concentrando 57%.
_STUB_INDICIO = {
    "ug": "133100", "ug_nome": "ITERJ", "indicio": True,
    "n_cnpjs": 30, "n_grupos": 21, "n_grupos_multi": 1,
    "hhi_cnpj": 1200.0, "hhi_grupo": 3400.0, "delta_hhi": 2200.0,
    "top_grupo_share": 57.0,
    "maior_grupo_multi": {"grupo": "11111111", "n_cnpjs": 10, "n_raizes": 8, "total": 5_700_000.0,
                          "share": 57.0, "top_nome": "ALFA CONSTRUCOES LTDA", "cnpjs": []},
    "grupos": [
        {"grupo": "11111111", "n_cnpjs": 10, "n_raizes": 8, "total": 5_700_000.0, "share": 57.0,
         "top_nome": "ALFA CONSTRUCOES LTDA", "cnpjs": []},
        {"grupo": "22222222", "n_cnpjs": 1, "n_raizes": 1, "total": 1_000_000.0, "share": 10.0,
         "top_nome": "BETA SERVICOS SA", "cnpjs": []},
    ],
    "nota": "stub",
}


def _render(ctx):
    L = []
    io._secao_concentracao_grupo_md(L.append, ctx)
    return "\n".join(L)


def test_helper_usa_detector_stubado(monkeypatch):
    """O helper _concentracao_grupo_orgao NÃO toca o DuckDB real: usa o detector stubado."""
    monkeypatch.setattr("compliance_agent.grafo_cartel.concentracao_por_grupo",
                        lambda ug, **kw: dict(_STUB_INDICIO))
    out = io._concentracao_grupo_orgao("133100")
    assert out["ok"] is True and out["indicio"] is True
    assert out["maior_grupo_multi"]["n_cnpjs"] == 10


def test_secao_indicio_aparece_com_tabela_e_base_legal():
    cg = dict(_STUB_INDICIO); cg["ok"] = True
    md = _render({"concentracao_grupo": cg})
    # cabeçalho da seção
    assert "## 1-H." in md and "GRUPO ECONÔMICO" in md
    # tabela com o grupo multi-CNPJ
    assert "ALFA CONSTRUCOES LTDA" in md
    assert "57.0%" in md  # share do maior grupo
    # prosa honesta: indício, base legal, destinatário
    assert "Indício" in md
    assert "Art. 90" in md and "337-F" in md and "12.529" in md
    assert "MP e CADE" in md or "CADE" in md


def test_secao_sem_indicio_verde_honesto():
    cg = dict(_STUB_INDICIO); cg["ok"] = True; cg["indicio"] = False
    md = _render({"concentracao_grupo": cg})
    assert "## 1-H." in md
    assert "🟢" in md and "INDISPONÍVEL" in md  # 🟢 e ressalva de INDISPONÍVEL ≠ afastado


def test_secao_indisponivel_honesto():
    md = _render({"concentracao_grupo": {"ok": False}})
    assert "## 1-H." in md and "indisponível" in md.lower()
    assert "INDISPONÍVEL não é prova de ausência" in md


def test_fato_grupo_entra_no_raciocinio():
    cg = dict(_STUB_INDICIO); cg["ok"] = True
    ctx = {"nome": "ITERJ — UG X", "ug": "133100",
           "pagamentos": {"tem_dados": True, "total_geral": 10_000_000.0, "n_geral": 30, "n_fornecedores": 1,
                          "por_favorecido_geral": {"ALFA": 5_700_000.0},
                          "hhi": {"indice": 1200.0, "nivel": "ALTO", "top_share": 57.0},
                          "anos": [], "por_ano": {}},
           "concentracao_grupo": cg}
    fatos = io._fatos_orgao(ctx)
    assert "grupo econômico" in fatos.lower() and "fictícia" in fatos.lower()
    assert "57.0%" in fatos
