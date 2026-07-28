# -*- coding: utf-8 -*-
"""Camada de triagem — a IA que roda 24/7 sobre o que a camada determinística marcou.

O que estes testes protegem é o bolso e a honestidade: o kill-switch tem de parar na hora, o
teto diário tem de ser respeitado em disco (não em memória, que morre com o processo), e
qualquer falha tem de degradar para string vazia — porque aí o detector responde
`nao_avaliavel`, que é a resposta honesta, em vez de inventar juízo.

Nada aqui chama LLM de verdade.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.llm import camada_triagem as T


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    """Aponta pausa e contador para tmp — nunca toca os arquivos reais."""
    monkeypatch.setattr(T, "PAUSE", tmp_path / ".pause_llm_triagem")
    monkeypatch.setattr(T, "USO", tmp_path / "triagem_uso.json")
    monkeypatch.setattr(T, "MAX_DIA", 5)
    return tmp_path


def _fingir_chain(monkeypatch, resposta="", explode=False):
    import sys
    import types

    falso = types.ModuleType("compliance_agent.llm.free_llm")

    def best_free_chat(prompt, system="", smart=False, fallback=""):
        if explode:
            raise RuntimeError("todos os provedores fora do ar")
        return resposta

    falso.best_free_chat = best_free_chat
    monkeypatch.setitem(sys.modules, "compliance_agent.llm.free_llm", falso)


# ───────────────────────────── kill-switch ────────────────────────────────────────────────────

def test_kill_switch_para_na_hora(isolar, monkeypatch):
    """Criar o arquivo tem de bastar — sem deploy, sem reiniciar nada."""
    _fingir_chain(monkeypatch, resposta='{"nivel":"generica","trecho":"x"}')
    gerar = T.gerar_triagem()
    assert gerar("p", "s") != ""

    (isolar / ".pause_llm_triagem").write_text("")
    assert T.pausado() is True
    assert gerar("p", "s") == "", "com a pausa criada, nenhuma chamada pode sair"
    assert T.ler_uso()["bloqueadas_pause"] == 1


def test_kill_switch_e_reversivel(isolar, monkeypatch):
    _fingir_chain(monkeypatch, resposta="ok")
    pausa = isolar / ".pause_llm_triagem"
    pausa.write_text("")
    gerar = T.gerar_triagem()
    assert gerar("p", "s") == ""
    pausa.unlink()
    assert gerar("p", "s") == "ok"


# ───────────────────────────── teto diário ────────────────────────────────────────────────────

def test_teto_diario_e_respeitado(isolar, monkeypatch):
    _fingir_chain(monkeypatch, resposta="ok")
    gerar = T.gerar_triagem()
    for _ in range(5):
        assert gerar("p", "s") == "ok"
    assert gerar("p", "s") == "", "a 6ª chamada estoura o teto de 5"
    assert T.ler_uso()["bloqueadas_teto"] == 1
    assert T.orcamento_restante() == 0


def test_teto_e_contado_em_DISCO_e_nao_em_memoria(isolar, monkeypatch):
    """Contador em memória zeraria a cada processo, e o cron cria um processo por execução —
    o teto diário viraria teto por execução, que não limita nada."""
    _fingir_chain(monkeypatch, resposta="ok")
    T.gerar_triagem()("p", "s")
    T.gerar_triagem()("p", "s")            # callable NOVO, como se fosse outro processo
    assert T.ler_uso()["chamadas"] == 2


def test_teto_pode_ser_apertado_por_chamada(isolar, monkeypatch):
    _fingir_chain(monkeypatch, resposta="ok")
    gerar = T.gerar_triagem(max_dia=1)
    assert gerar("p", "s") == "ok"
    assert gerar("p", "s") == ""


def test_contador_vira_a_pagina_na_virada_do_dia(isolar, monkeypatch):
    _fingir_chain(monkeypatch, resposta="ok")
    T.gerar_triagem()("p", "s")
    dados = json.loads((isolar / "triagem_uso.json").read_text())
    dados["data"] = "2020-01-01"
    (isolar / "triagem_uso.json").write_text(json.dumps(dados))
    assert T.ler_uso()["chamadas"] == 0, "dia novo, contador zerado"


# ───────────────────────────── degradação honesta ─────────────────────────────────────────────

def test_cadeia_fora_do_ar_devolve_vazio_e_nao_estoura(isolar, monkeypatch):
    """Vazio faz o detector responder nao_avaliavel — a resposta honesta. Exceção derrubaria
    a varredura inteira por causa de um provedor."""
    _fingir_chain(monkeypatch, explode=True)
    assert T.gerar_triagem()("p", "s") == ""
    assert T.ler_uso()["erros"] == 1


def test_resposta_vazia_do_provedor_e_contabilizada_separadamente(isolar, monkeypatch):
    """Distinguir 'respondeu vazio' de 'quebrou' é o que permite saber se o modelo é ruim ou
    se a infra caiu."""
    _fingir_chain(monkeypatch, resposta="   ")
    T.gerar_triagem()("p", "s")
    uso = T.ler_uso()
    assert uso["vazias"] == 1 and uso["erros"] == 0


def test_arquivo_de_uso_corrompido_nao_quebra(isolar, monkeypatch):
    (isolar / "triagem_uso.json").write_text("{ não é json")
    _fingir_chain(monkeypatch, resposta="ok")
    assert T.gerar_triagem()("p", "s") == "ok"


# ───────────────────────────── contrato com os detectores ─────────────────────────────────────

def test_assinatura_e_a_que_os_detectores_esperam(isolar, monkeypatch):
    """Os cards chamam `gerar(prompt, sistema)`. Qualquer desvio quebraria todos de uma vez."""
    _fingir_chain(monkeypatch, resposta='{"nivel":"generica","trecho":"citação"}')
    gerar = T.gerar_triagem()
    assert gerar("prompt", "sistema") == '{"nivel":"generica","trecho":"citação"}'


def test_detector_com_a_camada_degrada_para_nao_avaliavel_quando_bloqueada(isolar, monkeypatch):
    """O teste que fecha o ciclo: sem orçamento, o detector NÃO inventa — marca nao_avaliavel."""
    from compliance_agent.detectores.e3_lote_pacote import E3LotePacote

    _fingir_chain(monkeypatch, resposta="ok")
    (isolar / ".pause_llm_triagem").write_text("")

    lotes = [{"id": "L1", "itens": [{"descricao": f"i{i}", "catmat": f"{i}1110001"}
                                    for i in range(5)]}]
    res = E3LotePacote().avaliar({"processo": "SEI-X", "lotes": lotes,
                                  "gerar": T.gerar_triagem()})
    assert res.valores["interdependencia"] == "nao_avaliavel"


# ───────────────────────────── status para o operador ─────────────────────────────────────────

def test_status_mostra_o_que_esta_bloqueando(isolar, monkeypatch):
    _fingir_chain(monkeypatch, resposta="ok")
    T.gerar_triagem()("p", "s")
    (isolar / ".pause_llm_triagem").write_text("")
    st = T.status()
    assert st["chamadas_hoje"] == 1
    assert st["restante"] == 4
    assert st["pausado"] is True
    assert st["arquivo_pause"].endswith(".pause_llm_triagem")


# ── moldura jurídica ───────────────────────────────────────────────────────────────────────
# A camada 2 julga licitação brasileira em volume. Sem a moldura, fazia isso com o que o modelo
# tivesse aprendido na internet: dispositivo errado, súmula inexistente, Lei 8.666/1993 tratada
# como vigente para contratação nova. O ponto de injeção é `gerar()` porque TODO detector passa
# por ele — corrigir card a card seria esquecer metade.

def test_moldura_juridica_entra_no_system(isolar, monkeypatch):
    capturado = {}

    import sys
    import types
    falso = types.ModuleType("compliance_agent.llm.free_llm")

    def best_free_chat(prompt, system="", smart=False, fallback=""):
        capturado["system"] = system
        return "ok"

    falso.best_free_chat = best_free_chat
    monkeypatch.setitem(sys.modules, "compliance_agent.llm.free_llm", falso)

    T.gerar_triagem()("prompt", "Classifique em escala fechada.")
    sistema = capturado["system"]
    assert "14.133/2021" in sistema, "o regime vigente tem de estar no prompt"
    assert "presunção de legitimidade" in sistema.lower()
    assert "Classifique em escala fechada." in sistema, "a instrução do detector foi perdida"


def test_moldura_compacta_nao_carrega_o_catalogo_inteiro(isolar, monkeypatch):
    """A rubrica já vem fechada pelo detector; os 42 vícios seriam 3.200 tokens de ruído."""
    capturado = {}

    import sys
    import types
    falso = types.ModuleType("compliance_agent.llm.free_llm")
    falso.best_free_chat = lambda prompt, system="", smart=False, fallback="": (
        capturado.setdefault("system", system), "ok")[1]
    monkeypatch.setitem(sys.modules, "compliance_agent.llm.free_llm", falso)

    T.gerar_triagem()("p", "s")
    assert "VÍCIOS CATALOGADOS" not in capturado["system"]
