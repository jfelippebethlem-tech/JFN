# -*- coding: utf-8 -*-
"""O único gravador de `sei_ficha` não pode ser cego ao cache comprimido.

Defeito medido (31/07/2026). `sei_depurar_db.depurar()` é o ÚNICO caminho que leva uma ficha do
cache para a tabela `sei_ficha` (o painel, os dossiês e as perícias leem de lá), e roda a cada 30
minutos pelo `sweep_sei.sh`. Ele listava o acervo com `CACHE.glob("*.json")`:

    arquivos que ele enxergava        :   564   (233 são blobs `cdp_*`)
    blobs de processo realmente no disco: 6.028
    invisíveis para ele               : 5.795

Consequência medida no banco: 6.007 processos com blob em cache × 4.030 fichas gravadas =
**1.998 processos baixados cuja ficha nunca chegou à tabela**. Não foi coleta que faltou — foi
ingestão amputada quando o cache passou a ser comprimido em zstd para caber 23 GB.

É a mesma cegueira que já existia no `sei_refichar`, e o módulo criado justamente para evitá-la
(`compliance_agent/sei/cache_arquivo`) existia desde então sem este chamador tê-lo adotado. Ler
pelo `glob_cache`/`ler_json` é o que fecha o buraco — e `nome_logico` é obrigatório porque o
número do processo é derivado do NOME do arquivo, que num `.zst` termina em `.json.zst`.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess

import pytest

import tools.sei_depurar_db as D


def _zstd(dados: bytes) -> bytes:
    return subprocess.run(["zstd", "-q", "-c", "-"], input=dados, capture_output=True, check=True).stdout


def _ficha(objeto: str) -> dict:
    return {"numero": None, "ficha": {"objeto": objeto, "nivel_risco": "medio", "relevante": True,
                                      "resumo": "resumo", "analise": "analise"}}


@pytest.fixture()
def acervo(tmp_path, monkeypatch):
    """Cache com um blob CRU e um COMPRIMIDO, e um banco de mentira."""
    cache = tmp_path / "sei_cache"
    cache.mkdir()
    (cache / "cdp_SEI_030001_000111_2024.json").write_text(
        json.dumps(_ficha("objeto do blob cru")), encoding="utf-8")
    (cache / "cdp_SEI_030001_000222_2024.json.zst").write_bytes(
        _zstd(json.dumps(_ficha("objeto do blob comprimido")).encode("utf-8")))
    # ruído que o filtro existente já descartava — tem de continuar descartado
    (cache / "sei_sweep_progress.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(D, "CACHE", cache)
    db = tmp_path / "compliance.db"
    monkeypatch.setattr(D, "DB", db)  # o próprio `_conectar` cria o schema — não substituí-lo
    return db


def _numeros(db) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT numero_sei FROM sei_ficha")}
    finally:
        con.close()


def test_ficha_de_blob_comprimido_chega_a_tabela(acervo):
    """O ponto do defeito: 5.795 blobs `.zst` nunca viravam linha em `sei_ficha`."""
    D.depurar()

    assert "SEI-030001/000222/2024" in _numeros(acervo), (
        "a ficha do blob comprimido não chegou à tabela — a ingestão segue cega ao .zst")


def test_blob_cru_continua_chegando(acervo):
    """Guarda-costas: o caminho que já funcionava não pode regredir."""
    D.depurar()

    assert "SEI-030001/000111/2024" in _numeros(acervo)


def test_numero_sai_do_nome_logico_e_nao_traz_o_sufixo_zst(acervo):
    """O número vem do NOME do arquivo; sem `nome_logico` viria com '.json.zst' grudado."""
    D.depurar()

    assert not any(".zst" in n or ".json" in n for n in _numeros(acervo)), _numeros(acervo)


def test_estado_operacional_nao_vira_ficha(acervo):
    """`sei_sweep_progress.json` mora no mesmo diretório e nunca pode virar linha."""
    D.depurar()

    assert len(_numeros(acervo)) == 2, _numeros(acervo)
