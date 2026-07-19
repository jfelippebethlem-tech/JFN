# -*- coding: utf-8 -*-
"""spiderfoot_bridge — parse do JSON, score (vazio=1.0), guarda de elegibilidade e INDISPONÍVEL.

Não roda o SpiderFoot de verdade: JSON-fixture sintético + monkeypatch da presença do binário.
"""
from __future__ import annotations

import json
from pathlib import Path

from compliance_agent.enriquecimento import spiderfoot_bridge as sf

# Amostra realista de `sf.py -o json` (array de eventos {generated,type,data,module,source}).
_FIXTURE = json.dumps([
    {"generated": 1, "type": "INTERNET_NAME", "data": "lojax.com.br", "module": "sfp_dns", "source": "lojax.com.br"},
    {"generated": 2, "type": "DOMAIN_NAME", "data": "lojax.com.br", "module": "sfp_dns", "source": "lojax.com.br"},
    {"generated": 3, "type": "IP_ADDRESS", "data": "200.1.2.3", "module": "sfp_dns", "source": "lojax.com.br"},
    {"generated": 4, "type": "PROVIDER_MAIL", "data": "google.com", "module": "sfp_dns", "source": "lojax.com.br"},
    {"generated": 5, "type": "SOCIAL_MEDIA", "data": "instagram: lojax", "module": "sfp_social", "source": "lojax.com.br"},
    {"generated": 6, "type": "LINKED_URL_INTERNAL", "data": "https://lojax.com.br/sobre", "module": "sfp_spider", "source": "lojax.com.br"},
])


def test_parse_conta_tipos_e_flags():
    f = sf._parse_saida(_FIXTURE)
    assert f is not None
    assert f["n_achados"] == 6
    assert f["tipos"]["INTERNET_NAME"] == 1
    assert f["tem_site"] is True    # INTERNET_NAME / DOMAIN_NAME / LINKED_URL
    assert f["tem_mx"] is True      # PROVIDER_MAIL
    assert f["tem_redes"] is True   # SOCIAL_MEDIA
    assert "6 achados" in f["resumo"]


def test_parse_vazio():
    f = sf._parse_saida("[]")
    assert f["n_achados"] == 0
    assert f["tem_site"] is False and f["tem_mx"] is False and f["tem_redes"] is False
    assert "vazio" in f["resumo"]


def test_parse_malformado_indisponivel():
    assert sf._parse_saida("nao e json {{{") is None


def test_score_vazio_e_maximo():
    assert sf.score_footprint({"n_achados": 0}) == 1.0


def test_score_rico_proximo_de_zero():
    f = sf._parse_saida(_FIXTURE)          # 6 achados
    s = sf.score_footprint(f)
    assert 0.0 < s < 0.6                   # footprint com rastro → longe de 1.0
    assert sf.score_footprint({"n_achados": 40}) < 0.05


def test_score_none_propaga():
    assert sf.score_footprint(None) is None


def test_footprint_binario_ausente_retorna_none(monkeypatch):
    monkeypatch.setattr(sf, "_SF_PY", Path("/nao/existe/python"))
    monkeypatch.setattr(sf, "_SF_SCRIPT", Path("/nao/existe/sf.py"))
    assert sf.footprint("lojax.com.br") is None


def test_elegivel_limiar():
    assert sf.elegivel(50) is True
    assert sf.elegivel(75.0) is True
    assert sf.elegivel(49) is False
    assert sf.elegivel(None) is False
