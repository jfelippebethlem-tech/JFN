# -*- coding: utf-8 -*-
"""Testes do motor de investigação de fachada/laranja (investigacao_dd).

Puros/determinísticos (sem rede): passam `cadastral` pronto e `usar_rede=False`/`geocode=False`.
Cobrem: marcadores residenciais, capital ínfimo, recência, situação irregular, porte, sócio único,
honestidade (INDISPONÍVEL quando falta dado; nenhum achado quando empresa é regular)."""
from compliance_agent.investigacao_dd import _marcadores_residenciais, investigar


def _inv(cad, total=0.0, primeira=None):
    pag = {"total_pago": total}
    if primeira:
        pag["primeira_data"] = primeira
    return investigar("11222333000181", cadastral=cad, pagamentos=pag, usar_rede=False, geocode=False)


def _codigos(out):
    return {h["codigo"] for h in out["hipoteses"]}


def test_marcadores_residenciais_fortes():
    assert "CASA" in _marcadores_residenciais("CASA 2", "")
    assert "APTO" in _marcadores_residenciais("APTO 301", "")
    assert "FUNDOS" in _marcadores_residenciais("", "RUA X FUNDOS")
    # endereço claramente comercial não dispara
    assert _marcadores_residenciais("SALA 1203", "AV RIO BRANCO") == []


def test_endereco_residencial_indicio():
    out = _inv({"complemento": "CASA", "logradouro": "RUA DAS FLORES", "situacao": "ATIVA"},
               total=2_000_000)
    assert "H-END-RESID" in _codigos(out)
    h = next(h for h in out["hipoteses"] if h["codigo"] == "H-END-RESID")
    assert h["status"] == "INDICIO"
    assert h["nivel"] == "ALTO"  # >1M recebido


def test_capital_infimo():
    out = _inv({"capital": 1000.0, "situacao": "ATIVA"}, total=5_000_000)
    assert "H-CAPITAL" in _codigos(out)
    h = next(h for h in out["hipoteses"] if h["codigo"] == "H-CAPITAL")
    assert h["status"] == "INDICIO"


def test_capital_compativel_nao_dispara():
    out = _inv({"capital": 5_000_000.0, "situacao": "ATIVA"}, total=1_000_000)
    assert "H-CAPITAL" not in _codigos(out)


def test_empresa_recente():
    out = _inv({"abertura": "2024-01-01", "situacao": "ATIVA"}, total=100_000,
               primeira="2024-02-15")  # ~45 dias
    assert "H-RECENTE" in _codigos(out)
    assert next(h for h in out["hipoteses"] if h["codigo"] == "H-RECENTE")["nivel"] == "ALTO"


def test_empresa_antiga_nao_dispara():
    out = _inv({"abertura": "2005-01-01", "situacao": "ATIVA"}, total=100_000,
               primeira="2024-02-15")
    assert "H-RECENTE" not in _codigos(out)


def test_situacao_irregular_confirmado():
    out = _inv({"situacao": "BAIXADA"}, total=100_000)
    h = next(h for h in out["hipoteses"] if h["codigo"] == "H-SITUACAO")
    assert h["status"] == "CONFIRMADO"
    assert h["nivel"] == "ALTO"


def test_porte_acima_do_teto():
    out = _inv({"porte": "MICRO EMPRESA", "situacao": "ATIVA"}, total=2_000_000)  # teto 360k
    assert "H-PORTE" in _codigos(out)


def test_socio_unico_composite():
    out = _inv({"situacao": "ATIVA", "complemento": "CASA",
                "socios": [{"nome": "FULANO", "doc": "***", "qualificacao": "Sócio"}]},
               total=500_000)
    assert "H-SOCIO-UNICO" in _codigos(out)


def test_empresa_regular_sem_achados_e_honesto():
    out = _inv({"situacao": "ATIVA", "logradouro": "AV PRESIDENTE VARGAS", "numero": "100",
                "capital": 10_000_000.0, "porte": "DEMAIS",
                "socios": [{"nome": "A"}, {"nome": "B"}]}, total=1_000_000)
    assert out["hipoteses"] == []
    assert out["grau"] == "🟢"
    assert "Nenhum indício" in out["resumo"]


def test_cobertura_honesta_sem_dados():
    out = investigar("11222333000181", cadastral={}, pagamentos={}, usar_rede=False, geocode=False)
    cob = out["cobertura"]
    assert cob.get("capital", "").startswith("INDISPONIVEL")
    assert cob.get("situacao_cadastral", "").startswith("INDISPONIVEL")
    assert out["grau"] == "🟢"  # ausência de dado nunca vira achado


def test_grau_exige_corroboracao():
    # um único indício fraco (porte) não deve ir a 🔴
    out = _inv({"porte": "MICRO EMPRESA", "situacao": "ATIVA"}, total=400_001)
    assert out["grau"] in ("🟢", "🟡")
    assert out["n_confirmados"] == 0
