# -*- coding: utf-8 -*-
"""Gabarito SIAFE do OCR: a impressão de NL/NE/OB anexada ao processo traz CNPJ do credor e valor que o SIAFE tem
em campo estruturado — gabarito de graça, em milhares de páginas reais, para medir o acerto de cada motor de OCR.
O documento NATIVO (texto do próprio PDF) é o controle positivo: se ele não bate, a casação está errada e a medida
não vale."""
from __future__ import annotations

import json
import sqlite3

from tools import sei_ocr_gabarito_siafe as G


def test_chave_do_titulo():
    assert G.chave_do_titulo("Nota de Liquidação - NL 2025NL00990 (104293632)") == ("NL", "2025NL00990")
    assert G.chave_do_titulo("Anexo OB 2024 OB 12345") == ("OB", "2024OB12345")
    assert G.chave_do_titulo("Nota de Empenho Original - NE 2025NE00741") == ("NE", "2025NE00741")
    assert G.chave_do_titulo("Despacho de encaminhamento") is None


def test_valor_br():
    assert G.valor_br(153600.0) == "153.600,00"
    assert G.valor_br(42) == "42,00"
    assert G.valor_br("111.430,02") == "111.430,02"
    assert G.valor_br(None) is None


def test_referencia_exige_ug_no_texto_e_unica():
    linhas = [("296100", "10435993000188", 153600.0), ("243200", "17204881000165", 412717.65)]
    corpo = "Unidade Gestora 243200 - INSTITUTO ESTADUAL DO AMBIENTE ... 412.717,65"
    assert G.referencia(linhas, corpo) == ("243200", "17204881000165", 412717.65)
    assert G.referencia(linhas, "sem unidade nenhuma") is None
    assert G.referencia(linhas, "243200 e 296100 no mesmo texto") is None, "ambígua não vale"


def test_conferir_cnpj_e_valor():
    corpo = "Credor 17.204.881/0001-65 - Construtora\nValor Bruto 412.717,65"
    assert G.conferir(corpo, "17204881000165", 412717.65) == {"cnpj": True, "valor": True}
    assert G.conferir(corpo.replace("412.717,65", "412.711,65"), "17204881000165", 412717.65)["valor"] is False


def test_motor():
    assert G.motor({"ocr": "False"}) == "nativo"
    assert G.motor({"ocr": "True"}) == "tesseract"
    assert G.motor({"ocr": True, "ocr_motor": "surya-2.5"}) == "surya"
    assert G.motor({"ocr": True, "ocr_motor": "reserva-rapidocr"}) == "reserva"


def _acervo(tmp_path, docs):
    pasta = tmp_path / "arq" / "243201_000001_2024"
    (pasta / "texto").mkdir(parents=True)
    man = {"processo": "243201/000001/2024", "docs": []}
    for i, (titulo, corpo, ocr) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (pasta / rel).write_text(f"[{titulo}] (fase: x · tipo: y)\n\n{corpo}", encoding="utf-8")
        man["docs"].append({"i": str(i), "titulo": titulo, "texto": rel, "ocr": str(ocr)})
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("create table nl_siafe (numero, ug_emitente, credor, valor)")
    con.execute("create table ne_siafe (numero, ug_emitente, credor, valor)")
    con.execute("create table ob_orcamentaria_siafe (numero_ob, ug_emitente, credor, valor)")
    con.executemany("insert into nl_siafe values (?,?,?,?)", [
        ("2024NL00001", "243200", "17204881000165", 412717.65),
        ("2024NL00002", "243200", "17204881000165", 1000.0),
        ("2024NL00003", "243200", "17204881000165", 2000.0)])
    con.commit(); con.close()
    return tmp_path / "arq", db


def test_medir_ponta_a_ponta_com_controle_positivo(tmp_path):
    arq, db = _acervo(tmp_path, [
        ("Nota de Liquidação - NL 2024NL00001", "UG 243200 credor 17204881000165 valor 412.717,65", False),
        ("Nota de Liquidação - NL 2024NL00002", "UG 243200 credor 17204881000165 valor 1.000,00", True),
        ("Nota de Liquidação - NL 2024NL00003", "UG 243200 credor 1720488I000165 valor 2.0O0,00", True),
        ("Despacho", "nada", False)])
    r = G.medir(arq, db, limite_pastas=10)
    assert r["por_motor"]["nativo"] == {"n": 1, "cnpj": 1, "valor": 1}
    assert r["por_motor"]["tesseract"] == {"n": 2, "cnpj": 1, "valor": 1}
    assert r["controle_positivo_ok"] is True
    assert r["erros"][0]["numero"] == "2024NL00003"


def test_controle_positivo_baixo_invalida_a_medida(tmp_path):
    arq, db = _acervo(tmp_path, [
        ("Nota de Liquidação - NL 2024NL00001", "UG 243200 credor 99999999000199 valor 1,00", False)])
    r = G.medir(arq, db, limite_pastas=10)
    assert r["controle_positivo_ok"] is False and "NÃO" in r["veredito"]
