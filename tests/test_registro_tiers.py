# -*- coding: utf-8 -*-
"""O5.1 — registro completo + tiers (plano mestre v2 §5) em `config/qualidade_detectores.yaml`.

  · régua do tier (Wilson IC95, n ≥ 30 estratificado, ponto ≤ 15%, IC sup ≤ 25%, elegibilidade, cobertura ≥ 50%)
    provada em YAML sintético, condição a condição;
  · o tier/IC95/manchete_efetiva GRAVADO bate com o calculado hoje (`tools/registro_tiers.py --gravar` refaz);
  · catraca: `manchete: true` com tier ≠ 1 só para quem já estava na base (os 47 de 24/11/2026) — manchete NOVA
    sem tier 1 fica vermelha; a manchete EFETIVA (o que o painel lê na O7.3) é manchete E tier 1;
  · registro completo: padrões, EST-VALOR, perícias D1–D12 que gravam em `alertas`, os 10 cards sem varredura e as
    regras a portar estão no registro; fusões apontam para entrada canônica viva.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from compliance_agent.qualidade import catraca
from compliance_agent.qualidade import detectores as D

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("registro_tiers", REPO / "tools" / "registro_tiers.py")
RT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(RT)
HOJE = date(2026, 11, 24)


@pytest.fixture(scope="module")
def registro():
    return D.carregar()


def _fp(**kw):
    fp = {"data": "2026-11-20", "amostra": "a", "taxa": "t", "fonte_primaria": "SIAFE", "onde": "docs/x.md",
          "n": 60, "falsos": 3, "estratificada": True, "cobertura": 0.8}
    fp.update(kw)
    return fp


def _e(**kw):
    e = {"manchete": False, "dominio": "OB paga do SIAFE", "fp_medida": _fp()}
    e.update(kw)
    return e


# ───────────────────────── régua ─────────────────────────

def test_wilson_bate_com_valores_de_referencia():
    assert D.wilson_ic95(0, 30) == (0.0, 0.1135)
    assert D.wilson_ic95(1, 30) == (0.0059, 0.1667)
    assert D.wilson_ic95(13, 30) == (0.2738, 0.608)
    assert D.wilson_ic95(0, 0) is None


def test_tier1_quando_cumpre_tudo():
    t = D.avaliar_tier(_e(), HOJE)
    assert t["tier"] == 1 and t["tier_motivo"] == "cumpre_tier1" and t["fp_ic95"][1] <= 0.25


@pytest.mark.parametrize("mudanca, motivo", [
    ({"fp_medida": _fp(n=29, falsos=0)}, "n=29<30"),
    ({"fp_medida": _fp(estratificada=False)}, "amostra_nao_estratificada"),
    ({"fp_medida": _fp(n=60, falsos=10)}, "ponto="),
    ({"fp_medida": _fp(n=30, falsos=4)}, "ic95_sup="),                # ponto 13,3% passa; IC sup 29,7% não
    ({"dominio": None}, "sem_elegibilidade"),
    ({"fp_medida": _fp(cobertura=0.49)}, "cobertura=49%<50%"),
    ({"fp_medida": _fp(cobertura=None)}, "cobertura_desconhecida"),
])
def test_cada_condicao_do_tier1_rebaixa_para_2(mudanca, motivo):
    t = D.avaliar_tier(_e(**mudanca), HOJE)
    assert t["tier"] == 2 and motivo in t["tier_motivo"]


@pytest.mark.parametrize("fp, motivo", [
    (None, "sem_medida"),
    (_fp(data="2026-01-01"), "medida_incompleta_ou_vencida"),         # > 180 dias
    (_fp(onde=""), "medida_incompleta_ou_vencida"),
    (_fp(n=None, falsos=None), "medida_sem_contagem_de_decididos"),
    (_fp(n=0, falsos=0), "medida_sem_contagem_de_decididos"),
])
def test_sem_medida_utilizavel_e_tier3(fp, motivo):
    t = D.avaliar_tier(_e(fp_medida=fp), HOJE)
    assert (t["tier"], t["tier_motivo"]) == (3, motivo)


def test_manchete_efetiva_exige_tier1():
    assert D.campos_calculados(_e(manchete=True), HOJE)["manchete_efetiva"] is True
    assert D.campos_calculados(_e(manchete=True, dominio=None), HOJE)["manchete_efetiva"] is False
    assert D.campos_calculados(_e(manchete=False), HOJE)["manchete_efetiva"] is False


# ───────────────────────── o registro real ─────────────────────────

def test_registro_integro_com_campos_da_o51():
    assert D.problemas() == []


def test_tiers_gravados_batem_com_o_calculado():
    assert D.tiers_desatualizados() == [], "rode: python tools/registro_tiers.py --gravar"


def test_toda_entrada_tem_estado_e_tier(registro):
    assert all(e.get("estado") in D.ESTADOS and e.get("tier") in (1, 2, 3) for e in registro.values())


def test_manchete_efetiva_gravada_e_manchete_e_tier1(registro):
    for did, e in registro.items():
        assert e["manchete_efetiva"] == (bool(e["manchete"]) and e["tier"] == 1), did
    assert D.manchete_efetiva("rules.engine") is False             # 13/30 falsos: tier 2, não manchete


def test_catraca_manchete_sem_tier1_so_diminui():
    atual = D.dividas()["manchete_sem_tier1"]
    base = catraca.ler_base("detector_manchete_sem_tier1")
    assert len(base) == 47                                          # os 47 de 24/11/2026 (plano §2)
    excesso = catraca.cresceu(atual, base)
    assert not excesso, catraca.mensagem("O5.1 (§5 catraca de manchete)", "manchete sem tier 1", excesso)


def test_prova_manchete_nova_sem_tier1_fica_vermelha(tmp_path):
    p = tmp_path / "det.yaml"
    p.write_text(yaml.safe_dump({"detectores": {"velha": _e(manchete=True, dominio=None),
                                                "nova": _e(manchete=True, fp_medida=None),
                                                "boa": _e(manchete=True)}}), encoding="utf-8")
    atual = D.dividas(p, HOJE)["manchete_sem_tier1"]
    assert catraca.cresceu(atual, {"velha": 1}) == ["nova: 1 (base 0)"]


def test_medidas_conhecidas_viram_o_tier_esperado(registro):
    assert registro["rules.engine"]["tier"] == 2 and registro["rules.engine"]["fp_ic95"] == [0.2738, 0.608]
    assert registro["intel.comunidades"]["tier"] == 2                # 1/30, mas sem estrato, domínio nem cobertura
    assert registro["det.P4Fracionamento"]["tier_motivo"] == "medida_sem_contagem_de_decididos"
    assert sum(e["tier"] == 1 for e in registro.values()) == 0       # ninguém cumpre a régua hoje — honesto


# ───────────────────────── registro completo ─────────────────────────

def test_todo_padrao_tem_entrada(registro):
    ids = {p.stem for p in (REPO / "config" / "padroes").glob("*.yaml")}
    mods = {p.stem for p in (REPO / "compliance_agent" / "padroes").glob("*.py") if not p.stem.startswith("_")}
    assert ids == mods and len(ids) >= 24
    assert sorted(i for i in ids if f"padrao.{i}" not in registro) == []


def test_pericias_que_gravam_em_alertas_tem_entrada(registro):
    emendas = re.findall(r"^def (d\d+)_\w+\(", (REPO / "compliance_agent/emendas/pericia.py").read_text("utf-8"), re.M)
    assert emendas and sorted(d for d in emendas if f"emendas.{d.upper()}" not in registro) == []
    pcrj = re.findall(r"^def (d\d+_\w+)\(", (REPO / "compliance_agent/pcrj/pericia_gastos.py").read_text("utf-8"), re.M)
    falta = [f for f in pcrj if f != "d11_avaliacao" and f"pcrj.{f}" not in registro]
    assert pcrj and falta == []


def test_est_valor_e_regras_a_portar(registro):
    assert {"est.valor_excedido", "est.aditivo_teto"} <= set(registro)
    a_portar = {k for k, e in registro.items() if e["estado"] == "a_portar"}
    assert {"a_portar.p4_obra_e_lei_8666_tcerj", "a_portar.p5_dedup_por_processo",
            "a_portar.lex_fatos.c_pago_maior_que_nl", "a_portar.lex_fatos.c_ob_antes_da_nl"} <= a_portar
    assert all(registro[k].get("portar_para") for k in a_portar)


def test_os_10_cards_sem_varredura(registro):
    sem = sorted(k for k, e in registro.items() if e["estado"] == "sem_varredura")
    assert len(sem) == 10 and all(k.startswith("det.") for k in sem)
    assert all(re.match(r"\s*não grava \(sob demanda", registro[k]["grava"]) for k in sem)


def test_fusoes_apontam_para_canonica_viva(registro):
    fund = {k: e["fundido_em"] for k, e in registro.items() if e["estado"] == "fundido"}
    assert len(fund) >= 10
    assert all(registro[a]["estado"] != "fundido" for a in fund.values())


def test_prova_estado_e_fusao_invalidos_sao_acusados(tmp_path):
    base = {"modulo": "compliance_agent/qualidade/detectores.py", "simbolo": "carregar", "afirma": "x", "fonte": [],
            "grava": "x", "consome": [], "manchete": False, "controle_positivo": None, "controle_negativo": None,
            "hipoteses_inocentes": [], "dominio": None, "fp_medida": None}
    p = tmp_path / "det.yaml"
    p.write_text(yaml.safe_dump({"detectores": {
        "a": {**base, "estado": "vivo"},
        "b": {**base, "estado": "fundido", "fundido_em": "nao_existe"},
        "c": {**base, "estado": "fundido"},
        "d": {**base, "fp_medida": _fp(n=3, falsos=5)}}}), encoding="utf-8")
    msgs = D.problemas(p)
    assert any(m.startswith("a: estado") for m in msgs)
    assert any(m.startswith("b: fundido_em") for m in msgs)
    assert any(m.startswith("c: estado 'fundido'") for m in msgs)
    assert any(m.startswith("d: fp_medida.n/falsos") for m in msgs)


# ───────────────────────── gravador ─────────────────────────

def test_gravador_troca_so_os_campos_e_preserva_comentarios():
    texto = ("# cabeçalho\ndetectores:\n  a:\n    modulo: m  # comentário\n    tier: 9\n    x: 1\n\n"
             "  # bloco b\n  b:\n    modulo: n\n")
    novo = RT.aplicar_campos(texto, {"a": {"tier": 3, "fp_ic95": [0.0, 0.5]}, "b": {"tier": 2, "fp_ic95": None}},
                             ("tier", "fp_ic95"))
    assert "# comentário" in novo and "# bloco b" in novo and "tier: 9" not in novo
    d = yaml.safe_load(novo)["detectores"]
    assert d == {"a": {"modulo": "m", "x": 1, "tier": 3, "fp_ic95": [0.0, 0.5]},
                 "b": {"modulo": "n", "tier": 2, "fp_ic95": None}}
    assert RT.aplicar_campos(novo, {"a": {"tier": 3, "fp_ic95": [0.0, 0.5]}}, ("tier", "fp_ic95")) == novo
