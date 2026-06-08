# -*- coding: utf-8 -*-
"""Detector de conluio entre propostas (bid-rigging): markup uniforme, preços idênticos, texto similar."""
from __future__ import annotations
from compliance_agent.sei import conluio_propostas as C

# descrições REAIS e distintas (produtos diferentes) — como numa tabela de ARP de verdade
_DESC = ["Notebook corporativo i7 16GB", "Monitor LED 24 polegadas full hd",
         "Impressora laser monocromatica", "Switch gerenciavel 48 portas",
         "Servidor rack dois processadores"]


def _itens(precos):
    return [{"descricao": _DESC[i], "valor_unitario": p} for i, p in enumerate(precos)]


def test_markup_uniforme_detecta_cobertura():
    a = _itens([100, 200, 300, 400])
    b = _itens([95, 190, 285, 380])  # exatamente -5% em toda a lista
    mu = C.markup_uniforme(a, b)
    assert mu is not None and round(mu["pct"]) == -5 and mu["n_itens"] == 4


def test_markup_nao_dispara_quando_aleatorio():
    a = _itens([100, 200, 300, 400])
    b = _itens([97, 215, 280, 410])  # variação irregular → não é cobertura
    assert C.markup_uniforme(a, b) is None


def test_precos_identicos():
    a = _itens([100, 200, 300])
    b = _itens([100, 200, 300])
    assert C.precos_identicos(a, b) is not None


def test_texto_similar():
    # ≥20 tokens DISTINTOS (len>3) nos dois
    base = ("clausula tecnica especificacao detalhada fornecimento garantia prazo entrega instalacao suporte "
            "manutencao treinamento documentacao certificado homologacao compatibilidade desempenho seguranca "
            "qualidade durabilidade assistencia configuracao integracao")
    assert C.texto_similar(base, base)["jaccard"] >= 0.85
    assert C.texto_similar(base, "texto totalmente diferente versando sobre outro assunto qualquer presente aqui agora") is None


def test_detectar_par_a_par():
    props = [
        {"fornecedor": "EMPRESA A", "itens": _itens([100, 200, 300, 400])},
        {"fornecedor": "EMPRESA B", "itens": _itens([95, 190, 285, 380])},
        {"fornecedor": "EMPRESA C", "itens": _itens([130, 260, 390, 520])},
    ]
    r = C.detectar(props)
    assert r["ok"] and r["n_propostas"] == 3
    mu = [i for i in r["indicios"] if i["tipo"] == "markup_uniforme"]
    assert any(x["a"] == "EMPRESA A" and x["b"] == "EMPRESA B" for x in mu)
