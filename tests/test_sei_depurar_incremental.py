# -*- coding: utf-8 -*-
"""A ingestão precisa reler só o que mudou — a passada completa não cabe no relógio do sweep.

Medido em 31/07/2026, depois de a ingestão deixar de ser cega ao `.zst`: varrer os 6.428 blobs do
acervo leva **502–587 s**. O chamador é `tools/sweep_sei.sh`, que roda a cada 30 minutos com
`timeout 300`. Ou seja: a leitura completa seria MORTA no meio, toda rodada — e a correção da
cegueira teria trocado "não enxerga" por "é abortada", que é pior porque parece funcionar.

Somado a isso, reler 6.428 blobs comprimidos a cada meia hora numa VM de 2 vCPU compete com o
próprio sweep e com o Chromium (a regra da casa é um pesado por vez).

Então a ingestão passa a ser incremental por mtime: só entra o blob tocado depois da última
passada. Duas travas de segurança, porque marca d'água silenciosa é armadilha clássica:
  • tabela vazia ⇒ passada COMPLETA (banco novo/restaurado não pode ficar meio populado para sempre);
  • `--tudo` força a passada completa quando se quer reprocessar o acervo.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess

import pytest

import tools.sei_depurar_db as D


def _blob(cache, numero: str, objeto: str, *, comprimido=False, mtime=None):
    dados = json.dumps({"ficha": {"objeto": objeto, "nivel_risco": "medio", "relevante": True,
                                  "resumo": "r", "analise": "a"}}).encode("utf-8")
    nome = f"cdp_SEI_{numero}.json"
    if comprimido:
        p = cache / (nome + ".zst")
        p.write_bytes(subprocess.run(["zstd", "-q", "-c", "-"], input=dados,
                                     capture_output=True, check=True).stdout)
    else:
        p = cache / nome
        p.write_bytes(dados)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


@pytest.fixture()
def acervo(tmp_path, monkeypatch):
    cache = tmp_path / "sei_cache"
    cache.mkdir()
    monkeypatch.setattr(D, "CACHE", cache)
    monkeypatch.setattr(D, "DB", tmp_path / "compliance.db")
    monkeypatch.setattr(D, "MARCA", tmp_path / ".watermark")
    return cache


def _numeros(db) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT numero_sei FROM sei_ficha")}
    finally:
        con.close()


def test_primeira_passada_com_banco_vazio_le_tudo(acervo, tmp_path):
    """Banco vazio ⇒ passada completa, mesmo com blobs antigos."""
    _blob(acervo, "030001_000111_2024", "antigo", mtime=1_700_000_000)
    _blob(acervo, "030001_000222_2024", "antigo comprimido", comprimido=True, mtime=1_700_000_000)

    r = D.depurar()

    assert r["arquivos"] == 2
    assert len(_numeros(tmp_path / "compliance.db")) == 2


def test_segunda_passada_pula_o_que_nao_mudou(acervo):
    """O ganho: sem blob novo, a rodada seguinte não relê o acervo inteiro."""
    _blob(acervo, "030001_000111_2024", "a", mtime=1_700_000_000)
    D.depurar()

    r = D.depurar()

    assert r["arquivos"] == 0, f"releu {r['arquivos']} arquivo(s) sem necessidade"


def test_blob_tocado_depois_da_marca_entra_na_rodada_seguinte(acervo, tmp_path):
    """O refichador reescreve o blob — a ingestão TEM de pegar isso na próxima passada."""
    _blob(acervo, "030001_000111_2024", "a", mtime=1_700_000_000)
    D.depurar()
    _blob(acervo, "030001_000999_2024", "recem chegado")  # mtime = agora

    r = D.depurar()

    assert r["arquivos"] == 1
    assert "SEI-030001/000999/2024" in _numeros(tmp_path / "compliance.db")


def test_tudo_forca_a_passada_completa(acervo):
    """Escotilha de manutenção: reprocessar o acervo sem ter de apagar a marca à mão."""
    _blob(acervo, "030001_000111_2024", "a", mtime=1_700_000_000)
    D.depurar()

    assert D.depurar(completo=True)["arquivos"] == 1


def test_banco_esvaziado_volta_a_ler_tudo(acervo, tmp_path):
    """Marca d'água não pode deixar um banco restaurado do zero pela metade para sempre."""
    _blob(acervo, "030001_000111_2024", "a", mtime=1_700_000_000)
    D.depurar()
    con = sqlite3.connect(tmp_path / "compliance.db")
    con.execute("DELETE FROM sei_ficha")
    con.commit()
    con.close()

    assert D.depurar()["arquivos"] == 1, "com a tabela vazia a passada tem de ser completa"
