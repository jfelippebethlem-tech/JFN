# -*- coding: utf-8 -*-
"""E2 `arvore` (O3.3): paginação até o fim (> 40 documentos, nunca "os 40 primeiros"), paginação travada recusada,
identidade pela função única do domínio, guarda de convergência (hash igual e sem falta ⇒ sem mudança, nenhum evento;
hash igual COM falta ⇒ volta ao E3), idempotência pela posse e efeito independente no PostgreSQL (esquema temporário).
Navegador sempre FALSO (tests/sei_falso.py)."""
import uuid

import pytest
import yaml

from compliance_agent import evidencias as EV
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.dominio import documento_id as DI
from tests.fluxo_pg import DSN, precisa_pg
from tests.sei_falso import SEIFalso, arvore_falsa

PROC = "999002/000001/2026"


def _ctx(ficha: int = 1, chave: str = f"arvore:{PROC}") -> Contexto:
    return Contexto(no="vm2", tipo="arvore", chave=chave, ficha=ficha, tentativa=1)


# ── puro ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_pagina_ate_o_fim_com_mais_de_40_documentos():
    nav = SEIFalso(arvore_falsa(95))
    lido = A.ler_arvore(nav, PROC)
    assert len(lido["docs"]) == 95 and lido["paginas"] == 10
    assert nav.paginas_pedidas == list(range(0, 100, 10))           # até a última página, nunca parou no 40


def test_paginacao_que_para_de_trazer_documento_antes_do_fim_e_erro():
    with pytest.raises(RuntimeError, match="leitura incompleta"):
        A.ler_arvore(SEIFalso(arvore_falsa(95), travar_paginacao=True), PROC)


def test_identidade_e_a_da_carga_dos_manifestos():
    docs = arvore_falsa(3) + [{"t": "Despacho repetido (90000001)", "u": "x?id_documento=1"}, {"t": "Sem número",
                                                                                                 "u": "x?id_documento=2"}]
    ids, h = A.identidade(docs)
    assert ids == ["sei:90000000", "sei:90000001", "sei:90000002", "sei:90000001#2", "pos:4"]
    assert ids == DI.ids_documentos([{"titulo": d["t"], "i": i} for i, d in enumerate(docs)])
    assert h == EV.hash_arvore([f"{DI.sem_repeticao(k)}@{A.id_documento(d)}" if A.id_documento(d) else
                                DI.sem_repeticao(k) for k, d in zip(ids, docs)])           # O3.5: + id_documento
    assert A.hash_ids(ids) == EV.hash_arvore([DI.sem_repeticao(x) for x in ids])           # o da carga O3.1


def test_restrito_nao_conta_como_falta():
    docs = arvore_falsa(4, restritos=(2,))
    ids, _ = A.identidade(docs)
    assert A.faltantes(ids, docs, {ids[0]}) == [ids[1], ids[3]]


def test_payload_invalido_e_permanente():
    with pytest.raises(ErroPermanente):
        A.processo_do({"processo": "não é processo"}, _ctx(chave="arvore:x"))
    assert A.processo_do({}, _ctx(chave="arvore:SEI-999002/1/26")) == PROC


def test_registro_e_rotina_inativa_no_fluxo():
    assert estagio_de(f"arvore:{PROC}") is A.ESTAGIO and A.ESTAGIO.recursos == ["navegador"]
    rot = yaml.safe_load(open(A.RAIZ / "config" / "fluxo.yaml", encoding="utf-8"))["rotinas"]
    r = rot["arvore_e2"]
    assert r["estagio"] == "E2" and r["ativa"] is False and "parada de obras" in r["bloqueio"]


# ── PostgreSQL (esquema temporário) ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def pg():
    import psycopg
    nome = f"tmp_captura_{uuid.uuid4().hex[:10]}"
    A.aplicar_schema(DSN, nome)
    A.aplicar_schema(DSN, nome)                                       # idempotente
    con = A.conectar(DSN, nome)
    try:
        yield con, nome
    finally:
        con.close()
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')


def _rodar(nav, monkeypatch, nome, ficha):
    monkeypatch.setattr(A, "obter_navegador", lambda: nav)
    ctx = _ctx(ficha)
    r = A._handler({"processo": PROC, "dsn": DSN, "esquema": nome, "lente": "bombeiros"}, ctx)
    return r, A._efeito({"dsn": DSN, "esquema": nome}, ctx, r)


@precisa_pg
def test_convergencia_hash_igual_sem_falta_e_sem_mudanca(pg, monkeypatch):
    con, nome = pg
    nav = SEIFalso(arvore_falsa(95))
    r1, ok1 = _rodar(nav, monkeypatch, nome, 1)
    assert ok1 and r1.efeito["estado"] == A.DOC_NOVO and r1.efeito["faltantes"] == 95 and r1.efeito["n_docs"] == 95
    assert [e["fonte"] for e in r1.eventos] == ["arvore"] and r1.eventos[0]["detalhe"]["lente"] == ["bombeiros"]
    # mesma árvore, nada capturado ainda ⇒ volta ao E3 (convergir é ficar sem falta, não só ver o mesmo hash)
    r2, ok2 = _rodar(nav, monkeypatch, nome, 2)
    assert ok2 and r2.efeito["estado"] == A.DOC_NOVO and r2.efeito["anterior"] == r1.efeito["tree_hash"]
    # todos capturados (versão de qualquer origem) ⇒ hash igual e sem falta = sem mudança e FIM (nenhum evento)
    con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em) "
                "SELECT processo, doc_id, md5(doc_id), 1, 'teste', 'agora' FROM documentos WHERE processo = %s", (PROC,))
    r3, ok3 = _rodar(nav, monkeypatch, nome, 3)
    assert ok3 and r3.efeito["estado"] == A.SEM_MUDANCA and r3.eventos == []
    # documento novo na árvore ⇒ hash muda, só ele falta
    nav.docs = arvore_falsa(96)
    r4, ok4 = _rodar(nav, monkeypatch, nome, 4)
    assert ok4 and r4.efeito["estado"] == A.DOC_NOVO and r4.efeito["faltantes"] == 1
    assert con.execute("SELECT count(*) FROM arvore_leitura").fetchone()[0] == 4


@precisa_pg
def test_mesma_posse_nao_duplica_e_efeito_pega_adulteracao(pg, monkeypatch):
    con, nome = pg
    nav = SEIFalso(arvore_falsa(12))
    r1, ok1 = _rodar(nav, monkeypatch, nome, 7)
    r1b, ok1b = _rodar(nav, monkeypatch, nome, 7)                       # reexecução da MESMA posse
    assert ok1 and ok1b and con.execute("SELECT count(*) FROM arvore_leitura").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM documentos WHERE processo = %s", (PROC,)).fetchone()[0] == 12
    con.execute("UPDATE arvore_leitura SET ids = ids - 0")                # tira um id: o hash gravado não fecha mais
    assert not A._efeito({"dsn": DSN, "esquema": nome}, _ctx(7), r1)


@precisa_pg
def test_legado_com_mesmo_hash_e_tudo_guardado_e_sem_mudanca(pg, monkeypatch):
    con, nome = pg
    docs = arvore_falsa(5)
    ids, _ = A.identidade(docs)
    con.execute("INSERT INTO arvores(processo, hash, n_docs, vista_em, origem) VALUES (%s,%s,5,'x','sei_arquivo')",
                (PROC, A.hash_ids(ids)))                  # o legado (O3.1) tem o hash só dos doc_id
    for k in ids:
        con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em) VALUES "
                    "(%s,%s,%s,10,'sei_arquivo','x')", (PROC, k, "s" + k))
    r, ok = _rodar(SEIFalso(docs), monkeypatch, nome, 1)
    assert ok and r.efeito["estado"] == A.SEM_MUDANCA and r.eventos == []


def test_restrito_e_sigilo_sao_fora_de_alcance(monkeypatch):
    """26/11/2026: RESTRITO/sigilo integral é resultado declarado (rota do dono), marcado para não bloquear o estágio."""
    from compliance_agent.aplicacao.estagios import ForaDeAlcance
    monkeypatch.setattr(A, "obter_navegador", lambda: None)
    monkeypatch.setattr(A, "ler_arvore", lambda nav, p: {"docs": [], "restrito": "Unidade atual não possui acesso",
                                                        "sem_resultado": False, "via": "t"})
    # O3.8: antes do ForaDeAlcance o E2 tenta a pesquisa pública (aqui: nada) — sem tocar o PG de produção
    monkeypatch.setattr(A, "obter_navegador_publico", lambda pares=None: None)
    monkeypatch.setattr(A, "pares_crc", lambda c, p: {})
    monkeypatch.setattr(A, "conectar", lambda *a, **k: type("C", (), {"close": lambda self: None})())
    with pytest.raises(ForaDeAlcance) as e:
        A._handler({"processo": PROC}, _ctx(chave=f"arvore:{PROC}"))
    assert str(e.value).startswith("[fora_de_alcance]") and isinstance(e.value, ErroPermanente)
