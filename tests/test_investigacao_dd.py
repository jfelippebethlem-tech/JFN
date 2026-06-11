# -*- coding: utf-8 -*-
"""Testes do motor de investigação de fachada/laranja (investigacao_dd).

Puros/determinísticos (sem rede): passam `cadastral` pronto e `usar_rede=False`/`geocode=False`.
Cobrem: marcadores residenciais, capital ínfimo, recência, situação irregular, porte, sócio único,
honestidade (INDISPONÍVEL quando falta dado; nenhum achado quando empresa é regular)."""
from compliance_agent.investigacao_dd import (
    _cpf_completo, _marcadores_residenciais, _socio_eh_pf, investigar,
)


def _inv(cad, total=0.0, primeira=None):
    pag = {"total_pago": total}
    if primeira:
        pag["primeira_data"] = primeira
    return investigar("11222333000181", cadastral=cad, pagamentos=pag,
                      usar_rede=False, geocode=False, usar_beneficios=False)


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


# ───────────────────── H-PEP / H-BENEFICIO (Portal da Transparência) ─────────────────────

def test_cpf_completo_distingue_mascarado():
    assert _cpf_completo("12345678901") == "12345678901"
    assert _cpf_completo("123.456.789-01") == "12345678901"
    assert _cpf_completo("***456789**") == ""   # QSA mascarado (LGPD)
    assert _cpf_completo("123.***.**9-01") == ""
    assert _cpf_completo("") == ""


def test_socio_eh_pf_vs_pj():
    assert _socio_eh_pf({"doc": "***456789**"})          # CPF mascarado → trata como PF
    assert _socio_eh_pf({"doc": "12345678901"})          # CPF completo → PF
    assert not _socio_eh_pf({"doc": "12345678000190"})   # 14 díg → sócio PJ


def test_beneficios_pep_sem_chave_e_honesto(monkeypatch):
    # sem chave do Portal → INDISPONÍVEL (nunca "limpo"), e nenhuma hipótese H-PEP/H-BENEFICIO
    import compliance_agent.collectors.beneficios_sociais as bs
    monkeypatch.setattr(bs, "_chave", lambda: "")
    out = investigar("11222333000181",
                     cadastral={"situacao": "ATIVA", "socios": [{"nome": "FULANO DE TAL", "doc": "***1**"}]},
                     pagamentos={"total_pago": 1_000_000}, usar_rede=False, geocode=False)
    cob = out["cobertura"]
    assert cob.get("pep", "").startswith("INDISPONIVEL")
    assert cob.get("beneficio_social", "").startswith("INDISPONIVEL")
    assert {"H-PEP", "H-BENEFICIO"}.isdisjoint(_codigos(out))


def test_pep_por_nome_gera_indicio(monkeypatch):
    import compliance_agent.collectors.beneficios_sociais as bs
    monkeypatch.setattr(bs, "_chave", lambda: "k")

    async def fake_pep(cpf="", nome="", forcar_update=False):
        return {"verificado": True, "eh_pep": True,
                "peps": [{"nome": nome, "funcao": "Vereador", "orgao": "Câmara Municipal"}], "motivo": ""}

    async def fake_benef(cpf, forcar_update=False):
        return {"verificado": True, "recebe_beneficio": False, "beneficios": [], "motivo": ""}

    monkeypatch.setattr(bs, "verificar_pep", fake_pep)
    monkeypatch.setattr(bs, "verificar_beneficios", fake_benef)
    out = investigar("11222333000181",
                     cadastral={"situacao": "ATIVA", "socios": [{"nome": "FULANO DE TAL", "doc": "***1**"}]},
                     pagamentos={"total_pago": 500_000}, usar_rede=False, geocode=False)
    h = next(h for h in out["hipoteses"] if h["codigo"] == "H-PEP")
    assert h["status"] == "INDICIO"
    assert "Vereador" in h["evidencia"]
    # CPF do sócio mascarado → benefício fica INDISPONÍVEL (honesto), não falso-negativo
    assert out["cobertura"]["beneficio_social"].startswith("INDISPONIVEL")


def test_beneficio_por_cpf_completo_pf_gera_indicio(monkeypatch):
    import compliance_agent.collectors.beneficios_sociais as bs
    monkeypatch.setattr(bs, "_chave", lambda: "k")

    async def fake_benef(cpf, forcar_update=False):
        return {"verificado": True, "recebe_beneficio": True,
                "beneficios": [{"tipo": "Seguro-Defeso"}], "motivo": ""}

    async def fake_pep(cpf="", nome="", forcar_update=False):
        return {"verificado": True, "eh_pep": False, "peps": [], "motivo": ""}

    monkeypatch.setattr(bs, "verificar_beneficios", fake_benef)
    monkeypatch.setattr(bs, "verificar_pep", fake_pep)
    # favorecido PF (CPF de 11 díg) recebendo do Estado e beneficiário de subsistência → laranja
    out = investigar("12345678901", cadastral={"situacao": "ATIVA"},
                     pagamentos={"total_pago": 800_000}, usar_rede=False, geocode=False)
    h = next(h for h in out["hipoteses"] if h["codigo"] == "H-BENEFICIO")
    assert h["status"] == "INDICIO" and h["nivel"] == "ALTO"
    assert "Seguro-Defeso" in h["evidencia"]
