# -*- coding: utf-8 -*-
"""Links de investigação HOSPEDADA (consulta interativa, sem cadastro) — função `links`.

Ideia do dono (2026-06-08): além dos enrichers automáticos, agregar os grandes agregadores OSINT
hospedados — você só pesquisa. Gera deep-links já preenchidos com o alvo (CNPJ/nome) para:
- Max Intel (maxintel.org) — 100+ ferramentas grátis, sem cadastro (79 fontes corporativas/contratos/
  compliance + 67 de pessoas/doações);
- OSINT-Brazuca — diretório das fontes BR hospedadas (CNPJ, tribunais, diários, telefonia);
- Bellingcat Online Investigation Toolkit e OSINT Framework — diretórios curados;
- RedeCNPJ — grafo societário interativo;
- JusBrasil / Escavador — processos e menções (mídia/jurídico).

Tudo MANUAL (o JFN só monta o link e registra no dossiê). Honesto: são pistas de aprofundamento, não
dados coletados. Sem chave, sem rede (apenas constrói URLs)."""
from __future__ import annotations

import re
from urllib.parse import quote

from .base import Resultado, agora_iso


def _digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


class InvestigacaoHospedada:
    id = "links_hospedados"
    funcao = "links"

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, nome: str | None = None, cnpj: str | None = None, **_) -> Resultado:
        alvo = (nome or "").strip()
        c = _digitos(cnpj)
        q = quote(alvo or c)
        links = []
        if alvo or c:
            links.append({"fonte": "Max Intel", "categoria": "agregador (corporativo+pessoas)",
                          "url": f"https://maxintel.org/?q={q}",
                          "nota": "100+ ferramentas grátis, sem cadastro"})
            links.append({"fonte": "OSINT Framework", "categoria": "diretório por categoria",
                          "url": "https://osintframework.com/"})
            links.append({"fonte": "Bellingcat Toolkit", "categoria": "diretório curado",
                          "url": "https://bellingcat.gitbook.io/toolkit/"})
            links.append({"fonte": "OSINT-Brazuca", "categoria": "fontes BR (CNPJ/tribunais/diários/telefonia)",
                          "url": "https://github.com/osintbrazuca/osint-brazuca"})
        if c:
            links.append({"fonte": "RedeCNPJ", "categoria": "grafo societário interativo",
                          "url": f"https://redecnpj.com.br/#/?cnpj={c}"})
            links.append({"fonte": "Portal da Transparência", "categoria": "sanções/contratos (BR)",
                          "url": f"https://portaldatransparencia.gov.br/pessoa-juridica/{c}"})
        if alvo:
            links.append({"fonte": "JusBrasil", "categoria": "processos/menções jurídicas",
                          "url": f"https://www.jusbrasil.com.br/busca?q={q}"})
            links.append({"fonte": "Escavador", "categoria": "processos/pessoas/empresas",
                          "url": f"https://www.escavador.com/busca?q={q}"})
        return Resultado(True, {"tipo": "links_manuais", "alvo": alvo or c, "n": len(links), "links": links},
                         self.id, agora_iso())
