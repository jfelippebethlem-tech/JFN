"""Família do processo: citações sem página coletiva do D.O. (25/09/2026)."""
from tools.acervo_regras_e_familia import citacoes


def test_cita_a_contratacao_e_ignora_pagina_coletiva():
    docs = [{"titulo": "Contrato n° 39-2024 (90442094)", "texto": "fundamento no Processo nº SEI-030001/069533/2024"},
            {"titulo": "Nota de Liquidação", "texto": "Processo SEI-030001/069533/2024 e SEI-030001/000071/2025"},
            {"titulo": "Publicação do Contrato (DOERJ)", "texto": "SEI-070002/017819/2023 SEI-180002/002002/2024"}]
    c = citacoes(docs, "SEI-030001/000071/2025")
    assert c == {"SEI-030001/069533/2024": 2}          # o próprio processo e o D.O. ficam fora


def test_documento_que_cita_demais_e_pagina_coletiva_sem_titulo():
    muitos = " ".join(f"SEI-070002/{i:06d}/2023" for i in range(20))
    assert citacoes([{"titulo": "123456789", "texto": muitos}], "SEI-1/1/1") == {}
