# -*- coding: utf-8 -*-
"""Partes puras da captura de fachada sem Google Maps API (tools/fachada_capturar).

A captura em si abre browser (testada ao vivo); aqui garantimos o que é
determinístico: URL do Street View embed SEM chave (não gera cobrança) e a
detecção de 'sem cobertura' pelo texto da página."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.fachada_capturar import url_streetview_embed, sem_cobertura, _slug


def test_url_embed_sem_chave():
    u = url_streetview_embed(-22.9068, -43.1729)
    assert "output=svembed" in u
    assert "cbll=-22.9068,-43.1729" in u
    assert "key=" not in u.lower()          # NUNCA usa API key (sem billing)
    assert u.startswith("https://")


def test_url_embed_heading():
    u = url_streetview_embed(-22.9, -43.1, heading=90)
    assert "cbp=" in u and ",90," in u


def test_sem_cobertura_detecta_texto():
    assert sem_cobertura("Desculpe, não temos imagens aqui.")
    assert sem_cobertura("Sorry, we have no imagery here")
    assert sem_cobertura("no imagery here for this location")
    assert not sem_cobertura("Rua Fulano, 100 — imagem carregada")
    assert not sem_cobertura("")


def test_slug_para_nome_de_arquivo():
    assert _slug("MGS Clean Soluções LTDA") == "mgs_clean_solucoes_ltda"
    assert _slug("19.088.605/0001-04") == "19_088_605_0001_04"
    assert _slug("") == "fachada"
