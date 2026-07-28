# -*- coding: utf-8 -*-
"""Rede de proteção do detector P1 — especificação dirigida / marca disfarçada (art. 41/43).

Cinco regras objetivas: requisito nominativo sem "ou equivalente", valores não-redondos (cópia de
datasheet), interseção fechada de produtos, exigências que só este órgão pede, e corroboração
pelo resultado.

O guard mais fino do detector é anti-falso-positivo e merece teste explícito: a cláusula que
**proíbe** indicação de marca ("é vedada a indicação de marca") contém a palavra "marca" e cairia
na regex nominativa. O detector olha a janela de contexto e descarta a negação — sem isso, todo
edital bem redigido seria acusado por dizer que não aceita marca.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.p1_especificacao_dirigida import (
    P1EspecificacaoDirigida,
    _is_redondo,
    _pista_nominativa,
)

_P = {"processo": "SEI-TESTE/000008/2026"}


# ───────────────────────────── pista nominativa e a negação ───────────────────────────────────

@pytest.mark.parametrize("texto", [
    "impressora marca HP",
    "modelo LaserJet 4200",
    "código do fabricante XPTO-12",
    "part number 9910-A",
])
def test_reconhece_requisito_nominativo(texto):
    assert _pista_nominativa(texto) is not None


@pytest.mark.parametrize("texto", [
    "é vedada a indicação de marca no presente Termo de Referência",
    "não será aceita marca específica",
    "especificação sem indicação de marca ou modelo",
])
def test_clausula_que_PROIBE_marca_nao_e_pista_nominativa(texto):
    """Anti-falso-positivo central: o edital correto fala de marca justamente para vedá-la.

    Sem a janela de negação, o detector acusaria quem cumpriu o art. 41.
    """
    assert _pista_nominativa(texto) is None


def test_negacao_distante_nao_neutraliza_marca_citada_adiante():
    """A janela é de ±60 caracteres: uma vedação genérica no início do TR não pode escusar uma
    marca citada muitos parágrafos depois."""
    texto = ("É vedada a indicação de marca. " + "x" * 200 +
             " O equipamento deverá ser da marca ACME modelo Z9.")
    assert _pista_nominativa(texto) is not None


# ───────────────────────────── valor redondo ──────────────────────────────────────────────────

@pytest.mark.parametrize("v,redondo", [
    (10.0, True), (5.0, True), (100.0, True), (3.0, True),
    (17.3, False), (2847.0, False), (23.0, False),
])
def test_valor_redondo_vs_copiado_de_datasheet(v, redondo):
    """Especificação genérica usa número redondo; datasheet traz 17,3 e 2.847."""
    assert _is_redondo(v) is redondo


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_tr_e_sem_requisitos_e_nao_avaliavel():
    res = P1EspecificacaoDirigida().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_especificacao_neutra_nao_inventa_indicio():
    reqs = [{"requisito": "memória RAM", "valor": 16, "unidade": "GB"},
            {"requisito": "armazenamento", "valor": 500, "unidade": "GB"}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


# ───────────────────────────── requisito nominativo ───────────────────────────────────────────

def test_marca_sem_ou_equivalente_e_critico():
    reqs = [{"requisito": "impressora marca HP LaserJet"}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["n_requisitos_nominativos"] == 1
    assert res.evidencia


@pytest.mark.parametrize("sufixo", ["ou equivalente", "ou similar", "ou superior"])
def test_ou_equivalente_neutraliza_a_marca(sufixo):
    """Citar marca como referência COM 'ou equivalente' é lícito (art. 41, parágrafo único)."""
    reqs = [{"requisito": f"impressora marca HP LaserJet {sufixo}"}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.valores["n_requisitos_nominativos"] == 0


def test_flag_nominativo_explicito_no_requisito():
    reqs = [{"requisito": "equipamento conforme especificação anexa", "nominativo": True}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.valores["n_requisitos_nominativos"] == 1


def test_marca_solta_no_corpo_do_tr():
    tr = "O equipamento deverá ser da marca ACME, modelo Z9, com garantia de 12 meses."
    res = P1EspecificacaoDirigida().avaliar({**_P, "tr_texto": tr})
    assert res.valores["n_requisitos_nominativos"] == 1
    assert res.score > 0


def test_tr_que_veda_marca_nao_pontua():
    tr = "É vedada a indicação de marca ou modelo neste Termo de Referência."
    res = P1EspecificacaoDirigida().avaliar({**_P, "tr_texto": tr})
    assert res.valores["n_requisitos_nominativos"] == 0
    assert res.score == 0.0


# ───────────────────────────── valores copiados de catálogo ───────────────────────────────────

def test_dois_valores_nao_redondos_indicam_copia_de_datasheet():
    reqs = [{"requisito": "peso máximo", "valor": 17.3, "unidade": "kg"},
            {"requisito": "ciclo mensal", "valor": 2847, "unidade": "pág"}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.valores["n_valores_nao_redondos"] == 2
    assert res.score >= ANCORAS["medio"]


def test_um_valor_nao_redondo_sozinho_nao_pontua():
    """Um número específico pode ser exigência técnica real — o padrão é que denuncia a cópia."""
    reqs = [{"requisito": "peso máximo", "valor": 17.3, "unidade": "kg"}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.score == 0.0


def test_valores_pequenos_nao_contam_como_nao_redondos():
    """O corte é >10: exigir 3 portas USB ou 8 GB não é cópia de catálogo."""
    reqs = [{"requisito": "portas USB", "valor": 3}, {"requisito": "núcleos", "valor": 8}]
    res = P1EspecificacaoDirigida().avaliar({**_P, "requisitos": reqs})
    assert res.valores["n_valores_nao_redondos"] == 0


# ───────────────────────────── universo fechado ───────────────────────────────────────────────

@pytest.mark.parametrize("n,pontua", [(1, True), (2, True), (3, False), (7, False)])
def test_intersecao_de_produtos_fechada(n, pontua):
    """Se só 1 ou 2 produtos no mundo atendem ao conjunto, o conjunto foi desenhado para eles."""
    res = P1EspecificacaoDirigida().avaliar({
        **_P, "requisitos": [{"requisito": "spec genérica"}],
        "datasheets_finalistas": [f"produto {i}" for i in range(n)]})
    assert (res.score >= ANCORAS["forte"]) is pontua
    assert res.valores["n_produtos_intersecao"] == n


# ───────────────────────────── corroboração pelo resultado ────────────────────────────────────

def test_poucos_licitantes_corrobora_mas_nao_cria_achado_sozinho():
    """O resultado agrava o que já é indício; sozinho, poucos licitantes é mercado pequeno."""
    so_resultado = P1EspecificacaoDirigida().avaliar({
        **_P, "requisitos": [{"requisito": "memória RAM", "valor": 16}],
        "resultado": {"licitantes": 1}})
    assert so_resultado.score == 0.0

    com_indicio = P1EspecificacaoDirigida().avaliar({
        **_P, "requisitos": [{"requisito": "peso", "valor": 17.3},
                             {"requisito": "ciclo", "valor": 2847}],
        "resultado": {"licitantes": 1}})
    assert com_indicio.score >= ANCORAS["forte"]


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = P1EspecificacaoDirigida().avaliar({**_P,
                                             "requisitos": [{"requisito": "impressora marca HP"}]})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "P1"
    assert d["status"] in STATUS_VALIDOS
    assert 0.0 <= d["score"] <= 1.0


# ── Falsos positivos medidos no acervo real (2026-07-28) ──────────────────────────────────
# A varredura por certame acusou P1 em 106 de 150 certames (71%). Nenhum órgão dirige
# especificação em 71% das compras: a régua é que casava homônimo. Cada teste abaixo é um
# trecho REAL que produzia achado, com o hash da evidência guardado no banco de achados.

_CTX = {"processo": "SEI-TESTE/000001/2026"}


def test_termo_de_referencia_nao_e_indicacao_de_marca():
    """O caso mais comum: 'conforme descrição no Termo de Referência' casava a pista
    `referência`. Praticamente todo edital contém essa frase."""
    res = P1EspecificacaoDirigida().avaliar({
        **_CTX,
        "tr_texto": "O objeto está detalhado conforme descrição no Termo de Referência:\n"
                    "2.3.1 previsão de contratação para o exercício corrente.",
    })
    assert res.status != "confirmado", res.motivo_refutacao


def test_modelo_de_formulario_anexo_nao_e_marca():
    """'MODELO DE TERMO DE RECEBIMENTO' é um anexo, não um produto."""
    res = P1EspecificacaoDirigida().avaliar({
        **_CTX,
        "tr_texto": "ANEXO II — MINUTA DE ORDEM DE SERVIÇO\n"
                    "2. MODELO DE TERMO DE RECEBIMENTO PARCIAL DO OBJETO",
    })
    assert res.status != "confirmado", res.motivo_refutacao


def test_modelo_digital_de_elevacao_nao_e_marca():
    """Cartografia. 'modelo' aqui é vocabulário técnico do objeto contratado."""
    res = P1EspecificacaoDirigida().avaliar({
        **_CTX,
        "tr_texto": "Levantamento do canal Maxambomba. Associado ao modelo digital de "
                    "elevação obtido a partir de restituição aerofotogramétrica.",
    })
    assert res.status != "confirmado", res.motivo_refutacao


def test_citacao_da_propria_vedacao_legal_nao_e_violacao_dela():
    """O trecho que mais incomoda: o TR reproduz o art. 41, que PROÍBE indicar marca, e o
    detector acusava essa reprodução de ser indicação de marca."""
    res = P1EspecificacaoDirigida().avaliar({
        **_CTX,
        "tr_texto": "São vedadas, na especificação do objeto, indicações referentes a: "
                    "marca, fabricante, modelo, procedência ou qualquer outra que restrinja "
                    "a competitividade, nos termos do art. 41 da Lei 14.133/2021.",
    })
    assert res.status != "confirmado", res.motivo_refutacao


def test_marca_de_verdade_continua_sendo_pega():
    """A correção não pode cegar o detector: indicação real de marca segue acusada."""
    res = P1EspecificacaoDirigida().avaliar({
        **_CTX,
        "tr_texto": "Item 3.1 — Notebook marca Dell Latitude 5540, processador i7, "
                    "conforme especificação do fabricante.",
    })
    assert res.status == "confirmado"
    assert res.score > 0
