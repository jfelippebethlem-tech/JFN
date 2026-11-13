# -*- coding: utf-8 -*-
"""As camadas de JUÍZO usam o co-motor por padrão (cada uma com a sua tarefa) — sem rede, sem `claude`."""
import json

import pytest

from compliance_agent.llm import claude_motor, comotor


@pytest.fixture
def juizo_espiao(monkeypatch):
    pedidos = []

    def fabrica(resposta):
        def juizo(tarefa, **kw):
            pedidos.append({"tarefa": tarefa, **kw})

            def gerar(prompt, sistema="", timeout=45.0, json_saida=True, **k):
                return resposta
            return gerar
        monkeypatch.setattr(comotor, "juizo", juizo)
        return pedidos
    return fabrica


def test_motor_real_nunca_roda_sob_pytest():
    assert claude_motor.pensar("pericia_execucao", "p") is None
    assert "pytest" in claude_motor.ultimo_motivo


def test_fachada_usa_pericia_fornecedor_e_declara_motor(juizo_espiao, monkeypatch):
    from compliance_agent import direcionamento_cerebro as dc
    from compliance_agent import rede_fachada as rf
    monkeypatch.delenv("JFN_VEREDITO_LLM_DISABLED", raising=False)
    monkeypatch.setattr(dc, "ultimo_provedor", "gemini", raising=False)
    pedidos = juizo_espiao(json.dumps({"veredito": "INDICIOS", "confianca": "MEDIA"}))
    r = rf.veredito_llm({"cnpj": "00000000000000", "total_pago": 1.0})
    assert pedidos[0]["tarefa"] == "pericia_fornecedor" and pedidos[0]["espera"] <= 30
    assert r["disponivel"] and r["veredito"] == "INDICIOS" and r["motor"] == "gemini"


def test_risco_da_investigacao_usa_investigacao_risco(juizo_espiao):
    from compliance_agent.llm.orquestrador import _classificar_risco
    pedidos = juizo_espiao(json.dumps({"risco": "baixo", "citacao": "", "justificativa": "ok"}))
    r = _classificar_risco("não há indício de irregularidade", None)
    assert pedidos[0]["tarefa"] == "investigacao_risco" and r["risco"] == "baixo"


def test_exculpatoria_usa_camada_subjetiva(juizo_espiao):
    from compliance_agent.detectores.base import verificar_adversarial
    pedidos = juizo_espiao(json.dumps({"refuta": False, "motivo": "sobreviveu"}))
    refutada, _m, _e = verificar_adversarial([{"fonte": "x", "trecho": "y"}], "achado")
    assert pedidos[0]["tarefa"] == "camada_subjetiva" and refutada is False


def test_analise_discursiva_usa_parecer_juridico_em_opus(juizo_espiao):
    from compliance_agent.lex_analise_conteudo import analise_discursiva
    pedidos = juizo_espiao(json.dumps([{"i": 0, "analise": "mecanismo citado"}]))
    achados = analise_discursiva([{"rf": "R3", "trecho": "trecho real", "numero_proc": "1"}])
    assert pedidos[0]["tarefa"] == "parecer_juridico"
    assert pedidos[0]["modelo"] == claude_motor.MODELO_JUIZO
    assert achados[0]["analise"] == "mecanismo citado"
