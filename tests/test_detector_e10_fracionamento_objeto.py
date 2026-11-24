# -*- coding: utf-8 -*-
"""E10 `e10.p4_fracionamento_objeto` (O5.3 fatia 1): réguas portadas do sweep_fracionamento_tcerj + card P4, só sobre
processos elegíveis na E9. Fixtures sintéticas (sem banco real)."""
import sqlite3

import pytest

from compliance_agent.aplicacao.detectores import fracionamento_objeto as F


def _linha(proc, valor, objeto, *, enq="Lei 14.133/2021, Art. 75, I", afast="Dispensa", forn="ACME OBRAS LTDA",
           unidade="SEC X - SECRETARIA", ano=2025):
    return dict(processo=proc, unidade=unidade, ano_processo=ano, valor=valor, objeto=objeto, afastamento=afast,
                enquadramento=enq, fornecedor=forn)


def _itens(linhas, e9=None):
    it = F._itens(linhas)
    for c in it:
        c["e9"] = (e9 or {}).get(c["processo"], "E")
    return it


REFORMAS = [_linha("SEI-1", 100000, "REFORMA DO TELHADO DA ESCOLA ESTADUAL A"),
            _linha("SEI-2", 90000, "REFORMA DO TELHADO DA ESCOLA ESTADUAL B", forn="BETA CONSTRUCOES LTDA")]


@pytest.mark.parametrize("objeto, tipo", [
    ("REFORMA DA CISTERNA DA SEDE", "obras"),
    ("IMPERMEABILIZAÇÃO DA LAJE", "obras"),
    ("LOCAÇÃO DE MÃO DE OBRA DE LIMPEZA", "compras"),          # "mão de obra" não é obra
    ("AQUISIÇÃO DE MATERIAL DE CONSTRUÇÃO CIVIL", "compras"),  # aquisição é compra, ainda que "de construção"
    ("PAVIMENTAÇÃO DE ACESSO", "obras"),
])
def test_tipo_objeto(objeto, tipo):
    assert F.tipo_objeto(objeto) == tipo


def test_uma_linha_por_processo_grafias_e_irmaos():
    linhas = [_linha("SEI-310001/001411/2024", 50000, "A"), _linha("SEI 310001/001411/2024", 50000, "A"),
              _linha("SEI-000778/2025", 30000, "B"), _linha("SEI-000778A/2025", 30000, "B", forn="OUTRA"),
              _linha("SEI-000779/2025", 30000, "C"), _linha("SEI-000779A/2025", 31000, "C")]
    procs = sorted(c["processo"] for c in F._itens(linhas))
    # grafia repetida conta uma vez; irmão de sufixo com o MESMO valor é duplicata; com valor diferente fica
    assert len(procs) == 4 and "SEI-000779A/2025" in procs


@pytest.mark.parametrize("objeto", ["PAGAMENTO DE ANUIDADE DO CONSELHO", "CONSUMO DE ENERGIA ELÉTRICA",
                                    "RECONHECIMENTO DE DÍVIDA DE EXERCÍCIOS ANTERIORES", "CHAMADA PÚBLICA"])
def test_nao_contratacao_nao_e_dispensa_por_valor(objeto):
    assert F.dispensa_por_valor("Dispensa", "Art. 75, II", 1000.0, 2025, "compras", objeto) is False


def test_inexigibilidade_nao_e_dispensa_e_inciso_decide():
    assert F.dispensa_por_valor("Inexigibilidade", "Art. 74, I", 1000.0, 2025, "compras") is False
    assert F.dispensa_por_valor("Dispensa", "Art. 75, VIII", 1000.0, 2025, "compras") is False
    assert F.dispensa_por_valor("Dispensa", "Art. 75, II", 1000.0, 2025, "compras") is True


def test_positivo_reforma_e_obra_e_soma_acima_do_teto():
    ds = F.detectar(_itens(REFORMAS))
    assert len(ds) == 1
    d = ds[0]
    assert d.estado == "INDICIO" and d.grupo == "SEC X - SECRETARIA|2025" and "|obras|" in d.chave
    assert d.valores["soma_cluster"] == 190000.0 and d.valores["soma_acima_do_teto"] is True
    assert {c["processo"] for c in d.entradas["cluster"]} == {"SEI-1", "SEI-2"}
    assert all(f.papel.value == "suporte" for f in d.evidencias) and len(d.evidencias) == 2


def test_negativo_mao_de_obra_e_inelegivel_ficam_fora():
    # mão de obra é compra (inciso II): não soma com a reforma (inciso I) — cada natureza contra o próprio teto
    mista = [REFORMAS[0], _linha("SEI-3", 60000, "LOCAÇÃO DE MÃO DE OBRA DE MANUTENÇÃO", enq="Art. 75, II")]
    assert F.detectar(_itens(mista)) == []
    # invariante 3: processo sem veredito 'E' na E9 não entra (inelegível ou indeterminado)
    for v in ("I:NAO_DISPENSA_VALOR", "?:TETO_INDETERMINADO", None):
        assert F.detectar(_itens(REFORMAS, {"SEI-2": v})) == []


def test_resumo_conta_o_que_a_e9_nao_deixou_ver():
    it = _itens(REFORMAS + [_linha("SEI-9", 10, "X", enq="Art. 75, II")], {"SEI-9": "?:REGIME_INDETERMINADO"})
    r = F.resumo(it, F.detectar(it))
    assert (r["universo_processos"], r["elegiveis"], r["indeterminados"], r["disparos"]) == (3, 2, 1, 1)
    assert r["cobertura"] == round(2 / 3, 4)


def test_carregar_e_carregar_grupo_leem_so_leitura(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE compras_diretas_tcerj(processo, unidade, ano_processo INTEGER, valor, objeto, "
                "afastamento, enquadramento_legal, fornecedor)")
    for r in REFORMAS + [_linha("SEI-1", 100000, "REFORMA DO TELHADO DA ESCOLA ESTADUAL A"),   # 2º item do processo
                         _linha("SEI-7", 5, "X", unidade="OUTRA", ano=2024)]:
        con.execute("INSERT INTO compras_diretas_tcerj VALUES (?,?,?,?,?,?,?,?)",
                    (r["processo"], r["unidade"], r["ano_processo"], r["valor"], r["objeto"], r["afastamento"],
                     r["enquadramento"], r["fornecedor"]))
    con.commit()
    ro = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    assert len(F.carregar(ro).itens) == 3 and len(F.carregar(ro, 2024).itens) == 1
    g = F.carregar_grupo(ro, "SEC X - SECRETARIA|2025").itens
    assert sorted(c["chave_e9"] for c in g) == ["SEI-1", "SEI-2"]
