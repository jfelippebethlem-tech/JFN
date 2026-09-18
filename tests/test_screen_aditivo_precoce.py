# -*- coding: utf-8 -*-
"""Acréscimo logo após a assinatura: o sinal da CGE, agora medível.

Em 09/08/2026 a CGE apontou na SECID um acréscimo de 45,4% **dezessete dias** após a assinatura.
A precocidade é o que separa planejamento falho (ou direcionamento) de recomposição legítima:
desequilíbrio econômico superveniente não se forma em duas semanas.

Duas armadilhas ficam travadas aqui:
· **Natureza.** Prorrogação, reajuste e reequilíbrio NÃO são acréscimo de escopo — confundi-los foi
  a origem de 45% dos falsos positivos da varredura de execução. A régua é `limites_aditivo`.
· **Percentual não é veredito.** Acréscimo dentro dos 25% do art. 125 é lícito; a precocidade vale
  mesmo abaixo do teto, e passar do teto é um problema SOMADO, marcado à parte.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.screen_aditivo_precoce as S


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, data_assinatura TEXT,"
                " valor_inicial REAL, fornecedor_nome TEXT, orgao_nome TEXT, objeto TEXT)")
    con.execute("CREATE TABLE contrato_aditivo (numero_controle_pncp TEXT, numero_termo TEXT,"
                " objeto TEXT, valor_acrescido REAL, data_assinatura TEXT, tipo_termo TEXT,"
                " processo TEXT, qualif_acrescimo TEXT, qualif_vigencia TEXT,"
                " qualif_reajuste TEXT, fundamento_legal TEXT, prazo_aditado_dias INT)")

    def contrato(ncp, dia, inicial, obj="PAVIMENTACAO ASFALTICA DE VIAS"):
        con.execute("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?)",
                    (ncp, dia, inicial, f"F {ncp}", "SECID", obj))

    def termo(ncp, dia, acresc, obj, fund="Art. 125 da Lei 14.133/2021", prazo=None):
        con.execute("INSERT INTO contrato_aditivo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ncp, "1", obj, acresc, dia, "Termo de Aditamento", "SEI-1",
                     "1", "0", "0", fund, prazo))

    contrato("PRECOCE", "2025-01-01", 99_600_000.0)
    termo("PRECOCE", "2025-01-18", 45_300_000.0, "ACRESCIMO DE QUANTITATIVO DE 45,4%")
    contrato("TARDIO", "2024-01-01", 10_000_000.0)
    termo("TARDIO", "2025-06-01", 2_000_000.0, "ACRESCIMO DE QUANTITATIVO")
    contrato("PRORROGA", "2025-01-01", 10_000_000.0)
    termo("PRORROGA", "2025-01-10", 5_000_000.0,
          "PRORROGACAO DO PRAZO CONTRATUAL POR MAIS 12 MESES",
          fund="Artigo 107 da Lei 14.133/2021", prazo=365)
    contrato("MIUDO", "2025-01-01", 10_000_000.0)
    termo("MIUDO", "2025-01-05", 1_000.0, "ACRESCIMO DE QUANTITATIVO")
    contrato("DENTRO_DO_TETO", "2025-01-01", 10_000_000.0)
    termo("DENTRO_DO_TETO", "2025-01-20", 1_000_000.0, "ACRESCIMO DE QUANTITATIVO")  # 10%
    con.commit()
    con.close()
    return str(p)


def test_pega_o_acrescimo_precoce(db):
    r = {x["contrato"]: x for x in S.medir(db=db)}
    assert "PRECOCE" in r
    assert r["PRECOCE"]["dias"] == 17, "o intervalo tem de ser contado entre as DUAS assinaturas"
    assert r["PRECOCE"]["pct"] == pytest.approx(45.5, abs=0.2)
    assert r["PRECOCE"]["acima_do_teto"] is True and r["PRECOCE"]["teto_pct"] == 25


def test_tardio_fica_de_fora(db):
    assert "TARDIO" not in {x["contrato"] for x in S.medir(db=db)}
    assert "TARDIO" in {x["contrato"] for x in S.medir(db=db, dias=1000)}


def test_prorrogacao_nao_e_acrescimo(db):
    """Art. 107 não consome o teto do art. 125 — foi essa confusão que gerou 45% dos FP."""
    assert "PRORROGA" not in {x["contrato"] for x in S.medir(db=db)}


def test_piso_de_valor(db):
    assert "MIUDO" not in {x["contrato"] for x in S.medir(db=db)}


def test_dentro_do_teto_ainda_e_precoce(db):
    """A precocidade vale mesmo abaixo dos 25%: o screen mede QUANDO, não só QUANTO."""
    r = {x["contrato"]: x for x in S.medir(db=db)}
    assert "DENTRO_DO_TETO" in r and r["DENTRO_DO_TETO"]["acima_do_teto"] is False


def test_ordena_do_mais_precoce_para_o_menos(db):
    dias = [x["dias"] for x in S.medir(db=db)]
    assert dias == sorted(dias)


def test_base_sem_as_tabelas_devolve_vazio(tmp_path):
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert S.medir(db=str(p)) == []


def test_ressalva_nao_afirma_ilicito_e_declara_cobertura():
    assert "lícito" in S.RESSALVA
    assert "Cobertura" in S.RESSALVA


def test_cobertura_sai_declarada(db):
    """"0 achados" sem cobertura lê-se como "nada a apurar" — e a data do termo só passou a ser
    guardada em 2026-08-09, então a tela mede uma FATIA enquanto a recoleta não termina."""
    c = S.cobertura(db=db)
    assert c["estado"] == "medido"
    assert c["termos"] == 5 and c["avaliaveis"] == 5 and c["pct"] == 100.0


def test_cobertura_sem_tabela_nao_mente(tmp_path):
    p = tmp_path / "vazio.db"
    sqlite3.connect(p).close()
    assert S.cobertura(db=str(p))["estado"] == "sem_dado"


def test_cobertura_declara_o_gargalo_que_LIMITA_nao_o_confortavel(db):
    """A tela mede "aditivo DE VALOR precoce". Declarar só a cobertura de DATA (95,1% no acervo)
    fazia "1 achado" parecer conclusão sobre o Estado inteiro, quando 82,8% dos termos não trazem
    valor nenhum — a folga publicada era a da restrição que não manda (medido 2026-08-10, a
    cobertura real é 15,3%)."""
    c = S.cobertura(db=db)
    assert c["estado"] == "medido"
    assert c["avaliaveis"] <= c["com_as_duas_datas"], (
        "avaliáveis não pode passar de quem tem as duas datas — o valor é restrição ADICIONAL")
    assert c["pct"] <= c["pct_so_datas"]
    assert "valor_acrescido" in c["gargalo"]
