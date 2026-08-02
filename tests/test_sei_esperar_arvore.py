# -*- coding: utf-8 -*-
"""`_esperar_arvore` tem de esperar o CONTEÚDO da árvore, não só o frame existir.

Defeito real (2026-08-02): o frame `ifrArvore` nasce VAZIO e a árvore pinta segundos depois.
A espera antiga retornava assim que achava o frame (mais 2s fixos), então sob carga a extração
lia 0 documentos e o processo virava **falso INDISPONÍVEL** — 5 processos numa recaptura, todos
legíveis na re-tentativa (um deles devolveu 49 docs no minuto seguinte). INDISPONÍVEL ≠ 0.
"""
import asyncio

import pytest

from tools import sei_reader


class _FrameFake:
    """Frame que só ganha os nós da árvore depois de N consultas ao HTML."""

    def __init__(self, name="ifrArvore", url="…/arvore.php", pinta_apos=0):
        self.name = name
        self.url = url
        self._pinta_apos = pinta_apos
        self.consultas = 0

    async def content(self):
        self.consultas += 1
        return ("<a class='infraArvoreNo'>doc</a>" if self.consultas > self._pinta_apos
                else "<html><body></body></html>")


class _PageFake:
    def __init__(self, frames):
        self.frames = frames
        self.esperas = 0

    async def wait_for_timeout(self, ms):
        self.esperas += 1


def test_espera_ate_a_arvore_pintar_e_so_entao_declara_pronta():
    fr = _FrameFake(pinta_apos=5)          # a árvore só aparece na 6ª consulta
    pg = _PageFake([fr])
    assert asyncio.run(sei_reader._esperar_arvore(pg)) is True
    assert fr.consultas > 5, "declarou a árvore pronta antes de ela ter nós"


def test_arvore_ja_pintada_nao_paga_espera_extra():
    fr = _FrameFake(pinta_apos=0)
    pg = _PageFake([fr])
    assert asyncio.run(sei_reader._esperar_arvore(pg)) is True
    assert fr.consultas == 1


def test_sem_frame_de_arvore_desiste_honesto():
    pg = _PageFake([_FrameFake(name="ifrVisualizacao", url="…/visualizar.php")])
    assert asyncio.run(sei_reader._esperar_arvore(pg, voltas=2)) is False


def test_frame_que_nunca_pinta_nao_trava_o_leitor():
    """Frame presente e eternamente vazio: desiste em tempo finito (o chamador extrai o que tem
    e marca indisponivel — honesto), nunca fica preso."""
    fr = _FrameFake(pinta_apos=10**6)
    pg = _PageFake([fr])
    assert asyncio.run(asyncio.wait_for(sei_reader._esperar_arvore(pg, voltas=2), timeout=10)) in (True, False)


@pytest.mark.parametrize("nome,url", [("ifrArvore", "x"), ("qualquer", "…/arvore_visualizar.php")])
def test_reconhece_o_frame_por_nome_ou_por_url(nome, url):
    fr = _FrameFake(name=nome, url=url, pinta_apos=0)
    assert asyncio.run(sei_reader._esperar_arvore(_PageFake([fr]))) is True
