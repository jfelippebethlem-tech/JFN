# -*- coding: utf-8 -*-
"""Contexto DECLARADO de 1 milhão não é permissão para mandar 400 mil tokens de uma vez.

SEI-080001/003535/2025: 20 documentos, 801.665 caracteres, ~400.827 tokens. O catálogo
declara contexto de 1M para o modelo, então o planejador concluiu "cabe em 1 lote" e o
dossiê saiu com o carimbo **"Modo de leitura: leitura integral"**. O resultado real: 10 KB de
dossiê para 800 mil caracteres de processo, **zero documentos citados**, e a nota no vault
registrando o processo — de R$ 15,4 milhões — sem indício nenhum.

A casa já mediu que capacidade declarada ≠ capacidade real: no banco de provas, três modelos
que gabaritam tarefa curta **zeram** num documento de 25 mil tokens. Aceitar 400 mil porque o
catálogo diz 1M é preferir a estimativa ao fato.

O teto prático não inventa número novo: é o mesmo 128k que o código já usa como fallback
quando não sabe o contexto do modelo. Com ele, o processo acima vira 9 lotes sem truncamento
— cada um do tamanho que a casa já considera seguro.
"""
import pathlib

import pytest

from compliance_agent.sei.dossie_fracionado import TETO_PRATICO_CTX, planejar

ACERVO = pathlib.Path(__file__).resolve().parent.parent / "data" / "sei_arquivo"
PROC = "080001_003535_2025"

pytestmark = pytest.mark.skipif(not (ACERVO / PROC).is_dir(),
                                reason="acervo SEI ausente neste ambiente")


def test_contexto_declarado_gigante_nao_vira_lote_gigante():
    plano = planejar(PROC, ACERVO / PROC, contexto_modelo=1_000_000)
    assert not plano.cabe_inteiro, "400 mil tokens não podem sair como 'leitura integral'"
    assert len(plano.lotes) > 1


def test_o_teto_e_o_mesmo_fallback_que_o_codigo_ja_usava():
    """Não é número novo: 128k é o que `sei_dossie_md` assume quando não sabe o contexto."""
    assert TETO_PRATICO_CTX == 128_000


def test_contexto_menor_que_o_teto_e_respeitado():
    """O teto corta para baixo, nunca para cima — modelo pequeno continua pequeno."""
    pequeno = planejar(PROC, ACERVO / PROC, contexto_modelo=32_768)
    grande = planejar(PROC, ACERVO / PROC, contexto_modelo=1_000_000)
    assert len(pequeno.lotes) > len(grande.lotes)


def test_processo_pequeno_continua_cabendo_inteiro(tmp_path):
    """A mudança não pode fracionar o que sempre coube — 97% dos processos cabem."""
    p = tmp_path / "proc"
    (p / "texto").mkdir(parents=True)
    (p / "texto" / "000_doc.txt").write_text("um despacho curto", encoding="utf-8")
    plano = planejar("proc", p, contexto_modelo=1_000_000)
    assert plano.cabe_inteiro
