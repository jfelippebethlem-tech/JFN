# -*- coding: utf-8 -*-
"""Catraca do próprio registro de regras (CST-12): regra que não roda é enfeite.

  · toda regra tem os campos, caso real e ao menos um verificador;
  · todo verificador apontado EXISTE (arquivo, teste, sensor, critério do juiz);
  · o documento canônico é o gerado (ninguém edita à mão e deixa divergir);
  · toda catraca de regra tem prova e está no portão de pre-push e no sensor da automelhoria (CST-05, COR-15).
"""
from __future__ import annotations

import re

from compliance_agent.qualidade import doc, regras

REPO = regras.REPO


def test_registro_integro():
    probs = regras.problemas()
    assert not probs, "defeitos em config/qualidade_regras.yaml:\n  " + "\n  ".join(probs)


def test_cinco_familias_com_regras():
    res = regras.resumo()
    assert all(res["por_familia"][f] >= 5 for f in regras.FAMILIAS), res["por_familia"]


def test_toda_regra_tem_verificador_que_roda_ou_divida_declarada():
    so_manual = regras.resumo()["so_manuais"]
    assert not so_manual, f"regra só com verificador manual (enfeite): {so_manual}"


def test_documento_canonico_em_sincronia():
    assert doc.em_sincronia(), ("docs/REGRAS-DE-QUALIDADE.md diverge de config/qualidade_regras.yaml — "
                                "regenere com `python -m compliance_agent.qualidade doc` (não edite à mão)")


def _arquivos_de_catraca() -> list[str]:
    return sorted({v["ref"].split("::")[0] for r in regras.carregar() for v in r.verificadores
                   if v["tipo"] == "catraca"})


# Arquivos em que TODO teste já é a prova: cada um monta o caso com defeito (tem de acusar) e o caso conforme
# (tem de calar) — controles positivo e negativo. Entrar aqui exige isso, não um nome.
PROVA_POR_NATUREZA = {"tests/test_regra_verificadores.py", "tests/test_regra_controles_sinteticos.py"}


def test_toda_catraca_de_regra_tem_prova():
    """COR-15: cada arquivo de catraca de regra traz teste de PROVA (o defeito injetado deixa vermelho)."""
    sem = [a for a in _arquivos_de_catraca() if a not in PROVA_POR_NATUREZA
           and not re.search(r"def test_\w*prova\w*\(", (REPO / a).read_text(encoding="utf-8"))]
    assert not sem, f"catraca de regra sem teste de prova: {sem}"


def test_catracas_de_regra_estao_no_portao():
    """CST-05: catraca que não está no portão não barra nada. Confere o pre-push e o sensor da automelhoria."""
    portao = (REPO / "tools" / "pre_push_gate.sh").read_text(encoding="utf-8")
    m = re.search(r'^CATRACAS="([^"]*)"', portao, re.M)
    assert m, "a variável CATRACAS sumiu do portão"
    auto = (REPO / "tools" / "automelhoria_geral.py").read_text(encoding="utf-8")
    fora_portao = [a for a in _arquivos_de_catraca() if a not in m.group(1).split()]
    fora_sensor = [a for a in _arquivos_de_catraca() if a not in auto]
    assert not fora_portao, f"catraca de regra fora de tools/pre_push_gate.sh: {fora_portao}"
    assert not fora_sensor, f"catraca de regra fora do sensor de catracas da automelhoria: {fora_sensor}"


def test_prova_registro_acusa_verificador_inexistente(tmp_path):
    """A catraca do registro fica vermelha quando a regra aponta para o nada."""
    import yaml
    d = yaml.safe_load(regras.ARQ.read_text(encoding="utf-8"))
    d["regras"] = [dict(d["regras"][0], verificadores=[{"tipo": "catraca", "ref": "tests/test_nao_existe.py"}]),
                   dict(d["regras"][1], id="PAD-99", verificadores=[{"tipo": "sensor", "ref": "sensor_fantasma_inexistente"}]),
                   dict(d["regras"][2], id="PAD-98", porque="")]
    arq = tmp_path / "regras.yaml"
    arq.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    probs = "\n".join(regras.problemas(arq))
    assert "arquivo inexistente" in probs and "sensor inexistente" in probs and "campo(s) vazio(s): porque" in probs


def test_prova_documento_editado_a_mao_e_acusado(tmp_path):
    copia = tmp_path / "REGRAS.md"
    copia.write_text(doc.gerar() + "\nlinha acrescentada à mão\n", encoding="utf-8")
    assert not doc.em_sincronia(copia)
