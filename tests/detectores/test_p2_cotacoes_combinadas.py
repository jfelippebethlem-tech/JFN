# -*- coding: utf-8 -*-
"""Rede de proteção do detector P2 — cotações combinadas / orçamentos de fachada.

A pesquisa de preços é a origem de tudo: se o teto foi formado por cotações combinadas, todo o
certame nasce contaminado. Cinco regras objetivas: vínculo entre cotantes, metadados de PDF
idênticos, vencedor entre os cotantes, CV baixo demais e cotações acima da referência do PNCP.

Dois guards que o detector faz certo e que os testes trancam:
· **contador comum isolado** não sobe achado — em cidade pequena metade das empresas usa o mesmo
  escritório de contabilidade;
· **CV baixo com menos de 3 totais** não pontua — coeficiente de variação com n=2 não diz nada, e
  o detector registra a ressalva em vez de fingir que mediu.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.p2_cotacoes_combinadas import (
    P2CotacoesCombinadas,
    _cv,
    _norm_end,
    _norm_tel,
    _socios,
)

_P = {"processo": "SEI-TESTE/000009/2026"}


def _cot(cnpj: str, total: float, **extra) -> dict:
    return {"cnpj": cnpj, "razao": f"EMPRESA {cnpj[-4:]}", "total": total, **extra}


# ───────────────────────────── normalizadores ─────────────────────────────────────────────────

def test_telefone_normaliza_para_digitos():
    assert _norm_tel("(21) 99876-5432") == _norm_tel("21998765432") == "21998765432"


@pytest.mark.parametrize("a,b", [
    ("Rua São João, nº 100", "R. Sao Joao 100"),
    ("Av. Brasil, 500", "Avenida Brasil 500"),
    ("Praça da Bandeira - 22", "Pca da Bandeira 22"),
])
def test_endereco_normaliza_abreviacao_pontuacao_e_acento(a, b):
    """O MESMO endereço escrito de duas formas tem de casar — senão o vínculo por sede
    compartilhada (dos sinais mais fortes de cotação orquestrada) passa batido."""
    assert _norm_end(a) == _norm_end(b), f"{_norm_end(a)!r} != {_norm_end(b)!r}"


def test_enderecos_realmente_distintos_nao_colidem():
    """A normalização não pode ser tão agressiva a ponto de igualar endereços diferentes."""
    assert _norm_end("Rua São João, 100") != _norm_end("Rua São João, 200")


def test_endereco_comum_entre_cotantes_e_vinculo():
    cot = [_cot("11222333000144", 100.0, contato={"endereco": "Rua São João, nº 100"}),
           _cot("44555666000177", 150.0, contato={"endereco": "R. Sao Joao 100"})]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score >= ANCORAS["forte"], "mesma sede em grafias diferentes tem de ser detectada"


def test_socios_aceita_dict_e_string():
    assert _socios([{"nome": "Fulano"}, "Beltrano"]) == {"fulano", "beltrano"}
    assert _socios(None) == set()


def test_cv_precisa_de_dois_valores_e_media_nao_nula():
    assert _cv([100.0]) is None
    assert _cv([0.0, 0.0]) is None
    assert _cv([100.0, 100.0]) == 0.0


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

@pytest.mark.parametrize("n", [0, 1])
def test_menos_de_duas_cotacoes_e_nao_avaliavel(n):
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": [_cot("1122233300014" + str(i), 100.0)
                                                             for i in range(n)]})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_pesquisa_independente_nao_inventa_indicio():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 138.0),
           _cot("77888999000100", 172.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


# ───────────────────────────── vínculo entre cotantes ─────────────────────────────────────────

def test_telefone_comum_entre_cotantes_e_vinculo_forte():
    cot = [_cot("11222333000144", 100.0, contato={"telefone": "(21) 99876-5432"}),
           _cot("44555666000177", 150.0, contato={"telefone": "21998765432"})]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score >= ANCORAS["forte"]
    assert res.evidencia


def test_socio_comum_entre_cotantes_e_vinculo_forte():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 150.0)]
    qsa = {"11222333000144": [{"nome": "Fulano de Tal"}],
           "44555666000177": [{"nome": "Fulano de Tal"}]}
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot, "qsa_por_cnpj": qsa})
    assert res.score >= ANCORAS["forte"]


def test_cotantes_sem_vinculo_nao_pontuam():
    cot = [_cot("11222333000144", 100.0, contato={"telefone": "2199999999"}),
           _cot("44555666000177", 150.0, contato={"telefone": "2188888888"})]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score == 0.0


# ───────────────────────────── metadados de PDF ───────────────────────────────────────────────

def test_author_identico_entre_cotacoes_distintas_e_forte():
    """Duas empresas diferentes não produzem PDFs com o mesmo autor por acaso."""
    cot = [_cot("11222333000144", 100.0, metadados_pdf={"Author": "joao.silva", "CreateDate": "2026-01-10"}),
           _cot("44555666000177", 150.0, metadados_pdf={"Author": "joao.silva", "CreateDate": "2026-01-10"})]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score >= ANCORAS["forte"]


def test_so_producer_identico_e_fraco():
    """Producer igual é template de ERP — meia dúzia de sistemas domina o mercado. Não sustenta sozinho."""
    cot = [_cot("11222333000144", 100.0, metadados_pdf={"Producer": "Microsoft Word"}),
           _cot("44555666000177", 150.0, metadados_pdf={"Producer": "Microsoft Word"})]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score <= ANCORAS["fraco"]


# ───────────────────────────── vencedor entre os cotantes ─────────────────────────────────────

def test_vencedor_entre_os_cotantes_e_forte():
    """Cotou o próprio teto que ajudou a formar."""
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 150.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot,
                                          "vencedor_cnpj": "11222333000144"})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["vencedor_e_cotante"] is True


def test_vencedor_fora_dos_cotantes_nao_pontua():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 150.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot,
                                          "vencedor_cnpj": "99000111000122"})
    assert res.valores["vencedor_e_cotante"] is False
    assert res.score == 0.0


# ───────────────────────────── CV dos valores ─────────────────────────────────────────────────

def test_cv_baixo_com_apenas_duas_cotacoes_nao_pontua_e_declara_a_ressalva():
    """CV com n=2 não mede nada. O detector diz isso em vez de fingir que mediu."""
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 101.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score == 0.0
    assert "ressalva_cv_n" in res.valores
    assert "mín. 3" in res.valores["ressalva_cv_n"]


def test_cv_baixo_com_tres_cotacoes_pontua_mas_declara_fragilidade():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 101.0),
           _cot("77888999000100", 100.5)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.score > 0
    assert res.valores["ressalva_cv_n"].startswith("CV computado com n=3")


def test_item_de_preco_regulado_escusa_o_cv_baixo():
    """Combustível cotado por três postos dá CV baixo porque o preço é tabelado, não combinado."""
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 101.0),
           _cot("77888999000100", 100.5)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot, "item_preco_regulado": True})
    assert res.score == 0.0
    assert "REGULADO" in res.motivo_refutacao


# ───────────────────────────── referência do PNCP ─────────────────────────────────────────────

def test_cotacoes_muito_acima_da_referencia_pontuam():
    """Valores DISPERSOS (para o CV não disparar junto) mas todos muito acima do painel."""
    cot = [_cot("11222333000144", 200.0), _cot("44555666000177", 300.0),
           _cot("77888999000100", 450.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot, "ref_pncp": 100.0})
    assert res.score >= ANCORAS["medio"]
    assert res.valores["sobre_ref_pncp_pct"] > 0.25


def test_cv_baixo_e_sobrepreco_somam_sem_estourar_o_teto():
    """Duas regras batendo agravam, mas o score continua em [0,1]."""
    cot = [_cot("11222333000144", 200.0), _cot("44555666000177", 201.0),
           _cot("77888999000100", 200.5)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot, "ref_pncp": 100.0})
    assert 0.0 < res.score <= 1.0
    assert res.valores["cv_valores"] < 0.05
    assert res.valores["sobre_ref_pncp_pct"] > 0.25


def test_cotacoes_alinhadas_com_a_referencia_nao_pontuam():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 138.0),
           _cot("77888999000100", 172.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot, "ref_pncp": 130.0})
    assert res.score == 0.0


# ───────────────────────────── robustez e schema ──────────────────────────────────────────────

def test_lixo_na_lista_de_cotacoes_nao_quebra():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 150.0), None, "texto", 42]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot})
    assert res.status in STATUS_VALIDOS
    assert res.valores["n_cotacoes"] == 2


def test_schema_de_saida_conforme_spec():
    cot = [_cot("11222333000144", 100.0), _cot("44555666000177", 150.0)]
    res = P2CotacoesCombinadas().avaliar({**_P, "cotacoes": cot,
                                          "vencedor_cnpj": "11222333000144"})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "P2"
    assert 0.0 <= d["score"] <= 1.0
