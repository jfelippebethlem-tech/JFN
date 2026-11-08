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
    # A FILA COMPARTILHADA É ESTADO REAL, e sem isolá-la o acervo sintético desta fixture ficava
    # somado aos 3.617 processos da fila de verdade — os três testes daqui viraram vermelhos no
    # instante em que o arquivo passou a existir (2026-08-07). Um acervo de teste que enxerga o
    # acervo de produção não testa nada: mede o disco da máquina.
    monkeypatch.setattr(R, "COMPARTILHADA", tmp_path / "fila_compartilhada_inexistente.json")
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


def test_fila_da_outra_maquina_entra_e_nao_duplica(acervo, tmp_path, monkeypatch):
    """A ponte entre as duas máquinas: a fila da outra soma, sem repetir o que já se tem.

    POR QUE A PONTE EXISTE. Esta fila nasce do acervo LOCAL, e os acervos das duas máquinas mal se
    tocam — medido em 2026-08-07: 1.515 processos pendentes na VM-1, 96 na VM-2, apenas 45 em
    comum. A fatia (`JFN_SWEEP_FATIA`) só divide trabalho quando as duas veem o MESMO universo;
    sem a fila atravessar, aplicá-la faria cada máquina trabalhar menos sem que a segunda ajudasse
    no atraso da primeira. A recaptura não precisa do arquivo local: precisa do NÚMERO, e lê tudo
    do SEI.
    """
    _arquivo(acervo, "270003_004494_2025", 40, _AVISO_CACHE)
    outra = tmp_path / "compartilhada.json"
    outra.write_text(json.dumps({"itens": [
        # o mesmo processo que já está aqui — não pode entrar duas vezes e gastar dois slots
        {"numero": "270003/004494/2025", "arvore": 90, "lido": 40, "faltam": 50},
        {"numero": "SEI-080002/000999/2024", "arvore": 12, "lido": 10, "faltam": 2},
    ]}), encoding="utf-8")
    monkeypatch.setattr(R, "COMPARTILHADA", outra)

    fila = R.fila()
    numeros = [x["numero"] for x in fila]
    assert len(numeros) == len(set(numeros)), "processo repetido consome dois slots pelo mesmo trabalho"
    assert "SEI-080002/000999/2024" in numeros, "a fila da outra máquina não atravessou"
    vindos = [x for x in fila if x.get("origem") == "fila_da_outra_maquina"]
    assert len(vindos) == 1, "só o que ESTA máquina não tem deve vir de fora"


def test_fila_compartilhada_ausente_nao_quebra(acervo, tmp_path, monkeypatch):
    """Arquivo ausente, ilegível ou vazio é silêncio — nunca erro que derruba a recaptura."""
    monkeypatch.setattr(R, "COMPARTILHADA", tmp_path / "nao_existe.json")
    assert R.fila() == []
    quebrado = tmp_path / "quebrado.json"
    quebrado.write_text("{isso não é json", encoding="utf-8")
    monkeypatch.setattr(R, "COMPARTILHADA", quebrado)
    assert R.fila() == []
