# -*- coding: utf-8 -*-
"""Quem lê o cache comprimido também precisa poder ESCREVER nele sem descomprimir o acervo.

Defeito medido (31/07/2026): `tools/sei_refichar.py` — a ferramenta cujo trabalho é levar o acervo
ao schema de ficha atual — fazia `glob.glob('cdp_*.json')` e enxergava **232 de 5.973 caches (3,9%)**.
Os 5.741 `.json.zst` eram invisíveis justamente para ela. Numa amostra de 40 comprimidos: 14 (35%)
sem ficha nenhuma e 30 (75%) em schema anterior ao vigente.

`cache_arquivo` já resolvia a LEITURA transparente (`glob_cache`/`ler_json`), mas não a escrita — e
sem escrita transparente a correção óbvia (`write_text` no caminho do glob) gravaria texto puro por
cima de um `.zst`, corrompendo o blob. Daí `escrever_json`: grava na MESMA forma em que o arquivo
está no disco, e nunca deixa o arquivo pela metade se a escrita morrer no meio.
"""
from __future__ import annotations

import json
import subprocess

from compliance_agent.sei import cache_arquivo as CA


def test_escreve_comprimido_quando_o_arquivo_esta_comprimido(tmp_path):
    """O que era `.zst` continua `.zst` — o acervo não descomprime por escrever nele."""
    alvo = tmp_path / "cdp_SEI_x.json"
    zst = tmp_path / "cdp_SEI_x.json.zst"
    zst.write_bytes(subprocess.run(["zstd", "-q", "-c", "-"], input=b'{"ficha": "velha"}',
                                   capture_output=True, check=True).stdout)

    CA.escrever_json(alvo, {"ficha": "nova"})

    assert zst.exists(), "o blob comprimido tem que continuar existindo"
    assert not alvo.exists(), "não pode nascer uma cópia crua ao lado do comprimido"
    assert CA.ler_json(alvo) == {"ficha": "nova"}


def test_escreve_cru_quando_o_arquivo_esta_cru(tmp_path):
    """O caminho não-comprimido segue igual — nada de comprimir por conta própria."""
    alvo = tmp_path / "cdp_SEI_y.json"
    alvo.write_text('{"ficha": "velha"}', encoding="utf-8")

    CA.escrever_json(alvo, {"ficha": "nova"})

    assert not (tmp_path / "cdp_SEI_y.json.zst").exists()
    assert json.loads(alvo.read_text(encoding="utf-8")) == {"ficha": "nova"}


def test_arquivo_novo_nasce_cru(tmp_path):
    """Sem arquivo prévio não há forma a preservar: nasce `.json`, e a manutenção comprime depois."""
    alvo = tmp_path / "cdp_SEI_z.json"

    CA.escrever_json(alvo, {"ficha": "nova"})

    assert alvo.exists() and CA.ler_json(alvo) == {"ficha": "nova"}


def test_acentuacao_sobrevive_a_ida_e_volta(tmp_path):
    """Ficha do SEI é cheia de acento — `ensure_ascii` estragaria a comparação de conteúdo."""
    alvo = tmp_path / "cdp_SEI_w.json"
    zst = tmp_path / "cdp_SEI_w.json.zst"
    zst.write_bytes(subprocess.run(["zstd", "-q", "-c", "-"], input=b"{}",
                                   capture_output=True, check=True).stdout)

    CA.escrever_json(alvo, {"objeto": "aquisição de mobiliário — pregão nº 3"})

    assert CA.ler_json(alvo)["objeto"] == "aquisição de mobiliário — pregão nº 3"


def test_escrita_interrompida_nao_deixa_blob_pela_metade(tmp_path, monkeypatch):
    """Grava em temporário e só então troca: falha no meio preserva o conteúdo anterior."""
    alvo = tmp_path / "cdp_SEI_v.json"
    alvo.write_text('{"ficha": "velha"}', encoding="utf-8")

    def _explode(*_a, **_kw):
        raise OSError("disco cheio")

    monkeypatch.setattr(CA.Path, "replace", _explode)
    try:
        CA.escrever_json(alvo, {"ficha": "nova"})
    except OSError:
        pass

    assert json.loads(alvo.read_text(encoding="utf-8")) == {"ficha": "velha"}
    assert list(tmp_path.glob("*.tmp")) == [], "temporário não pode ficar para trás"
