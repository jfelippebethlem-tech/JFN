# -*- coding: utf-8 -*-
"""Extração pública do PCA (SIGA): csv ';' com BOM vira itens numéricos (12/09/2026)."""
from __future__ import annotations

from tools.siga_pca import ler_csv

_CSV = ("﻿PCA;Unidade;Data de Publicação PNCP;ID do PNCP;Código do Item;Descrição do Item;Quantidade;Vl. Unitário;Vl. Total;PLOA/LOA;Data Desejada;Situação;Ano Vigência PCA\n"
        "294200/00001/2026;FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO;31/07/2025;42498600000171-0-000028/2026;130886;TIPO SERVICO: APOIO TECNICO ASSISTENCIAL;1,0;956031176,0000;956031176,0000;956031176,0000;02/01/2026;Publicado;2026\n").encode("utf-8")


def test_le_csv_com_bom_e_decimais_brasileiros():
    (i,) = ler_csv(_CSV)
    assert i["pca"] == "294200/00001/2026" and i["unidade"].startswith("FUNDACAO SAUDE")
    assert i["vl_total"] == 956031176.0 and i["quantidade"] == 1.0 and i["data_desejada"] == "02/01/2026"
