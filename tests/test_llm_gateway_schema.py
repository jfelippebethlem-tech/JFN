# -*- coding: utf-8 -*-
"""Gateway LLM, O6.1 (d): schema estrito (Pydantic) + validação pós-parse das citações por verificador injetável
(documento enviado, sha igual, 1 ≤ página ≤ total, trecho literal); citação que não confere é descartada; nenhuma
sobrou ⇒ INDETERMINADO_FALHA_CITACAO, sem escalar para camada mais cara. ABSTEVE(motivo) é resposta válida.
Backends dublês; nenhuma chamada real."""
import json
import sqlite3

import pytest
from pydantic import BaseModel

from compliance_agent.adaptadores.llm import gateway as G
from compliance_agent.adaptadores.llm import prompt_seguro as PS
from compliance_agent.dominio.estados import EstadoSaida

MSG = [{"role": "system", "content": "Você extrai o valor do contrato."}, {"role": "user", "content": "Qual o valor?"}]
PAG1 = "CONTRATO Nº 12/2026. Objeto: limpeza predial."
PAG2 = "O valor global do contrato é de R$ 483.333,33, pago em 12 parcelas."
DOC = PS.Documento("sei:123", "", paginas=(PAG1, PAG2))


class Citacao(BaseModel):
    documento_id: str
    versao_sha256: str
    pagina: int
    trecho: str


class Valor(BaseModel):
    valor: str
    parcelas: int
    citacoes: list[Citacao]


def _cit(**kw):
    c = {"documento_id": "sei:123", "versao_sha256": DOC.versao_sha256, "pagina": 2,
         "trecho": "valor global do contrato é de R$ 483.333,33"}
    c.update(kw)
    return c


def _resp(citacoes, **extra):
    return json.dumps({"valor": "483333.33", "parcelas": 12, "citacoes": citacoes, **extra}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_LLM_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    return tmp_path


def _dubles(*respostas):
    vistos = []

    def faz(nome, texto):
        def b(**kw):
            vistos.append((nome, kw))
            return G.Retorno(texto=texto, modelo="claude-haiku-5-5" if nome == "api_anthropic" else None,
                             tokens_in=10, tokens_out=5)
        return b
    nomes = ("assinatura_claude", "api_anthropic")
    return vistos, {n: faz(n, t) for n, t in zip(nomes, respostas)}


def _chamar(backends, **kw):
    return G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico", documentos=[DOC],
                    schema=Valor, exigir_citacao=True, backends=backends, **kw)


def test_citacao_conferida_vira_modelo_pydantic():
    vistos, bk = _dubles(_resp([_cit()]))
    r = _chamar(bk)
    assert r.estado == G.RESPONDIDO and isinstance(r.dados, Valor)
    assert r.dados.citacoes[0].pagina == 2 and r.extras["citacoes_descartadas"] == []
    nome, kw = vistos[0]
    assert isinstance(kw["schema"], dict) and "citacoes" in json.dumps(kw["schema"])   # backend recebe JSON Schema
    assert G.PS.REGRA_CITACAO in kw["sistema"] and G.PS.REGRA_ABSTENCAO in kw["sistema"]


@pytest.mark.parametrize("ruim, motivo", [
    (dict(documento_id="sei:999"), "não está entre os enviados"),
    (dict(versao_sha256="0" * 64), "versao_sha256 não confere"),
    (dict(pagina=3), "fora de 1..2"),
    (dict(pagina=None), "página ausente"),
    (dict(pagina=1), "não está literalmente"),                       # trecho é da página 2
    (dict(trecho="valor global do contrato é de R$ 500.000,00"), "não está literalmente"),
])
def test_citacao_que_nao_confere_e_descartada_e_a_boa_fica(ruim, motivo):
    _, bk = _dubles(_resp([_cit(**ruim), _cit()]))
    r = _chamar(bk)
    assert r.estado == G.RESPONDIDO and len(r.dados.citacoes) == 1
    [(_did, m)] = r.extras["citacoes_descartadas"]
    assert motivo in m


def test_nenhuma_citacao_sobrou_e_indeterminado_sem_escalar_para_o_pago(_isolado):
    vistos, bk = _dubles(_resp([_cit(trecho="frase que não existe no documento")]), _resp([_cit()]))
    r = _chamar(bk)
    assert r.estado == G.INDETERMINADO_FALHA_CITACAO and r.dados["citacoes"] == []
    assert [n for n, _ in vistos] == ["assinatura_claude"]           # não gastou a API para "tentar de novo"
    con = sqlite3.connect(_isolado / "trace.db")
    [(estado, desc)] = con.execute("SELECT estado, citacoes_descartadas FROM llm_trace WHERE origem='gateway'")
    assert estado == "INDETERMINADO_FALHA_CITACAO" and desc == 1


def test_exigir_citacao_sem_lista_e_indeterminado():
    _, bk = _dubles(json.dumps({"valor": "1", "parcelas": 1}))
    assert _chamar(bk).estado == G.INDETERMINADO_FALHA_CITACAO


def test_schema_estrito_reprova_tipo_errado_e_escala(_isolado):
    vistos, bk = _dubles(_resp([_cit()]).replace('"parcelas": 12', '"parcelas": "12"'), _resp([_cit()]))
    r = _chamar(bk)
    assert r.camada == 3 and [n for n, _ in vistos] == ["assinatura_claude", "api_anthropic"]
    assert "schema estrito" in r.motivo_escalonamento


def test_absteve_com_motivo_e_resposta_valida():
    _, bk = _dubles(json.dumps({"absteve": True, "motivo": "o documento não traz o valor"}))
    r = _chamar(bk)
    assert r.estado == G.ABSTEVE and r.saida.estado is EstadoSaida.ABSTEVE
    assert str(r.saida) == "ABSTEVE(o documento não traz o valor)"


def test_absteve_sem_motivo_e_falha():
    _, bk = _dubles(json.dumps({"absteve": True}), json.dumps({"estado": "ABSTEVE", "motivo": "sem dado"}))
    r = _chamar(bk)
    assert r.camada == 3 and r.estado == G.ABSTEVE and "abstenção sem motivo" in r.motivo_escalonamento


def test_verificador_injetado_recebe_citacao_e_documentos():
    recebidos = []

    def ver(cit, docs):
        recebidos.append((cit["documento_id"], sorted(docs)))
        return cit["pagina"] == 1, "só aceito página 1"
    _, bk = _dubles(_resp([_cit(), _cit(pagina=1, trecho="qualquer coisa")]))
    r = _chamar(bk, verificador=ver)
    assert recebidos == [("sei:123", ["sei:123"])] * 2
    assert [c.pagina for c in r.dados.citacoes] == [1] and r.extras["citacoes_descartadas"][0][1] == "só aceito página 1"


def test_citacao_com_cpf_mascarado_confere_no_original():
    d = [int(x) for x in "274185963"]
    for n in (9, 10):
        d.append((sum(v * p for v, p in zip(d, range(n + 1, 1, -1))) * 10 % 11) % 10)
    cpf = "".join(map(str, d))
    cpf = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
    doc = PS.Documento("d1", f"Pagamento ao credor de CPF {cpf} no valor de R$ 10,00.")
    cit = {"documento_id": "d1", "versao_sha256": doc.versao_sha256, "pagina": 1,
           "trecho": "credor de CPF [CPF_1] no valor"}
    _, bk = _dubles(json.dumps({"valor": "10", "parcelas": 1, "citacoes": [cit]}))
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico", documentos=[doc],
                 schema=Valor, exigir_citacao=True, backends=bk)
    assert r.estado == G.RESPONDIDO and r.dados.citacoes[0].trecho == f"credor de CPF {cpf} no valor"


def test_exigir_citacao_sem_schema_e_recusado():
    with pytest.raises(G.GatewayErro, match="exigir_citacao pede schema"):
        G.chamar("classificacao", MSG, prompt_version="v1", classe_dado="publico", exigir_citacao=True)


def test_schema_antigo_em_dict_continua_valendo():
    vistos, bk = _dubles('{"a": 1}', '{"a": 1, "b": 2}')
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico", schema={"a": 0, "b": 0},
                 backends=bk)
    assert r.dados == {"a": 1, "b": 2} and "faltam b" in r.motivo_escalonamento
