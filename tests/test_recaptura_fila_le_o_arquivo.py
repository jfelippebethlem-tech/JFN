# -*- coding: utf-8 -*-
"""A fila de recaptura só olhava o CACHE — e 26 processos truncados não tinham rota nenhuma.

Depois que `manifesto_norm.captura_integra` passou a reconhecer o teto de coleta de 40 documentos
(2026-08-05), 176 arquivos ficaram marcados como captura não íntegra. Medindo as rotas de volta:

  · 137 voltam pela fila do `sweep_sei` — estão no universo de OB do SIAFE;
  ·  57 voltam por esta fila — o cache sabe que a árvore é maior que o lido;
  · união: 150. Os outros **26 eram órfãos**: nenhuma fila os oferecia, e ficariam truncados para
    sempre enquanto o motor os tratava como não-avaliáveis.

Lição aplicada aqui: **reparo se verifica pelo EFEITO, não pela ação**. Ter feito
`_arquivo_incompleto` devolver `True` provava que eles não seriam PULADOS — não que seriam
OFERECIDOS. A régua desta fila passou a ser a mesma do motor, de propósito: o que a avaliação
recusa por captura insuficiente é o que a leitura precisa refazer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import sweep_recaptura_integral as R

_AVISO_CACHE = "arquivo montado a partir do CACHE do sweep: contém o TEXTO dos documentos"


def _arquivo(raiz: Path, tag: str, n_docs: int, aviso: str | None) -> None:
    pasta = raiz / tag
    (pasta / "texto").mkdir(parents=True)
    docs = []
    for i in range(n_docs):
        nome = f"{i:03d}_doc.txt"
        (pasta / "texto" / nome).write_text(
            f"[Doc {i}] (tipo: despacho)\n\nTeor com mais de quarenta caracteres para contar "
            f"como documento efetivamente lido.", encoding="utf-8")
        docs.append({"i": i, "titulo": f"Doc {i}", "tipo": "despacho", "texto": f"texto/{nome}"})
    man = {"processo": tag.replace("_", "/", 2), "docs": docs}
    if aviso:
        man["aviso"] = aviso
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")


@pytest.fixture()
def acervo(tmp_path, monkeypatch):
    arq, cache = tmp_path / "sei_arquivo", tmp_path / "sei_cache"
    arq.mkdir()
    cache.mkdir()
    monkeypatch.setattr(R, "ARQUIVO", arq)
    monkeypatch.setattr(R, "CACHE", cache)
    return arq


def test_arquivo_truncado_sem_cache_entra_na_fila(acervo):
    """O órfão: teto de coleta no arquivo e nenhum `cdp_*.json` que o denuncie."""
    _arquivo(acervo, "270003_004494_2025", 40, _AVISO_CACHE)
    numeros = {x["numero"] for x in R.fila()}
    assert "270003/004494/2025" in numeros
    assert all(x.get("origem") == "arquivo_nao_integro" for x in R.fila())


def test_arquivo_integro_nao_entra(acervo):
    """39 documentos vindos do cache é contagem natural — não é teto."""
    _arquivo(acervo, "270003_000111_2025", 39, _AVISO_CACHE)
    assert R.fila() == []


def test_arquivo_de_outra_origem_com_40_docs_nao_entra(acervo):
    """Sem o aviso do cache, 40 é só um número."""
    _arquivo(acervo, "270003_000222_2025", 40, aviso=None)
    assert R.fila() == []
