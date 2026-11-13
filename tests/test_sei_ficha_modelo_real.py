# -*- coding: utf-8 -*-
"""A ficha registra o modelo que RESPONDEU, e o modelo morto sai do padrão.

Laudo dos motores (13/11/2026): `reflection/beam-1.0-501b-a23b:free` responde 404 "free period
has ended" desde 10/11 (~122 linhas "MORTO (404" nos logs do sweep e da varredura), a troca
automática funciona — e mesmo assim o log do sweep seguia escrevendo `ficha[reflection/beam-1.0…]`
em 12 e 13/11. O rótulo era a CONSTANTE `STEPFUN` (1º da lista), não o modelo que respondeu.
"""
import asyncio
import json

import tools.sei_ficha as sf
import tools.sei_sweep as S


def test_beam_fora_do_padrao():
    assert "beam-1.0" not in sf._PADRAO_SWEEP


def test_rotulo_da_ficha_e_o_modelo_vivo(tmp_path, monkeypatch):
    proc = "SEI-270054/000146/2023"
    cf = tmp_path / "cdp_SEI_270054_000146_2023.json"
    cf.write_text(json.dumps({"numero": proc, "texto": "", "conteudo_documentos": [
        {"doc": "Despacho", "conteudo": "Teor do despacho de autorização da despesa. " * 20}]}),
        encoding="utf-8")
    monkeypatch.setattr(S, "CACHE", tmp_path)
    monkeypatch.setattr(sf, "MODELOS_SWEEP", ["morto:free", "vivo:free"])
    monkeypatch.setattr(sf, "_MORTOS", set())

    async def _fake(texto, model, provider="nous"):
        sf._MORTOS.add("morto:free")          # o 1º caiu durante a chamada; o 2º respondeu
        return {"objeto": "x"}

    monkeypatch.setattr(sf, "extrair_ficha", _fake)
    r = asyncio.run(S._ficha_e_storage(proc))
    assert r is not None
    assert r[2] == "vivo:free"
    assert json.loads(cf.read_text(encoding="utf-8"))["_ficha_modelo"] == "vivo:free"
