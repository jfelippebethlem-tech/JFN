# -*- coding: utf-8 -*-
"""E10 `detectar` (O5.3 fatia 1, SOMBRA ⚖️): registro e contrato do estágio, catracas (Tier ≠ 1 nunca manchete; teto de
dispensa só em limites_dispensa; todo detector tem exigência na E9), rotina inativa do config/fluxo.yaml e — com PG
(VM-2) — handler idempotente pela chave (detector, escopo), leitura da E9 e efeito conferido, SEMPRE em esquemas
temporários (nunca `dominio` nem `sombra` reais)."""
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from compliance_agent.aplicacao import detectores as DET
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import detectar as D
from compliance_agent.aplicacao.estagios import elegibilidade as E9
from compliance_agent.fluxo import grafo as G
from tests.fluxo_pg import DSN, precisa_pg

REPO = Path(__file__).resolve().parents[1]


def test_estagio_registrado():
    assert estagio_de("detectar") is D.ESTAGIO
    assert estagio_de("detectar:e10.ob_antes_da_liquidacao") is D.ESTAGIO
    assert "cpu_pesado" in D.ESTAGIO.recursos


@pytest.mark.parametrize("did", sorted(DET.MODULOS))
def test_todo_detector_tem_registro_tier3_e_exigencia_na_e9(did):
    reg = E9.carregar_registro()[did]
    det = DET.carregar_detector(did)
    assert det.ID == did and reg["tier"] == 3 and reg["manchete"] is False and reg["manchete_efetiva"] is False
    assert reg["controle_positivo"] and reg["controle_negativo"] and reg["dominio"]
    unidade, exige = D.exigencia(did)
    assert unidade == det.UNIDADE and unidade in E9.UNIDADES
    assert D.versao_execucao(did).startswith(det.VERSAO + "@")


def test_regras_a_portar_apontam_para_o_detector_portado():
    reg = E9.carregar_registro()
    for antigo, novo in (("a_portar.p4_obra_e_lei_8666_tcerj", "e10.p4_fracionamento_objeto"),
                         ("a_portar.p5_dedup_por_processo", "e10.p5_emergencia_recorrente"),
                         ("a_portar.lex_fatos.c_pago_maior_que_nl", "e10.ob_paga_acima_liquidado"),
                         ("a_portar.lex_fatos.c_ob_antes_da_nl", "e10.ob_antes_da_liquidacao")):
        assert reg[antigo]["portar_para"] == novo
        assert E9.exiges_do_detector(antigo) == E9.exiges_do_detector(novo)


def test_catraca_teto_literal_fora_de_limites_dispensa():
    """Nenhum teto de dispensa escrito à mão nos detectores do E10 (fonte única: limites_dispensa.py)."""
    for p in (REPO / "compliance_agent" / "aplicacao" / "detectores").glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{2,3}[_.]?\d{3}(?:\.\d{2})?\b", txt.split('"""', 2)[-1]), p.name


def test_escopo_invalido_e_permanente():
    with pytest.raises(ErroPermanente):
        D._escopo({"detector": "inventado"})
    assert D._escopo({}, Contexto(no="t", tipo="detectar:e10.ob_antes_da_liquidacao", chave="k", ficha=1,
                                  tentativa=1)) == ("e10.ob_antes_da_liquidacao", None, "todos")
    assert D._escopo({"detector": "e10.p5_emergencia_recorrente", "exercicio": "2025"})[2] == "2025"


def test_rotina_e10_inativa_com_efeito_verificavel():
    r = G.carregar().rotinas["detectar_sombra"]
    assert r.estagio == "E10" and r.ativa is False and "O4.10" in (r.bloqueio or "")
    dets = {a[a.index("--detector") + 1] for a in r.argvs()}
    assert dets == set(DET.MODULOS)
    assert re.search(r.efeito.log_contem, "detectar: 3 achado(s) conferido(s) em sombra.achado (x, escopo todos)")
    assert re.search(r.efeito.log_contem, "detectar: 0 achado(s) conferido(s) em sombra.achado (x, escopo todos)")
    assert not re.search(r.efeito.log_contem, "detectar: EFEITO NÃO CONFERIDO")


# ── PostgreSQL: esquemas temporários (E9 e E10) ─────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio INTEGER, data_emissao, nl, credor, valor, status,
  status_envio, tipo_regularizacao);
CREATE TABLE nl_siafe(numero, ug_emitente, exercicio INTEGER, status, valor, data_emissao, credor);
INSERT INTO nl_siafe VALUES ('2025NL1','010100',2025,'Contabilizado',1000,'05/03/2025','22222222000100'),
  ('2025NL2','010100',2025,'Contabilizado',1000,'05/03/2025','22222222000100');
INSERT INTO ob_orcamentaria_siafe VALUES
  ('2025OB1','010100',2025,'01/03/2025','2025NL1','22222222000100',600,'Contabilizado','',''),
  ('2025OB2','010100',2025,'02/03/2025','2025NL2','22222222000100',600,'Contabilizado','','');
"""


@pytest.fixture()
def fonte(tmp_path):
    p = tmp_path / "compliance.db"
    c = sqlite3.connect(p)
    c.executescript(_DDL)
    c.commit()
    c.close()
    return p


@pytest.fixture()
def pg():
    e9, e10 = f"tmp_e9_{uuid.uuid4().hex[:10]}", f"tmp_e10_{uuid.uuid4().hex[:10]}"
    con = E9.conectar(DSN, "public")
    try:
        E9.aplicar_schema(con, e9)

        def veredito(chave, v):
            con.execute(f'INSERT INTO "{e9}".elegibilidade (unidade, chave, exiges, versao, entrada_hash) '
                        "VALUES ('ob_siafe', %s, %s::jsonb, %s, 'h') ON CONFLICT (unidade, chave) DO UPDATE "
                        "SET exiges = EXCLUDED.exiges", (chave, '{"execucao": "%s"}' % v, E9.VERSAO))
        veredito("010100|2025OB1|2025", "E")
        veredito("010100|2025OB2|2025", "?:SEM_NE")      # anterior à NL também, mas indeterminada na E9
        yield con, e9, e10, veredito
    finally:
        for s in (e9, e10):
            con.execute(f'DROP SCHEMA IF EXISTS "{s}" CASCADE')
        con.close()


def _ctx(did):
    return Contexto(no="teste", tipo=f"detectar:{did}", chave=f"detectar:{did}:todos", ficha=1, tentativa=1)


@precisa_pg
def test_handler_idempotente_le_a_e9_e_efeito_conferido(pg, fonte):
    con, e9, e10, veredito = pg
    did = "e10.ob_antes_da_liquidacao"
    payload = {"detector": did, "fonte": str(fonte), "dsn": DSN, "esquema": e10, "esquema_e9": e9}
    res = D.ESTAGIO.handler(payload, _ctx(did))
    assert res.efeito["achados"] == 1 and res.efeito["achados_novos"] == 1 and res.eventos   # só a OB1 ('E')
    assert res.efeito["resumo"]["por_veredito"] == {"?:SEM_NE": 1, "E": 1}
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is True
    again = D.ESTAGIO.handler(payload, _ctx(did))                        # mesma entrada: 0 linha, mesma rodada
    assert again.efeito["achados_novos"] == 0 and not again.eventos and again.efeito["rodada"] == res.efeito["rodada"]
    assert con.execute(f'SELECT count(*) FROM "{e10}".achado').fetchone()[0] == 1
    estado, status = con.execute(f'SELECT estado, status FROM "{e10}".achado').fetchone()
    assert (estado, status) == ("INDICIO", "triagem")
    # efeito INDEPENDENTE: declarar mais do que há, ou adulterar o hash gravado, é recusado
    falso = D.Resultado(efeito={**again.efeito, "achados": 2})
    assert D.ESTAGIO.efeito(payload, _ctx(did), falso) is False
    con.execute(f"UPDATE \"{e10}\".execucao_regra SET entradas_hash = repeat('0', 64) WHERE origem LIKE 'e10:%:010100%'")
    assert D.ESTAGIO.efeito(payload, _ctx(did), again) is False


@precisa_pg
def test_sem_elegivel_zero_achado_declarado_e_conferido(pg, fonte):
    con, e9, e10, veredito = pg
    veredito("010100|2025OB1|2025", "I:TRANSFERENCIA")
    did = "e10.ob_antes_da_liquidacao"
    payload = {"detector": did, "fonte": str(fonte), "dsn": DSN, "esquema": e10, "esquema_e9": e9}
    res = D.ESTAGIO.handler(payload, _ctx(did))
    assert res.efeito["achados"] == 0 and res.efeito["resumo_novo"] is True
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is True             # 0 achado DECLARADO, com o resumo
    n = con.execute(f"SELECT (resultado->>'ob_com_nl_na_base')::int FROM \"{e10}\".execucao_regra "
                    "WHERE origem LIKE '%:resumo'").fetchone()[0]
    assert n == 2                                                        # o denominador fica gravado
