# -*- coding: utf-8 -*-
"""Confirmação do OCR por documento/página (plano de reescrita, Fase 5 — dono 23/11/2026: "só entra no lote o que
sabemos ser 100% correto"). Documento de OCR (Tesseract OU IA) só vale quando uma leitura INDEPENDENTE confirma
todos os números críticos e as palavras batem; senão, as páginas com número sem confirmação vão à conferência."""
from compliance_agent.sei import ocr_confirmacao as C

CANON = ("CONTRATO Nº 012/2024. Valor global R$ 483.333,33. Contratada CNPJ 11.222.333/0001-81. "
         "Rio de Janeiro, 12/06/2024. Processo SEI-270066/000314/2022.")


def test_duas_leituras_concordando_confirmam_o_documento():
    outra = CANON.replace("CONTRATO", "C0NTRATO")                     # ruído em palavra, números iguais
    r = C.confirmar(CANON, {"surya_ao_lado": outra})
    assert r["estado"] == "confirmado" and r["numeros_a_conferir"] == [] and r["similaridade"] >= C.LIMIAR_PALAVRAS


def test_numero_divergente_deixa_a_conferir_e_aponta_a_pagina():
    paginada = {1: "CONTRATO Nº 012/2024. Valor global R$ 488.333,33.", 2: "CNPJ 11.222.333/0001-81. 12/06/2024."}
    r = C.confirmar(CANON, {"surya_paginas": paginada})
    assert r["estado"] == "a_conferir"
    assert ("valor", "483333.33") in {(n["tipo"], n["norma"]) for n in r["numeros_a_conferir"]}
    assert r["paginas_a_conferir"] == [1]                               # onde a outra leitura viu o número parecido


def test_sem_segunda_leitura_nao_confirma():
    r = C.confirmar(CANON, {})
    assert r["estado"] == "sem_segunda_leitura"


def test_palavras_muito_diferentes_nao_confirmam_mesmo_com_numeros_iguais():
    lixo = "XKQ ZZW 483.333,33 11.222.333/0001-81 12/06/2024 270066/000314/2022 012/2024 QQQ"
    r = C.confirmar(CANON, {"reserva_ao_lado": lixo})
    assert r["estado"] == "a_conferir" and r["similaridade"] < C.LIMIAR_PALAVRAS


def test_siafe_do_processo_confirma_numero_que_a_outra_leitura_nao_trouxe():
    outra = CANON.replace("R$ 483.333,33", "R$ ...")
    r = C.confirmar(CANON, {"surya_ao_lado": outra}, externos={"siafe_ob": {("valor", "483333.33")}})
    assert r["estado"] == "confirmado"


def test_motor_proprio_nao_confirma_a_si_mesmo():
    assert C.motor_do_doc({"ocr": True}) == "tesseract"
    assert C.motor_do_doc({"ocr_motor": "surya-2.5"}) == "gpu"
    assert C.motor_do_doc({"ocr_motor": "reserva-rapidocr"}) == "reserva"


def test_rotulo_com_ruido_nao_derruba_numero_identico_mas_numero_diferente_derruba():
    assert C.confirmar(CANON, {"x": CANON.replace("CONTRATO", "C0NTRATO")})["estado"] == "confirmado"
    outra = CANON.replace("CONTRATO Nº 012/2024", "C0NTRATO Nº 013/2024")
    r = C.confirmar(CANON, {"x": outra})
    assert r["estado"] == "a_conferir" and r["numeros_a_conferir"][0]["tipo"] == "contrato"
