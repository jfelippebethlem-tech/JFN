# -*- coding: utf-8 -*-
"""NF-e: chave de acesso, contingência (offline) e situação na SEFAZ (live, injetável) — plano #4, item 1.3.

"Dá pra saber se a NF foi cancelada / emitida em contingência?" → SIM. A chave de acesso (44 dígitos) que
está no texto do processo carrega UF, AAMM, CNPJ do emitente, modelo, série, número e o tpEmis — a
contingência sai da PRÓPRIA chave, sem rede. Cancelamento/denegação exige consulta à SEFAZ (injetável).
"""
from __future__ import annotations

import asyncio

from compliance_agent import nfe_verifica as NF

# Chave montada com a ESTRUTURA oficial (43 dígitos + DV calculado):
# cUF 33 (RJ) · AAMM 2405 · CNPJ 05506560000136 · mod 55 · série 001 · nNF 000123456 · tpEmis · cNF 12345678
_BASE_NORMAL = "33" "2405" "05506560000136" "55" "001" "000123456" "1" "12345678"
assert len(_BASE_NORMAL) == 43


def _com_dv(base43: str) -> str:
    return base43 + str(NF.digito_verificador(base43))


CHAVE_NORMAL = _com_dv(_BASE_NORMAL)
CHAVE_CONTINGENCIA = _com_dv(_BASE_NORMAL[:34] + "4" + _BASE_NORMAL[35:])   # tpEmis=4 (EPEC)


# ───────────────────────────── extração e validação (offline) ─────────────────────────────

def test_extrai_chave_do_texto_e_valida_dv():
    txt = f"Nota fiscal eletrônica chave de acesso {CHAVE_NORMAL} referente ao serviço prestado."
    chaves = NF.extrair_chaves(txt)
    assert chaves == [CHAVE_NORMAL]
    assert NF.chave_valida(CHAVE_NORMAL)


def test_chave_com_dv_errado_e_descartada():
    ruim = CHAVE_NORMAL[:-1] + str((int(CHAVE_NORMAL[-1]) + 1) % 10)
    assert not NF.chave_valida(ruim)
    assert NF.extrair_chaves(f"chave {ruim}") == []


def test_numero_de_44_digitos_que_nao_e_chave_nao_entra():
    # anti-FP: sequência longa de dígitos (protocolo, código de barras) sem DV válido não é chave
    assert NF.extrair_chaves("codigo 12345678901234567890123456789012345678901234") == []


def test_extrai_chave_com_separadores():
    formatada = " ".join(CHAVE_NORMAL[i:i + 4] for i in range(0, 44, 4))
    assert NF.extrair_chaves(f"Chave: {formatada}") == [CHAVE_NORMAL]


def test_decompoe_a_chave():
    d = NF.decompor(CHAVE_NORMAL)
    assert d["uf"] == "33" and d["uf_nome"] == "RJ"
    assert d["aamm"] == "2405" and d["cnpj_emitente"] == "05506560000136"
    assert d["modelo"] == "55" and d["serie"] == "001" and d["numero"] == "000123456"
    assert d["tp_emissao"] == "1"


# ───────────────────────────── contingência: sai da própria chave ─────────────────────────────

def test_contingencia_detectada_offline_pela_chave():
    r = NF.tp_emissao(CHAVE_CONTINGENCIA)
    assert r["contingencia"] is True
    assert "EPEC" in r["descricao"].upper()
    assert r["fonte"] == "chave de acesso (offline)"


def test_emissao_normal_nao_e_contingencia():
    assert NF.tp_emissao(CHAVE_NORMAL)["contingencia"] is False


# ───────────────────────────── situação na SEFAZ (live, injetável) ─────────────────────────────

def test_situacao_cancelada_e_vermelha():
    async def consulta(chave):
        return {"situacao": "cancelada", "protocolo": "133240000123456", "data": "2024-06-10"}

    r = asyncio.run(NF.situacao(CHAVE_NORMAL, consultar=consulta))
    assert r["situacao"] == "cancelada" and r["grau"] == "vermelho"
    assert r["verificado"] is True


def test_sem_consulta_disponivel_e_honesto_nao_verificado():
    r = asyncio.run(NF.situacao(CHAVE_NORMAL, consultar=None))
    assert r["verificado"] is False
    assert r["situacao"] == "nao_verificada"
    assert r["grau"] == "a_verificar"                 # nunca 'autorizada' por omissão
    assert "sefaz" in r["acao"].lower()


def test_consulta_que_falha_nao_inventa():
    async def consulta(chave):
        raise RuntimeError("sem certificado A1")

    r = asyncio.run(NF.situacao(CHAVE_NORMAL, consultar=consulta))
    assert r["verificado"] is False and r["situacao"] == "nao_verificada"
    assert "certificado" in (r.get("erro") or "").lower()


# ───────────────────────────── veredito sobre o processo ─────────────────────────────

def test_analisar_texto_sem_chave_e_resolvido():
    r = asyncio.run(NF.analisar_nfe("Processo de pagamento sem menção a nota fiscal eletrônica."))
    assert r["grau"] == "a_verificar" and r["chaves"] == []
    assert "chave" in r["acao"].lower()
    assert r["grau"] not in ("indeterminado", "indisponivel")


def test_analisar_marca_contingencia_offline_mesmo_sem_rede():
    r = asyncio.run(NF.analisar_nfe(f"NF-e chave {CHAVE_CONTINGENCIA} anexada ao processo."))
    assert r["grau"] == "amarelo"
    assert r["notas"][0]["contingencia"] is True
    assert any("conting" in s.lower() for s in r["sinais"])


def test_analisar_nf_cancelada_com_ob_paga_e_vermelho_forte():
    async def consulta(chave):
        return {"situacao": "cancelada", "protocolo": "133240000123456"}

    r = asyncio.run(NF.analisar_nfe(f"Ordem Bancária 2025OB800123 paga. NF-e {CHAVE_NORMAL}.",
                                    consultar=consulta))
    assert r["grau"] == "vermelho"
    assert any("cancelada" in s.lower() for s in r["sinais"])
    assert any("ordem bancária" in s.lower() or "paga" in s.lower() for s in r["sinais"])
