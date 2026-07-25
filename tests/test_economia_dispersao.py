"""A economia separa o que compara produto IGUAL do que compara rotulo generico.

Medido em 25/07/2026: dos R$ 15,58 mi de "economia potencial", **R$ 9,41 mi (60,4%)**
vinham de grupos cuja descricao do PNCP mistura produtos diferentes. O guarda que ja
existia — >=60% dos certames a <=2x a mediana — responde "a mediana faz sentido?", e nao
"quem esta ACIMA dela e comparavel?".

Casos reais que denunciaram sozinhos, pela propria descricao:
  · 'Locação de Veículos - Leves / Pesados' ..... dispersao   300,9x
  · 'Peça mecânica / elétrica - veículo' ........ dispersao 1.292,5x  (parafuso e motor)
  · 'Pneu veículo automotivo' .................... dispersao     6,6x  (leve x pesado)
e os que passam limpos:
  · 'Papel Higiênico' ............................ dispersao     1,4x
  · 'CALCA, COR: BRANCO, TAMANHO: M' ............ dispersao     2,6x
"""
import sqlite3

import pytest

from compliance_agent.comparador_precos import economia_potencial

DDL = """
CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
  quantidade REAL, orgao_nome TEXT, unidade_nome TEXT, fornecedor_nome TEXT,
  fornecedor_cnpj TEXT, certame TEXT, data_pub TEXT, ordem_classificacao INTEGER);
"""


def _banco(linhas) -> str:
    import tempfile
    p = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    con = sqlite3.connect(p)
    con.executescript(DDL)
    con.executemany(
        "INSERT INTO pncp_resultado VALUES (?,?,?,?,?,?,?,?,?,?,1)",
        [(d, un, vu, q, org, org, "FORN", "11111111000191", cert, "2025-01-01")
         for d, un, vu, q, org, cert in linhas])
    con.commit(); con.close()
    return p


def _grupo(desc, precos, base_cert="c"):
    """5+ compras, 3+ órgãos, 3+ certames — o mínimo que o detector exige."""
    return [(desc, "unidade", p, 10.0, f"ORGAO{i%3}", f"{base_cert}{i}")
            for i, p in enumerate(precos)]


def test_grupo_homogeneo_conta_como_economia_confiavel():
    """Preços 10..14: dispersão baixa, produto igual — a economia entra na manchete."""
    db = _banco(_grupo("caneta esferografica azul", [10, 11, 12, 13, 14, 12]))
    r = economia_potencial(db_path=db, esfera="todas")
    assert r["economia_homogenea"] > 0
    assert r["economia_descricao_generica"] == 0
    it = r["por_item"][0]
    assert it["descricao_generica"] is False
    assert it["dispersao"] <= 4.0


def test_rotulo_generico_NAO_entra_na_manchete():
    """Preços 10..900: a mediana é válida, mas a cauda é outro produto."""
    db = _banco(_grupo("peca veiculo", [10, 11, 12, 13, 14, 500, 900]))
    r = economia_potencial(db_path=db, esfera="todas")
    assert r["economia_total"] > 0, "o total continua contando — nada é descartado"
    assert r["economia_homogenea"] == 0, "mas a manchete não se apoia em produto diferente"
    assert r["economia_descricao_generica"] == r["economia_total"]
    assert r["por_item"][0]["descricao_generica"] is True
    assert r["por_item"][0]["dispersao"] > 4.0


def test_o_total_nunca_encolhe_a_separacao_e_so_de_leitura():
    """Compatibilidade: `economia_total` segue sendo a soma inteira."""
    db = _banco(_grupo("caneta esferografica azul", [10, 11, 12, 13, 14, 12])
                + _grupo("peca veiculo", [10, 11, 12, 13, 14, 500, 900], base_cert="z"))
    r = economia_potencial(db_path=db, esfera="todas")
    assert r["economia_total"] == pytest.approx(
        r["economia_homogenea"] + r["economia_descricao_generica"], rel=1e-6)
    assert r["economia_homogenea"] > 0 and r["economia_descricao_generica"] > 0


def test_limiar_de_dispersao_e_parametro():
    """Quem quiser ser mais/menos rígido ajusta — o padrão é 4×, não um número mágico solto."""
    linhas = _grupo("peca veiculo", [10, 11, 12, 13, 14, 500, 900])
    db = _banco(linhas)
    frouxo = economia_potencial(db_path=db, esfera="todas", disp_max=1000.0)
    assert frouxo["economia_homogenea"] == frouxo["economia_total"]
    assert frouxo["dispersao_max"] == 1000.0
