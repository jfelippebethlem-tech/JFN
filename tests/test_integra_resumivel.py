# -*- coding: utf-8 -*-
"""Resumibilidade do arquivo (fix 2026-07-03): stub (manifest sem texto) NÃO conta como arquivado."""
from tools.sei_integra_fila import _arquivado_ok


def test_stub_manifest_sem_texto_reprocessa(tmp_path):
    d = tmp_path / "120228_000263_2023"
    d.mkdir()
    (d / "manifest.json").write_text('{"docs": []}')
    assert _arquivado_ok(d) is False  # stub → re-baixa


def test_arquivo_com_texto_e_completo(tmp_path):
    d = tmp_path / "270006_032910_2024"
    (d / "texto").mkdir(parents=True)
    (d / "texto" / "001_despacho.txt").write_text("conteudo real")
    (d / "manifest.json").write_text('{"docs": [1]}')
    assert _arquivado_ok(d) is True


def test_dir_inexistente(tmp_path):
    assert _arquivado_ok(tmp_path / "nao_existe") is False
