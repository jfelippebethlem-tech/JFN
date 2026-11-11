# -*- coding: utf-8 -*-
"""Pasta do acervo SEM TEXTO não é fila da leitura dupla — é fila de CAPTURA.

Medido em 11/11/2026: `_pendentes()` devolvia 115 processos, **111 com 0 byte de texto**. O
`confrontar()` devolve "processo não está no acervo" sem gravar, a pasta nunca saía da fila e as
4 fatias da lane a retentavam a cada 10 min (400.786 linhas desse erro no log). Quem traz o texto
é a fila de íntegras (`sei_integra_fila._arquivado_ok` já devolve à captura pasta sem texto);
quando o texto chegar, o processo volta sozinho para cá.
"""
import sqlite3

import tools.sei_leitura_dupla as L


def _pasta(raiz, tag, textos):
    t = raiz / tag / "texto"
    t.mkdir(parents=True)
    for i, corpo in enumerate(textos):
        (t / f"{i:03d}.txt").write_text(corpo, encoding="utf-8")


def test_pendentes_ignora_pasta_sem_texto(tmp_path, monkeypatch):
    _pasta(tmp_path, "040014_005088_2025", ["Teor real do documento."])
    _pasta(tmp_path, "270006_010915_2026", [])          # pasta texto/ vazia
    _pasta(tmp_path, "270007_014968_2026", ["", ""])     # .txt de 0 byte
    (tmp_path / "270007_017398_2026").mkdir()            # sem texto/
    monkeypatch.setattr(L, "_ARQ", tmp_path)
    assert L._pendentes(sqlite3.connect(":memory:"), 10) == ["040014/005088/2025"]


def test_pendentes_mantem_ordem_por_tamanho(tmp_path, monkeypatch):
    _pasta(tmp_path, "040014_000001_2025", ["curto"])
    _pasta(tmp_path, "040014_000002_2025", ["bem mais longo que o outro"])
    monkeypatch.setattr(L, "_ARQ", tmp_path)
    assert L._pendentes(sqlite3.connect(":memory:"), 10) == ["040014/000002/2025",
                                                             "040014/000001/2025"]
