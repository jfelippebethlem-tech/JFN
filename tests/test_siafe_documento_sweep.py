# -*- coding: utf-8 -*-
"""Varredura de NE/NL: prioriza a UG de maior valor pago e pula a que já está completa e fresca."""
import sqlite3
import time
from datetime import datetime

from compliance_agent import siafe_documento as N
from tools import siafe_documento_sweep as W


def _db(tmp_path):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente,exercicio,status,valor,credor)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,2025,?,?,?)", [
        ("A", "Contabilizado", 900.0, "11111111000101"), ("B", "Contabilizado", 500.0, "11111111000101"),
        ("C", "Contabilizado", 100.0, "11111111000101"), ("D", "Anulado", 9e9, "11111111000101"),
        ("E", "Contabilizado", 50.0, "11111111000101"),
        ("F", "Contabilizado", 9e8, "CG0004700")])            # folha: valor alto, mas não é fornecedor
    c.execute("CREATE TABLE siafe_documento_cobertura(tipo,ug_emitente,exercicio,completo,colhidas,em)")
    hoje = time.strftime("%F %T")
    c.executemany("INSERT INTO siafe_documento_cobertura VALUES (?,?,2025,?,0,?)", [
        ("NE", "A", 1, hoje), ("NL", "A", 1, hoje),          # A completa e fresca: pula
        ("NE", "B", 1, hoje), ("NL", "B", 0, hoje),          # B só NE: falta NL
        ("NE", "C", 1, "2020-01-01 00:00:00"), ("NL", "C", 1, "2020-01-01 00:00:00")])   # C velha: refaz
    c.commit()
    c.close()
    return p


def test_fila_por_valor_pago_pulando_completa_e_fresca(tmp_path):
    fila = W.fila(2025, db=_db(tmp_path), max_ugs=10)
    assert fila == [("B", "NL"), ("C", "NE"), ("C", "NL"), ("E", "NE"), ("E", "NL")]   # A fora; D só anulada


def test_limite_de_ugs(tmp_path):
    assert [u for u, _ in W.fila(2025, db=_db(tmp_path), max_ugs=1)] == ["B"]


# ── prazo que cruza a meia-noite (laudo 13/11/2026, 4.5 defeito 2) ────────────────────────────────────────────
# O cron das 23:20 com `--ate 02:55` encerrava NA HORA ("23:20" >= "02:55" como texto): a varredura de 2023
# nunca coletou. Prazo anterior à hora de início é o da MADRUGADA seguinte.


def test_prazo_da_madrugada_e_do_dia_seguinte():
    assert N.prazo_absoluto("02:55", datetime(2026, 11, 13, 23, 20)) == datetime(2026, 11, 14, 2, 55)


def test_prazo_no_mesmo_dia_continua_no_mesmo_dia():
    assert N.prazo_absoluto("04:40", datetime(2026, 11, 13, 3, 10)) == datetime(2026, 11, 13, 4, 40)


def test_execucao_das_23h20_trabalha_ate_a_madrugada(monkeypatch):
    """Critério do laudo: a execução das 23:20 começa a 1ª UG em vez de parar por 'prazo'."""
    agora = {"t": datetime(2026, 11, 13, 23, 20)}
    monkeypatch.setattr(W, "_agora", lambda: agora["t"])
    prazo = N.prazo_absoluto("02:55", W._agora())
    assert W._passou(prazo) is False                     # 23:20 → ainda longe de 02:55 do dia 14
    agora["t"] = datetime(2026, 11, 14, 1, 0)
    assert W._passou(prazo) is False
    agora["t"] = datetime(2026, 11, 14, 2, 55)
    assert W._passou(prazo) is True


def test_coletor_recebe_prazo_absoluto_e_respeita(monkeypatch):
    """O prazo vai para dentro do coletor; em forma absoluta ele não pode reinterpretar 02:55 como 'já passou'."""
    monkeypatch.setattr(N.time, "strftime", lambda fmt: "2026-11-13T23:30" if "T" in fmt else "23:30")
    assert N._passou("2026-11-14T02:55") is False
    monkeypatch.setattr(N.time, "strftime", lambda fmt: "2026-11-14T02:56" if "T" in fmt else "02:56")
    assert N._passou("2026-11-14T02:55") is True


def test_coletor_avulso_normaliza_hhmm_pela_hora_de_inicio():
    assert N._normalizar_prazo("02:55", datetime(2026, 11, 13, 23, 30)) == "2026-11-14T02:55"
    assert N._normalizar_prazo("2026-11-14T02:55", datetime(2026, 11, 13, 23, 30)) == "2026-11-14T02:55"
    assert N._normalizar_prazo(None, datetime(2026, 11, 13, 23, 30)) is None


# ── 19/11/2026: fila de vários exercícios, incremental do ano corrente, parada no login ─────────────────────────

def _db_varios(tmp_path):
    p = tmp_path / "v.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente,exercicio,status,valor,credor)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,'Contabilizado',?,'11111111000101')", [
        ("A", 2026, 900.0), ("B", 2025, 800.0), ("C", 2024, 100.0), ("D", 2026, 50.0)])
    c.execute("CREATE TABLE siafe_documento_cobertura(tipo,ug_emitente,exercicio,completo,colhidas,em)")
    c.executemany("INSERT INTO siafe_documento_cobertura VALUES (?,?,?,?,0,?)", [
        ("NE", "A", 2026, 1, "2026-11-10 03:00:00"), ("NL", "A", 2026, 1, "2026-11-18 03:00:00"),  # NE incremental
        ("NE", "B", 2025, 1, "2026-11-15 03:00:00"), ("NL", "B", 2025, 0, "2026-11-15 03:00:00"),  # NL parcial
        ("NE", "C", 2024, 1, "2026-09-01 03:00:00"), ("NL", "C", 2024, 1, "2026-11-15 03:00:00"),  # NE velha
    ])
    c.execute("CREATE TABLE ne_siafe(numero,ug_emitente,exercicio)")
    c.executemany("INSERT INTO ne_siafe VALUES (?,'A',2026)", [("2026NE00099",), ("2026NE01234",), ("2025NE09999",)])
    c.commit()
    c.close()
    return p


def test_fila_varios_falta_primeiro_depois_incremental_depois_velha(tmp_path):
    f = W.fila_varios((2026, 2025, 2024), db=_db_varios(tmp_path), agora=datetime(2026, 11, 19, 10, 0))
    assert [(x["ug"], x["tipo"], x["exercicio"], x["motivo"]) for x in f] == [
        ("B", "NL", 2025, "parcial"), ("D", "NE", 2026, "nunca_lida"), ("D", "NL", 2026, "nunca_lida"),
        ("A", "NE", 2026, "incremental"), ("C", "NE", 2024, "releitura_30d")]
    inc = [x for x in f if x["motivo"] == "incremental"][0]
    assert inc["a_partir"] == "2026NE01234"          # último do PRÓPRIO ano, não o RP de 2025


def test_passada_para_no_login_e_no_siafe_ocupado():
    assert W._parar({"ok": False, "etapa": "login", "erro": "mfa_sem_codigo"}, "").startswith("login falhou")
    assert W._parar({"rc": 1}, "SIAFE ocupado: {...}") == "SIAFE ocupado por outra coleta"
    assert W._parar({"ok": False, "etapa": "prazo"}, "") is None
    assert W._parar({"ok": True, "ingeridas": 10}, "") is None


def test_bloqueio_judicial_relido_uma_vez_por_dia(tmp_path):
    p = _db_varios(tmp_path)
    assert W.bj_vencido(db=p, agora=datetime(2026, 11, 19, 10, 0)) is True
    c = sqlite3.connect(p)
    c.execute("INSERT INTO siafe_documento_cobertura VALUES ('BJ','TODAS',2026,1,105,'2026-11-19 08:00:00')")
    c.commit()
    c.close()
    assert W.bj_vencido(db=p, agora=datetime(2026, 11, 19, 10, 0)) is False
    assert W.bj_vencido(db=p, agora=datetime(2026, 11, 20, 9, 0)) is True
