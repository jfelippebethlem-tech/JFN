# -*- coding: utf-8 -*-
"""Furos do Radar de empresas-fantasma (empresa_fantasma) medidos em 14/11/2026 no fantasma_score real.

- `cnae_incompativel` marcava 116 empresas; 56 (48%) tinham o CNAE gravado como CÓDIGO ('4644301',
  atacado de medicamentos) e o sinal comparava radicais de TEXTO ('farmac', 'medicament') contra
  dígitos — incompatível sempre. STAFF MEDICAL (4644301) vendendo rituximabe saía "incompatível".
- "obra" casava "obras paradidáticas" (livros) e "mão de obra" (terceirização).
- `situacao_irregular` (peso 32, o maior) usava o retrato de HOJE, sem data nem motivo: 11 das 15
  empresas "risco ALTO" do painel vinham dele — a mesma família do caso Fênix.
"""
from __future__ import annotations

from compliance_agent.empresa_fantasma import avaliar_perfil


def _ids(**kw):
    base = dict(cnpj="24262316000110", razao_social="X LTDA", situacao="ATIVA", capital_social=1e6,
                total_recebido=1e6, cnae="", objeto_pago="", sancionada=False)
    base.update(kw)
    return {s["id"] for s in avaliar_perfil(base)["sinais"]}


def test_cnae_em_codigo_nao_e_comparado_com_radical_de_texto():
    assert "cnae_incompativel" not in _ids(
        cnae="4644301", objeto_pago="aquisicao dos medicamentos rituximabe 500 mg")


def test_obras_paradidaticas_e_mao_de_obra_nao_sao_obra():
    assert "cnae_incompativel" not in _ids(
        cnae="Comércio atacadista de livros", objeto_pago="aquisicao de obras paradidaticas para salas de leitura")
    assert "cnae_incompativel" not in _ids(
        cnae="Serviços combinados de escritório e apoio administrativo",
        objeto_pago="servico de apoio administrativo com mao de obra dedicada")


def test_obra_de_verdade_segue_comparada():
    assert "cnae_incompativel" in _ids(cnae="Comércio varejista de roupas",
                                       objeto_pago="obras de reforma predial e construção")


def test_baixa_por_incorporacao_nao_e_situacao_irregular():
    assert "situacao_irregular" not in _ids(situacao="BAIXADA", motivo_situacao="02",
                                            data_situacao="2021-05-03", ultima_ob="2025-08-26")


def test_situacao_posterior_ao_ultimo_pagamento_e_sinal_fraco():
    s = [x for x in avaliar_perfil(dict(cnpj="1", situacao="BAIXADA", motivo_situacao="01",
                                        data_situacao="2024-09-23", ultima_ob="2023-10-11"))["sinais"]
         if x["id"] == "situacao_irregular"]
    assert s and s[0]["peso"] <= 6 and "depois" in s[0]["detalhe"].lower()


def test_inexistente_de_fato_com_pagamento_posterior_e_o_mais_forte():
    s = [x for x in avaliar_perfil(dict(cnpj="28470707000180", situacao="INAPTA", motivo_situacao="15",
                                        data_situacao="2026-01-28", ultima_ob="2026-03-24"))["sinais"]
         if x["id"] == "situacao_irregular"][0]
    assert s["peso"] >= 32 and "inexist" in s["detalhe"].lower()


def test_data_do_dump_da_receita_aaaammdd_e_lida():
    """O dump grava data_situacao como AAAAMMDD; sem ler, a regra de data nunca entrava."""
    s = [x for x in avaliar_perfil(dict(cnpj="1", situacao="BAIXADA", motivo_situacao="01",
                                        data_situacao="20240923", ultima_ob="2023-10-11"))["sinais"]
         if x["id"] == "situacao_irregular"]
    assert s[0]["peso"] <= 6


def test_associacao_pela_natureza_juridica_tem_capital_infimo_legitimo():
    """CPASC (03.686.998/0001-18) e Espaço Cidadania (02.539.959/0001-25): associações com capital
    R$ 0,00 saíam 'risco ALTO' porque o nome não tem 'instituto/associação'. A natureza jurídica do dump
    (3xx = entidade sem fins lucrativos) é a fonte, não o nome."""
    r = avaliar_perfil(dict(cnpj="03686998000118", razao_social="CENTRO DE PESQUISAS E DE ACOES SOCIAIS",
                            natureza_cod="3999", capital_social=0.0, total_recebido=210_376_569.26, n_socios=1))
    sinais = {s["id"]: s["peso"] for s in r["sinais"]}
    assert sinais.get("capital_incompativel") == 6
    assert "socio_unico_capital_baixo" not in sinais


def test_programas_de_computador_e_informatica():
    assert "cnae_incompativel" not in _ids(cnae="desenvolvimento de programas de computador sob encomenda",
                                           objeto_pago="servicos de informatica e suporte")
