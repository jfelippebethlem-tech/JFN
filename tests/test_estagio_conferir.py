# -*- coding: utf-8 -*-
"""E12 `conferir:<laudo|achado>` (O8.5): registro, entrada por risco (regra da O6.5 reaproveitada), porta da
assinatura fechada antes de 28/11/2026 19h sem sondar ninguém, regra do dono (o Opus não reconfere o próprio laudo)
e — com PG (VM-2) — gravação idempotente, ABSTEVE(sem_llm) que nunca vira "feito" e efeito conferido, sempre em
esquema temporário."""
import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

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


SEM_AUT = Path("/nao/existe/autorizacao.json")
ANTES = datetime(2026, 11, 26, 10, 0, tzinfo=C.BRT)
DEPOIS = datetime(2026, 11, 28, 19, 0, tzinfo=C.BRT)


def test_porta_sem_autorizacao_recusa_antes_de_sabado_19h_sem_sondar():
    m, ex = C.porta_opus(datetime(2026, 11, 28, 18, 59, tzinfo=C.BRT), ritmo=_explode, escolher=_explode,
                         nivel=_explode, caminho=SEM_AUT)
    assert ex is None and m.startswith("sem_llm:") and "28/11/2026 19h" in m


def test_porta_depois_da_virada_usa_ritmo_e_executor():
    assert "contido" in C.porta_opus(DEPOIS, ritmo=lambda t: "ritmo contido", escolher=_explode, caminho=SEM_AUT)[0]
    assert "nenhum executor" in C.porta_opus(DEPOIS, ritmo=lambda t: None, escolher=lambda: (None, "x"),
                                             caminho=SEM_AUT)[0]
    assert C.porta_opus(DEPOIS, ritmo=lambda t: None, escolher=lambda: ("vm2", "ok"), caminho=SEM_AUT) == (None, "vm2")


@pytest.fixture()
def aut(tmp_path):
    a = tmp_path / "aut.json"
    a.write_text(json.dumps({"escopo": "passada --com-llm pela ASSINATURA (backend cli); nunca API paga",
                             "teto_semana_pct": 80.0}))
    return a


def test_porta_com_autorizacao_do_dono_libera_antes_e_confere_o_teto(aut, monkeypatch):
    abaixo = lambda: {"medido": True, "semana_pct": 70.0}                         # noqa: E731
    m, ex = C.porta_opus(ANTES, nivel=abaixo, ritmo=_explode, escolher=_explode, caminho=aut)
    assert ex is None and m.startswith("sem_llm:")           # sem o escopo do ensaio: a autorização não vale
    monkeypatch.setenv("JFN_ASSINATURA_ESCOPO", "ensaio_o85")
    assert C.porta_opus(ANTES, nivel=abaixo, ritmo=_explode, escolher=lambda: ("itcampo", "hb"),
                        caminho=aut) == (None, "itcampo")
    m, ex = C.porta_opus(ANTES, nivel=lambda: {"medido": True, "semana_pct": 80.0}, escolher=_explode, caminho=aut)
    assert ex is None and m.startswith("teto_assinatura:")
    m, _ = C.porta_opus(ANTES, nivel=lambda: {"medido": False, "semana_pct": None}, escolher=_explode, caminho=aut)
    assert m.startswith("teto_assinatura:") and "sem medição" in m


def test_autorizacao_fora_do_escopo_nao_vale(tmp_path):
    a = tmp_path / "aut.json"
    a.write_text(json.dumps({"escopo": "API paga", "teto_semana_pct": 80.0}))
    assert C.autorizacao_dono(a) is None and C.autorizacao_dono(SEM_AUT) is None


def test_decidir_sem_motivo_e_nao_julgado_nunca_limpo():
    assert C.decidir({"autor": "regra:x"}, []) == (CR.NAO_JULGADO, C.NAO_JULGADO, CR.ROTULO_NAO_JULGADO)


def test_opus_nao_reconfere_o_proprio_laudo():
    d, e, m = C.decidir({"autor": "claude-opus-5-5"}, ["valor"])
    assert (d, e) == ("fila", C.ABSTEVE) and m.startswith("autor_e_conferente")


def test_com_motivo_vai_ao_julgamento():
    assert C.decidir({"autor": "regra:x"}, ["valor"]) == ("fila", None, "")


@pytest.mark.parametrize("texto, veredito", [
    ('{"veredito": "confirma", "justificativa": "OB 1 e NL 1 batem"}', "confirma"),
    ('Segue: {"veredito": "REBAIXA", "justificativa": "só contexto", "hipotese_inocente": "rateio"}', "rebaixa"),
    ('{"veredito": "diverge", "justificativa": "NL anulada depois"}', "diverge"),
    ('{"veredito": "talvez", "justificativa": "x"}', None),
    ('{"veredito": "confirma", "justificativa": ""}', None),
    ("sem json", None),
])
def test_analisar_resposta_so_aceita_veredito_com_justificativa(texto, veredito):
    r = C.analisar_resposta(texto)
    assert (r or {}).get("veredito") == veredito


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
    monkeypatch.setattr(C, "porta_opus", lambda: ("sem_llm: assinatura contida (teste)", None))
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


# ── julgamento com executor FALSO (nada chama a assinatura) ──────────────────────────────────────────────────
def _falso(monkeypatch, resposta, modelo="claude-opus-5-5"):
    chamadas = []

    def chamar(prompt, executor):
        chamadas.append((prompt, executor))
        return resposta, modelo, ""
    monkeypatch.setattr(C, "porta_opus", lambda: (None, "falso"))
    monkeypatch.setattr(C, "chamar_opus", chamar)
    return chamadas


@precisa_pg
@pytest.mark.parametrize("veredito, concorda", [("confirma", 1), ("rebaixa", 0), ("diverge", 0)])
def test_veredito_do_opus_gravado_e_conferido(esq, monkeypatch, veredito, concorda):
    con, nome = esq
    chamadas = _falso(monkeypatch, json.dumps({"veredito": veredito, "justificativa": "pelos fatos 1 e 2"}))
    aid = _gravar(con, nome, "5000000.00", _origem(False))
    payload = {"alvo": "achado", "ref": str(aid), "dsn": DSN, "esquema": nome}
    res = C.ESTAGIO.handler(payload, _ctx(aid))
    assert res.efeito["estado"] == C.CONFERIDO and res.efeito["veredito"] == veredito and len(chamadas) == 1
    assert "<ITEM>" in chamadas[0][0] and chamadas[0][1] == "falso"
    assert res.eventos == [{"fonte": "conferir", "tipo": "veredito", "chave": "e10.x",
                            "detalhe": {"alvo": "achado", "ref": str(aid), "veredito": veredito}}]
    row = con.execute(f'SELECT estado, veredito, concorda, modelo, rotulo FROM "{nome}".conferencia_e12').fetchone()
    assert row[:4] == (C.CONFERIDO, veredito, concorda, "claude-opus-5-5") and row[4].startswith("NÃO JULGADO")
    assert C.ESTAGIO.efeito(payload, _ctx(aid), res) is True
    again = C.ESTAGIO.handler(payload, _ctx(aid))                    # mesma entrada: o Opus NÃO é chamado de novo
    assert len(chamadas) == 1 and again.efeito["veredito"] == veredito
    con.execute(f"UPDATE \"{nome}\".conferencia_e12 SET resposta = 'adulterada'")           # veredito sem resposta
    assert C.ESTAGIO.efeito(payload, _ctx(aid), res) is False


@precisa_pg
def test_resposta_fora_do_formato_nunca_vira_feito(esq, monkeypatch):
    con, nome = esq
    _falso(monkeypatch, "acho que está certo")
    aid = _gravar(con, nome, "5000000.00", _origem(False))
    with pytest.raises(RuntimeError, match="resposta_fora_do_formato"):
        C.ESTAGIO.handler({"alvo": "achado", "ref": str(aid), "dsn": DSN, "esquema": nome}, _ctx(aid))
    assert con.execute(f'SELECT estado, veredito FROM "{nome}".conferencia_e12').fetchone() == (C.ABSTEVE, None)


@precisa_pg
def test_teto_atingido_abstem_sem_chamar_o_opus(esq, monkeypatch, aut):
    con, nome = esq
    monkeypatch.setattr(C, "AUTORIZACAO_DONO", aut)
    monkeypatch.setenv("JFN_ASSINATURA_ESCOPO", "ensaio_o85")          # a autorização só vale no escopo do ensaio
    from compliance_agent.llm import ritmo_assinatura
    monkeypatch.setattr(ritmo_assinatura, "nivel", lambda: {"medido": True, "semana_pct": 85.0})
    monkeypatch.setattr(C, "chamar_opus", lambda *a: pytest.fail("acima do teto o Opus não podia ser chamado"))
    aid = _gravar(con, nome, "5000000.00", _origem(False))
    with pytest.raises(C.SemCota, match=r"ABSTEVE\(teto_assinatura"):
        C.ESTAGIO.handler({"alvo": "achado", "ref": str(aid), "dsn": DSN, "esquema": nome}, _ctx(aid))
    estado, motivo = con.execute(f'SELECT estado, motivo FROM "{nome}".conferencia_e12').fetchone()
    assert estado == C.ABSTEVE and motivo.startswith("teto_assinatura")


@precisa_pg
def test_assinatura_recusa_abstem(esq, monkeypatch):
    con, nome = esq
    monkeypatch.setattr(C, "porta_opus", lambda: (None, "falso"))
    monkeypatch.setattr(C, "chamar_opus", lambda p, e: (None, "", "limite de uso"))
    aid = _gravar(con, nome, "5000000.00", _origem(False))
    with pytest.raises(C.SemCota, match=r"ABSTEVE\(sem_llm: limite de uso"):
        C.ESTAGIO.handler({"alvo": "achado", "ref": str(aid), "dsn": DSN, "esquema": nome}, _ctx(aid))


def test_chamar_opus_so_pela_assinatura(monkeypatch):
    from compliance_agent.llm import claude_motor
    from compliance_agent.llm import conferencia_executor as CE
    visto = {}

    def pensar(tarefa, prompt, **kw):
        visto.update(kw)
        return None
    monkeypatch.setattr(claude_motor, "pensar", pensar)
    monkeypatch.setattr(CE, "executar_em", lambda nome: f"exec:{nome}")
    monkeypatch.setattr(claude_motor, "ultimo_motivo", "trava ocupada")
    assert C.chamar_opus("p", "vm2") == (None, "", "trava ocupada")
    assert visto["backend"] == "cli" and visto["executar"] == "exec:vm2"
    assert visto["modelo"] == claude_motor.MODELO_JUIZO
