# -*- coding: utf-8 -*-
"""Varredura de NE/NL: prioriza a UG de maior valor pago e pula a que já está completa e fresca."""
import sqlite3
import time

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
