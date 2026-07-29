# -*- coding: utf-8 -*-
"""A trava que impede o prompt de mudar em silêncio.

Sem ela, a catraca de F1 acusa uma queda e não há como saber contra o quê comparar: o prompt de
hoje pode não ser o prompt medido ontem. O par (versão declarada, hash da fonte) é o que liga a
regressão à alteração.
"""
from __future__ import annotations

import pytest

from compliance_agent.nucleo import prompt_versao as pv


def test_todo_prompt_de_juizo_tem_hash_gravado():
    faltando = [pid for pid in pv.REGISTRO if not pv.HASHES.get(pid)]
    assert not faltando, f"prompt no registro sem hash aceito: {faltando}"


def test_nenhum_prompt_mudou_sem_subir_a_versao():
    """SE ESTE TESTE FALHOU: você alterou um prompt de juízo. Suba `versao` no REGISTRO e o hash
    em HASHES, no MESMO commit — e refaça a medição, porque a comparação com o baseline antigo
    passou a comparar coisas diferentes."""
    fora = pv.divergencias()
    assert not fora, f"prompt alterado sem carimbo novo: {fora}"


def test_alvo_que_sumiu_vira_divergencia_e_nao_silencio():
    """Prompt renomeado/movido sairia da trava sem ninguém notar."""
    pv.REGISTRO["_teste_fantasma"] = {"alvo": "compliance_agent.nucleo.prompt_versao:nao_existe",
                                      "versao": "v1", "papel": "só do teste"}
    try:
        fora = pv.divergencias({**pv.HASHES, "_teste_fantasma": "x"})
        assert any(d["prompt_id"] == "_teste_fantasma" and "erro" in d for d in fora)
    finally:
        pv.REGISTRO.pop("_teste_fantasma")


def test_hash_muda_quando_o_texto_muda():
    a = pv.impressao("compliance_agent.knowledge.subsuncao:SCHEMA_PROMPT")
    b = pv.impressao("compliance_agent.direcionamento_cerebro:_SYS")
    assert a != b and len(a) == 12


def test_prompt_montado_por_funcao_tambem_entra_na_trava():
    """Hashear só constantes deixaria de fora justamente os prompts mais elaborados."""
    assert pv.impressao("compliance_agent.editais.narrativa_certame:montar_prompt")


def test_carimbo_traz_id_versao_e_hash():
    c = pv.assinar("hermeneutica")
    assert c["prompt_id"] == "hermeneutica" and c["prompt_versao"] and len(c["prompt_hash"]) == 12


def test_prompt_fora_do_registro_levanta_em_vez_de_carimbar_generico():
    """Devolver carimbo neutro esconderia exatamente o caso que a trava existe para pegar."""
    with pytest.raises(KeyError):
        pv.assinar("prompt_que_ninguem_registrou")


def test_carimbar_nao_sobrescreve_campo_ja_presente():
    v = {"grau": "amarelo", "prompt_versao": "v9"}
    assert pv.carimbar(v, "hermeneutica")["prompt_versao"] == "v9"
    assert v["prompt_hash"]
