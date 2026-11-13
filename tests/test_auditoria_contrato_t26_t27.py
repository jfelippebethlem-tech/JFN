# -*- coding: utf-8 -*-
"""T26 (liquidação antes do recebimento) e T27 (pagamento fora do objeto). Determinísticos, sem rede.

Confronto CGE × JFN 13/11/2026 (lacuna 4): a CGE achou liquidação em 30/12/2025 de equipamentos entregues só
em 07/05/2026, e pagamento mensal de mobiliário num contrato de locação de imóvel cuja proposta dizia "sem custos
extras". A perícia não tinha teste para nenhum dos dois. Critério: dispara nesses padrões e ZERO disparo em 20
controles regulares. Dados SINTÉTICOS.
"""
from __future__ import annotations

import pytest

from compliance_agent.auditoria_contrato import _t26_liquidacao_antes_recebimento as t26
from compliance_agent.auditoria_contrato import _t27_item_fora_do_objeto as t27
from compliance_agent.auditoria_contrato import auditar_contrato


# ── T26 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_t26_liquidacao_antes_da_entrega_e_indicio():
    h = t26({"liquidacoes": [{"nl": "2025NL00001", "data": "2025-12-30", "valor": 421_752.41}],
             "recebimentos": [{"data": "2026-05-07", "documento": "Termo de Recebimento Definitivo"}]})
    assert h["codigo"] == "T26-LIQUIDACAO-ANTES-RECEBIMENTO" and h["status"] == "INDICIO" and h["nivel"] == "alto"
    assert "30/12/2025" in h["evidencia"] and "07/05/2026" in h["evidencia"] and "4.320" in h["base_legal"]


def test_t26_aceita_data_brasileira_e_nl_dentro_da_ob():
    h = t26({"obs": [{"nl": "2025NL00001", "data_liquidacao": "30/12/2025", "status": "Contabilizado"}],
             "recebimentos": [{"data": "07/05/2026"}]})
    assert h["status"] == "INDICIO"


def test_t26_sem_recebimento_ou_sem_liquidacao_datada_e_indisponivel():
    assert t26({"liquidacoes": [{"data": "2025-12-30"}]})["status"] == "INDISPONIVEL"
    assert t26({"recebimentos": [{"data": "2026-05-07"}]})["status"] == "INDISPONIVEL"


# 20 controles G0 sintéticos: liquidação no mesmo dia ou depois do recebimento
CONTROLES_T26 = [
    {"liquidacoes": [{"nl": f"2025NL{i:05d}", "data": f"2025-{(i % 12) + 1:02d}-20"}],
     "recebimentos": [{"data": f"2025-{(i % 12) + 1:02d}-{10 + (i % 10):02d}"}]}
    for i in range(20)
]


@pytest.mark.parametrize("d", CONTROLES_T26)
def test_t26_zero_disparo_em_20_controles(d):
    assert t26(d)["status"] == "AFASTADO"


# ── T27 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_t27_mobiliario_pago_em_contrato_de_locacao_de_imovel():
    h = t27({"objeto": "Locação de imóvel para a sede do instituto",
             "obs": [{"numero_ob": "2026OB00001", "status": "Contabilizado", "valor": 7_413.98,
                      "historico": "Pagamento referente ao mobiliário do imóvel locado — competência 03/2026"},
                     {"numero_ob": "2026OB00002", "status": "Contabilizado", "valor": 110_000.00,
                      "historico": "Aluguel competência 03/2026"}]})
    assert h["codigo"] == "T27-ITEM-FORA-DO-OBJETO" and h["status"] == "INDICIO"
    assert "mobili" in h["evidencia"].lower() and "2026OB00001" in h["evidencia"]
    assert "2026OB00002" not in h["evidencia"]


def test_t27_ob_anulada_nao_conta():
    h = t27({"objeto": "Locação de imóvel",
             "obs": [{"numero_ob": "X", "status": "Anulado", "historico": "mobiliário"}]})
    assert h["status"] != "INDICIO"


def test_t27_sem_objeto_ou_sem_historico_e_indisponivel():
    assert t27({"obs": [{"status": "Contabilizado", "historico": "mobiliário"}]})["status"] == "INDISPONIVEL"
    assert t27({"objeto": "Locação de imóvel", "obs": [{"status": "Contabilizado"}]})["status"] == "INDISPONIVEL"


CONTROLES_T27 = [
    ("Locação de imóvel", "Aluguel competência 0{m}/2026"),
    ("Serviços de limpeza e conservação predial", "Limpeza predial competência 0{m}/2026"),
    ("Vigilância patrimonial armada", "Serviço de vigilância — medição 0{m}/2026"),
    ("Fornecimento de mobiliário escolar", "Aquisição de mobiliário — NF 12{m}"),
    ("Locação de veículos com motorista", "Locação de veículos 0{m}/2026"),
]


@pytest.mark.parametrize("objeto,hist", [(o, h.format(m=m)) for o, h in CONTROLES_T27 for m in range(1, 5)])
def test_t27_zero_disparo_em_20_controles(objeto, hist):
    h = t27({"objeto": objeto, "obs": [{"numero_ob": "C", "status": "Contabilizado", "historico": hist}]})
    assert h["status"] == "AFASTADO", (objeto, hist, h["evidencia"])


def test_bateria_inclui_t26_e_t27():
    r = auditar_contrato({"obs": []})
    codigos = {a["codigo"] for a in r["achados"]}
    assert {"T26-LIQUIDACAO-ANTES-RECEBIMENTO", "T27-ITEM-FORA-DO-OBJETO"} <= codigos
