# -*- coding: utf-8 -*-
"""E14 `caso` (O7.4): RBAC puro (papéis na sessão existente, justificativa, classe restrita, segredo), chave do caso,
classe mínima; e no PG (esquema temporário, VM-2): relação por processo/CNPJ/UG por igualdade de valor, versionamento
idempotente, contestação como evento (revisor ≠ autor, desfecho vira decisão humana, o achado da regra não muda),
append-only NO BANCO (acesso_log, contestação, desfecho, caso_achado, caso_versao), trilha de toda tentativa
(permitida e negada) e o efeito conferido."""
import uuid
from decimal import Decimal

import pytest

from compliance_agent.aplicacao.estagios import ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import caso as E14
from compliance_agent.dominio import acesso as AC
from compliance_agent.dominio.achado import Achado, ExecucaoRegra, Fato, Papel, hash_entradas
from compliance_agent.dominio.estados import EstadoSaida
from tests.fluxo_pg import DSN, precisa_pg

DONO = AC.Principal("dono:sessao_painel", AC.Papel.DONO)
ANALISTA = AC.Principal("analista:teste", AC.Papel.ANALISTA)
LEITURA = AC.Principal("leitura:teste", AC.Papel.LEITURA)
SERVICO = AC.Principal("servico:teste", AC.Papel.SERVICO)
JUST = "pedido do dono: dossiê do órgão para a reunião"
CPF_TESTE = "529" + "982" + "247" + "25"          # sintético, montado em tempo de execução (scan_pii)


# ── RBAC puro ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("p,acao,ok", [
    (LEITURA, AC.Acao.LER_CASO, True), (LEITURA, AC.Acao.CONTESTAR, False), (LEITURA, AC.Acao.EXPORTAR_DOSSIE, False),
    (SERVICO, AC.Acao.MONTAR_CASO, True), (SERVICO, AC.Acao.CONTESTAR, False),
    (SERVICO, AC.Acao.REVISAR_CONTESTACAO, False), (SERVICO, AC.Acao.ABRIR_RESTRITO, False),
    (ANALISTA, AC.Acao.REVISAR_CONTESTACAO, True), (ANALISTA, AC.Acao.ADMINISTRAR, False),
    (DONO, AC.Acao.ADMINISTRAR, True)])
def test_matriz_de_papeis(p, acao, ok):
    assert AC.decidir(p, acao, justificativa=JUST).permitido is ok


def test_exportar_e_abrir_restrito_exigem_justificativa():
    for acao in (AC.Acao.EXPORTAR_DOSSIE, AC.Acao.ABRIR_RESTRITO):
        assert not AC.decidir(DONO, acao, justificativa="").permitido
        assert not AC.decidir(DONO, acao, justificativa="ok, pode ir").permitido      # < 15 úteis
        assert AC.decidir(DONO, acao, justificativa=JUST).permitido
    assert "justificativa" in AC.decidir(SERVICO, AC.Acao.EXPORTAR_DOSSIE).motivo


def test_ler_caso_restrito_e_abrir_restrito():
    d = AC.decidir(LEITURA, AC.Acao.LER_CASO, justificativa=JUST, classe="pessoal")
    assert not d.permitido and "abrir_restrito" in d.exigidas
    assert not AC.decidir(ANALISTA, AC.Acao.LER_CASO, classe="restrito").permitido           # sem justificativa
    assert AC.decidir(ANALISTA, AC.Acao.LER_CASO, justificativa=JUST, classe="restrito").permitido
    assert not AC.decidir(ANALISTA, AC.Acao.LER_CASO, justificativa=JUST, classe="segredo").permitido
    assert AC.decidir(DONO, AC.Acao.LER_CASO, justificativa=JUST, classe="segredo").permitido
    assert not AC.decidir(DONO, AC.Acao.LER_CASO, classe="inventada").permitido              # falha fechada


def test_papeis_na_sessao_existente_sem_credencial_nova():
    assert AC.principal_da_sessao(cookie_valido=True, local_sem_proxy=False).papel is AC.Papel.DONO
    assert AC.principal_da_sessao(cookie_valido=False, local_sem_proxy=True, no="vm1").papel is AC.Papel.SERVICO
    assert AC.principal_da_sessao(cookie_valido=False, local_sem_proxy=False) is None
    assert AC.principal_do_processo(interativo=True, dono_do_repo=True, no="vm1").papel is AC.Papel.DONO
    assert AC.principal_do_processo(interativo=False, dono_do_repo=True, no="vm1").papel is AC.Papel.SERVICO
    assert AC.principal_do_processo(interativo=True, dono_do_repo=False, no="vm1").papel is AC.Papel.SERVICO
    # analista e leitura existem na matriz, mas nenhuma identidade existente mapeia para eles (BLOQUEADO: credencial)
    assert set(AC.PAPEIS_SEM_IDENTIDADE) == {AC.Papel.ANALISTA, AC.Papel.LEITURA}


def test_chave_do_caso():
    assert E14.analisar_chave("processo:SEI-480002/3703/24") == ("processo", "480002/003703/2024",
                                                                 "processo:480002/003703/2024")
    assert E14.analisar_chave("cnpj:19.088.605/0001-04")[2] == "cnpj:19088605000104"
    assert E14.analisar_chave("ug:166100")[2] == "ug:166100"
    assert E14.analisar_chave("lista:7, 3,3")[2] == "lista:3,7"
    for ruim in ("processo:SEI-08000/007404/2022", "cnpj:123", "ug:16610", "orgao:x", "lista:a"):
        with pytest.raises(ErroPermanente):
            E14.analisar_chave(ruim)


def test_classe_minima_pessoa_fisica():
    base = {"achados": [{"evidencias": [{"fato": {"dados": {"cnpj": "1"}}}], "valores": {}}]}
    assert E14.classe_minima(base) == "interno"
    pf = {"achados": [{"evidencias": [{"fato": {"dados": {"cpf": CPF_TESTE}}}], "valores": {}}]}
    assert E14.classe_minima(pf) == "pessoal"


def test_registro_do_estagio():
    assert estagio_de("caso:processo:480002/003703/2024") is E14.ESTAGIO


# ── PG (esquema temporário) ──────────────────────────────────────────────────────────────────────────────────────
def _achado(regra: str, origem: str, *, processo=None, resultado=None, estado=EstadoSaida.INDICIO, papel=Papel.SUPORTE,
            dados=None, alternativas=("reemissão legítima",)) -> Achado:
    ent = {"origem": origem}
    exe = ExecucaoRegra(regra_id=regra, versao="t1", entradas_hash=hash_entradas(ent), processo=processo,
                        resultado={"entradas": ent, **(resultado or {})}, origem=origem)
    fatos = [Fato(papel=papel, tipo="ob", fonte="ob_orcamentaria_siafe", referencia="2024OB00001",
                  descricao="OB paga", valor=Decimal("10.00"), dados=dados or {})]
    return Achado.de_regra(execucao=exe, estado=estado, motivo_estado="sem NL" if estado is EstadoSaida.INCERTO else "",
                           observacao="A OB 2024OB00001 foi paga", inferencia="pagamento antes da liquidação",
                           hipotese="pagamento antes da liquidação", hipoteses_alternativas=list(alternativas),
                           evidencias=fatos)


@pytest.fixture(scope="module")
def esquema():
    import psycopg
    nome = f"tmp_e14_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        E14.aplicar_schema(con, nome)
        yield nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


@pytest.fixture()
def pg(esquema, monkeypatch):
    from compliance_agent.adaptadores.achados import gravar
    monkeypatch.setenv(E14.ENV_ESQUEMA, esquema)
    monkeypatch.setenv("JFN_E11_ESQUEMA", esquema)
    monkeypatch.setattr(E14, "_registro", lambda: {"r.teste": {"tier": 3, "hipoteses_inocentes": [
        {"hipotese": "correção de domicílio bancário", "excluida_por": None}]}})
    con = E14.conectar({"dsn": DSN, "esquema": esquema})
    tag = uuid.uuid4().hex[:8]
    gravar(con, esquema, [
        _achado("r.teste", f"t:{tag}:1", processo="SEI-480002/003703/2024", resultado={"ug": "166100"}),
        _achado("r.teste", f"t:{tag}:2", resultado={"entradas2": {"processo": "480002/3703/24"},
                                                    "cnpj": "19088605000104"}),
        _achado("r.teste", f"t:{tag}:3", resultado={"valores": {"credor": "19.088.605/0001-04"}},
                estado=EstadoSaida.INCERTO, papel=Papel.CONTEXTO, dados={"cpf": CPF_TESTE}),
        _achado("r.teste", f"t:{tag}:4", processo="SEI-480002/003704/2024", resultado={"ug": 166101,
                                                                                         "nota": "19088605000104x"}),
    ])
    ids = [r[0] for r in con.execute("SELECT a.id FROM achado a JOIN execucao_regra e ON e.id = a.execucao_regra_id "
                                     "WHERE e.origem LIKE %s ORDER BY e.origem", (f"t:{tag}:%",))]
    con.tag, con.ids = tag, ids
    yield con
    con.close()


def _rel(pg, chave):
    t, v, _ = E14.analisar_chave(chave)
    return {a for a in E14.relacionados(pg, t, v) if a in pg.ids}


@precisa_pg
def test_relacao_por_igualdade_de_valor(pg):
    a1, a2, a3, a4 = pg.ids
    assert _rel(pg, "processo:SEI-480002/003703/2024") == {a1, a2}        # grafias diferentes, mesma chave
    assert _rel(pg, "cnpj:19088605000104") == {a2, a3}                    # cru e formatado; "…04x" não casa
    assert _rel(pg, "ug:166100") == {a1}                                  # 166101 não casa
    assert _rel(pg, f"lista:{a4}") == {a4}


@precisa_pg
def test_montar_versiona_idempotente_e_classe_sobe(pg):
    ch = f"lista:{','.join(map(str, pg.ids[1:3]))}"
    m1 = E14.montar(pg, ch, SERVICO)
    m2 = E14.montar(pg, ch, SERVICO)
    assert m1["versao_nova"] and not m2["versao_nova"] and m1["versao_chave"] == m2["versao_chave"]
    assert m1["classe"] == "pessoal"                                     # evidência com CPF ⇒ ao menos pessoal
    der = E14.vigente(pg, m1["caso_id"])["derivado"]
    assert {h["origem"] for h in der["hipoteses_inocentes"]} == {"achado", "registro"}
    assert any(lac["tipo"] == "estado INCERTO" for lac in der["lacunas"])
    assert any(d["origem"] == "lacuna" for d in der["diligencias"])
    with pytest.raises(AC.AcessoNegado):                                 # pessoal: ler é abrir restrito
        E14.ler(pg, ch, SERVICO, justificativa=JUST)
    assert E14.ler(pg, ch, DONO, justificativa=JUST)["versao"] == 1
    neg = pg.execute("SELECT permitido, motivo FROM acesso_log WHERE recurso = %s AND acao = 'ler_caso' ORDER BY id",
                     (f"caso:{ch}",)).fetchall()
    assert [r[0] for r in neg] == [False, True]                          # a negada TAMBÉM ficou na trilha


@precisa_pg
def test_contestacao_evento_revisa_derivados_e_nunca_apaga(pg, tmp_path):
    a1 = pg.ids[0]
    ch = f"lista:{a1}"
    m = E14.montar(pg, ch, SERVICO)
    with pytest.raises(AC.AcessoNegado):
        E14.contestar(pg, ch, LEITURA, "não concordo")
    anexo = tmp_path / "nf.pdf"
    anexo.write_bytes(b"%PDF nota fiscal 3890")
    c = E14.contestar(pg, ch, ANALISTA, "a NL foi emitida antes; segue o espelho", achado_id=a1, anexo=anexo)
    assert c["versao_nova"] and c["versao_versao"] == m["versao_versao"] + 1
    der = E14.vigente(pg, m["caso_id"])["derivado"]
    assert der["achados"][0]["contestacao_pendente"] is True
    assert any(d["origem"] == f"contestacao:{c['contestacao_id']}" for d in der["diligencias"])
    with pytest.raises(ErroPermanente):                                  # revisor = autor (código)
        E14.decidir_contestacao(pg, c["contestacao_id"], ANALISTA, "acolhida", "conferi o espelho da NL")
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException):                   # revisor = autor (banco)
        pg.execute("INSERT INTO contestacao_desfecho(contestacao_id, revisor, papel, desfecho, fundamentacao) "
                   "VALUES (%s,%s,'dono','rejeitada','x')", (c["contestacao_id"], ANALISTA.id))
    with pytest.raises(AC.AcessoNegado):
        E14.decidir_contestacao(pg, c["contestacao_id"], SERVICO, "acolhida", "conferi")
    d = E14.decidir_contestacao(pg, c["contestacao_id"], DONO, "acolhida", "a NL 2024NL00010 precede a OB")
    der = E14.vigente(pg, m["caso_id"])["derivado"]
    a = der["achados"][0]
    assert a["status_efetivo"] == "refutado" and a["status_regra"] == "triagem" and not a["contestacao_pendente"]
    assert any(x["origem"] == f"contestacao:{c['contestacao_id']}" for x in der["contraevidencias"])
    assert [h["evento"] for h in der["historico"]][-2:] == ["contestacao", "desfecho"] or \
        {"contestacao", "desfecho", "decisao"} <= {h["evento"] for h in der["historico"]}
    st = pg.execute("SELECT status FROM achado WHERE id = %s", (a1,)).fetchone()[0]
    assert st == "triagem"                                               # o achado da regra não muda
    dh = pg.execute("SELECT status, autor FROM decisao_humana WHERE id = %s", (d["decisao_humana_id"],)).fetchone()
    assert dh == ("refutado", DONO.id)
    versoes = pg.execute("SELECT versao, vigente FROM caso_versao WHERE caso_id = %s ORDER BY versao",
                         (m["caso_id"],)).fetchall()
    assert [v for v, _ in versoes] == list(range(1, len(versoes) + 1)) and [g for _, g in versoes].count(True) == 1
    sha = pg.execute("SELECT anexo_sha256 FROM contestacao WHERE id = %s", (c["contestacao_id"],)).fetchone()[0]
    import hashlib
    assert sha == hashlib.sha256(anexo.read_bytes()).hexdigest()


@precisa_pg
@pytest.mark.parametrize("sql", [
    "UPDATE acesso_log SET motivo = 'x'", "DELETE FROM acesso_log", "TRUNCATE acesso_log",
    "UPDATE contestacao SET argumento = 'x'", "DELETE FROM contestacao", "DELETE FROM contestacao_desfecho",
    "DELETE FROM caso_achado", "DELETE FROM caso_versao", "UPDATE caso_versao SET motivo = 'x'",
    "UPDATE caso_versao SET vigente = true WHERE NOT vigente", "DELETE FROM entrega"])
def test_append_only_no_banco(pg, sql):
    import psycopg
    E14.montar(pg, f"lista:{pg.ids[3]}", SERVICO)
    c = E14.contestar(pg, f"lista:{pg.ids[3]}", DONO, "contesto o método")
    E14.decidir_contestacao(pg, c["contestacao_id"], ANALISTA, "rejeitada", "o método segue o registro")
    pg.execute("INSERT INTO entrega(produto, chave, manifesto_sha256, destino, ok) VALUES ('p','c',%s,'arquivo',true)",
               ("0" * 64,))
    E14.montar(pg, f"lista:{pg.ids[3]}", SERVICO)
    with pytest.raises(psycopg.errors.RaiseException):
        pg.execute(sql)


@precisa_pg
def test_estagio_handler_e_efeito(pg):
    from compliance_agent.aplicacao.estagios import Contexto
    ch = "processo:SEI-480002/003703/2024"
    payload = {"chave": ch, "dsn": DSN, "esquema": pg.execute("SHOW search_path").fetchone()[0].strip('"')}
    ctx = Contexto(no="teste", tipo=f"caso:{ch}", chave=f"caso:{ch}", ficha=0, tentativa=1)
    r = E14.ESTAGIO.handler(payload, ctx)
    assert E14.ESTAGIO.efeito(payload, ctx, r) is True
    assert r.efeito["achados"] >= 2
    falso = type(r)(efeito={**r.efeito, "versao_chave": "f" * 64}, eventos=[])
    assert E14.ESTAGIO.efeito(payload, ctx, falso) is False              # declarou versão que não é a vigente
