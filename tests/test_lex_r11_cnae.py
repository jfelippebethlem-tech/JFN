"""
Loop 11 — Lex: achado R11 (atividade-fim/CNAE incompatível com o objeto contratado).

Conecta ao parecer jurídico o mesmo sinal estrutural do RF-05 do /relatorio: empresa de
prateleira/fachada / qualificação técnica frágil. Conservador (zero-overlap de termos
significativos) — sem falso-positivo. Offline (monkeypatch do TCE-RJ; sem rede/SEI).
"""
import os

import pytest

os.environ.setdefault("JFN_LEX_LER_SEI", "0")
os.environ.setdefault("JFN_LEX_DISCURSIVO", "0")


def _ctx(cnae: str) -> dict:
    return {"cnpj": "19088605000104", "nome": "MGS CLEAN", "data": "2026-06-09",
            "enriq": {"ok": True, "dados": {"empresa": {"cnae_principal": cnae}}}}


def _patch_tcerj(monkeypatch, objeto: str):
    import compliance_agent.lex as lex
    monkeypatch.setattr(lex, "_contratos_tcerj",
                        lambda cnpj: [{"_tipo": "contrato", "objeto": objeto, "valor_contrato": 1_000_000}])
    return lex


def test_r11_dispara_em_cnae_incompativel(monkeypatch):
    lex = _patch_tcerj(monkeypatch, "CONTRATAÇÃO DE PRESTAÇÃO DE SERVIÇOS CONTINUADOS DE LIMPEZA E CONSERVAÇÃO")
    an = lex._analise(_ctx("6319400 - Portais e provedores de conteúdo na internet"), ler_sei=False)
    achados = [a for a in an["achados"] if a["rf"] == "R11"]
    assert achados, "R11 deveria disparar p/ CNAE de internet × objeto de limpeza"
    assert "fachada" in achados[0]["obs"].lower() or "prateleira" in achados[0]["obs"].lower()


def test_r11_nao_dispara_em_cnae_aderente(monkeypatch):
    lex = _patch_tcerj(monkeypatch, "CONTRATAÇÃO DE SERVIÇOS DE LIMPEZA E CONSERVAÇÃO PREDIAL")
    an = lex._analise(_ctx("8121400 - Limpeza em prédios e em domicílios"), ler_sei=False)
    assert not any(a["rf"] == "R11" for a in an["achados"]), "R11 não pode disparar quando o CNAE adere ao objeto"
