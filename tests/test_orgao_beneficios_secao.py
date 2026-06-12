# -*- coding: utf-8 -*-
"""Testes da seção 1-F (benefícios dos sócios/admin = laranja) do relatório de órgão. Sem rede/DB:
exercita o render a partir de um ctx mockado e a entrada do sinal no raciocínio (_fatos_orgao)."""
from compliance_agent.reporting import inteligencia_orgao as io


def _render(ctx):
    L = []
    io._secao_beneficios_md(L.append, ctx)
    return "\n".join(L)


def test_secao_indicio_aparece_com_tabela_e_conclusao():
    ctx = {"beneficios_socios": {
        "ok": True, "total_qsa": 50, "n_varridos": 40, "n_resolvidos": 6, "n_verificados": 6,
        "n_com_beneficio": 2, "n_pessoas_beneficio": 2, "n_indisponivel": 44, "cobertura": 12.0,
        "itens": [
            {"cnpj": "C1", "razao": "ALFA LTDA", "nome": "JOAO ADM", "papel": "Administrador",
             "gestao": True, "fonte": "tse_doadores", "tipos": ["Bolsa Família"]},
            {"cnpj": "C2", "razao": "BETA SA", "nome": "MARIA S", "papel": "Sócio",
             "gestao": False, "fonte": "favorecidos_pf", "tipos": ["BPC"]},
        ]}}
    md = _render(ctx)
    assert "## 1-F." in md and "LARANJA" in md
    assert "ALFA LTDA" in md and "JOAO ADM" in md and "Bolsa Família" in md
    assert "337-F" in md and "Indício" in md  # conclusão/base legal
    assert "doadores TSE" in md  # fonte do CPF traduzida


def test_secao_indisponivel_honesto():
    md = _render({"beneficios_socios": {"ok": False}})
    assert "## 1-F." in md and "INDISPONÍVEL" in md
    assert "ausência" in md  # explicita que INDISPONÍVEL ≠ ausência


def test_fato_beneficio_entra_no_raciocinio():
    ctx = {"nome": "TESTE — UG X", "ug": "999999",
           "pagamentos": {"tem_dados": True, "total_geral": 1000.0, "n_geral": 2,
                          "por_favorecido_geral": {"ALFA": 1000.0}, "hhi": {"indice": 1.0, "nivel": "BAIXO", "top_share": 100.0},
                          "anos": [], "por_ano": {}},
           "beneficios_socios": {"ok": True, "n_verificados": 6, "n_com_beneficio": 2,
                                 "n_pessoas_beneficio": 2, "cobertura": 12.0}}
    fatos = io._fatos_orgao(ctx)
    assert "laranja" in fatos.lower() and "interposição" in fatos.lower()
