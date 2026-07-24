# -*- coding: utf-8 -*-
"""Cérebro de EXECUÇÃO — o atesto FAZ SENTIDO? (plano #4, itens 1.1 e 1.5).

O determinístico (`execucao_sinais`) vê se o atesto EXISTE. Esta camada julga se ele é COERENTE com a
medição e com o objeto — um "de acordo" genérico, datado antes da medição ou com quantidade divergente é
atesto meramente formal. Fecha o ciclo com fusão det×LLM e snapshot versionado.
"""
from __future__ import annotations

import asyncio

from compliance_agent import execucao_cerebro as EC

_OBJETO = "Reforma da cobertura do prédio anexo — 1.200 m² de telhado"
_PGTO = ("PROCESSO DE PAGAMENTO. Ordem Bancária 2025OB800123 no valor de R$ 480.000,00. ")
_MEDICAO = ("Boletim de medição nº 3, período de 01/05/2025 a 31/05/2025: executados 400 m² de telhado, "
            "correspondentes a 33% do objeto. ")
_ATESTO = ("Atesto de recebimento: atesto que os serviços foram prestados a contento, de acordo. "
           "Data: 15/04/2025. Fiscal do contrato. ")


def _fake(json_txt):
    async def gerar(messages):
        gerar.messages = messages
        return json_txt
    gerar.messages = None
    return gerar


def _explode():
    async def gerar(messages):
        raise RuntimeError("gemini fora do ar")
    return gerar


def _nunca():
    async def gerar(messages):
        raise AssertionError("LLM NÃO deveria ser chamado neste caso")
    return gerar


# ───────────────────────────── extração das peças ─────────────────────────────

def test_extrai_atesto_e_medicao_do_texto():
    p = EC.extrair_pecas(_PGTO + _MEDICAO + _ATESTO)
    assert "medição" in p["medicao"].lower() or "medicao" in p["medicao"].lower()
    assert "atesto" in p["atesto"].lower()
    assert p["tem_atesto"] and p["tem_medicao"]


# ───────────────────────────── 1.1 coerência do atesto ─────────────────────────────

def test_sem_atesto_nao_chama_llm_e_e_nao_aplicavel():
    r = asyncio.run(EC.avaliar_coerencia_atesto(_PGTO + _MEDICAO, objeto=_OBJETO, gerar=_nunca()))
    assert r["grau"] == "nao_aplicavel"
    assert r["coerente"] is None                      # não se afirma coerência do que não existe


def test_atesto_sem_medicao_e_pendente_captura_com_acao():
    r = asyncio.run(EC.avaliar_coerencia_atesto(_PGTO + _ATESTO, objeto=_OBJETO, gerar=_nunca()))
    assert r["grau"] == "pendente_captura"
    assert "medi" in r["acao"].lower()                 # diz o que buscar
    assert r["grau"] not in ("indeterminado", "indisponivel")


def test_llm_julga_incoerencia_com_trecho():
    gerar = _fake('{"grau":"vermelho","coerente":false,"incoerencias":[{"tipo":"data",'
                  '"trecho":"Data: 15/04/2025","por_que":"atesto anterior ao período medido (maio/2025)"}],'
                  '"resumo":"atesto genérico e anterior à medição","dados_suficientes":true}')
    r = asyncio.run(EC.avaliar_coerencia_atesto(_PGTO + _MEDICAO + _ATESTO, objeto=_OBJETO, gerar=gerar))
    assert r["grau"] == "vermelho" and r["coerente"] is False
    assert r["incoerencias"][0]["trecho"]
    # o prompt levou as TRÊS peças (atesto, medição, objeto)
    user = gerar.messages[-1]["content"]
    assert "ATESTO" in user.upper() and "MEDI" in user.upper() and "1.200 m²" in user


def test_llm_indisponivel_nao_inventa():
    r = asyncio.run(EC.avaliar_coerencia_atesto(_PGTO + _MEDICAO + _ATESTO, objeto=_OBJETO, gerar=_explode()))
    assert r["grau"] == "pendente_reprocessar"
    assert r["coerente"] is None
    assert "reprocess" in r["acao"].lower()


def test_llm_lixo_nao_parseavel_nao_inventa():
    r = asyncio.run(EC.avaliar_coerencia_atesto(_PGTO + _MEDICAO + _ATESTO, objeto=_OBJETO,
                                                gerar=_fake("desculpe, não consegui")))
    assert r["grau"] == "pendente_reprocessar"


# ───────────────────────────── 1.5 fusão + snapshot ─────────────────────────────

def test_fusao_nunca_silencia_o_alarme_deterministico():
    # det: NF CANCELADA lastreando OB paga → vermelho. LLM olha o atesto e diz verde. A fusão mantém
    # vermelho e REGISTRA a divergência (o LLM pode ter subestimado o vício literal).
    gerar = _fake('{"grau":"verde","coerente":true,"incoerencias":[],"resumo":"ok","dados_suficientes":true}')
    txt = _PGTO + _MEDICAO + _ATESTO + "Observação: a nota fiscal foi cancelada após a emissão."
    r = asyncio.run(EC.avaliar_execucao(txt, objeto=_OBJETO, gerar=gerar))
    assert r["grau"] == "vermelho"
    assert r["grau_det"] == "vermelho" and r["grau_llm"] == "verde"
    assert r["fonte_grau"] == "objetivo"
    assert r["divergencia"] and r["divergencia"]["camada_mais_severa"] == "objetivo"


def test_estado_inconclusivo_do_llm_nao_vira_grau():
    # 'pendente_captura' (sem medição) NÃO é veredito: não entra na fusão, mas fica visível ao auditor
    r = asyncio.run(EC.avaliar_execucao(_PGTO + _ATESTO, objeto=_OBJETO, gerar=_nunca()))
    assert r["grau_llm"] is None
    assert r["coerencia_atesto"]["grau"] == "pendente_captura"
    assert r["grau"] == r["grau_det"]


def test_avaliar_execucao_offline_e_resolvido():
    r = asyncio.run(EC.avaliar_execucao(_PGTO + _MEDICAO + _ATESTO, objeto=_OBJETO, gerar=None))
    assert r["grau"] not in ("indeterminado", "indisponivel", "")
    assert r["grau_llm"] is None                       # honesto: a camada subjetiva não rodou
    assert r["_versao_hash"] and len(r["_versao_hash"]) == 16
    assert r["deterministico"]["fonte"].startswith("execucao_sinais")


def test_nfe_cancelada_pela_chave_entra_no_veredito_de_execucao():
    from compliance_agent import nfe_verifica as NF
    base = "33" "2405" "05506560000136" "55" "001" "000123456" "1" "12345678"
    chave = base + str(NF.digito_verificador(base))

    async def consulta(_):
        return {"situacao": "cancelada", "protocolo": "133240000123456"}

    txt = _PGTO + _MEDICAO + _ATESTO + f" Nota fiscal eletrônica chave {chave}."
    r = asyncio.run(EC.avaliar_execucao(txt, objeto=_OBJETO, gerar=None, consultar_nfe=consulta))
    assert r["nfe"]["grau"] == "vermelho"
    assert r["grau"] == "vermelho"                     # o vício da NF sobe ao veredito de execução
    assert any("cancelada" in s.lower() for s in r["nfe"]["sinais"])


def test_sem_consulta_a_nfe_nao_vira_verde_por_omissao():
    from compliance_agent import nfe_verifica as NF
    base = "33" "2405" "05506560000136" "55" "001" "000123456" "1" "12345678"
    chave = base + str(NF.digito_verificador(base))
    r = asyncio.run(EC.avaliar_execucao(_PGTO + _MEDICAO + _ATESTO + f" NF-e {chave}.",
                                        objeto=_OBJETO, gerar=None))
    assert r["nfe"]["grau"] == "a_verificar"
    assert not r["nfe"]["notas"][0]["verificado"]


def test_snapshot_so_sobe_quando_a_captura_muda():
    r = asyncio.run(EC.avaliar_execucao(_PGTO + _MEDICAO + _ATESTO, objeto=_OBJETO, gerar=None))
    chamadas = []

    def guardar(numero_sei, veredito, *, versao_hash, criado_em):
        chamadas.append(versao_hash)
        return f"remote:bucket/{numero_sei}/{versao_hash}.json"

    # versão já conhecida → NÃO re-sobe (idempotente)
    assert EC.guardar_snapshot_execucao("SEI-123", r, versoes_conhecidas={r["_versao_hash"]},
                                        guardar=guardar) is None
    assert chamadas == []
    # versão nova → sobe e devolve o ponteiro canônico
    loc = EC.guardar_snapshot_execucao("SEI-123", r, versoes_conhecidas=set(), guardar=guardar)
    assert loc and loc.startswith("remote:bucket/SEI-123/")
    assert chamadas == [r["_versao_hash"]]
