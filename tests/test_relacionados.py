# -*- coding: utf-8 -*-
"""Processo relacionado: onde mora o ato de designação quando ele não está no processo de pagamento.

Medido em 2026-07-28 sobre 600 caches: **18% citam ao menos um número SEI DIFERENTE do próprio**.
Isso importa porque só 68 dos 2.053 processos do acervo (3,3%) têm algum documento de designação
no próprio processo — o ato costuma viver no processo-PAI da contratação, e o de pagamento
apenas o referencia.

O guard central: não casar o PRÓPRIO número. Todo cache cita a si mesmo várias vezes (o bloco de
relacionados repete o número do processo em cada linha), e sem o filtro a função devolveria o
processo que já se está lendo.
"""
from __future__ import annotations

import json

from compliance_agent.sei.relacionados import (
    numero_para_pasta, pasta_para_numero, relacionados_de,
)


def _cache(tmp_path, numero, relacionados):
    nome = "cdp_SEI_" + numero.replace("SEI-", "").replace("/", "_") + ".json"
    (tmp_path / nome).write_text(json.dumps(
        {"numero": numero, "relacionados": relacionados}, ensure_ascii=False))
    return tmp_path


def test_extrai_outro_processo_e_ignora_o_proprio(tmp_path):
    base = _cache(tmp_path, "SEI-420001/004987/2025", [
        {"texto": "SEI-420001/004987/2025", "titulo": "Financeiro: Pagamento"},
        {"texto": "SEI-420001/000698/2024", "titulo": "Contratação"},
    ])
    assert relacionados_de("SEI-420001/004987/2025", base) == ["SEI-420001/000698/2024"]


def test_nao_duplica_o_mesmo_relacionado(tmp_path):
    base = _cache(tmp_path, "SEI-260007/004415/2025", [
        {"texto": "SEI-260007/006085/2024"},
        {"texto": "SEI-260007/006085/2024", "titulo": "outra linha"},
    ])
    assert relacionados_de("SEI-260007/004415/2025", base) == ["SEI-260007/006085/2024"]


def test_acha_numero_dentro_de_titulo_e_url(tmp_path):
    """O número aparece em campos diferentes conforme a linha do bloco."""
    base = _cache(tmp_path, "SEI-030001/000001/2026", [
        {"titulo": "Referente ao SEI-030001/009999/2025"},
    ])
    assert relacionados_de("SEI-030001/000001/2026", base) == ["SEI-030001/009999/2025"]


def test_cache_ausente_devolve_lista_vazia(tmp_path):
    assert relacionados_de("SEI-999999/999999/9999", tmp_path) == []


def test_cache_ilegivel_nao_quebra(tmp_path):
    (tmp_path / "cdp_SEI_030001_000002_2026.json").write_text("{ não é json")
    assert relacionados_de("SEI-030001/000002/2026", tmp_path) == []


def test_sem_relacionados_devolve_vazio(tmp_path):
    base = _cache(tmp_path, "SEI-030001/000003/2026", [])
    assert relacionados_de("SEI-030001/000003/2026", base) == []


# ── conversão entre as duas grafias ────────────────────────────────────────────────────────

def test_ida_e_volta_entre_numero_e_pasta():
    assert numero_para_pasta("SEI-260007/004415/2025") == "260007_004415_2025"
    assert pasta_para_numero("260007_004415_2025") == "SEI-260007/004415/2025"
    for n in ("SEI-030001/004946/2026", "SEI-420001/000698/2024"):
        assert pasta_para_numero(numero_para_pasta(n)) == n


def test_conversao_tolera_numero_sem_prefixo():
    assert numero_para_pasta("260007/004415/2025") == "260007_004415_2025"
