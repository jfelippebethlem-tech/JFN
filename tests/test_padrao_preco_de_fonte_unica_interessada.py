# -*- coding: utf-8 -*-
"""preco_de_fonte_unica_interessada — CDEL (SEI-420001/003312/2024) e STEM (SEI-420001/006323/2025)."""
from compliance_agent.padroes._carona_comum import Doc
from compliance_agent.padroes.preco_de_fonte_unica_interessada import avaliar

TR_CDEL = Doc("arquivo", "7", "Termo de Referência (85049997)",
              "Além disso os preços de capa das coleções avaliadas, no site das respectivas editoras, são de: ... "
              "Com relação a temática dos Direitos das Mulheres, a SEGOV localizou apenas a coleção “Cidadania Hoje – "
              "Direitos das Mulheres”, da Eureka Soluções Pedagógicas")
TR_STEM = Doc("arquivo", "22", "Termo de Referência (121707526)",
              "9. ESTIMATIVA DO VALOR DA CONTRATAÇÃO O levantamento do preço estimado da contratação foi realizado com "
              "base no valor unitário do kit de material educativo, conforme disponibilizado no sítio eletrônico "
              "https://www.educarmelhor.com/projetos-educacionais, com a aplicação do desconto previsto na Ata")


def test_positivo_cdel_fonte_unica_e_capa():
    r = avaliar([TR_CDEL])
    assert r["fonte_unica"] and r["base_do_vendedor"]


def test_positivo_stem_site_do_vendedor():
    assert avaliar([TR_STEM])["base_do_vendedor"]


def test_negativo_regra_de_pesquisa_e_cesta():
    tr = Doc("arquivo", "3", "Termo de Referência", "O preço estimado deverá ser obtido com base em no mínimo três "
             "cotações, Painel de Preços e contratações similares. Foram obtidas cinco cotações de empresas distintas.")
    r = avaliar([tr])
    assert r == {"fonte_unica": None, "base_do_vendedor": None}


def test_negativo_contrato_nao_e_lido():
    c = Doc("arquivo", "5", "Contrato nº 1/2025", "a SEGOV localizou apenas a coleção X; preços de capa no site da editora")
    assert avaliar([c]) == {"fonte_unica": None, "base_do_vendedor": None}
