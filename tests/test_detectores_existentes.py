# -*- coding: utf-8 -*-
"""Teste TARGETED dos WRAPPERS que reusam o código existente do JFN (J1/P3/C + orquestrador).

Estratégia (leve, VM 2 vCPU/sem swap): monkeypatch das funções REUSADAS (`concentracao_por_grupo`,
`rodizio_orgao`, `sobrepreco_interno`, `investigar`) com retornos FAKE — nada de DuckDB/LLM ao vivo. Verifica:
  • cada wrapper produz um `ResultadoDetector` VÁLIDO (schema §1.4) com âncora correta e evidência preenchida;
  • `nao_avaliavel` honesto quando a fonte degrada (base vazia, sem referencial, investigação indisponível);
  • a exculpatória adversarial degrada honesto SEM LLM (gerar fake) sem quebrar.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detectores_existentes.py -q
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import (
    ANCORAS,
    REGISTRO,
    CFachada,
    J1Cartel,
    P3Sobrepreco,
    ResultadoDetector,
    rodar_fornecedor,
    rodar_orgao,
    score_processo,
)
from compliance_agent.detectores.base import STATUS_VALIDOS


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4 que todo ResultadoDetector deve respeitar."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ───────────────────────────── J1 — conluio/cartel ─────────────────────────────
def _conc_com_socio_elo(share=42.0, n_cnpjs=4, n_raizes=2):
    """maior_grupo_multi com n_cnpjs > n_raizes ⇒ sócio-elo (CNPJs de raízes distintas unidos por sócio)."""
    return {
        "ug": "036100", "ug_nome": "X", "indicio": True, "n_cnpjs": 30, "n_grupos": 12, "n_grupos_multi": 1,
        "maior_grupo_multi": {"grupo": "g", "n_cnpjs": n_cnpjs, "n_raizes": n_raizes, "total": 1_000_000.0,
                              "share": share, "top_nome": "ALFA LTDA", "cnpjs": ["11111111000100", "22222222000100"]},
        "grupos": [],
    }


def _conc_sem_socio_elo(share=42.0):
    """grupo multi-raiz mas n_cnpjs == n_raizes ⇒ SEM sócio-elo materializado (apenas concentração)."""
    m = _conc_com_socio_elo(share=share, n_cnpjs=2, n_raizes=2)
    return m


def test_j1_critico_com_socio_elo():
    ctx = {"ug": "036100", "concentracao": _conc_com_socio_elo(), "rodizio": {"indicio": False}}
    r = J1Cartel().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]           # sócio comum entre "concorrentes" = crítico
    assert r.valores["socio_elo_presente"] is True
    assert r.evidencia, "deve citar os CNPJs do grupo + o sócio-elo"
    assert any("sócio" in e["trecho"].lower() or "socio" in e["trecho"].lower() for e in r.evidencia)


def test_j1_medio_so_concentracao_sem_socio():
    ctx = {"ug": "036100", "concentracao": _conc_sem_socio_elo(), "rodizio": {"indicio": False}}
    r = J1Cartel().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["medio"]             # concentração sem sócio-elo → médio (FP: mercado restrito)
    assert r.valores["socio_elo_presente"] is False


def test_j1_rodizio_reforca_para_forte():
    rod = {"indicio": True, "score": 0.7, "n_campeoes": 3, "n_anos": 3, "alternancia": 0.6,
           "campeoes": [{"nome": "ALFA"}, {"nome": "BETA"}]}
    ctx = {"ug": "036100", "concentracao": _conc_sem_socio_elo(), "rodizio": rod}
    r = J1Cartel().avaliar(ctx)
    _valido(r)
    assert r.score == ANCORAS["forte"]             # médio + rodízio corroborando → forte
    assert r.valores["rodizio_indicio"] is True


def test_j1_descartado_sem_grupo_multi():
    conc = {"n_cnpjs": 30, "maior_grupo_multi": None, "n_grupos_multi": 0}
    r = J1Cartel().avaliar({"ug": "036100", "concentracao": conc, "rodizio": None})
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j1_nao_avaliavel_base_vazia():
    r = J1Cartel().avaliar({"ug": "999", "concentracao": {"n_cnpjs": 0}, "rodizio": None})
    _valido(r)
    assert r.status == "nao_avaliavel"             # base vazia ≠ 0 (honestidade JFN)


def test_j1_degrada_quando_funcao_reusada_quebra(monkeypatch):
    """Sem injetar `concentracao` → wrapper chama a função real; se ela lança (sem DuckDB) → nao_avaliavel."""
    import compliance_agent.grafo_cartel as gc

    def _boom(*a, **k):
        raise RuntimeError("DuckDB indisponível")

    monkeypatch.setattr(gc, "concentracao_por_grupo", _boom)
    r = J1Cartel().avaliar({"ug": "036100"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "indisponível" in r.motivo_refutacao


# ───────────────────────────── P3 — sobrepreço ─────────────────────────────
def _achado_sobrepreco(razao=4.5):
    return [{"item": "papel a4", "n": 5, "min": 10.0, "max": 10.0 * razao, "mediana": 18.0,
             "razao_max_min": razao, "sobrepreco_pct_vs_mediana": 150.0,
             "mais_caro": {"preco": 10.0 * razao, "ref": "C2", "orgao": "B"},
             "mais_barato": {"preco": 10.0, "ref": "C1", "orgao": "A"}}]


@pytest.mark.parametrize("razao,esperado", [(4.5, "forte"), (3.2, "medio"), (2.1, "fraco")])
def test_p3_ancora_por_magnitude(razao, esperado):
    r = P3Sobrepreco().avaliar({"processo": "item-x", "achados": _achado_sobrepreco(razao)})
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS[esperado]
    assert r.evidencia and "papel a4" in r.evidencia[0]["trecho"]
    assert r.valores["razao_max_min"] == razao


def test_p3_nao_avaliavel_sem_registros():
    r = P3Sobrepreco().avaliar({"processo": "item-x", "registros": []})
    _valido(r)
    assert r.status == "nao_avaliavel"             # sem_referencial: não pontua sem base (regra dura P3)
    assert "sem_referencial" in r.motivo_refutacao


def test_p3_nao_avaliavel_amostra_insuficiente():
    # 2 registros do mesmo item, min_amostras=3 ⇒ sobrepreco_interno não compara ⇒ sem_referencial
    regs = [{"descricao": "toner hp", "preco_unitario": 100.0, "ref": "A"},
            {"descricao": "toner hp", "preco_unitario": 400.0, "ref": "B"}]
    r = P3Sobrepreco().avaliar({"processo": "item-x", "registros": regs, "min_amostras": 3})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "sem_referencial" in r.motivo_refutacao


def test_p3_descartado_homogeneo():
    # 3 amostras comparáveis mas sem dispersão ≥2× ⇒ descartado (não nao_avaliavel)
    regs = [{"descricao": "caneta azul", "preco_unitario": p, "ref": str(p)} for p in (1.0, 1.1, 1.2)]
    r = P3Sobrepreco().avaliar({"processo": "item-x", "registros": regs, "min_amostras": 3})
    _valido(r)
    assert r.status == "descartado"


def test_p3_usa_funcao_real_via_registros():
    """Sem injetar `achados`: o wrapper chama o sobrepreco_interno REAL (reuso de código, sem mock)."""
    regs = [{"descricao": "monitor 24", "preco_unitario": p, "ref": str(i), "orgao": f"o{i}"}
            for i, p in enumerate((500.0, 520.0, 2500.0, 510.0))]
    r = P3Sobrepreco().avaliar({"processo": "item-x", "registros": regs, "min_amostras": 3})
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]             # 2500/500 = 5× → forte


# ───────────────────────────── C — fachada/laranja ─────────────────────────────
def _inv_fake():
    """Investigação fake cobrindo H-RECENTE(C1)/H-CAPITAL(C2)/H-SITUACAO(C3-5)/H-COEND(C4)."""
    return {
        "cnpj": "12345678000190", "grau": "🔴", "score": 60, "n_indicios": 3, "n_confirmados": 1,
        "cobertura": {}, "resumo": "x",
        "hipoteses": [
            {"codigo": "H-RECENTE", "titulo": "Empresa recém-aberta", "status": "INDICIO", "nivel": "ALTO",
             "evidencia": "aberta 40 dias antes do 1º recebimento", "fonte": "Receita", "base_legal": "x", "peso": 18},
            {"codigo": "H-CAPITAL", "titulo": "Capital ínfimo", "status": "INDICIO", "nivel": "MEDIO",
             "evidencia": "capital R$ 1.000 contra R$ 2M recebidos", "fonte": "Receita", "base_legal": "x", "peso": 8},
            {"codigo": "H-SITUACAO", "titulo": "Situação irregular", "status": "CONFIRMADO", "nivel": "ALTO",
             "evidencia": "situação BAIXADA na Receita", "fonte": "Receita", "base_legal": "x", "peso": 20},
            {"codigo": "H-COEND", "titulo": "Co-endereço", "status": "INDICIO", "nivel": "MEDIO",
             "evidencia": "3 fornecedores na mesma sede", "fonte": "JFN", "base_legal": "x", "peso": 8},
            {"codigo": "H-PEP", "titulo": "PEP", "status": "INDICIO", "nivel": "ALTO",  # NÃO mapeado → ignorado
             "evidencia": "sócio é PEP", "fonte": "CGU", "base_legal": "x", "peso": 12},
        ],
    }


def test_c_mapeia_hipoteses_para_detectores():
    res = CFachada().avaliar_todos({"cnpj": "12345678000190", "investigacao": _inv_fake()})
    ids = {r.detector for r in res}
    assert {"C1", "C2", "C3/C5", "C4"} <= ids        # H-RECENTE/H-CAPITAL/H-SITUACAO/H-COEND mapeados
    assert "C" not in ids                             # houve hipóteses → sem placeholder nao_avaliavel
    for r in res:
        _valido(r)
        assert r.status == "confirmado"
        assert r.evidencia and r.explicacao_inocente


def test_c_ancora_confirmado_alto_vira_forte():
    res = CFachada().avaliar_todos({"cnpj": "x", "investigacao": _inv_fake()})
    c35 = next(r for r in res if r.detector == "C3/C5")   # H-SITUACAO CONFIRMADO/ALTO → forte
    assert c35.score == ANCORAS["forte"]
    c1 = next(r for r in res if r.detector == "C1")       # H-RECENTE INDICIO/ALTO → medio
    assert c1.score == ANCORAS["medio"]
    c2 = next(r for r in res if r.detector == "C2")       # H-CAPITAL INDICIO/MEDIO → fraco
    assert c2.score == ANCORAS["fraco"]


def test_c_nao_avaliavel_sem_hipoteses():
    inv = {"cnpj": "x", "grau": "🟢", "score": 0, "cobertura": {"capital": "INDISPONIVEL"}, "hipoteses": []}
    res = CFachada().avaliar_todos({"cnpj": "x", "investigacao": inv})
    assert len(res) == 1
    _valido(res[0])
    assert res[0].status == "nao_avaliavel"          # nenhuma hipótese ≠ regular (ausência de juízo)


def test_c_degrada_quando_investigar_quebra(monkeypatch):
    import compliance_agent.investigacao_dd as idd

    def _boom(*a, **k):
        raise RuntimeError("rede indisponível")

    monkeypatch.setattr(idd, "investigar", _boom)
    res = CFachada().avaliar_todos({"cnpj": "12345678000190"})  # sem investigacao injetada → chama real
    assert len(res) == 1
    _valido(res[0])
    assert res[0].status == "nao_avaliavel"


# ───────────────────────────── Orquestrador ─────────────────────────────
def test_rodar_orgao_usa_j1(monkeypatch):
    r = rodar_orgao("036100", contexto={"concentracao": _conc_com_socio_elo(), "rodizio": {"indicio": False}})
    assert any(x.detector == "J1" and x.status == "confirmado" for x in r)
    for x in r:
        _valido(x)


def test_rodar_fornecedor_combina_p3_e_c():
    ctx = {
        "achados": _achado_sobrepreco(4.5),
        "investigacao": _inv_fake(),
    }
    r = rodar_fornecedor("12345678000190", contexto=ctx)
    ids = {x.detector for x in r}
    assert "P3" in ids
    assert {"C1", "C2", "C3/C5", "C4"} <= ids
    for x in r:
        _valido(x)
    # convergência multiplicativa (§7.2) sobre os confirmados não quebra e fica em [0,1]
    from compliance_agent.detectores import PESOS_DETECTOR
    s = score_processo(r, PESOS_DETECTOR)
    assert 0.0 <= s <= 1.0


def test_rodar_fornecedor_exculpatoria_degrada_sem_llm():
    """exculpatoria=True com `gerar` que SIMULA LLM offline → não refuta, não quebra (honesto)."""
    def _gerar_offline(prompt, sistema):
        raise RuntimeError("LLM offline")

    ctx = {"achados": _achado_sobrepreco(4.5), "investigacao": _inv_fake()}
    r = rodar_fornecedor("12345678000190", contexto=ctx, exculpatoria=True, gerar=_gerar_offline)
    for x in r:
        _valido(x)
        if x.status == "confirmado":
            assert x.refutada is False               # LLM offline ≠ refutado (degrada honesto)
            assert "nao_avaliavel" in x.motivo_refutacao


def test_registro_tem_os_novos():
    assert {"P4", "J1", "P3", "C"} <= set(REGISTRO)
