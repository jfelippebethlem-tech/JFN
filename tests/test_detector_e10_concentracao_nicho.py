# -*- coding: utf-8 -*-
"""E10 `e10.c_concentracao_nicho` (regra única #14, ex-`tools/_triagem_bombeiros.py`, 27/11/2026): um fornecedor com
> 60% do valor contratado de um nicho de objeto acima de R$ 5.000.000,00, na mesma unidade e exercício, com ao menos 3
contratos; monopólio legítimo afasta; nicho OUTROS nunca dispara; só item com veredito 'E' da E9."""
import sqlite3

from compliance_agent.aplicacao.detectores import concentracao_nicho as CN

UNI = "SECRETARIA X"


def _con(linhas):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE contratos_tcerj(processo, num_contratacao, sei_norm, valor_contrato, unidade, "
                "data_contratacao, objeto, status, cnpj, fornecedor)")
    con.executemany("INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?,?,?,?,?)", linhas)
    return con


def _ct(i, valor, cnpj, forn, objeto="LOCACAO DE VIATURAS", data="2025-03-01", st="Vigente"):
    return (f"P{i}", f"N{i}", f"S{i}", valor, UNI, data, objeto, st, cnpj, forn)


def _itens(con, e9="E"):
    itens = CN.carregar(con).itens
    for c in itens:
        c["e9"] = e9
    return itens


def test_positivo_dominante_acima_de_60_por_cento_num_nicho_grande():
    con = _con([_ct(1, 4_000_000, "11111111000111", "ALFA LTDA"), _ct(2, 2_500_000, "11111111000111", "ALFA LTDA"),
                _ct(3, 1_000_000, "22222222000122", "BETA LTDA")])
    (d,) = CN.detectar(_itens(con))
    assert d.estado == "INDICIO" and d.valores["fornecedor_dominante"] == "ALFA LTDA"
    assert d.valores["fatia"] == round(6_500_000 / 7_500_000, 4) and d.valores["n_contratos"] == 3


def test_negativo_monopolio_legitimo_nicho_pequeno_poucos_contratos_e_outros():
    grande = [_ct(1, 4_000_000, "11111111000111", "LIGHT SERVICOS DE ELETRICIDADE"),
              _ct(2, 2_500_000, "11111111000111", "LIGHT SERVICOS DE ELETRICIDADE"), _ct(3, 1_000_000, "2" * 14, "B")]
    assert CN.detectar(_itens(_con(grande))) == []                                    # monopólio legítimo afasta
    pequeno = [_ct(1, 2_000_000, "1" * 14, "A"), _ct(2, 1_500_000, "1" * 14, "A"), _ct(3, 500_000, "2" * 14, "B")]
    assert CN.detectar(_itens(_con(pequeno))) == []                                   # nicho ≤ R$ 5 mi
    dois = [_ct(1, 9_000_000, "1" * 14, "A"), _ct(2, 1_000_000, "2" * 14, "B")]
    assert CN.detectar(_itens(_con(dois))) == []                                      # < 3 contratos: aritmética
    outros = [_ct(i, 4_000_000, "1" * 14, "A", objeto="PRESTACAO DE SERVICOS DIVERSOS") for i in range(3)]
    assert CN.detectar(_itens(_con(outros))) == []                                    # nicho OUTROS


def test_so_item_elegivel_conta_e_cancelado_fica_fora():
    lin = [_ct(1, 4_000_000, "1" * 14, "A"), _ct(2, 2_500_000, "1" * 14, "A"), _ct(3, 1_000_000, "2" * 14, "B")]
    assert CN.detectar(_itens(_con(lin), e9="?:SEM_CNPJ")) == []
    lin[0] = _ct(1, 4_000_000, "1" * 14, "A", st="Cancelado")
    assert CN.detectar(_itens(_con(lin))) == []                                       # sem o cancelado não domina


def test_conferencia_do_grupo_relida_da_fonte_da_o_mesmo_disparo():
    con = _con([_ct(1, 4_000_000, "1" * 14, "A"), _ct(2, 2_500_000, "1" * 14, "A"), _ct(3, 1_000_000, "2" * 14, "B")])
    (d,) = CN.detectar(_itens(con))
    itens = CN.carregar_grupo(con, CN.grupo_de(d)).itens
    for c in itens:
        c["e9"] = "E"
    (d2,) = CN.detectar(itens)
    assert d2.entradas == d.entradas and d2.valores == d.valores
