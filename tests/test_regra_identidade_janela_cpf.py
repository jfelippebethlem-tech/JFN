# -*- coding: utf-8 -*-
"""Catraca: casar CPF mascarado de FOLHA com o do QSA só pela régua única (`identidade_pessoa`).

A janela que a folha publica VARIA POR FONTE (GESPERJ 4–9, DPRJ 3–8 — controle positivo 13/11 e
19/11/2026). A casa errou isto três vezes com o mesmo atalho: fatiar strings como se toda folha
tivesse a mesma janela (`frag_qsa[0:5] == frag_folha[1:6]`, `d[1:6]`). No sócio-na-folha o atalho
produziu 911 "homônimos" e 0 casamento no Executivo. Esta catraca barra o atalho de volta: comparação
de fragmento de CPF entre bases passa por `posicoes_qsa`/`posicoes_folha`/`comparar_cpf`.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ATALHOS = [
    re.compile(r"\[0:5\]\s*==\s*[\w\"'\]\[]+\[1:6\]"),     # frag_qsa[0:5] == frag_folha[1:6]
    re.compile(r"\[1:6\]\s*==\s*[\w\"'\]\[]+\[0:5\]"),
    re.compile(r"return d\[1:6\] if len\(d\) == 6"),        # 'posições 4-8 da folha' presumindo 3-8
]
PASTAS = ["compliance_agent", "tools", "rotas"]


def test_ninguem_compara_fragmento_de_cpf_fatiando_string():
    achados = []
    for pasta in PASTAS:
        for f in (RAIZ / pasta).rglob("*.py"):
            txt = f.read_text(encoding="utf-8", errors="ignore")
            for rx in ATALHOS:
                for m in rx.finditer(txt):
                    linha = txt.count("\n", 0, m.start()) + 1
                    achados.append(f"{f.relative_to(RAIZ)}:{linha}: {m.group(0)}")
    assert not achados, ("comparação de CPF mascarado presumindo UMA janela para toda folha — use "
                         "compliance_agent.identidade_pessoa (posicoes_qsa/posicoes_folha/comparar_cpf):\n"
                         + "\n".join(achados))
