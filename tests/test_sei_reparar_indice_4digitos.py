# -*- coding: utf-8 -*-
"""Reparo dos arquivos do índice de 3 dígitos: o texto do arquivo atual só é reaproveitado se for do documento certo."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_titulo_confere_so_na_faixa_que_colidia():
    from tools.sei_reparar_indice_4digitos import titulo_confere
    assert titulo_confere(100, "Nota Fiscal 731", "[Nota Fiscal 731] teor")
    assert not titulo_confere(105, "Nota Fiscal 731", "[Despacho 1050] teor de outro documento")
    assert titulo_confere(105, "Nota Fiscal 731", "teor escaneado sem colchete")
    assert titulo_confere(42, "x", "[outro] fora da faixa")


def test_montar_origem_reaproveita_o_certo_e_busca_o_resto(tmp_path, monkeypatch):
    import tools.sei_reparar_indice_4digitos as R
    arq, cache = tmp_path / "arq", tmp_path / "cache"
    monkeypatch.setattr(R, "ARQUIVO", arq)
    monkeypatch.setattr(R, "CACHE", cache)
    (arq / "T" / "texto").mkdir(parents=True)
    (arq / "T" / "texto" / "100_a.txt").write_text("[cab]\n\n[Documento 100] teor certo", encoding="utf-8")
    (arq / "T" / "texto" / "101_b.txt").write_text("[cab]\n\n[Documento 1010] teor alheio", encoding="utf-8")
    antigo = {"docs": [{"i": 100, "texto": "texto/100_a.txt", "ocr_motor": "surya-ocr-2.5"},
                       {"i": 100, "texto": "texto/100_a.txt"},
                       {"i": 101, "texto": "texto/101_b.txt"},
                       {"i": 1000, "nao_capturado": True}, {"i": 1001, "nao_capturado": True}]}
    (cache / "integra_T").mkdir(parents=True)
    (cache / "integra_T" / "1000.txt").write_text("nativo depurado do mil", encoding="utf-8")
    cache_man = {"docs": [{"i": i, "titulo": f"Documento {i}"} for i in (100, 101, 1000, 1001)]}

    buscar, restaurar = R.montar_origem("T", antigo, cache_man, tmp_path / "origem")

    assert (tmp_path / "origem" / "100.txt").read_text(encoding="utf-8") == "[Documento 100] teor certo"
    assert restaurar[100]["ocr_motor"] == "surya-ocr-2.5"
    assert not (tmp_path / "origem" / "101.txt").exists(), "teor de outro documento não é reaproveitado"
    assert (tmp_path / "origem" / "1000.txt").exists()
    assert buscar == [101, 1001]
    assert json.loads((tmp_path / "origem" / "manifest.json").read_text())["docs"][0]["i"] == 100
