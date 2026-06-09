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


def _blk(linhas):
    return {"linhas": linhas, "total": sum(l["valor"] for l in linhas), "n": len(linhas)}


def _ctx_controle(socios):
    return {"cnpj": "19088605000104", "nome": "MGS CLEAN", "data": "2026-06-09",
            "enriq": {"ok": True, "dados": {"empresa": {"cnae_principal": "8121400 - Limpeza", "socios": socios}}},
            "pagamentos": {"tem_dados": True, "anos": [2022, 2024], "total_geral": 50_000_000, "n_geral": 2,
                           "hhi": {"top_share": 0, "indice": 0, "nivel": "baixa"}, "por_orgao_geral": {},
                           "por_ano": {2022: _blk([{"data": "2022-06-01", "valor": 40_000_000, "orgao": "X"}]),
                                       2024: _blk([{"data": "2025-01-01", "valor": 10_000_000, "orgao": "X"}])}}}


def test_r6_troca_de_controle_dispara(monkeypatch):
    """R6: sócio entra DEPOIS de R$40M já pagos → indício de sucessão/interposição."""
    lex = _patch_tcerj(monkeypatch, "")
    an = lex._analise(_ctx_controle([{"nome": "NOVO DONO", "data_entrada": "2024-12-11"}]), ler_sei=False)
    r6 = [a for a in an["achados"] if a["rf"] == "R6"]
    assert r6 and "posterior" in r6[0]["obs"]


def test_r6_nao_dispara_socio_antigo(monkeypatch):
    lex = _patch_tcerj(monkeypatch, "")
    an = lex._analise(_ctx_controle([{"nome": "DONO ORIGINAL", "data_entrada": "2010-01-01"}]), ler_sei=False)
    assert not any(a["rf"] == "R6" for a in an["achados"])
