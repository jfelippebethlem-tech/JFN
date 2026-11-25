# -*- coding: utf-8 -*-
"""E10 · troca de gestão com data de corte parametrizada (O5.3 fatia 2): D01, D02, D05, D09, D10, D16, D20 portados de
governo_couto_regras — controle positivo e negativo de cada um, sobre fixtures sintéticas (corte 23/03/2026)."""
import sqlite3

import pytest

from compliance_agent import credor_institucional
from compliance_agent.aplicacao.detectores import troca_gestao as T

CORTE = "2026-03-23"
_DDL = """
CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio INTEGER, data_emissao, credor, nome_credor, valor,
  processo, status, status_envio, gd, nl);
CREATE TABLE despesa_execucao(ug, nome_ug);
INSERT INTO despesa_execucao VALUES ('010100', 'SECRETARIA DE ESTADO DE SAUDE'), ('020100', 'TRIBUNAL DE JUSTICA');
CREATE TABLE contratos_tcerj(processo, num_contratacao, sei_norm, valor_contrato, unidade, data_contratacao, objeto,
  status, cnpj, fornecedor);
CREATE TABLE compras_diretas_tcerj(sei_norm, ano_processo, valor, objeto, afastamento, enquadramento_legal, unidade,
  fornecedor, ingerido_em);
CREATE TABLE doerj_tac(data_doe, numero_tac, orgao, fornecedor, cnpj, valor, processo);
"""
_N = [0]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(credor_institucional, "_receita", lambda cnpj: None)    # sem a Receita (como no E10)
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.executescript(_DDL)
    ob(con, "15/07/2026", "99999999000199", "ULTIMA OB LTDA", 1.0, ug="010100")   # fim da coleta: g1 = 30/06/2026
    con.commit()
    yield con, p
    con.close()


def ob(con, data, credor, nome, valor, *, ug="010100", status="Contabilizado", proc=None):
    _N[0] += 1
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"OB{_N[0]}", ug, int(data[-4:]), data, credor, nome, valor, proc or f"P{_N[0]}", status, "", "", None))


def ro(con, p):
    con.commit()
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def anotar(itens, ver=None):
    for c in itens:
        c["e9"] = (ver or {}).get(c["chave_e9"], "E") if c.get("chave_e9") else None
    return itens


def rodar(det, con, p, ver=None):
    carga = det.carregar(ro(con, p))
    return det.detectar(anotar(carga.itens, ver), carga.contexto), carga


# ── D05 ──
def test_d05_positivo_concentracao(db):
    con, p = db
    ob(con, "10/04/2026", "11111111000111", "ALFA SERVICOS LTDA", 7e6)
    ob(con, "11/04/2026", "22222222000122", "BETA COMERCIO LTDA", 4e6)
    ds, _ = rodar(T._Concentracao(corte=CORTE), con, p)
    assert [d.chave for d in ds] == ["010100|11111111000111"]
    assert ds[0].estado == "INDICIO" and ds[0].valores["tipo"] == "NOVA" and ds[0].valores["share"] > 0.6


def test_d05_negativo_ug_pequena(db):
    con, p = db
    ob(con, "10/04/2026", "11111111000111", "ALFA SERVICOS LTDA", 6e6)
    ob(con, "10/04/2026", "33333333000133", "GAMA LTDA", 6e6, ug="020100")      # outro Poder: fora
    assert rodar(T._Concentracao(corte=CORTE), con, p)[0] == []                  # UG < R$ 10 mi


def test_d05_inelegivel_na_e9_nao_conta(db):
    con, p = db
    ob(con, "10/04/2026", "11111111000111", "ALFA SERVICOS LTDA", 7e6)
    ob(con, "11/04/2026", "22222222000122", "BETA COMERCIO LTDA", 4e6)
    carga = T._Concentracao(corte=CORTE).carregar(ro(con, p))
    ver = {c["chave_e9"]: "I:ENTE_PUBLICO" for c in carga.itens if c["cnpj"] == "11111111000111"}
    assert T.CONCENTRACAO.detectar(anotar(carga.itens, ver), carga.contexto) == []


# ── D09 ──
def test_d09_positivo_pico(db):
    con, p = db
    ob(con, "10/02/2026", "44444444000144", "DELTA LTDA", 1e6)
    ob(con, "18/03/2026", "44444444000144", "DELTA LTDA", 4e6)
    ds, carga = rodar(T._PicoVespera(corte=CORTE), con, p)
    assert carga.contexto["ini_ultima_semana"] == "2026-03-16"
    assert [d.chave for d in ds] == ["44444444000144"] and ds[0].valores["x"] > 5


def test_d09_negativo_ritmo_constante(db):
    con, p = db
    ob(con, "10/02/2026", "44444444000144", "DELTA LTDA", 70e6)
    ob(con, "18/03/2026", "44444444000144", "DELTA LTDA", 4e6)
    assert rodar(T._PicoVespera(corte=CORTE), con, p)[0] == []


# ── D10 ──
def test_d10_positivo_estreante(db):
    con, p = db
    ob(con, "10/05/2026", "55555555000155", "EPSILON LTDA", 6e6)
    ds, _ = rodar(T._CredorEstreante(corte=CORTE), con, p)
    assert [d.chave for d in ds] == ["55555555000155"] and ds[0].valores["rotulo"] == "estreia"


def test_d10_negativo_filial_de_fornecedor_antigo(db):
    con, p = db
    ob(con, "10/05/2023", "55555555000155", "EPSILON LTDA", 10.0)                 # a matriz recebeu em 2023
    ob(con, "10/05/2026", "55555555000236", "EPSILON LTDA FILIAL", 6e6)
    ob(con, "11/05/2026", "66666666000166", "CONSORCIO ZETA", 6e6)                 # consórcio: à parte
    det = T._CredorEstreante(corte=CORTE)
    ds, carga = rodar(det, con, p)
    assert ds == [] and det.resumo(carga.itens, ds)["consorcio_a_parte"] == 1


# ── D20 ──
def test_d20_positivo_anuladas_por_ug(db):
    con, p = db
    ob(con, "10/04/2026", "77777777000177", "ETA LTDA", 500.0, status="Anulado")
    ob(con, "10/04/2025", "77777777000177", "ETA LTDA", 100.0, status="Excluído")
    ds, _ = rodar(T._ObAnulada(corte=CORTE), con, p)
    assert [d.chave for d in ds] == ["010100"] and ds[0].estado == "INCERTO"
    assert ds[0].valores == {"n": 1, "valor": 500.0, "n_ano_anterior": 1, "valor_ano_anterior": 100.0,
                             "diferenca": 400.0}


def test_d20_negativo_ob_paga_nao_conta(db):
    con, p = db
    ob(con, "10/04/2026", "77777777000177", "ETA LTDA", 500.0)
    assert rodar(T._ObAnulada(corte=CORTE), con, p)[0] == []


# ── D01 / D02 ──
def _ct(con, proc, sei, valor, data, cnpj, forn, unidade="SEC X"):
    con.execute("INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?,?,?,?,?)",
                (proc, "1", sei, valor, unidade, data, "SERVIÇO", "Vigente", cnpj, forn))


def _cd(con, sei, enq, forn="ACME LTDA", unidade="SEC X"):
    con.execute("INSERT INTO compras_diretas_tcerj VALUES (?,?,?,?,?,?,?,?,?)",
                (sei, 2026, 1.0, "SERVIÇO", "Dispensa", enq, unidade, forn, "2026-08-09T07:00:00"))


def test_d01_positivo_salto_de_direta(db):
    con, p = db
    _ct(con, "SEI-1", "S1", 12e6, "2026-04-10", "12121212000112", "ACME LTDA")
    _ct(con, "SEI-2", "S2", 4e6, "2026-04-20", "13131313000113", "OUTRA LTDA")
    _cd(con, "S1", "Lei 14.133/2021, Art. 75, II")
    ds, carga = rodar(T._DiretaSalto(corte=CORTE), con, p)
    assert carga.contexto["fim"] == "2026-06-30"
    assert [d.chave for d in ds] == ["SEC X"] and ds[0].estado == "INCERTO" and ds[0].valores["share_direta"] == 0.75


def test_d01_negativo_regime_proprio_fora_da_conta(db):
    con, p = db
    _ct(con, "SEI-1", "S1", 12e6, "2026-04-10", "14141414000114", "ACME LTDA")
    _cd(con, "S1", "Lei 13.303/2016, art. 29")                                    # estatal: regime próprio
    ds, carga = rodar(T._DiretaSalto(corte=CORTE), con, p)
    assert ds == [] and carga.contexto["fora_da_conta"]["n"] == 1


def test_d02_positivo_incumbente(db):
    con, p = db
    # O4.8: o casamento passa por dominio.identidade — CNPJ com DV válido (o de antes não tinha DV válido)
    _ct(con, "SEI-0", "S0", 1e6, "2025-05-01", "11222333000181", "ACME LTDA")     # contrato antes do corte
    _ct(con, "SEI-9", "S9", 3e6, "2026-04-05", "11222333000181", "ACME LTDA")
    _cd(con, "S9", "Lei 14.133/2021, Art. 75, VIII")
    ds, _ = rodar(T._EmergencialIncumbente(corte=CORTE), con, p)
    assert [d.chave for d in ds] == ["SEI-9|1"] and ds[0].estado == "INDICIO"


def test_d02_negativo_fornecedor_sem_contrato_anterior(db):
    con, p = db
    _ct(con, "SEI-9", "S9", 3e6, "2026-04-05", "16161616000116", "NOVA LTDA")
    _cd(con, "S9", "Lei 14.133/2021, Art. 75, VIII", forn="NOVA LTDA")
    det = T._EmergencialIncumbente(corte=CORTE)
    ds, carga = rodar(det, con, p)
    assert ds == [] and det.resumo(carga.itens, ds)["emergenciais_posteriores"] == 1


# ── D16 ──
def _tac(con, data, forn, cnpj, valor):
    con.execute("INSERT INTO doerj_tac VALUES (?,?,?,?,?,?,?)", (data, f"TAC-{data}", "SES", forn, cnpj, valor, "SEI-T"))


def test_d16_positivo_fornecedor_novo_em_tac(db):
    con, p = db
    ob(con, "10/02/2026", "17171717000117", "NOVA SAUDE LTDA", 10.0)               # o credor tem OB (veredito E9)
    _tac(con, "2026-05-01", "NOVA SAUDE LTDA", "17171717000117", 2e6)
    _tac(con, "2026-02-01", "ANTIGA LTDA", "", 5e6)
    _tac(con, "2026-06-01", "ANTIGA LTDA", "", 5e6)                                # já tinha TAC antes: não é novo
    ds, carga = rodar(T._TacAceleracao(corte=CORTE), con, p)
    assert [d.valores["valor_tac"] for d in ds] == [2e6] and carga.contexto["variacao_dia"] is not None


def test_d16_negativo_tac_sem_cnpj_fica_indeterminado(db):
    con, p = db
    _tac(con, "2026-05-01", "SEM CNPJ LTDA", "", 2e6)
    det = T._TacAceleracao(corte=CORTE)
    ds, carga = rodar(det, con, p)
    assert ds == [] and det.resumo(carga.itens, ds)["por_veredito"] == {"?:SEM_LINHA_E9": 1}


def test_corte_e_parametro_nao_constante(db):
    """A mesma régua com outro corte (outra troca de gestão) muda a janela — a constante Couto é só o padrão."""
    con, p = db
    assert T.CONCENTRACAO.corte == "2026-03-23"
    jn = T.janelas(ro(con, p), "2025-01-01")
    assert (jn["corte"], jn["b0"], jn["p0"], jn["p1"]) == ("2025-01-01", "2024-01-01", "2025-01-01", "2024-12-31")


def test_carregar_grupo_reproduz_o_disparo(db):
    con, p = db
    ob(con, "10/04/2026", "11111111000111", "ALFA SERVICOS LTDA", 7e6)
    ob(con, "11/04/2026", "22222222000122", "BETA COMERCIO LTDA", 4e6)
    det = T._Concentracao(corte=CORTE)
    src = ro(con, p)
    d = det.detectar(anotar(det.carregar(src).itens))[0]
    g = det.carregar_grupo(src, d.grupo)
    assert [x.entradas for x in det.detectar(anotar(g.itens), g.contexto)] == [d.entradas]
