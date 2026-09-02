"""Testes do detector de fracionamento de dispensa da PCRJ.

Os cenários são construídos em banco temporário — nada depende do acervo real, que muda.
"""
import sqlite3

import pytest

from tools import fracionamento_dispensa_pcrj as fd

AVISO = ("AVISO DE DISPENSA ELETRÔNICA N° {n}/2025\n"
         "(Processo Administrativo n° {proc})\n"
         "na hipótese do art. 75, inciso II, nos termos da Lei nº 14.133\n"
         "destinada a Unidade {unidade}, Rio de Janeiro\n")


@pytest.fixture()
def banco(tmp_path):
    def _criar(linhas):
        p = tmp_path / "t.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE edital_documento (numero_controle_pncp TEXT, ano INT, "
                    "orgao_cnpj TEXT, objeto TEXT, valor_estimado REAL, texto TEXT)")
        con.executemany("INSERT INTO edital_documento VALUES (?,?,?,?,?,?)", linhas)
        con.commit()
        con.close()
        return str(p)
    return _criar


def _linha(cert, proc, unidade, objeto, valor, ano=2025, cnpj="42498733000148"):
    return (cert, ano, cnpj, objeto, valor,
            AVISO.format(n=cert[-8:], proc=proc, unidade=unidade))


def test_teto_vem_do_ano_e_o_de_2025_e_o_do_decreto_12343(banco):
    assert fd.teto(2025) == 62_725.59        # Decreto 12.343/2024, conferido na fonte
    assert fd.teto(2023) == 59_906.02
    assert fd.teto(None) == fd.TETO_PADRAO   # ano desconhecido não vira zero


def test_corte_a_exige_soma_acima_do_teto_e_mais_de_uma_dispensa(banco):
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital Municipal X", "Aquisição de gaze", 40_000.0),
        _linha("A-2", "SMS-PRO-2025/00001", "Hospital Municipal X", "Aquisição de gaze", 30_000.0),
        # mesmo processo, mas a soma NÃO passa o teto -> não é achado
        _linha("B-1", "SMS-PRO-2025/00002", "Hospital Municipal Y", "Aquisição de luva", 10_000.0),
        _linha("B-2", "SMS-PRO-2025/00002", "Hospital Municipal Y", "Aquisição de luva", 20_000.0),
        # dispensa isolada acima do teto: é outro vício, NÃO fracionamento
        _linha("C-1", "SMS-PRO-2025/00003", "Hospital Municipal Z", "Aquisição de soro", 90_000.0),
    ])
    a = fd.corte_a_mesmo_processo(fd.carregar_dispensas(db))
    assert [x["processo"] for x in a] == ["SMS-PRO-2025/00001"]
    assert a[0]["soma"] == pytest.approx(70_000.0)
    assert a[0]["razao"] == pytest.approx(70_000.0 / 62_725.59)


def test_limite_e_estritamente_acima_do_teto_nao_igual(banco):
    """Teto legal é limite INCLUSIVO ('até'): somar exatamente o teto não é estouro."""
    t = fd.teto(2025)
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital X", "Aquisição de gaze", t / 2),
        _linha("A-2", "SMS-PRO-2025/00001", "Hospital X", "Aquisição de gaze", t / 2),
    ])
    assert fd.corte_a_mesmo_processo(fd.carregar_dispensas(db)) == []


def test_so_entra_dispensa_do_inciso_II(banco):
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital X", "Aquisição de gaze", 40_000.0),
        _linha("A-2", "SMS-PRO-2025/00001", "Hospital X", "Aquisição de gaze", 40_000.0),
    ])
    con = sqlite3.connect(db)
    con.execute("UPDATE edital_documento SET texto=replace(texto,'inciso II','inciso VIII') "
                "WHERE numero_controle_pncp='A-2'")
    con.commit()
    con.close()
    ds = fd.carregar_dispensas(db)
    assert [d["certame"] for d in ds] == ["A-1"]          # a de emergência ficou de fora
    assert fd.corte_a_mesmo_processo(ds) == []            # sobra uma só: não há fracionamento


def test_corte_b_nao_agrupa_unidades_diferentes(banco):
    """A defesa legítima do §1º é a unidade gestora autônoma — o corte tem de respeitá-la."""
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital Municipal Alfa", "Aquisição de gaze", 40_000.0),
        _linha("A-2", "SMS-PRO-2025/00002", "Hospital Municipal Beta", "Aquisição de gaze", 40_000.0),
    ])
    assert fd.corte_b_mesma_unidade(fd.carregar_dispensas(db)) == []


def test_corte_b_agrupa_mesma_unidade_com_objeto_semelhante(banco):
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital Municipal Alfa",
               "Aquisição de gaze hospitalar", 40_000.0),
        _linha("A-2", "SMS-PRO-2025/00002", "Hospital Municipal Alfa",
               "Aquisição de gaze hospitalar", 40_000.0),
    ])
    b = fd.corte_b_mesma_unidade(fd.carregar_dispensas(db))
    assert len(b) == 1 and b[0]["n"] == 2
    assert b[0]["processos"] == ["SMS-PRO-2025/00001", "SMS-PRO-2025/00002"]


def test_corte_b_nao_agrupa_objetos_distintos_na_mesma_unidade(banco):
    """'Aquisição de' e 'material' são stopwords: sozinhas não podem casar objetos."""
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital Municipal Alfa",
               "Aquisição de material de gaze", 40_000.0),
        _linha("A-2", "SMS-PRO-2025/00002", "Hospital Municipal Alfa",
               "Aquisição de material de tomógrafo", 40_000.0),
    ])
    assert fd.corte_b_mesma_unidade(fd.carregar_dispensas(db)) == []


def test_unidade_ausente_nao_vira_grupo_fantasma(banco):
    """Sem unidade no texto, o registro NÃO pode ser agrupado — INDISPONÍVEL ≠ mesma unidade."""
    db = banco([
        ("A-1", 2025, "42498733000148", "Aquisição de gaze", 40_000.0,
         "AVISO DE DISPENSA\n(Processo n° SMS-PRO-2025/00001)\nart. 75, inciso II\n"),
        ("A-2", 2025, "42498733000148", "Aquisição de gaze", 40_000.0,
         "AVISO DE DISPENSA\n(Processo n° SMS-PRO-2025/00002)\nart. 75, inciso II\n"),
    ])
    ds = fd.carregar_dispensas(db)
    assert all(d["unidade"] is None for d in ds)
    assert fd.corte_b_mesma_unidade(ds) == []


def test_bunching_conta_faixas_e_nao_divide_por_zero(banco):
    t = fd.teto(2025)
    db = banco([
        _linha("A-1", "SMS-PRO-2025/00001", "Hospital X", "Aquisição de gaze", t * 0.99),
        _linha("A-2", "SMS-PRO-2025/00002", "Hospital X", "Aquisição de luva", t * 0.5),
    ])
    bn = fd.agrupamento_no_teto(fd.carregar_dispensas(db))
    assert bn["colado_5pct_abaixo"] == 1
    assert bn["acima_do_teto"] == 0
    assert bn["razao"] is None          # sem nenhuma acima, a razão é INDISPONÍVEL, não infinito


# --- comparabilidade do item (mora em cruzamentos_intel, usada pelo índice de certames) ---

def test_descricao_pobre_e_declarada_fraca():
    from compliance_agent.cruzamentos_intel import comparabilidade_item
    for d in ("Seringa", "INSULINA", "Álcool Etílico", "Agulha Hipodérmica"):
        comp, motivo = comparabilidade_item(d)
        assert comp == "FRACA", d
        assert "token" in motivo


def test_descricao_especificada_e_forte():
    from compliance_agent.cruzamentos_intel import comparabilidade_item
    comp, _ = comparabilidade_item(
        "TIPO: SUBCLAVIA, MATERIAL CATETER: PTFE, USO: HEMODINAMICA")
    assert comp == "FORTE"


def test_fraca_nao_zera_o_flag_apenas_declara():
    """O controle positivo achou 41 flags frágeis com razão >=10x — cortar perderia sinal real.
    A fragilidade se DECLARA; o valor do flag não pode ser silenciosamente rebaixado."""
    import inspect

    from compliance_agent.editais import indice_certame
    src = inspect.getsource(indice_certame._f_preco)
    assert 'fl["comparabilidade"]' in src          # campo aditivo existe
    # o valor do flag vem de `melhor[0]`, calculado só a partir da razão — sem fator de comparabilidade
    assert "_flag(\"sobrepreco_vs_mediana\", melhor[0], melhor[1])" in src
