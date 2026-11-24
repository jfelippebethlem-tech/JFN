# -*- coding: utf-8 -*-
"""Carga da identidade dos manifests no PG (tools/evidencias_carga_manifestos.py; plano mestre v2 O3.1/O3.2).

Fixtures sintéticas pequenas. A parte PG roda SÓ com `JFN_EVIDENCIAS_DSN=postgresql://…` e SEMPRE num esquema
temporário criado e apagado aqui (o padrão de tests/test_evidencias_pg.py) — nunca no `public`."""
import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest

from compliance_agent import evidencias as E

_SPEC = importlib.util.spec_from_file_location(
    "evidencias_carga_manifestos", Path(__file__).resolve().parents[1] / "tools" / "evidencias_carga_manifestos.py")
C = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(C)

DSN = os.environ.get(E.ENV_DSN, "")
precisa_pg = pytest.mark.skipif(not DSN.startswith(("postgresql://", "postgres://")),
                                reason="sem JFN_EVIDENCIAS_DSN (PostgreSQL de teste) — rodar na VM-2 com o DSN")

CORPO = "Governo do Estado do Rio de Janeiro — conteúdo servido pelo SEI, longo o bastante. "


def _pasta(raiz: Path, nome: str, processo, docs) -> Path:
    """docs = [(titulo, texto|None, tipo), …]; `i` gravado como string (formato do cache do sweep)."""
    p = raiz / nome
    (p / "texto").mkdir(parents=True)
    man = []
    for i, (titulo, texto, tipo) in enumerate(docs):
        d = {"i": str(i), "titulo": titulo, "fase": "", "tipo": tipo, "texto": "", "chars": "0", "ocr": "",
             "fotos": "[]"}
        if texto is not None:
            rel = f"texto/{i:03d}_x.txt"
            (p / rel).write_text(f"[{titulo}] (fase: x · tipo: {tipo})\n\n{texto}", encoding="utf-8")
            d["texto"], d["chars"] = rel, str(len(texto))
        man.append(d)
    m = {"docs": man}
    if processo is not None:
        m["processo"] = processo
    (p / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return p


@pytest.fixture()
def acervo(tmp_path):
    raiz = tmp_path / "sei_arquivo"
    _pasta(raiz, "100001_000001_2025", "100001/000001/2025", [
        ("Despacho de Encaminhamento (11111111)", CORPO + "um", "tramitacao"),
        ("Nota de Empenho (22222222)", CORPO + "dois", "empenho"),
        ("Nota de Empenho (22222222)", CORPO + "dois-bis", "empenho"),        # número repetido → #2
        ("Nota Fiscal", CORPO + "três", "outros"),                            # sem número → pos:3
        ("Anexo sem texto (33333333)", None, "outros"),                       # sem texto → sem versão
    ])
    _pasta(raiz, "100002_000077_2024", "SEI-100002/77/24", [                  # grafia curta no campo
        ("Contrato (44444444)", CORPO + "contrato", "contrato")])
    _pasta(raiz, "406_2025", "406/2025", [("Ofício (55555555)", CORPO, "outros")])  # sem número completo
    return raiz


# ── sem banco ─────────────────────────────────────────────────────────────────────────────────────────
def test_ler_processo_usa_as_funcoes_unicas(acervo):
    p = C.ler_processo(acervo / "100001_000001_2025")
    assert p["processo"] == "100001/000001/2025"
    assert p["ids"] == ["sei:11111111", "sei:22222222", "sei:22222222#2", "pos:3", "sei:33333333"]
    assert p["hash"] == E.hash_arvore(["sei:11111111", "sei:22222222", "sei:22222222", "pos:3", "sei:33333333"])
    posicoes = [r[2] for r in p["linhas_doc"]]
    assert posicoes == [0, 1, 2, 3, 4]                                          # `i` string → int (manifesto_norm)
    tipos = {r[1]: r[4] for r in p["linhas_doc"]}
    assert tipos["sei:22222222"] == "nota_empenho"                              # vocabulário fino canônico


def test_chave_canonica_da_grafia_curta_e_recusa_sem_numero(acervo):
    assert C.ler_processo(acervo / "100002_000077_2024")["processo"] == "100002/000077/2024"
    r = C.ler_processo(acervo / "406_2025")
    assert r["erro"] == "sem número de processo completo" and r["processo_bruto"] == "406/2025"


def test_versoes_tem_o_mesmo_sha_do_importar_pasta(acervo, tmp_path):
    """Paridade com o caminho antigo: mesma chave, mesmos ids, mesmo hash de árvore e mesmo sha de versão."""
    pasta = acervo / "100001_000001_2025"
    sq = E.conectar(tmp_path / "ev.db")
    try:
        E.importar_pasta(sq, pasta)
        ant_ver = set(sq.execute("SELECT processo, doc_id, sha256, chars, ocr FROM versoes").fetchall())
        ant_arv = sq.execute("SELECT processo, hash FROM arvores").fetchone()
        ant_doc = {r[0] for r in sq.execute("SELECT doc_id FROM documentos")}
    finally:
        sq.close()
    p = C.ler_processo(pasta)
    novo = {(r[0], r[1], r[2], r[3], r[5]) for r in C.linhas_versao(pasta, p)}
    assert novo == ant_ver and len(novo) == 4                                   # o doc sem texto não tem versão
    assert (p["processo"], p["hash"]) == tuple(ant_arv) and set(p["ids"]) == ant_doc
    assert {r[6] for r in C.linhas_versao(pasta, p)} == {"texto"}
    assert {r[7] for r in C.linhas_versao(pasta, p)} == {"legado"}


def test_esquema_de_producao_nao_se_apaga(monkeypatch):
    monkeypatch.setenv(E.ENV_DSN, "postgresql://ninguem@127.0.0.1:1/x")
    assert C.main(["apagar-esquema", "--esquema", "public"]) == 2


# ── PostgreSQL (esquema temporário) ───────────────────────────────────────────────────────────────────
@pytest.fixture()
def pg():
    import psycopg
    nome = f"tmp_carga_{uuid.uuid4().hex[:10]}"
    con = C.preparar(DSN, nome)
    try:
        yield con, nome
    finally:
        con.close()
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')


def _n(con, sql):
    return con.execute(sql).fetchone()[0]


@precisa_pg
def test_carga_paridade_e_idempotencia(pg, acervo):
    con, _ = pg
    pastas = C.pastas_do_acervo(acervo)
    r = C.carregar(con, pastas, lote=2, pausa=0)
    assert r["totais"]["processos"] == 2 and r["totais"]["documentos"] == 6 and r["totais"]["versoes"] == 5
    assert [e["pasta"] for e in r["erros"]] == ["406_2025"]
    assert _n(con, "SELECT COUNT(*) FROM versoes WHERE aquisicao_id='legado' AND hash_de='texto'") == 5
    assert _n(con, "SELECT fonte FROM aquisicao WHERE id='legado'") == "sei_arquivo"
    assert _n(con, "SELECT COUNT(*) FROM transformacao") == 0
    par = C.paridade(con, pastas)
    assert par["bate_100"] is True, par["diferencas"]
    assert par["contagem"]["documentos"] == {"manifests": 6, "pg": 6, "manifests_incl_sem_chave": 7}
    assert par["contagem"]["manifests_sem_chave"] == 1
    # de novo: tudo pulado, nada muda
    r2 = C.carregar(con, pastas, lote=2, pausa=0)
    assert r2["totais"] == {"pulados_ja_carregados": 2}
    assert _n(con, "SELECT COUNT(*) FROM documentos") == 6 and _n(con, "SELECT COUNT(*) FROM versoes") == 5


@precisa_pg
def test_retomada_e_versao_nova_nao_apaga_a_antiga(pg, acervo):
    con, _ = pg
    pastas = C.pastas_do_acervo(acervo)
    C.carregar(con, pastas[:1], pausa=0)                                        # "caiu" depois do 1º processo
    r = C.carregar(con, pastas, pausa=0)
    assert r["totais"]["pulados_ja_carregados"] == 1 and r["totais"]["processos"] == 1
    assert C.paridade(con, pastas)["bate_100"] is True
    alvo = acervo / "100001_000001_2025" / "texto" / "000_x.txt"
    alvo.write_text("[Despacho] (fase: x · tipo: y)\n\n" + CORPO + "RETIFICADO", encoding="utf-8")
    C.carregar(con, pastas, pausa=0, forcar=True)
    assert _n(con, "SELECT COUNT(*) FROM versoes WHERE doc_id='sei:11111111'") == 2
    assert _n(con, "SELECT COUNT(*) FROM documentos") == 6                     # identidade não muda


@precisa_pg
def test_migracao_idempotente(pg):
    import psycopg
    con, nome = pg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(C.renderizar(C.MIGRACAO.read_text(encoding="utf-8"), nome))   # segunda aplicação
        assert c.execute(f'SELECT COUNT(*) FROM "{nome}".aquisicao').fetchone()[0] == 1
        assert c.execute(f'SELECT versao FROM "{nome}".migracoes').fetchall() == [("evidencias_001",)]
    with pytest.raises(psycopg.errors.CheckViolation):                         # hash_de só 'texto'/'binario'
        with con:
            con.execute("INSERT INTO versoes(processo, doc_id, sha256, chars, origem, vista_em, hash_de) "
                        "VALUES('a','b','c',1,'o','t','palpite')")
