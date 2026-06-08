# -*- coding: utf-8 -*-
"""Vazamentos/offshore — ICIJ Offshore Leaks (sem API pública: link de busca hospedada, MANUAL)."""
from __future__ import annotations

from urllib.parse import quote

from .base import Resultado, agora_iso


class OffshoreLeaksLink:
    id = "offshoreleaks"
    funcao = "leaks"

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, termo: str, **_) -> Resultado:
        url = f"https://offshoreleaks.icij.org/search?q={quote(termo)}"
        return Resultado(True, {"tipo": "link_manual", "fonte": "ICIJ Offshore Leaks",
                                "url": url, "nota": "Panama/Pandora/Paradise Papers — consulta interativa"},
                         self.id, agora_iso())
