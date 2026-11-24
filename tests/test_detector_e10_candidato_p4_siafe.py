# -*- coding: utf-8 -*-
"""E10 `e10.candidato_p4_siafe` (O5.3 fatia 2): a série de OB por credor × UG vira só `candidato_p4(processos[])`,
INCERTO — nunca "fracionamento" (plano §4 item 5). Régua da triagem do fracionamento_siafe, sobre itens 'E' da E9."""
import sqlite3

import pytest

from compliance_agent.aplicacao.detectores import candidato_p4_siafe as CP
from compliance_agent.limites_dispensa import limite_dispensa

TETO = limite_dispensa(2025, "compras")


@pytest.fixture()
def fonte(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente, credor, nome_credor, data_emissao, valor, processo, "
                "numero_ob, status, nl, exercicio INTEGER)")
    con.commit()
    con.close()
    return p


def _ler(p, linhas, e9=None):
    con = sqlite3.connect(p)
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)", linhas)
    con.commit()
    con.close()
    itens = CP.carregar(sqlite3.connect(f"file:{p}?mode=ro", uri=True)).itens
    for c in itens:
        c["e9"] = (e9 or {}).get(c["numero_ob"], "E")
    return itens


def _ob(i, proc, valor=None, credor="11111111000111", nome="ACME SERVICOS LTDA", status="Contabilizado"):
    return ("010100", credor, nome, f"0{i}/03/2025", valor or TETO * 0.5, proc, f"2025OB{i}", status, None, 2025)


def test_positivo_serie_de_tres_processos_vira_candidato_p4(fonte):
    ds = CP.detectar(_ler(fonte, [_ob(1, "P1"), _ob(2, "P2"), _ob(3, "P3")]))
    assert len(ds) == 1 and ds[0].estado == "INCERTO" and ds[0].valores["natureza"] == "candidato_p4"
    assert ds[0].valores["processos"] == ["P1", "P2", "P3"] and ds[0].valores["n_rente_ao_teto"] == 0
    assert "fracionamento" not in ds[0].observacao.lower()           # só o P4, por objeto, afirma fracionamento


def test_negativo_parcelas_do_mesmo_processo_nao_viram_candidato(fonte):
    assert CP.detectar(_ler(fonte, [_ob(1, "P1"), _ob(2, "P1"), _ob(3, "P1")])) == []


def test_negativo_ente_publico_acima_do_teto_e_anulada_ficam_fora(fonte):
    itens = _ler(fonte, [_ob(1, "P1", nome="FUNDO MUNICIPAL DE SAUDE DE ITABORAI"), _ob(2, "P2", valor=TETO * 2),
                         _ob(3, "P3", status="Anulado"), _ob(4, "P4"), _ob(5, "P5")])
    assert len(itens) == 2 and CP.detectar(itens) == []


def test_item_sem_elegibilidade_sai_da_serie(fonte):
    itens = _ler(fonte, [_ob(1, "P1"), _ob(2, "P2"), _ob(3, "P3")], e9={"2025OB2": "?:SEM_NE"})
    assert CP.detectar(itens) == []
    assert CP.resumo(itens, [])["cobertura"] == round(2 / 3, 4)


def test_carregar_grupo_reproduz(fonte):
    itens = _ler(fonte, [_ob(1, "P1"), _ob(2, "P2"), _ob(3, "P3")])
    d = CP.detectar(itens)[0]
    g = CP.carregar_grupo(sqlite3.connect(f"file:{fonte}?mode=ro", uri=True), d.grupo).itens
    for c in g:
        c["e9"] = "E"
    assert [x.entradas for x in CP.detectar(g)] == [d.entradas]
