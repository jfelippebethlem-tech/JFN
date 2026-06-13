# -*- coding: utf-8 -*-
"""Testes do doubt-sender de fachada (seleção, captura passiva, override na DD). Sem rede."""
import sqlite3

import pytest

from compliance_agent import fachada_doubt as fd


# ───────────────────────── fixtures: compliance.db e state.db temporários ─────────────────────────
def _compliance(tmp_path):
    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE endereco_verificacao (
          cnpj TEXT PRIMARY KEY, status TEXT, nivel TEXT, exato INTEGER,
          lat REAL, lon REAL, municipio_geo TEXT, evidencia TEXT, verificado_em TEXT,
          visual_classe TEXT, visual_conf REAL, visual_fonte TEXT, visual_em TEXT);
        CREATE TABLE endereco_fornecedor (
          cnpj TEXT PRIMARY KEY, razao TEXT, endereco TEXT, endereco_norm TEXT,
          municipio TEXT, uf TEXT, cep TEXT, atualizado_em TEXT);
        CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, valor REAL);
    """)
    # 3 fornecedores: A dúvida c/ R$ alto, B dúvida c/ R$ baixo, C dúvida SEM coord, D não-dúvida
    def addr(c, st, exato, lat, lon, vis=None, razao=None, endereco=None):
        con.execute("INSERT INTO endereco_verificacao(cnpj,status,exato,lat,lon,evidencia,visual_classe) "
                    "VALUES(?,?,?,?,?,?,?)", (c, st, exato, lat, lon, "ev " + c, vis))
        con.execute("INSERT INTO endereco_fornecedor(cnpj,razao,endereco,municipio,uf,cep) "
                    "VALUES(?,?,?,?,?,?)", (c, razao or ("EMPRESA " + c),
                    endereco or ("RUA X, " + c), "RIO", "RJ", "20000000"))
    addr("11111111000111", "INDISPONIVEL", 1, -22.9, -43.1)
    addr("22222222000122", "INDISPONIVEL", 0, -22.8, -43.2)
    addr("33333333000133", "INDISPONIVEL", 1, None, None)      # sem coord → fora
    addr("44444444000144", "AFASTADO", 1, -22.7, -43.3)        # não é dúvida → fora
    addr("55555555000155", "INDISPONIVEL", 1, -22.6, -43.4)    # dúvida mas R$=0 → fora (HAVING>0)
    for c, v in (("11111111000111", 5_000_000), ("22222222000122", 100_000),
                 ("33333333000133", 9_000_000), ("44444444000144", 7_000_000)):
        con.execute("INSERT INTO ordens_bancarias VALUES(?,?)", (c, v))
    con.commit()
    con.close()
    return db


# ───────────────────────────────── codigo_de ─────────────────────────────────
def test_codigo_deterministico_e_alfabeto():
    c = "11111111000111"
    assert fd.codigo_de(c) == fd.codigo_de(c)
    cod = fd.codigo_de(c)
    assert len(cod) == 5
    assert all(ch in fd._ALFA for ch in cod)
    assert "0" not in cod and "O" not in cod and "1" not in cod and "I" not in cod


def test_codigo_distingue_cnpjs():
    assert fd.codigo_de("11111111000111") != fd.codigo_de("22222222000122")


# ───────────────────────────────── candidatos ─────────────────────────────────
def test_candidatos_rankeia_por_recebido_e_filtra(tmp_path):
    con = fd.conectar(_compliance(tmp_path))
    cands = fd.candidatos(con, limite=10, so_residencial=False)
    cnpjs = [c["cnpj"] for c in cands]
    # 33 (sem coord), 44 (não-dúvida), 55 (R$0) ficam de fora; 11 antes de 22 (R$ maior)
    assert cnpjs == ["11111111000111", "22222222000122"]
    assert cands[0]["total_recebido"] == 5_000_000


def test_candidatos_exato_apenas(tmp_path):
    con = fd.conectar(_compliance(tmp_path))
    cands = fd.candidatos(con, limite=10, incluir_aproximado=False, so_residencial=False)
    assert [c["cnpj"] for c in cands] == ["11111111000111"]  # 22 é exato=0


def test_candidatos_exclui_ja_enviados(tmp_path):
    con = fd.conectar(_compliance(tmp_path))
    cands = fd.candidatos(con, limite=10, so_residencial=False)
    fd.registrar_envio(con, cands[0], fd.codigo_de(cands[0]["cnpj"]), "streetview", 999)
    rest = [c["cnpj"] for c in fd.candidatos(con, limite=10, so_residencial=False)]
    assert "11111111000111" not in rest and "22222222000122" in rest


def test_candidatos_so_residencial_e_blocklist(tmp_path):
    db = _compliance(tmp_path)
    con = fd.conectar(db)
    # fachada residencial com R$ menor + banco com R$ enorme + empreiteiro sem marcador
    con.execute("INSERT INTO endereco_verificacao(cnpj,status,exato,lat,lon,evidencia) "
                "VALUES('66666666000166','INDISPONIVEL',1,-22.5,-43.5,'e')")
    con.execute("INSERT INTO endereco_fornecedor(cnpj,razao,endereco,municipio,uf,cep) "
                "VALUES('66666666000166','XPTO COMERCIO LTDA','RUA A, 10, CASA 2, FUNDOS','RIO','RJ','2')")
    con.execute("INSERT INTO ordens_bancarias VALUES('66666666000166', 800000)")
    con.execute("INSERT INTO endereco_verificacao(cnpj,status,exato,lat,lon,evidencia) "
                "VALUES('77777777000177','INDISPONIVEL',1,-22.4,-43.6,'e')")
    con.execute("INSERT INTO endereco_fornecedor(cnpj,razao,endereco,municipio,uf,cep) "
                "VALUES('77777777000177','BANCO XPTO SA','AV CENTRAL, 1','RIO','RJ','3')")
    con.execute("INSERT INTO ordens_bancarias VALUES('77777777000177', 9000000000)")
    con.commit()
    # default (so_residencial=True): só a fachada residencial entra; banco é bloqueado, 11/22 sem marcador
    cands = fd.candidatos(con, limite=10)
    cnpjs = [c["cnpj"] for c in cands]
    assert cnpjs == ["66666666000166"]
    assert "FUNDOS" in cands[0]["marcadores"] or "CASA" in cands[0]["marcadores"]
    # so_residencial=False ainda bloqueia o BANCO pelo nome
    todos = [c["cnpj"] for c in fd.candidatos(con, limite=10, so_residencial=False)]
    assert "77777777000177" not in todos and "66666666000166" in todos


# ───────────────────────────────── legenda honesta ─────────────────────────────────
def test_legenda_usa_endereco_e_pano():
    base = {"cnpj": "1", "razao": "X", "endereco": "RUA Y, 10", "municipio": "RIO", "uf": "RJ",
            "total_recebido": 1000}
    leg = fd.legenda(base, "ABCDE", "streetview", {"lat": -22.9, "lon": -43.1, "date": "2024-07"})
    assert "Street View do endereço" in leg and "pano 2024-07" in leg
    assert "cbll=-22.9,-43.1" in leg                       # link de conferência no mapa
    assert "RUA Y, 10, RIO, RJ" in leg                     # endereço declarado
    assert "ABCDE fachada" in leg and "ABCDE real" in leg and "ABCDE pular" in leg


def test_endereco_completo_formata_cep():
    c = {"endereco": "RUA Y, 10", "municipio": "RIO", "uf": "RJ", "cep": "20031000"}
    assert fd.endereco_completo(c) == "RUA Y, 10, RIO, RJ, 20031-000"


# ───────────────────────────────── interpretar ─────────────────────────────────
@pytest.mark.parametrize("texto,esperado", [
    ("ABCDE fachada", "fachada"),
    ("é real essa, ABCDE", "real"),
    ("ABCDE: laranja confirmada", "fachada"),
    ("abcde PULAR", "pular"),
    ("ABCDE sede legítima", "real"),
    ("ABCDE", None),                       # código sem veredito → ignora
    ("fachada sem codigo", None),          # veredito sem código → ignora
    ("ZZZZZ fachada", None),               # código desconhecido
])
def test_interpretar(texto, esperado):
    pend = {"ABCDE": "11111111000111"}
    achados = fd.interpretar(texto, pend)
    if esperado is None:
        assert achados == []
    else:
        assert achados and achados[0][1] == esperado and achados[0][0] == "11111111000111"


def test_interpretar_case_insensitive():
    pend = {"ABCDE": "1"}
    assert fd.interpretar("o codigo AbCdE é fachada", pend)[0][1] == "fachada"


# ───────────────────────── captura passiva via state.db ─────────────────────────
def _state_db(tmp_path, msgs):
    """state.db mínimo do Hermes: sessions(source) + messages(role,content,timestamp,session_id)."""
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
                               content TEXT, timestamp REAL);
    """)
    con.execute("INSERT INTO sessions VALUES('s1','telegram:45338178')")
    con.execute("INSERT INTO sessions VALUES('s2','cli')")
    for i, (sess, role, content, ts) in enumerate(msgs):
        con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(?,?,?,?,?)",
                    (i + 1, sess, role, content, ts))
    con.commit()
    con.close()
    return db


def test_processar_respostas_fim_a_fim(tmp_path, monkeypatch):
    comp = _compliance(tmp_path)
    monkeypatch.setattr(fd, "_CURSOR", tmp_path / ".cursor")
    con = fd.conectar(comp)
    cands = fd.candidatos(con, limite=10, so_residencial=False)
    c11, c22 = cands[0], cands[1]
    cod11, cod22 = fd.codigo_de(c11["cnpj"]), fd.codigo_de(c22["cnpj"])
    fd.registrar_envio(con, c11, cod11, "streetview", 100)
    fd.registrar_envio(con, c22, cod22, "mapillary", 101)

    state = _state_db(tmp_path, [
        ("s1", "user", f"[J FN id=45338178] {cod11} fachada", 1000.0),
        ("s1", "user", f"a sede {cod22} é real mesmo", 1001.0),
        ("s2", "user", "msg de cli ignorada", 1002.0),       # source != telegram
    ])
    grav = fd.processar_respostas(con, state_db=state)
    status = dict((r["cnpj"], r["status"]) for r in
                  con.execute("SELECT cnpj,status FROM fachada_veredito"))
    assert status[c11["cnpj"]] == "fachada"
    assert status[c22["cnpj"]] == "real"
    assert len(grav) == 2
    # idempotente: 2ª passada não regrava (cursor avançou)
    assert fd.processar_respostas(con, state_db=state) == []


def test_veredito_humano_accessor(tmp_path):
    comp = _compliance(tmp_path)
    con = fd.conectar(comp)
    cands = fd.candidatos(con, limite=10, so_residencial=False)
    fd.registrar_envio(con, cands[0], fd.codigo_de(cands[0]["cnpj"]), "streetview", 1)
    assert fd.veredito_humano(cands[0]["cnpj"], db=comp) is None  # pendente → None
    con.execute("UPDATE fachada_veredito SET status='fachada' WHERE cnpj=?", (cands[0]["cnpj"],))
    con.commit()
    v = fd.veredito_humano(cands[0]["cnpj"], db=comp)
    assert v and v["status"] == "fachada"


# ───────────────────────── override na DD (investigacao_dd) ─────────────────────────
def test_dd_usa_veredito_humano(tmp_path, monkeypatch):
    from compliance_agent import investigacao_dd as dd
    # investigar faz `from compliance_agent.fachada_doubt import veredito_humano` lá dentro → patch na origem
    monkeypatch.setattr("compliance_agent.fachada_doubt.veredito_humano",
                        lambda cnpj, db=None: {"status": "fachada", "em": "2026-06-13", "raw": "manual"})
    out = dd.investigar("11111111000111", cadastral={}, pagamentos={"total_pago": 1_000_000})
    cods = [h["codigo"] for h in out["hipoteses"]]
    assert "H-END-HUMANO" in cods
    h = next(h for h in out["hipoteses"] if h["codigo"] == "H-END-HUMANO")
    assert h["status"] == "CONFIRMADO"


# ───────────────────── classificador de resposta livre + quote (decisões 2 e 3) ─────────────────────
import pytest as _pytest


@_pytest.mark.parametrize("texto,esperado", [
    ("Empresa real. Tem a logomarca dela no portao", "real"),
    ("Fachada certa, é um predio comercial", "real"),
    ("Inconclusivo, mas o endereco ta certo. O angulo da camera que nao é a fachada do endereco", "pular"),
    ("Marcou certo, mas é endereco residencial sim pelo que parece. Merece atencao. Pode ser laranja", "indicio"),
    ("Endereco residencial também. Marcador de indício. Acertou o endereco", "indicio"),
    ("é uma casa, claramente fachada", "fachada"),     # casa + fachada, sem problema-de-foto → fachada
    ("laranja na certa, baldio", "fachada"),
    ("foto ta errada, nao é esse endereco", "pular"),
    ("blá blá sem veredito", None),
])
def test_classificar_resposta(texto, esperado):
    assert fd.classificar_resposta(texto) == esperado


def test_interpretar_quote_por_cnpj():
    content = ('[Replying to: "🕵️ DÚVIDA DE FACHADA Empresa: X CNPJ: 12647362000158 Endereço..."] '
               'Empresa real. Tem a logomarca no portao')
    out = fd.interpretar(content, {}, {"12647362000158"})
    assert out and out[0][0] == "12647362000158" and out[0][1] == "real"


def test_interpretar_quote_indicio():
    content = ('[Replying to: "DÚVIDA Empresa: Y CNPJ: 19543304000123 ..."] '
               'é endereco residencial, merece atencao')
    out = fd.interpretar(content, {}, {"19543304000123"})
    assert out and out[0] == ("19543304000123", "indicio", out[0][2])


def test_interpretar_quote_cnpj_nao_pendente_ignora():
    content = '[Replying to: "... CNPJ: 99999999999999 ..."] real'
    assert fd.interpretar(content, {}, {"11111111111111"}) == []


def test_dd_veredito_indicio(monkeypatch):
    from compliance_agent import investigacao_dd as dd
    monkeypatch.setattr("compliance_agent.fachada_doubt.veredito_humano",
                        lambda cnpj, db=None: {"status": "indicio", "em": "2026-06-13", "raw": "residencial"})
    out = dd.investigar("11111111000111", cadastral={}, pagamentos={"total_pago": 500000})
    h = [x for x in out["hipoteses"] if x["codigo"] == "H-END-HUMANO"]
    assert h and h[0]["status"] == "INDICIO"


# ───────────────────── hipóteses Google na DD (verificacao_sede) ─────────────────────
def test_dd_hipoteses_google_sede(monkeypatch):
    from compliance_agent import investigacao_dd as dd
    # sem veredito humano → as hipóteses Google entram
    monkeypatch.setattr("compliance_agent.fachada_doubt.veredito_humano", lambda cnpj, db=None: None)
    monkeypatch.setattr(dd, "_verificacao_sede", lambda cnpj, db_path=None: {
        "status": "INDICIO", "nivel": "ALTO", "geo_tipo": "APPROXIMATE", "addr_completo": 0,
        "addr_residencial": 1, "places_achou": 0, "places_bate_nome": None, "evidencia": "x"})
    out = dd.investigar("11111111000111", cadastral={}, pagamentos={"total_pago": 6_000_000})
    cods = {h["codigo"] for h in out["hipoteses"]}
    assert {"H-END-RESID-GOOGLE", "H-SEM-PERFIL", "H-ENDERECO-INVALIDO"} <= cods


def test_dd_google_suprimido_por_veredito_humano(monkeypatch):
    from compliance_agent import investigacao_dd as dd
    # veredito humano 'real' → NÃO emite as hipóteses Google (o auditor vence)
    monkeypatch.setattr("compliance_agent.fachada_doubt.veredito_humano",
                        lambda cnpj, db=None: {"status": "real", "em": "2026-06-13", "raw": "manual"})
    monkeypatch.setattr(dd, "_verificacao_sede", lambda cnpj, db_path=None: {
        "status": "INDICIO", "nivel": "ALTO", "geo_tipo": "APPROXIMATE", "addr_completo": 0,
        "addr_residencial": 1, "places_achou": 0, "places_bate_nome": None, "evidencia": "x"})
    out = dd.investigar("11111111000111", cadastral={}, pagamentos={"total_pago": 6_000_000})
    cods = {h["codigo"] for h in out["hipoteses"]}
    assert not ({"H-END-RESID-GOOGLE", "H-SEM-PERFIL", "H-ENDERECO-INVALIDO"} & cods)
