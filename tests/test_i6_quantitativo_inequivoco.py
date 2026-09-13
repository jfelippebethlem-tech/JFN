# -*- coding: utf-8 -*-
"""Comparar a PRIMEIRA quantidade de cada documento é sorteio, não achado.

`_qtds` usa `setdefault`: fica com a primeira ocorrência de cada unidade e ignora o resto. Num
processo de veículos aberto em 2026-08-04, os autos traziam **3, 4, 5, 10, 12, 19, 30, 40, 50 e
100 veículos** — lotes, itens e fases diferentes — além de "2019 VEICULO", que é data. Comparar a
primeira de um lado com a primeira do outro produziu "o objeto é de 30 veículos e o atesto fala
em 3".

A divergência só sustenta achado quando cada lado declara UM único quantitativo para a unidade.
Efeito medido no acervo: 7 → 6 disparos. É pouco, e o valor não está na contagem: está em não
afirmar divergência a partir de uma escolha arbitrária entre uma dúzia de números.
"""
from compliance_agent.sei import instrumento_assinatura as IA

_OBJ = "CLÁUSULA PRIMEIRA — DO OBJETO. Constitui objeto a locação de "
_ATESTO = "ATESTO a boa execução dos serviços referentes a "


def _doc(ref, tipo, texto):
    return {"ref": ref, "tipo": tipo, "texto": texto}


def test_quantitativo_UNICO_dos_dois_lados_sustenta_o_achado():
    docs = [_doc("Contrato 1", "contrato", _OBJ + "30 (trinta) veículos."),
            _doc("Atesto", "outro", _ATESTO + "3 (três) veículos.")]
    r = IA.quantitativo_divergente(docs)
    assert r["achado"] is True and r["objeto"] == 30 and r["atesto"] == 3


def test_instrumento_com_VARIOS_quantitativos_nao_decide():
    """Lotes e itens: não há "o" contratado a comparar."""
    docs = [_doc("Contrato 1", "contrato",
                 _OBJ + "4 (quatro) veículos, 5 (cinco) veículos e 19 (dezenove) veículos."),
            _doc("Atesto", "outro", _ATESTO + "3 (três) veículos.")]
    assert IA.quantitativo_divergente(docs)["achado"] is False


def test_atesto_com_VARIOS_quantitativos_tambem_nao_decide():
    docs = [_doc("Contrato 1", "contrato", _OBJ + "30 (trinta) veículos."),
            _doc("Atesto", "outro", _ATESTO + "3 (três) veículos e 12 (doze) veículos.")]
    assert IA.quantitativo_divergente(docs)["achado"] is False


def test_quantitativos_IGUAIS_nao_viram_achado():
    docs = [_doc("Contrato 1", "contrato", _OBJ + "30 (trinta) veículos."),
            _doc("Atesto", "outro", _ATESTO + "30 (trinta) veículos.")]
    assert IA.quantitativo_divergente(docs)["achado"] is False


def test_qtds_distintas_junta_todas_as_ocorrencias():
    d = IA._qtds_distintas("4 (quatro) veículos, 19 (dezenove) veículos, 4 (quatro) veículos")
    assert d["veiculo"] == {4, 19}
