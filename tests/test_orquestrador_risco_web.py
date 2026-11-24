# -*- coding: utf-8 -*-
"""O6.7 — orquestrador: termo da web não vira risco alto sozinho; conclusão do LLM é observação, não fato de
entidade; nenhum Alerta grave nem Telegram com fundamento único em texto de LLM (catraca).

Antes (orquestrador.py:252-253, :192-208): qualquer `riscos_web` não vazio — termo casado em snippet de busca, sem
saber se era a mesma empresa — virava risco ALTO, `Alerta` severidade alta e mensagem no Telegram; e a conclusão
do agente era gravada como memória da entidade.
"""
from __future__ import annotations

import asyncio
import ast
import inspect
import json
import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compliance_agent.database.models import Alerta, Base, MemoriaAprendizado
from compliance_agent.llm import memoria as M
from compliance_agent.llm import orquestrador as O

RAIZ_SEI = M.raiz_fonte_primaria("sei", "SEI-270131/000548/2023")


def _gerar_alto(_p, _s=None):
    return json.dumps({"risco": "alto", "citacao": "foi condenada por fraude em licitação",
                       "justificativa": "x"})


CONCLUSAO_LLM = "A empresa foi condenada por fraude em licitação segundo notícias."


# ── classificação ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("riscos", [["fraude"], ["condenação", "improbidade"],
                                    [{"termo": "fraude", "url": "https://blog.x.com"}]])
def test_termo_web_sem_fonte_primaria_e_incerto(riscos):
    r = O._classificar_risco("", riscos_web=riscos, gerar=None)
    assert r["risco"] != "alto" and r["web_estado"] == "INCERTO"
    assert not O.alerta_permitido(r)


def test_fonte_primaria_sem_identidade_resolvida_e_incerto():
    """Com fonte primária e sem documento para resolver identidade (item e alvo sem CNPJ/CPF), INCERTO."""
    r = O._classificar_risco("", riscos_web=[{"termo": "sanção", "source_root_id": RAIZ_SEI}], gerar=None)
    assert r["web_estado"] == "INCERTO" and r["risco"] != "alto"


def test_fonte_primaria_e_identidade_resolvida_decide(monkeypatch):
    """Controle positivo: com resolvedor de identidade que confirma, o achado é alertável."""
    falso = types.ModuleType("compliance_agent.dominio.identidade")
    falso.resolver = lambda item, alvo: item.get("cnpj") == alvo.get("cnpj")
    monkeypatch.setitem(sys.modules, "compliance_agent.dominio.identidade", falso)
    item = {"termo": "sanção CEIS", "source_root_id": RAIZ_SEI, "cnpj": "11222333000181"}
    r = O._classificar_risco("", riscos_web=[item], gerar=None, alvo={"cnpj": "11222333000181"})
    assert r["risco"] == "alto" and O.alerta_permitido(r)
    homonimo = O._classificar_risco("", riscos_web=[item], gerar=None, alvo={"cnpj": "99888777000166"})
    assert homonimo["web_estado"] == "INCERTO" and not O.alerta_permitido(homonimo)


def test_identidade_real_forte_permite_alerta():
    """O4.13, módulo real: CNPJ completo com DV válido igual (forte) + fonte primária → alertável."""
    item = {"termo": "sanção CEIS", "source_root_id": RAIZ_SEI, "cnpj": "11.222.333/0001-81"}
    r = O._classificar_risco("", riscos_web=[item], gerar=None, alvo={"nome": "ACME", "cnpj": "11222333000181"})
    assert r["risco"] == "alto" and r["fonte"] == "web_primaria_identidade" and O.alerta_permitido(r)


@pytest.mark.parametrize("item_id,alvo", [
    ({"cnpj": "11222333", "nome": "ACME LTDA"}, {"cnpj": "11222333000181", "nome": "ACME LTDA"}),   # parcial (raiz)
    ({"cpf": "XX123456XXX", "nome": "FULANA DE TAL"}, {"cpf": "***.234.567-**", "nome": "Fulana Tal"}),  # parcial
    ({"nome": "ACME LTDA"}, {"nome": "ACME LTDA"}),                                                   # homônimo
    ({"cnpj": "99888777000100"}, {"cnpj": "11222333000181"}),                                         # divergente
])
def test_identidade_real_nao_forte_fica_incerto(item_id, alvo):
    item = {"termo": "sanção", "source_root_id": RAIZ_SEI, **item_id}
    r = O._classificar_risco("", riscos_web=[item], gerar=None, alvo=alvo)
    assert r["web_estado"] == "INCERTO" and r["risco"] != "alto" and not O.alerta_permitido(r)


def test_rubrica_llm_alto_nunca_e_alertavel():
    r = O._classificar_risco(CONCLUSAO_LLM, riscos_web=[], gerar=_gerar_alto)
    assert r["risco"] == "alto" and r["fonte"] == "rubrica_llm"
    assert not O.alerta_permitido(r)


# ── investigar_alvo ponta a ponta (agente, web e Telegram falsos) ───────────────────────────────

@pytest.fixture()
def ambiente(monkeypatch):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    enviados = []

    class _Agente:
        def __init__(self):
            self._session = types.SimpleNamespace(close=lambda: None)

        async def chat(self, _tarefa):
            return CONCLUSAO_LLM

    async def _web(_nome, _cnpj=""):
        return {"riscos_detectados": ["fraude", "condenação"], "resumo": "notícias"}

    async def _telegram(msg, *a, **k):
        enviados.append(msg)

    import compliance_agent.agent as agent_mod
    import compliance_agent.collectors.web_research as web_mod
    import compliance_agent.notifications.telegram as tg_mod
    import compliance_agent.llm.comotor as comotor_mod
    monkeypatch.setattr(agent_mod, "ComplianceAgent", _Agente)
    monkeypatch.setattr(web_mod, "investigar", _web)
    monkeypatch.setattr(tg_mod, "enviar_mensagem", _telegram)
    monkeypatch.setattr(comotor_mod, "juizo", lambda _nome: _gerar_alto)
    monkeypatch.setattr(O, "_tarefa_template", lambda **k: "tarefa")
    yield s, enviados
    s.close()


def test_llm_alto_mais_termo_web_nao_alerta_nem_telegram(ambiente):
    """CATRACA: o pior caso de antes (texto do LLM dizendo 'fraude' + termos web) não cria Alerta nem envia."""
    s, enviados = ambiente
    r = asyncio.run(O.investigar_alvo({"nome": "ACME LTDA", "cnpj": "11222333000181", "motivo": "OB alta"}, s))
    assert r["risco"] == "alto"                          # o juízo existe (hipótese)…
    assert s.query(Alerta).count() == 0                   # …mas não vira Alerta grave
    assert enviados == []                                 # …nem Telegram


def test_conclusao_do_llm_e_observacao_nao_fato_de_entidade(ambiente):
    s, _ = ambiente
    asyncio.run(O.investigar_alvo({"nome": "ACME LTDA", "cnpj": "", "motivo": "m"}, s))
    perfil = M.perfil_entidade("ACME LTDA", session=s)
    assert perfil["investigado_orquestrador"] is True
    assert "risco" not in perfil and "riscos_web" not in perfil        # juízo do LLM não é fato da entidade
    assert s.query(MemoriaAprendizado).filter_by(categoria="entidade_investigada").count() == 0
    obs = s.query(MemoriaAprendizado).filter_by(categoria="observacao", chave="investigacao:ACME LTDA").one()
    assert (obs.origem, obs.estado) == ("llm", "nao_confirmado")
    assert CONCLUSAO_LLM[:40] in obs.valor


def test_ralo_do_alerta_recusa_fundamento_llm(ambiente):
    """Chamar `_alertar_investigacao` direto, sem veredito primário, também não grava nem envia."""
    s, enviados = ambiente
    res = {"risco": "alto", "conclusao_agente": CONCLUSAO_LLM, "dossie_web": {"riscos": ["fraude"]}}
    asyncio.run(O._alertar_investigacao({"nome": "X"}, res, s))
    asyncio.run(O._alertar_investigacao({"nome": "X"}, res, s, veredito={"fonte": "rubrica_llm"}))
    assert s.query(Alerta).count() == 0 and enviados == []


def test_fundamentos_alertaveis_nao_incluem_texto_nem_termo():
    assert O.FUNDAMENTOS_ALERTAVEIS == frozenset({"web_primaria_identidade"})


def test_alerta_e_telegram_so_no_ralo_guardado():
    """CATRACA estática: `Alerta(` e `enviar_mensagem(` só aparecem dentro de `_alertar_investigacao`, que começa
    pela guarda `alerta_permitido` — caminho novo para Alerta/Telegram neste módulo morde aqui."""
    arvore = ast.parse(inspect.getsource(O))
    donos = {}
    for f in ast.walk(arvore):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(f):
                if isinstance(n, ast.Call):
                    nome = getattr(n.func, "id", getattr(n.func, "attr", ""))
                    if nome in ("Alerta", "enviar_mensagem"):
                        donos.setdefault(nome, set()).add(f.name)
    assert donos == {"Alerta": {"_alertar_investigacao"}, "enviar_mensagem": {"_alertar_investigacao"}}
    corpo = next(f for f in arvore.body if getattr(f, "name", "") == "_alertar_investigacao").body
    primeira = next(n for n in corpo if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)))
    assert isinstance(primeira, ast.If) and "alerta_permitido" in ast.unparse(primeira.test)
