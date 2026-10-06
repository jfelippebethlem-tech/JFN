# -*- coding: utf-8 -*-
"""Veredito por blob — o que devolve a janela do lane ao trabalho útil.

Medido em 2026-08-27: `ler_json` custa ~715 ms por cache (blobs com 11,9 MB descomprimidos em
média) e 3.494 caches sem arquivo davam 42 min por varredura — mais que o `timeout 1500` do lane,
que por isso NUNCA completava. Amostrando 90 deles, ZERO era arquivável: 90% amostra trimada.
Guardar o veredito impede reabrir o mesmo blob inútil em todo disparo.

A alternativa tentadora — cortar por TAMANHO EM DISCO (87% têm <20 KB) — foi DERRUBADA pelo
controle positivo: entre 60 blobs pequenos, 8 eram arquiváveis, um com 40.119 caracteres.
"""
import json

import pytest


def test_veredito_invalida_quando_o_blob_muda(tmp_path, monkeypatch):
    """A marca é o mtime: blob reescrito tem de ser reavaliado, não pulado para sempre."""
    from tools import sei_arquivar_do_cache as m

    arq = tmp_path / ".cache_veredito.json"
    monkeypatch.setattr(m, "_VEREDITOS", arq)
    m._grava_vereditos({"cdp_x.json": "1000"})
    assert m._ler_vereditos() == {"cdp_x.json": "1000"}

    # mesmo nome, mtime diferente → a comparação falha e o blob volta a ser aberto
    assert m._ler_vereditos().get("cdp_x.json") != "2000"


def test_grava_MESCLANDO_e_nao_sobrescrevendo(tmp_path, monkeypatch):
    """Dois disparos do lane podem se sobrepor; sobrescrever apagaria o trabalho do outro."""
    from tools import sei_arquivar_do_cache as m

    arq = tmp_path / ".cache_veredito.json"
    monkeypatch.setattr(m, "_VEREDITOS", arq)
    m._grava_vereditos({"a.json": "1"})
    m._grava_vereditos({"b.json": "2"})
    d = m._ler_vereditos()
    assert d == {"a.json": "1", "b.json": "2"}, f"perdeu entrada alheia: {d}"


def test_arquivo_ausente_ou_corrompido_nao_derruba(tmp_path, monkeypatch):
    """Sem veredito guardado, a varredura roda normalmente — o cache é otimização, não requisito."""
    from tools import sei_arquivar_do_cache as m

    arq = tmp_path / "nao_existe.json"
    monkeypatch.setattr(m, "_VEREDITOS", arq)
    assert m._ler_vereditos() == {}

    ruim = tmp_path / "ruim.json"
    ruim.write_text("{ isto não é json", encoding="utf-8")
    monkeypatch.setattr(m, "_VEREDITOS", ruim)
    assert m._ler_vereditos() == {}
