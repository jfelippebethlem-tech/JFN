# -*- coding: utf-8 -*-
"""Testes do FUNDAMENTO dos detectores (compliance_agent/detectores/base.py).

Valida: schema padrão (§1.4) + to_dict · âncoras fixas (§1.2) · rubrica fechada com citação obrigatória ·
verificador adversarial DEGRADANDO HONESTO sem LLM · pipeline isolando detector quebrado · convergência §7.2.
Sem rede, sem LLM ao vivo: o `gerar` é injetado (fake) ou ausente. Fixtures pequenas."""
from __future__ import annotations

import pytest

from compliance_agent.detectores import base


# ───────────────────────────── Schema padrão (§1.4) ─────────────────────────────
def test_schema_padrao_tem_todos_os_campos_do_spec():
    r = base.ResultadoDetector(detector="P4", processo="proc-1", score=0.85, status="confirmado")
    d = r.to_dict()
    esperado = {"detector", "processo", "score", "valores", "evidencia", "explicacao_inocente",
                "refutada", "motivo_refutacao", "status"}
    assert set(d) == esperado
    assert d["detector"] == "P4" and d["processo"] == "proc-1" and d["score"] == 0.85
    assert d["status"] == "confirmado" and d["refutada"] is False


def test_status_invalido_rejeitado():
    with pytest.raises(ValueError):
        base.ResultadoDetector(detector="X", processo="p", status="suspeito")


def test_score_clamp_para_0_1():
    assert base.ResultadoDetector(detector="X", processo="p", score=9.9).score == 1.0
    assert base.ResultadoDetector(detector="X", processo="p", score=-3).score == 0.0
    assert base.ResultadoDetector(detector="X", processo="p", score="lixo").score == 0.0


def test_add_evidencia_tem_hash_e_timestamp():
    r = base.ResultadoDetector(detector="X", processo="p")
    r.add_evidencia(fonte="CNPJ 12.345.678/0001-90", trecho="data de abertura: 02/03/2025")
    ev = r.evidencia[0]
    assert set(ev) == {"fonte", "trecho", "hash", "capturado_em"}
    assert ev["hash"].startswith("sha256:") and len(ev["hash"]) > 20
    assert ev["capturado_em"]  # timestamp preenchido


# ───────────────────────────── Âncoras (§1.2) ─────────────────────────────
def test_ancoras_valores_fixos_do_spec():
    assert base.ancora("ausente") == 0.0
    assert base.ancora("fraco") == 0.3
    assert base.ancora("medio") == 0.6
    assert base.ancora("forte") == 0.85
    assert base.ancora("critico") == 1.0


def test_ancora_invalida_levanta():
    with pytest.raises(ValueError):
        base.ancora("0.72")  # valor contínuo proibido — só âncora nomeada


# ───────────────────────────── Rubrica fechada (§1.3) ─────────────────────────────
ESCALA = {"ausente": "critico", "generica": "medio", "robusta": "ausente"}


def test_rubrica_classifica_para_ancora():
    nivel, score, _ = base.avaliar_rubrica({"nivel": "ausente", "trecho": "marca citada sem justificativa"}, ESCALA)
    assert nivel == "critico" and score == 1.0


def test_rubrica_sem_citacao_e_descartada():
    # regra de ouro: classificação sem `trecho` literal é descartada (não pontua)
    nivel, score, motivo = base.avaliar_rubrica({"nivel": "generica"}, ESCALA)
    assert nivel is None and score == 0.0 and "cita" in motivo.lower()


def test_rubrica_abstencao_e_valida():
    nivel, score, _ = base.avaliar_rubrica({"nivel": "nao_avaliavel"}, ESCALA)
    assert nivel is None and score == 0.0


def test_rubrica_nivel_fora_da_escala_descartado():
    nivel, score, _ = base.avaliar_rubrica({"nivel": "talvez", "trecho": "x"}, ESCALA)
    assert nivel is None and score == 0.0


# ───────────────────────────── Verificador adversarial (degrada honesto) ─────────────────────────────
def test_adversarial_sem_llm_nao_refuta_e_marca_nao_avaliavel():
    # gerar que SEMPRE falha (simula LLM offline) → honesto: NÃO refuta, marca nao_avaliavel
    def gerar_quebrado(prompt, sistema):
        raise RuntimeError("sem rede / chave esgotada")

    refutada, motivo, explic = base.verificar_adversarial(
        [base.evidencia("fonte", "trecho")], "achado P4", gerar=gerar_quebrado)
    assert refutada is False
    assert "nao_avaliavel" in motivo.lower() and "indispon" in motivo.lower()
    assert explic == ""


def test_adversarial_resposta_inparseavel_nao_refuta():
    refutada, motivo, _ = base.verificar_adversarial(
        [], "achado", gerar=lambda p, s: "isto não é json")
    assert refutada is False and "nao_avaliavel" in motivo.lower()


def test_adversarial_refuta_quando_llm_diz_refuta():
    raw = '{"explicacao_inocente":"padronização formal pré-existente","refuta":true,"motivo":"art.43 cobre"}'
    refutada, motivo, explic = base.verificar_adversarial([], "achado", gerar=lambda p, s: raw)
    assert refutada is True and "art.43" in motivo and "padroniz" in explic


def test_adversarial_sobrevive_quando_llm_nao_refuta():
    raw = '{"explicacao_inocente":"x","refuta":false,"motivo":"dados sustentam o indício"}'
    refutada, motivo, _ = base.verificar_adversarial([], "achado", gerar=lambda p, s: raw)
    assert refutada is False and "sustenta" in motivo


def test_aplicar_exculpatoria_descarta_se_refutada():
    r = base.ResultadoDetector(detector="P4", processo="p", score=0.85, status="confirmado")
    raw = '{"refuta":true,"motivo":"contrato anterior justifica","explicacao_inocente":"renovação lícita"}'
    base.aplicar_exculpatoria(r, "achado", gerar=lambda p, s: raw)
    assert r.refutada is True and r.status == "descartado"


def test_aplicar_exculpatoria_sem_llm_mantem_status():
    # LLM offline: a exculpatória é nao_avaliavel → NÃO muda o status objetivo do código
    r = base.ResultadoDetector(detector="P4", processo="p", score=0.85, status="confirmado")
    def quebrado(p, s):
        raise RuntimeError("offline")
    base.aplicar_exculpatoria(r, "achado", gerar=quebrado)
    assert r.refutada is False and r.status == "confirmado"


# ───────────────────────────── Pipeline + convergência ─────────────────────────────
class _DetOk(base.Detector):
    id, nome, familia = "OK", "ok", "preco"
    def avaliar(self, contexto):
        return self._novo(str(contexto.get("processo")), score=0.6, status="confirmado")


class _DetQuebrado(base.Detector):
    id, nome, familia = "BUG", "bug", "preco"
    def avaliar(self, contexto):
        raise RuntimeError("estourou")


def test_pipeline_isola_detector_quebrado():
    out = base.pipeline([_DetOk(), _DetQuebrado()], {"processo": "p1"})
    assert len(out) == 2
    ok = next(r for r in out if r.detector == "OK")
    bug = next(r for r in out if r.detector == "BUG")
    assert ok.status == "confirmado" and ok.score == 0.6
    assert bug.status == "nao_avaliavel" and "exce" in bug.motivo_refutacao.lower()


def test_score_processo_convergencia_multiplicativa():
    rs = [
        base.ResultadoDetector(detector="A", processo="p", score=0.85, status="confirmado"),
        base.ResultadoDetector(detector="B", processo="p", score=0.6, status="confirmado"),
        base.ResultadoDetector(detector="C", processo="p", score=0.9, status="descartado"),  # ignorado
    ]
    pesos = {"A": 1.0, "B": 0.8}
    # 1 - (1-1.0*0.85)*(1-0.8*0.6) = 1 - 0.15*0.52 = 1 - 0.078 = 0.922
    assert base.score_processo(rs, pesos) == pytest.approx(0.922, abs=1e-3)


def test_score_processo_ignora_refutado():
    rs = [base.ResultadoDetector(detector="A", processo="p", score=0.85, status="confirmado", refutada=True)]
    assert base.score_processo(rs, {"A": 1.0}) == 0.0
