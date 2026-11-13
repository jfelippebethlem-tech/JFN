# -*- coding: utf-8 -*-
"""Contratação DIRETA grande encabeça a fila do sweep; o valor é só de OB não cancelada.

Confronto CGE × JFN (13/11/2026, vault `notas/cge-irregularidades-x-jfn-2026-11-13.md`): dos 64
processos de contratação direta que a CGE auditou, o JFN não tinha lido NENHUM — 25 estavam no
catálogo e nunca foram abertos. A fila ordenava por "legível > lacuna provada > sinal > valor" e a
modalidade (Inexigibilidade/Dispensa, que o painel de NE da CGE traz) não entrava em lugar nenhum.
Com a base de hoje: 1.156 processos SEI em NE de inexigibilidade/dispensa/emergencial, 227 com OB,
16 acima de R$ 1 mi.

E o valor da fila somava OB de qualquer status: Anulado (R$ 7,06 bi) e Excluído (R$ 8,91 bi)
entravam como se fossem pagamento. Só OB `Contabilizado` é pago.
"""
from __future__ import annotations

import sqlite3

import tools.sei_sweep as S


def _ob(tmp_path, linhas):
    """linhas: (processo, valor, status)"""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, credor TEXT, nome_credor TEXT,"
                " valor REAL, status TEXT, ug_emitente TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,'12345678000199','',?,?,'010100')",
                    linhas)
    con.commit()
    con.close()
    return p


def _ne(tmp_path, linhas):
    """linhas: (tipo_de_licitacao, processos_sei_json, historico)"""
    p = tmp_path / "d.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE cge_ne_credor (tipo_de_licitacao TEXT, processos_sei TEXT, historico TEXT)")
    con.executemany("INSERT INTO cge_ne_credor VALUES (?,?,?)", linhas)
    con.commit()
    con.close()
    return p


def _isola(monkeypatch, db, ne):
    monkeypatch.setattr(S, "DB", db)
    monkeypatch.setattr(S, "DB_DADOS_ABERTOS", ne)
    monkeypatch.setattr(S, "_unidades_legiveis", lambda: {"080002"})
    monkeypatch.setattr(S, "_raizes_com_sinal_osint", lambda: set())
    monkeypatch.setattr(S, "_fila_com_lacuna_provada", lambda con: set())
    monkeypatch.setattr(S, "fatia_desta_maquina", lambda: (0, 1))


def test_modalidades_de_contratacao_direta(tmp_path):
    ne = _ne(tmp_path, [
        ("Inexigibilidade", '["SEI-150013/000138/2026"]', "patrocínio"),
        ("Dispensa de Licitação", '["SEI-090002/000263/2025"]', "limpeza"),
        ("Pregão Eletrônico", '["SEI-080002/000001/2025"]', "aquisição emergencial de insumos"),
        ("Pregão Eletrônico", '["SEI-080002/000002/2025"]', "material de escritório"),
        ("Inexigibilidade", "[]", "sem processo"),
    ])
    assert S._contratacao_direta(ne) == {"1500130001382026", "0900020002632025", "0800020000012025"}


def test_sem_base_de_dados_abertos_nao_quebra(tmp_path):
    assert S._contratacao_direta(tmp_path / "nao_existe.db") == set()


def test_direta_acima_de_1_mi_vem_antes_de_tudo_que_e_infimo(tmp_path, monkeypatch):
    db = _ob(tmp_path, [
        ("SEI-080002/000617/2024", 617.10, "Contabilizado"),        # ínfimo, unidade legível
        ("SEI-080002/009999/2024", 50_000_000.0, "Contabilizado"),   # grande, licitação comum
        ("SEI-150013/000138/2026", 3_940_000.0, "Contabilizado"),    # inexigibilidade, unidade nunca lida
    ])
    ne = _ne(tmp_path, [("Inexigibilidade", '["SEI-150013/000138/2026"]', "patrocínio")])
    _isola(monkeypatch, db, ne)
    fila = [r[0] for r in S._fila(None, 10)]
    assert fila[0] == "SEI-150013/000138/2026", fila
    assert fila.index("SEI-150013/000138/2026") < fila.index("SEI-080002/000617/2024")


def test_direta_pequena_nao_fura_a_fila(tmp_path, monkeypatch):
    """O degrau é para contratação direta GRANDE; a pequena segue a ordem de sempre."""
    db = _ob(tmp_path, [
        ("SEI-080002/009999/2024", 50_000_000.0, "Contabilizado"),
        ("SEI-080002/000263/2025", 70_000.0, "Contabilizado"),
    ])
    ne = _ne(tmp_path, [("Dispensa de Licitação", '["SEI-080002/000263/2025"]', "limpeza")])
    _isola(monkeypatch, db, ne)
    assert [r[0] for r in S._fila(None, 10)] == ["SEI-080002/009999/2024", "SEI-080002/000263/2025"]


def test_ob_anulada_ou_excluida_nao_conta_como_pago(tmp_path, monkeypatch):
    db = _ob(tmp_path, [
        ("SEI-150013/000138/2026", 900_000.0, "Contabilizado"),
        ("SEI-150013/000138/2026", 5_000_000.0, "Anulado"),
        ("SEI-150013/000138/2026", 5_000_000.0, "Excluído"),
        ("SEI-080002/000001/2024", 1_000.0, "Contabilizado"),
    ])
    ne = _ne(tmp_path, [("Inexigibilidade", '["SEI-150013/000138/2026"]', "x")])
    _isola(monkeypatch, db, ne)
    linhas = {r[0]: r[2] for r in S._fila(None, 10)}
    assert linhas["SEI-150013/000138/2026"] == 900_000.0, "Anulado/Excluído não é pagamento"
    # e, com R$ 900 mil pagos de verdade, NÃO chega ao degrau de R$ 1 mi (os R$ 10 mi anulados/
    # excluídos não o promovem): segue atrás da unidade legível, como qualquer outro
    assert [r[0] for r in S._fila(None, 10)][0] == "SEI-080002/000001/2024"
