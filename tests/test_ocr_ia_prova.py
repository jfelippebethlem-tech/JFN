# -*- coding: utf-8 -*-
"""Trava de prova do OCR por IA (`compliance_agent/sei/ocr_ia_prova`): número de documento de IA só é prova
confirmado; doc não-IA inalterado."""
import json

import pytest

from compliance_agent.sei import ocr_ia_prova as P

CNPJ = "11.222.333/0001-81"          # DV válido
DOC_IA = {"i": 7, "ocr": True, "ocr_motor": "surya-ocr-2.5 (vLLM, RTX 5070, it-campo)", "texto": "texto/007_nf.txt",
          "titulo": "Nota Fiscal 187"}
DOC_TESS = {"i": 3, "ocr": True, "ocr_motor": "tesseract", "texto": "texto/003_x.txt"}
DOC_NATIVO = {"i": 2, "ocr": False, "texto": "texto/002_contrato.txt"}


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    lg = tmp_path / "conf.jsonl"
    monkeypatch.setattr(P, "LEDGER", lg)
    return lg


def test_doc_nao_ia_inalterado():
    assert P.vale_como_prova("T", DOC_NATIVO, "cnpj", CNPJ)
    assert P.vale_como_prova("T", DOC_TESS, "valor", "1.234,56")
    txt = f"CNPJ {CNPJ} R$ 1.234,56"
    assert P.texto_para_prova("/x/T", DOC_NATIVO, txt) == txt


def test_reserva_tambem_e_ia():
    assert P.eh_ocr_ia({"ocr_motor": "reserva:rapidocr"})
    assert not P.eh_ocr_ia({"ocr_motor": ""}) and not P.eh_ocr_ia(None)


def test_numero_de_ia_nao_confirmado_nao_vira_prova():
    assert not P.vale_como_prova("T", DOC_IA, "cnpj", CNPJ)
    txt = f"Prestador CNPJ {CNPJ} valor total R$ 100.033,95 em 05/03/2025"
    m = P.texto_para_prova("/x/T", DOC_IA, txt)
    assert CNPJ not in m and "100.033,95" not in m and "05/03/2025" not in m
    assert m.count(P.MARCA) == 3 and m.startswith("Prestador CNPJ ")    # texto continua legível


def test_confirmado_por_tesseract_vira_prova():
    nums = P.extrair(f"CNPJ {CNPJ} total R$ 100.033,95")
    r = P.confirmar_numeros(nums, {"tesseract": f"CNPJ: {CNPJ.replace('.', '')} TOTAL 100.033.95"})
    assert {x["estado"] for x in r} == {"confirmado"} and {x["fonte"] for x in r} == {"tesseract"}
    P.registrar([{"tag": "T", "i": 7, **x} for x in r])
    assert P.vale_como_prova("T", DOC_IA, "cnpj", CNPJ)
    assert P.vale_como_prova("T", DOC_IA, "valor", "R$ 100.033,95")
    assert P.texto_para_prova("/x/T", DOC_IA, f"CNPJ {CNPJ}") == f"CNPJ {CNPJ}"


def test_divergente_fica_fora_da_prova_com_as_duas_leituras():
    nums = P.extrair("total R$ 100.033,95")
    r = P.confirmar_numeros(nums, {"tesseract": "total R$ 100.083,95"})
    assert r[0]["estado"] == "divergente" and r[0]["leitura_2"] == "100083.95" and r[0]["norma"] == "100033.95"
    P.registrar([{"tag": "T", "i": 7, **x} for x in r])
    assert not P.vale_como_prova("T", DOC_IA, "valor", "100.033,95")


def test_sem_segunda_fonte_fica_a_conferir():
    r = P.confirmar_numeros(P.extrair("em 05/03/2025"), {"tesseract": "texto sem número nenhum"})
    assert r[0]["estado"] == "a_conferir"


def test_fonte_externa_e_outro_documento_confirmam():
    nums = P.extrair(f"CNPJ {CNPJ} valor 5.000,00 data 05/03/2025")
    r = {x["tipo"]: x for x in P.confirmar_numeros(
        nums, {}, externos={"siafe_ob": {("valor", "5000.00")}},
        outros_docs={"documento_2": {("cnpj", "11222333000181"), ("data", "2025-03-05")}})}
    assert r["valor"]["estado"] == "confirmado" and r["valor"]["fonte"] == "siafe_ob"
    assert r["cnpj"]["estado"] == "confirmado" and r["cnpj"]["fonte"] == "documento_2"
    assert r["data"]["estado"] == "a_conferir"        # data coincide por acaso: outro documento não confirma


def test_decisao_humana_prevalece_sobre_automatica(ledger):
    P.registrar([{"tag": "T", "i": 7, "tipo": "cnpj", "norma": "11222333000181", "estado": "confirmado",
                  "fonte": "tesseract"}])
    P.registrar([{"tag": "T", "i": 7, "tipo": "cnpj", "norma": "11222333000181", "estado": "errado",
                  "por": "jorge"}])
    P.registrar([{"tag": "T", "i": 7, "tipo": "cnpj", "norma": "11222333000181", "estado": "confirmado",
                  "fonte": "tesseract"}])                       # lote automático depois não desfaz o humano
    assert not P.vale_como_prova("T", DOC_IA, "cnpj", CNPJ)
    assert all(json.loads(ln)["em"] for ln in ledger.read_text().splitlines())


def test_cnpj_com_dv_invalido_nao_e_extraido():
    assert P.extrair("CNPJ 11.222.333/0001-82") == []


def test_mascarar_sobreposto_nao_corrompe():
    t = "Contrato nº 012/2024 e R$ 1,00"
    m = P.mascarar(t, P.extrair(t))
    assert m == f"{P.MARCA} e R$ {P.MARCA}"


def test_paginas_da_ia():
    bruto = "[página 1]\nnada\n\n[página 2]\nR$ 1.234,56\n"
    pp = P.paginas_da_ia(bruto)
    assert set(pp) == {1, 2} and P.paginas_com(P.extrair("1.234,56"), pp) == [2]


def test_nf_nao_pega_contador_de_pagina_do_portal():
    nfs = [n["norma"] for n in P.extrair("Portal da Nota Fiscal Eletrônica\n1217/429 | |") if n["tipo"] == "nf"]
    assert nfs == []
    assert [n["norma"] for n in P.extrair("NF-e\nN. 000001536\nSÉRIE 1") if n["tipo"] == "nf"] == ["1536"]
    assert [n["norma"] for n in P.extrair("Número da NFS-e: 187") if n["tipo"] == "nf"] == ["187"]
