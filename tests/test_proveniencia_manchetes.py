# -*- coding: utf-8 -*-
"""PAD-01/02/06/07: toda rota de manchete inventariada devolve `proveniencia` completa e dentro do vocabulário."""
from __future__ import annotations

from pathlib import Path

import yaml

from compliance_agent.proveniencia_manchetes import PROVENIENCIA, anexar
from compliance_agent.qualidade import verificadores as v

REPO = Path(__file__).resolve().parents[1]


def _rotas_de_manchete() -> set[str]:
    inv = yaml.safe_load((REPO / "config" / "qualidade_inventario.yaml").read_text(encoding="utf-8"))
    return {m["rota"] for m in inv.get("manchetes", []) if m.get("rota")}


def test_toda_rota_de_manchete_tem_proveniencia_declarada():
    assert _rotas_de_manchete() <= set(PROVENIENCIA)


def test_anexar_produz_bloco_completo_para_cada_rota():
    for rota in PROVENIENCIA:
        p = anexar(rota, {"ok": True, "gerado_em": "2026-11-19T10:00:00"})
        assert not v.proveniencia_incompleta(p), (rota, v.proveniencia_incompleta(p))
        assert p["proveniencia"]["data_ref"] == "2026-11-19T10:00:00"


def test_erro_nao_ganha_proveniencia_inventada():
    assert "proveniencia" not in anexar("/api/intel/fenix", {"ok": False, "erro": "x"})


def test_nao_sobrescreve_bloco_da_propria_rota():
    proprio = {"fonte": "x"}
    assert anexar("/api/intel/fenix", {"ok": True, "proveniencia": proprio})["proveniencia"] is proprio


def test_indicio_de_detector_nunca_sai_verificado():
    for rota in ("/api/comparador/economia", "/api/comparador/vedada", "/api/comparador/dossie", "/api/intel/radar",
                 "/api/intel/fenix", "/api/intel/comunidades", "/api/intel/ninho_sala", "/api/intel/lift"):
        assert PROVENIENCIA[rota]["estado"] == "PENDENTE", rota


def test_esfera_sistema_so_em_medicao_do_proprio_jfn():
    for rota, b in PROVENIENCIA.items():
        if b["esfera"] == "sistema":
            assert b["natureza"] == "contagem", rota
