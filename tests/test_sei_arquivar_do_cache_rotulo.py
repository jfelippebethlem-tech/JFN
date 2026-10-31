# -*- coding: utf-8 -*-
"""O rótulo do contador do lane do cache é CONTRATO SEMÂNTICO.

A linha dizia "processos no cache com texto e sem arquivo: N", texto congelado na população
original. Mas `candidatos()` passou a incluir também quem TEM arquivo desatualizado
(re-arquivamento por frescor). Medido em 2026-08-27: o lane imprimia "0" disparo após disparo
enquanto 98 processos tinham cache mais novo que o manifesto — 32 deles já `completo`, um com
787.668 caracteres parados havia mais de uma semana. Fila que se declara vazia não é investigada.
"""
import re
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "tools" / "sei_arquivar_do_cache.py"


def test_rotulo_nao_diz_apenas_sem_arquivo():
    """Se o texto voltar a prometer só 'sem arquivo', a mensagem mente quando a fila é de frescor."""
    txt = FONTE.read_text(encoding="utf-8")
    linha = [l for l in txt.splitlines()
             if "print(" in l and "processos" in l and "cache" in l]
    assert linha, "sumiu a linha do contador — se mudou de forma, atualize este teste de propósito"
    junto = " ".join(linha)
    assert "sem arquivo:" not in junto, (
        "o rótulo voltou a prometer só 'sem arquivo', mas `candidatos()` traz duas populações")


def test_contador_separa_as_duas_populacoes():
    """O número tem de vir decomposto: quantos são novos e quantos são re-arquivamento."""
    txt = FONTE.read_text(encoding="utf-8")
    assert "novos = sum(" in txt, "sumiu a contagem separada dos que nunca foram arquivados"
    assert "cache mais novo que o arquivo" in txt, (
        "a mensagem não diz mais que parte da fila é re-arquivamento por frescor")
