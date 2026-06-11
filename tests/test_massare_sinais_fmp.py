# -*- coding: utf-8 -*-
"""Sinais FMP (senate/insider) — normalizadores PUROS, com linhas reais do MCP."""
from __future__ import annotations

from massare import sinais_fmp as S


def test_norm_senate_purchase_e_sale():
    rows = [
        {"symbol": "NVDA", "transactionDate": "2026-05-08", "office": "Sheldon Whitehouse",
         "type": "Sale", "amount": "$100,001 - $250,000",
         "link": "https://efdsearch.senate.gov/x"},
        {"symbol": "PTON", "transactionDate": "2026-06-05", "firstName": "James", "lastName": "Banks",
         "type": "Purchase", "amount": "$1,001 - $15,000", "link": "https://efd/y"},
    ]
    out = S._norm_senate(rows)
    assert out[0]["symbol"] == "NVDA" and out[0]["operacao"] == "sell" and out[0]["ator"] == "Sheldon Whitehouse"
    assert out[1]["operacao"] == "buy" and out[1]["ator"] == "James Banks"


def test_norm_insider_aquisicao_disposicao():
    rows = [
        {"symbol": "kalv", "transactionDate": "2026-06-11", "reportingName": "Palleiko Benjamin L",
         "typeOfOwner": "CEO", "acquisitionOrDisposition": "D", "securitiesTransacted": 479989,
         "price": 0, "url": "https://sec.gov/z"},
        {"symbol": "MSFT", "transactionDate": "2026-06-01", "reportingName": "Fulano",
         "typeOfOwner": "director", "acquisitionOrDisposition": "A", "securitiesTransacted": 100,
         "price": 400.0, "url": "https://sec.gov/w"},
    ]
    out = S._norm_insider(rows)
    assert out[0]["symbol"] == "KALV" and out[0]["operacao"] == "sell"  # D = disposição
    assert out[1]["operacao"] == "buy" and "director" in out[1]["detalhe"]


def test_norm_ignora_sem_symbol():
    assert S._norm_senate([{"transactionDate": "2026-01-01", "type": "Sale"}]) == []
    assert S._norm_insider([{"reportingName": "x", "acquisitionOrDisposition": "A"}]) == []
