# -*- coding: utf-8 -*-
"""Catracas do registro de detectores (`config/qualidade_detectores.yaml`) — COR-03, COR-04, COR-05, COR-10.

  · o registro é íntegro (controle aponta para teste que existe; exclusão aponta para função que existe);
  · cinco dívidas só diminuem; detector NOVO nasce em zero (os dois controles, hipóteses, domínio, e — se for
    manchete — fp medida). Base: `tests/golden/qualidade_base.json`, chaves `detector_*` (CST-05: só desce);
  · toda classe `Detector`, toda função de `cruzamentos_intel` servida por `/api/intel/*` e toda regra do motor
    têm entrada (enumeradas por regex, sem importar o pacote);
  · provas (COR-15): o verificador fica vermelho com o defeito injetado em YAML sintético.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from compliance_agent.qualidade import catraca
from compliance_agent.qualidade import detectores as D

REPO = Path(__file__).resolve().parents[1]
CATRACAS = {  # base → dívida
    "detector_sem_controle_positivo": "sem_controle_positivo",
    "detector_sem_controle_negativo": "sem_controle_negativo",
    "detector_sem_hipotese_inocente": "sem_hipotese_inocente",
    "detector_sem_dominio": "sem_dominio",
    "detector_manchete_sem_fp": "manchete_sem_fp_medida",
}


@pytest.fixture(scope="module")
def registro():
    return D.carregar()


def test_registro_integro():
    assert D.problemas() == []


@pytest.mark.parametrize("base", sorted(CATRACAS))
def test_divida_do_registro_so_diminui(base):
    atual = D.dividas()[CATRACAS[base]]
    excesso = catraca.cresceu(atual, catraca.ler_base(base))
    assert not excesso, catraca.mensagem("COR-03/04/05/10", base.replace("_", " "), excesso)


def test_toda_classe_detector_tem_entrada(registro):
    classes = {m for f in (REPO / "compliance_agent" / "detectores").glob("*.py")
               for m in re.findall(r"^class (\w+)\(Detector\)", f.read_text(encoding="utf-8"), re.M)}
    assert len(classes) > 30
    assert sorted(c for c in classes if f"det.{c}" not in registro) == []


def _intel_servidas() -> set[str]:
    publicas = set(re.findall(r"^def ([a-z]\w*)\(", (REPO / "compliance_agent" / "cruzamentos_intel.py")
                              .read_text(encoding="utf-8"), re.M)) - {"ler_cache_intel", "gerar_cache_intel"}
    rotas = (REPO / "rotas" / "investigacao.py").read_text(encoding="utf-8")
    nomes = set()
    for bloco in re.split(r"@router\.get\(", rotas)[1:]:
        if not bloco.startswith(('"/api/intel/', "'/api/intel/")):
            continue
        for imp in re.findall(r"from compliance_agent\.cruzamentos_intel import ([\w, ]+)", bloco):
            nomes |= {n.strip() for n in imp.split(",")}
        nomes |= set(re.findall(r"ler_cache_intel\(\s*[\"'](\w+)[\"']", bloco))
    return nomes & publicas


def test_toda_funcao_intel_servida_por_rota_tem_entrada(registro):
    servidas = _intel_servidas()
    assert {"empresa_fenix", "radar_risco", "sancionadas_contratadas"} <= servidas
    assert sorted(n for n in servidas if f"intel.{n}" not in registro) == []


def test_toda_regra_do_motor_tem_entrada(registro):
    regras = re.findall(r"def _regra_(\w+)\(", (REPO / "compliance_agent" / "rules" / "engine.py")
                        .read_text(encoding="utf-8"))
    assert regras and sorted(r for r in regras if f"rules.{r}" not in registro) == []


def test_api_do_sensor(registro):
    """Assinatura usada pelo sensor `calibragem_manchetes` (outro autor)."""
    nc = D.nao_calibrados_em_manchete()
    assert set(nc) <= {k for k, e in registro.items() if e["manchete"]}
    assert all(not D.calibrado(k) for k in nc)
    r = D.resumo()
    assert r["total"] == len(registro) and r["por_divida"]["manchete_sem_fp_medida"] == len(nc)


# ───────────────────────── provas (COR-15): o defeito injetado deixa vermelho ─────────────────────────

def _entrada(**kw):
    e = {"modulo": "compliance_agent/qualidade/detectores.py", "simbolo": "carregar", "afirma": "x", "fonte": [],
         "grava": "x", "consome": [], "manchete": False,
         "controle_positivo": "tests/test_regra_controles_detector.py::test_registro_integro",
         "controle_negativo": "tests/test_regra_controles_detector.py::test_registro_integro",
         "hipoteses_inocentes": [{"hipotese": "h", "excluida_por": "compliance_agent/qualidade/detectores.py:carregar"}],
         "dominio": "d", "fp_medida": None}
    e.update(kw)
    return e


def _yaml(tmp_path, **entradas) -> Path:
    p = tmp_path / "det.yaml"
    p.write_text(yaml.safe_dump({"detectores": entradas}, allow_unicode=True), encoding="utf-8")
    return p


def test_prova_detector_novo_sem_controle_negativo_faz_a_catraca_crescer(tmp_path):
    p = _yaml(tmp_path, velho=_entrada(), novo=_entrada(controle_negativo=None))
    atual = D.dividas(p)["sem_controle_negativo"]
    assert catraca.cresceu(atual, {}) == ["novo: 1 (base 0)"]
    assert catraca.cresceu(D.dividas(_yaml(tmp_path, velho=_entrada()))["sem_controle_negativo"], {}) == []


def test_prova_controle_apontando_para_teste_inexistente_e_acusado(tmp_path):
    p = _yaml(tmp_path, a=_entrada(controle_positivo="tests/test_regra_controles_detector.py::test_nao_existe"),
              b=_entrada(controle_negativo="tests/arquivo_que_nao_existe.py::test_x"),
              c=_entrada(hipoteses_inocentes=[{"hipotese": "h", "excluida_por": "compliance_agent/x.py:f"}]))
    msgs = D.problemas(p)
    assert any(m.startswith("a: controle_positivo") and "test_nao_existe" in m for m in msgs)
    assert any(m.startswith("b: controle_negativo") and "inexistente" in m for m in msgs)
    assert any(m.startswith("c: hipótese") for m in msgs)
    assert D.problemas(_yaml(tmp_path, ok=_entrada())) == []


def test_prova_fp_medida_velha_nao_calibra(tmp_path):
    hoje = date(2026, 11, 13)
    fp = {"amostra": 30, "taxa": 0.1, "fonte_primaria": "DOERJ", "onde": "docs/x.md"}
    velha = _entrada(manchete=True, fp_medida={**fp, "data": (hoje - timedelta(days=181)).isoformat()})
    nova = _entrada(manchete=True, fp_medida={**fp, "data": (hoje - timedelta(days=10)).isoformat()})
    p = _yaml(tmp_path, velha=velha, nova=nova, sem=_entrada(manchete=True))
    assert not D._calibrado(velha, hoje) and D._calibrado(nova, hoje)
    assert set(D.dividas(p, hoje)["manchete_sem_fp_medida"]) == {"velha", "sem"}


def test_prova_refutado_em_manchete_entra_na_lista_de_atencao(tmp_path):
    rev = {"veredito": "REFUTADA", "afirmado": "a", "sustentado": "b"}
    p = _yaml(tmp_path, m=_entrada(manchete=True, revisao_2026_11_13=rev), n=_entrada(revisao_2026_11_13=rev))
    assert D.dividas(p)["refutado_em_manchete"] == {"m": 1}
