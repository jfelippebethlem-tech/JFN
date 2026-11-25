# -*- coding: utf-8 -*-
"""E12 `conferir:<laudo|achado>` (O8.5): registro, entrada por risco (regra da O6.5 reaproveitada), porta da
assinatura fechada antes de 28/11/2026 19h sem sondar ninguém, regra do dono (o Opus não reconfere o próprio laudo)
e — com PG (VM-2) — gravação idempotente, ABSTEVE(sem_llm) que nunca vira "feito" e efeito conferido, sempre em
esquema temporário."""
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import conferir as C
from compliance_agent.llm import conferencia_risco as CR
from tests.fluxo_pg import DSN, precisa_pg


def test_estagio_registrado_com_contrato():
    assert estagio_de("conferir") is C.ESTAGIO and estagio_de("conferir:achado:1") is C.ESTAGIO
    assert C.ESTAGIO.recursos == ["llm"] and C.ESTAGIO.prioridade == 30 and C.ESTAGIO.volta


def test_alvo_invalido_e_permanente():
    with pytest.raises(ErroPermanente):
        C.alvo_de({"alvo": "outro", "ref": "1"})
    ctx = Contexto(no="t", tipo="conferir:laudo:330002/000010/2024", chave="k", ficha=1, tentativa=1)
    assert C.alvo_de({}, ctx) == ("laudo", "330002/000010/2024")


def _explode(*a, **k):
    raise AssertionError("não podia sondar a assinatura antes da liberação")


def test_porta_recusa_antes_de_sabado_19h_sem_sondar():
    m = C.porta_opus(datetime(2026, 11, 28, 18, 59, tzinfo=C.BRT), ritmo=_explode, escolher=_explode)
    assert m and "28/11/2026 19h" in m


def test_porta_depois_usa_ritmo_e_executor():
    depois = datetime(2026, 11, 28, 19, 0, tzinfo=C.BRT)
    assert "contido" in C.porta_opus(depois, ritmo=lambda t: "ritmo contido", escolher=_explode)
    assert "nenhum executor" in C.porta_opus(depois, ritmo=lambda t: None, escolher=lambda: (None, "x"))
    assert C.porta_opus(depois, ritmo=lambda t: None, escolher=lambda: ("vm2", "ok")) is None


def test_decidir_sem_motivo_e_nao_julgado_nunca_limpo():
    assert C.decidir({"autor": "regra:x"}, [], porta=_explode) == (CR.NAO_JULGADO, C.NAO_JULGADO,
                                                                    CR.ROTULO_NAO_JULGADO)


def test_opus_nao_reconfere_o_proprio_laudo():
    d, e, m = C.decidir({"autor": "claude-opus-5-5"}, ["valor"], porta=_explode)
    assert (d, e) == ("fila", C.ABSTEVE) and m.startswith("autor_e_conferente")


def test_com_motivo_sem_llm_abstem():
    d, e, m = C.decidir({"autor": "regra:x"}, ["valor"], porta=lambda: "assinatura contida")
    assert (d, e) == ("fila", C.ABSTEVE) and m == "sem_llm: assinatura contida"
    # porta aberta: o conferente do motor ainda não está ligado — continua abstenção, nunca veredito
    assert C.decidir({"autor": "regra:x"}, ["valor"], porta=lambda: None)[2].startswith("sem_llm")


def _achado(estado="INDICIO", valores=("10.00",), origem="e10:x:todos:k"):
    return {"alvo": "achado", "ref": "1", "estado": estado, "origem": origem, "entradas_hash": "h",
            "regra_id": "x", "regra_versao": "v", "autor": "regra:x",
            "fatos": [{"papel": "suporte", "tipo": "ob", "valor": v} for v in valores]
            + [{"papel": "contexto", "tipo": "ob", "valor": "99999999.00"}]}


def _origem(sorteada: bool) -> str:
    return next(o for o in (f"e10:x:todos:{i}" for i in range(500)) if CR.sorteado(o) is sorteada)


def test_motivos_do_achado_pela_regra_da_o65():
    o = _origem(False)
    assert C.motivos(_achado(valores=("600000.00", "500000.00"), origem=o), limiar=1e6)["motivos"] == ["valor"]
    assert C.motivos(_achado(origem=o), limiar=1e6)["motivos"] == []             # contexto não soma valor
    assert C.motivos(_achado(estado="INCERTO", origem=o), limiar=1e6)["motivos"] == ["baixa_confianca"]
    assert C.motivos(_achado(origem=_origem(True)), limiar=1e6)["motivos"] == ["amostra"]
    m = C.motivos(_achado(origem=o), limiar=1e6)
    assert m["entrada_sha"] == C.motivos(_achado(origem=o), limiar=1e6)["entrada_sha"]
    assert m["entrada_sha"] != C.motivos(_achado(estado="INCERTO", origem=o), limiar=1e6)["entrada_sha"]


def test_motivos_do_laudo_reaproveitam_o_periciar():
    laudo = {"processo": "p", "chave": "c", "grau_global": 2, "ob_paga": 0.0, "cobertura": {"fracao": 1.0},
             "eixos": {"execucao": {"estado": "PROPOSTA"}}}
    m = C.motivos({"alvo": "laudo", "ref": "p", "chave_laudo": "c", "autor": "claude-opus-5-5", "laudo": laudo})
    assert "grave" in m["motivos"]


# ── PostgreSQL ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def esq():
    import psycopg

    from compliance_agent.adaptadores.achados import aplicar_schema
    nome = f"tmp_e12_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        aplicar_schema(con, nome)
        yield con, nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


def _gravar(con, nome, valor: str, origem: str) -> int:
    from compliance_agent.adaptadores.achados import gravar
    from compliance_agent.dominio.achado import Achado, ExecucaoRegra, Fato, Papel, StatusAchado, hash_entradas
    from compliance_agent.dominio.estados import EstadoSaida
    exe = ExecucaoRegra(regra_id="e10.x", versao="v1", entradas_hash=hash_entradas({"o": origem}), resultado={},
                        origem=origem)
    a = Achado.de_regra(execucao=exe, status=StatusAchado.TRIAGEM, estado=EstadoSaida.INDICIO, observacao="o",
                        inferencia="i", hipotese="h",
                        evidencias=[Fato(papel=Papel.SUPORTE, tipo="ob", fonte="ob_orcamentaria_siafe",
                                         referencia="2025OB1", valor=Decimal(valor))])
    gravar(con, nome, [a])
    return con.execute(f'SELECT a.id FROM "{nome}".achado a JOIN "{nome}".execucao_regra e ON e.id = '
                       "a.execucao_regra_id WHERE e.origem = %s", (origem,)).fetchone()[0]


def _ctx(aid):
    return Contexto(no="t", tipo=f"conferir:achado:{aid}", chave=f"conferir:achado:{aid}", ficha=1, tentativa=1)


@precisa_pg
def test_achado_de_risco_grava_abstencao_e_nunca_vira_feito(esq, monkeypatch):
    con, nome = esq
    monkeypatch.setattr(C, "porta_opus", lambda: "assinatura contida (teste)")
    aid = _gravar(con, nome, "5000000.00", _origem(False))
    payload = {"alvo": "achado", "ref": str(aid), "dsn": DSN, "esquema": nome}
    with pytest.raises(C.SemCota, match=r"ABSTEVE\(sem_llm"):
        C.ESTAGIO.handler(payload, _ctx(aid))
    estado, motivos = con.execute(f'SELECT estado, motivos FROM "{nome}".conferencia_e12').fetchone()
    assert estado == "ABSTEVE" and motivos == ["valor"]
    with pytest.raises(C.SemCota):                                      # idempotente pela chave: 1 linha
        C.ESTAGIO.handler(payload, _ctx(aid))
    assert con.execute(f'SELECT count(*) FROM "{nome}".conferencia_e12').fetchone()[0] == 1


@precisa_pg
def test_achado_sem_risco_nao_julgado_conferido(esq):
    con, nome = esq
    aid = _gravar(con, nome, "10.00", _origem(False))
    payload = {"alvo": "achado", "ref": str(aid), "dsn": DSN, "esquema": nome}
    res = C.ESTAGIO.handler(payload, _ctx(aid))
    assert res.efeito["estado"] == "NAO_JULGADO" and res.efeito["motivos"] == [] and not res.eventos
    assert C.ESTAGIO.efeito(payload, _ctx(aid), res) is True
    con.execute(f"UPDATE \"{nome}\".conferencia_e12 SET motivos = '[\"valor\"]'")      # adulterado: recusa
    assert C.ESTAGIO.efeito(payload, _ctx(aid), res) is False


@precisa_pg
def test_item_inexistente_e_permanente(esq):
    con, nome = esq
    with pytest.raises(ErroPermanente):
        C.ESTAGIO.handler({"alvo": "achado", "ref": "999999", "dsn": DSN, "esquema": nome}, _ctx(999999))
