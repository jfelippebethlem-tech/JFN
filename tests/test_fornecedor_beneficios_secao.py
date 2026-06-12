# -*- coding: utf-8 -*-
"""Testes da seção 1-C (benefícios dos sócios/admin = laranja) do relatório de FORNECEDOR. Sem rede/DB:
render a partir de ctx mockado (ctx['beneficios_socios'] já provido) + entrada no raciocínio."""
from compliance_agent.reporting import inteligencia as ig


def test_render_indicio_com_tabela_e_conclusao():
    ctx = {"cnpj": "11111111000111", "beneficios_socios": {
        "ok": True, "total_qsa": 3, "n_varridos": 3, "n_resolvidos": 1, "n_verificados": 1,
        "n_com_beneficio": 1, "n_pessoas_beneficio": 1, "n_indisponivel": 2, "cobertura": 33.3,
        "itens": [{"cnpj": "11111111000111", "razao": "ALFA LTDA", "nome": "JOAO ADM",
                   "papel": "Administrador", "gestao": True, "fonte": "tse_doadores", "tipos": ["Bolsa Família"]}]}}
    md = ig._render_beneficios_socios(ctx)
    assert "## 1-C." in md and "LARANJA" in md
    assert "JOAO ADM" in md and "Bolsa Família" in md and "337-F" in md
    assert "doadores TSE" in md


def test_render_indisponivel_sem_qsa():
    md = ig._render_beneficios_socios({"cnpj": "x", "beneficios_socios": {"total_qsa": 0}})
    assert "## 1-C." in md and "INDISPONÍVEL" in md and "ausência" in md


def test_fato_beneficio_entra_no_raciocinio():
    ctx = {"nome": "ALFA LTDA", "cnpj_fmt": "11.111.111/0001-11", "cnpj": "11111111000111",
           "risco": "MÉDIO", "score": 40, "pagamentos": {"tem_dados": False},
           "beneficios_socios": {"n_verificados": 2, "n_com_beneficio": 1, "n_pessoas_beneficio": 1}}
    fatos = ig._fatos_para_raciocinio(ctx)
    assert "laranja" in fatos.lower() and "interposição" in fatos.lower()
