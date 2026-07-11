# -*- coding: utf-8 -*-
"""C2 — termos aditivos do PNCP (api/pncp/v1)."""
import json
from pathlib import Path

from compliance_agent.collectors import pncp

FIX = json.loads((Path(__file__).parent / "fixtures" / "contratos" / "pncp_termos.json").read_text())


def test_parse_termo():
    row = pncp._parse_termo(FIX[0])
    assert row["valor_acrescido"] == 37313280.0
    assert "prorroga" in (row["objeto"] or "").lower()
    assert row["vigencia_fim"] == "2028-03-31"
