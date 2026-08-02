# -*- coding: utf-8 -*-
"""Promessa feita ao Mestre não pode morrer junto com o processo.

O Yoda responde *"Eu te envio aqui mesmo em ~1–2 min"* e a rota delega para um
`asyncio.create_task`. O tratamento de erro DENTRO da tarefa já é bom (avisa no Telegram e limpa no
`finally`). O buraco é outro: se o processo morre no meio, a tarefa morre com ele — **sem aviso e
sem retentativa**. O humano fica esperando um PDF que nunca chega, que é exatamente a queixa
"promete e não entrega".

Não era hipótese: medido em 31/07/2026, o `jfn.service` era reiniciado **7 a 14 vezes por dia** pelo
`guardiao_db_malformed.sh` (defeito do WAL-index, corrigido no mesmo dia). Toda geração em curso
naquele instante virava silêncio.

`_REL_EM_CURSO` já era o registro de "em curso" — só vivia em memória. Aqui ele ganha disco: a
promessa é anotada ANTES de prometer, apagada quando a entrega termina, e o que sobrar no arquivo
depois de um boot é exatamente o que ficou devendo.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent import promessas


@pytest.fixture()
def registro(tmp_path, monkeypatch):
    monkeypatch.setattr(promessas, "_ARQ", tmp_path / "promessas.json")
    return tmp_path / "promessas.json"


def test_promessa_anotada_fica_pendente(registro):
    promessas.registrar("orgao:iterj", "orgao", {"orgao": "iterj"})

    assert promessas.pendentes() == [{"chave": "orgao:iterj", "tipo": "orgao",
                                      "args": {"orgao": "iterj"}}]


def test_concluir_apaga_a_promessa(registro):
    promessas.registrar("orgao:iterj", "orgao", {"orgao": "iterj"})
    promessas.concluir("orgao:iterj")

    assert promessas.pendentes() == []


def test_o_que_sobra_apos_o_boot_e_o_que_ficou_devendo(registro):
    """O ponto do defeito: o processo morreu entre registrar e concluir."""
    promessas.registrar("orgao:iterj", "orgao", {"orgao": "iterj"})
    promessas.registrar("dossie:123", "dossie", {"alvo": "123"})
    promessas.concluir("dossie:123")     # esta entregou

    pend = promessas.pendentes()

    assert [p["chave"] for p in pend] == ["orgao:iterj"], (
        "sobrou promessa errada — o boot re-despacharia o que já foi entregue")


def test_registrar_duas_vezes_a_mesma_chave_nao_duplica(registro):
    """Pedido repetido do Mestre não pode virar duas entregas."""
    promessas.registrar("orgao:iterj", "orgao", {"orgao": "iterj"})
    promessas.registrar("orgao:iterj", "orgao", {"orgao": "iterj"})

    assert len(promessas.pendentes()) == 1


def test_concluir_chave_inexistente_nao_estoura(registro):
    """O `finally` da tarefa chama isto sempre — inclusive quando nada foi registrado."""
    promessas.concluir("nunca-existiu")   # não pode levantar
    assert promessas.pendentes() == []


def test_arquivo_corrompido_nao_derruba_o_boot(registro):
    """Degrada honesto: JSON quebrado vira lista vazia, o servidor sobe."""
    registro.write_text("{lixo", encoding="utf-8")

    assert promessas.pendentes() == []


def test_escrita_e_atomica(registro, monkeypatch):
    """Crash no meio do write deixaria JSON truncado — e o boot perderia TODAS as promessas."""
    promessas.registrar("orgao:iterj", "orgao", {"orgao": "iterj"})

    def _explode(*_a, **_kw):
        raise OSError("disco cheio")

    monkeypatch.setattr(promessas.os, "replace", _explode)
    try:
        promessas.registrar("dossie:9", "dossie", {"alvo": "9"})
    except OSError:
        pass

    assert json.loads(registro.read_text(encoding="utf-8")), "o registro anterior foi perdido"
    assert not list(registro.parent.glob("*.tmp")), "temporário ficou para trás"
