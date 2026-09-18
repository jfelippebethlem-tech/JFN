# -*- coding: utf-8 -*-
"""O nome do arquivo no site da FSERJ carrega tipo, nº, processo e fornecedor — o índice nasce daí (12/09/2026)."""
from __future__ import annotations

from tools.fserj_site_docs import parse_nome

B = "https://www.rj.gov.br/fundacaosaude/sites/default/files/arquivos-paginas/"


def test_padrao_contrato_proc_fornecedor():
    d = parse_nome(B + "CONTRATO%20048.2025_Proc%204203.2023_EXTRACOR%20COMERCIO%20E%20REPRESENTA%C3%87%C3%95ES%20DE%20MATERIAL%20HOSPITALAR%20LTDA.pdf")
    assert d["tipo"] == "CONTRATO" and d["numero"] == "048/2025" and d["processo"] == "SEI-080002/004203/2023"
    assert d["fornecedor"] == "EXTRACOR COMERCIO E REPRESENTACOES DE MATERIAL HOSPITALAR LTDA"


def test_comodato_arp_e_sufixo_duplicata():
    d = parse_nome(B + "CONTRATO-DE-COMODATO-003.2025_Proc.-15863.2024_M4-IMPORTA%C3%87%C3%83O-E-COMERCIO-LTDA.pdf")
    assert d["tipo"] == "COMODATO" and d["numero"] == "003/2025" and d["processo"] == "SEI-080002/015863/2024"
    assert d["fornecedor"].startswith("M4-IMPORTACAO")
    d2 = parse_nome(B + "CONTRATO 093.2025_Proc. 8790.2024_ GRAGER DO BRASIL LTDA_0.pdf")
    assert d2["fornecedor"] == "GRAGER DO BRASIL LTDA" and d2["processo"] == "SEI-080002/008790/2024"


def test_sem_underscore_e_processo_sei_no_nome():
    d = parse_nome(B + "CONTRATO 108.2025 RIO TERUMED COMERCIO DE MATERIAL CIRURGICO LTDA.pdf")
    assert d["numero"] == "108/2025" and d["fornecedor"] == "RIO TERUMED COMERCIO DE MATERIAL CIRURGICO LTDA" and d["processo"] is None
    d2 = parse_nome(B + "CONTRATO 120.2025 SEI-RJ - SEI-080002_016174_2024.pdf")
    assert d2["processo"] == "SEI-080002/016174/2024" and d2["fornecedor"] is None
