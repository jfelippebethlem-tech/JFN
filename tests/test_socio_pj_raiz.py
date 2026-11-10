# -*- coding: utf-8 -*-
"""Sócio PJ pela RAIZ de 8 dígitos — a mudança de leiaute da Receita não pode virar troca de controle.

O FATO. No `Socios*.zip`, o documento do sócio PESSOA JURÍDICA (identificador `1`) vinha com 14
dígitos até 2026-07 e vem com 8 (só a raiz) em 2026-10. A chave da série é
(`cnpj_basico`, `doc_socio`, `nome_norm`): sem normalizar, cada sócio PJ "sai" com 14 e "entra" com 8
no mesmo mês — ~3.200 falsas trocas de controle no detector `troca_de_controle`.

O mês do dump também era fixo (`2026-05`) e o refresh mensal re-baixava maio com "VALIDACAO=OK" três
vezes seguidas. Aqui se trava a decisão que denuncia esse congelamento.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_socio_pj_raiz.py -q
"""
from __future__ import annotations

import gzip
import sqlite3
import zipfile

import pytest

from compliance_agent.osint.historico_societario import (
    criar_schema,
    diff_snapshots,
    historico_do_socio,
    normalizar_doc_socio,
    registrar_snapshot,
)


# ───────────────────────────── 1. a função única ───────────────────────────────────────────────

@pytest.mark.parametrize("ident,doc,esperado", [
    ("1", "12345678000199", "12345678"),     # leiaute antigo: CNPJ íntegro → raiz
    ("1", "12345678", "12345678"),           # leiaute novo: já é a raiz
    (1, "12345678000199", "12345678"),       # ident numérico (tabelas de teste usam INTEGER)
    ("2", "***123456**", "***123456**"),     # PF mascarado fica como vem
    ("3", "", ""),                           # estrangeiro sem documento fica como vem
    ("3", "***999999**", "***999999**"),
    ("2", "12345678000199", "12345678000199"),  # só o identificador 1 é tocado
])
def test_normaliza_so_o_socio_pj(ident, doc, esperado):
    assert normalizar_doc_socio(ident, doc) == esperado


# ───────────────────────────── 2. a falsa troca de controle ────────────────────────────────────

def test_virada_de_leiaute_nao_gera_saida_nem_entrada():
    con = sqlite3.connect(":memory:")
    criar_schema(con)
    pj = {"cnpj_basico": "11111111", "nome_socio": "HOLDING ALFA LTDA", "ident": "1",
          "qualificacao_txt": "Sócio", "data_entrada": "20190101"}
    registrar_snapshot(con, "2026-07", [{**pj, "doc_socio": "22222222000155"}], origem="t")
    registrar_snapshot(con, "2026-08", [{**pj, "doc_socio": "22222222"}], origem="t")
    r = diff_snapshots(con)
    assert r["n_vinculos"] == 1, "14 e 8 dígitos são o MESMO sócio"
    assert r["n_sairam"] == 0
    h = historico_do_socio(con, doc_socio="22222222")
    assert len(h) == 1 and h[0]["status"] == "ativo" and h[0]["visto_de"] == "2026-07"


# ───────────────────────────── 3. os pontos de gravação lendo o ZIP ────────────────────────────

_LINHAS = [
    '"11111111";"1";"HOLDING ALFA LTDA";"22222222000155";"22";"20190101";"";"";"";"00";"0"',
    '"11111111";"2";"MARIA DA SILVA";"***123456**";"49";"20200101";"";"";"";"00";"5"',
    '"33333333";"1";"HOLDING ALFA LTDA";"22222222";"22";"20210101";"";"";"";"00";"0"',
]


def _zip(pasta, linhas=_LINHAS):
    zf = pasta / "Socios0.zip"
    with zipfile.ZipFile(zf, "w") as z:
        z.writestr("K3241.SOCIOCSV", ("\n".join(linhas) + "\n").encode("latin1"))
    return zf


@pytest.fixture()
def dump(tmp_path, monkeypatch):
    from tools import socios_dump_sweep as sds
    from tools import socios_reverso_build as srb
    db = tmp_path / "c.db"
    (tmp_path / "_nossas_raizes.txt").write_text("11111111\n33333333\n")
    for mod in (sds, srb):
        monkeypatch.setattr(mod, "_DB", db)
        monkeypatch.setattr(mod, "_DUMP", tmp_path)
        monkeypatch.setattr(mod, "_guarda_recursos", lambda: None)
    monkeypatch.setattr(sds, "_RAIZES", tmp_path / "_nossas_raizes.txt")
    _zip(tmp_path)
    return tmp_path, db


def test_socios_receita_grava_a_raiz_e_apaga_a_foto_anterior(dump):
    from tools import socios_dump_sweep as sds
    pasta, db = dump
    con = sqlite3.connect(db)
    con.execute(sds._DDL)
    con.execute("INSERT INTO socios_receita VALUES ('11111111','2','EX SOCIO','EX SOCIO',"
                "'***999999**','22','Sócio','20100101','5','2026-05')")
    con.commit(); con.close()

    sds.indexar("2026-10")

    con = sqlite3.connect(db)
    linhas = con.execute("SELECT cnpj_basico, doc_socio, fonte_mes FROM socios_receita "
                         "ORDER BY 1, 2").fetchall()
    assert ("11111111", "***999999**", "2026-05") not in linhas, "ex-sócio não pode ficar para sempre"
    assert {l[2] for l in linhas} == {"2026-10"}, "etiqueta do mês que foi de fato carregado"
    assert ("11111111", "22222222", "2026-10") in linhas
    assert not [l for l in linhas if len(l[1]) == 14]


def test_carga_vazia_nao_apaga_a_foto_anterior(dump):
    """Falha no meio (aqui: zero linhas casadas) não pode deixar a tabela vazia."""
    from tools import socios_dump_sweep as sds
    pasta, db = dump
    (pasta / "_nossas_raizes.txt").write_text("99999999\n")
    con = sqlite3.connect(db)
    con.execute(sds._DDL)
    con.execute("INSERT INTO socios_receita VALUES ('11111111','2','A','A','***1**','22','S','',"
                "'5','2026-05')")
    con.commit(); con.close()
    with pytest.raises(SystemExit):
        sds.indexar("2026-10")
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM socios_receita").fetchone()[0] == 1


def test_reverso_casa_o_socio_pj_pelos_dois_leiautes(dump):
    from tools import socios_dump_sweep as sds
    from tools import socios_reverso_build as srb
    sds.indexar("2026-10")
    srb.construir("2026-10")
    con = sqlite3.connect(dump[1])
    raizes = sorted(r[0] for r in con.execute(
        "SELECT cnpj_basico FROM socios_reverso WHERE doc_socio='22222222'"))
    assert raizes == ["11111111", "33333333"], "a linha de 14 e a de 8 são a mesma pessoa"


def test_serie_historica_grava_a_raiz(tmp_path):
    from tools.socios_serie_historica import _stream_para_snapshot
    con = sqlite3.connect(":memory:")
    criar_schema(con)
    _stream_para_snapshot(_zip(tmp_path), {"11111111"}, {}, con, "2026-07")
    docs = {r[0] for r in con.execute("SELECT doc_socio FROM socio_snapshot")}
    assert docs == {"22222222", "***123456**"}


# ───────────────────────────── 4. mês automático e congelamento ────────────────────────────────

_PROPFIND = """<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">
<d:response><d:href>/public.php/webdav/</d:href></d:response>
<d:response><d:href>/public.php/webdav/2026-05/</d:href></d:response>
<d:response><d:href>/public.php/webdav/2026-10/</d:href></d:response>
<d:response><d:href>/public.php/webdav/2026-09/</d:href></d:response>
<d:response><d:href>/public.php/webdav/cnpj.tar.gz</d:href></d:response>
</d:multistatus>"""


def test_mes_mais_recente_da_listagem_webdav():
    from tools.receita_mes import mes_mais_recente
    assert mes_mais_recente(_PROPFIND) == "2026-10"
    assert mes_mais_recente("<d:multistatus/>") is None


@pytest.mark.parametrize("baixado,anterior,receita,ok", [
    ("2026-05", "2026-05", "2026-10", False),  # o congelamento medido: re-baixou maio
    ("2026-10", "2026-05", "2026-10", True),   # andou para o mais recente
    ("2026-10", "2026-10", "2026-10", True),   # re-execução do mesmo mês, nada mais novo
    ("2026-09", "2026-05", "2026-10", True),   # mês forçado, mas diferente do carregado
    ("2026-05", "2026-05", None, True),        # listagem indisponível: não afirma congelamento
])
def test_decisao_de_congelamento(baixado, anterior, receita, ok):
    from tools.receita_mes import decidir_validacao_mes
    r_ok, motivo = decidir_validacao_mes(baixado, anterior, receita)
    assert r_ok is ok
    assert baixado in motivo
    if receita is None:
        assert "INDISPONIVEL" in motivo


# ───────────────────────────── 5. migração das linhas antigas ──────────────────────────────────

def _base_migracao():
    con = sqlite3.connect(":memory:")
    criar_schema(con)
    from tools import socios_dump_sweep as sds
    from tools import socios_reverso_build as srb
    con.execute(sds._DDL)
    con.execute(srb._DDL)
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, valor REAL)")
    pj14, pj8, pf = "22222222000155", "22222222", "***123456**"
    for mes in ("2026-06", "2026-07"):
        registrar_snapshot(con, mes, [
            {"cnpj_basico": "11111111", "doc_socio": pj14, "nome_socio": "HOLDING", "ident": "1"},
            {"cnpj_basico": "11111111", "doc_socio": pf, "nome_socio": "MARIA", "ident": "2"},
        ], origem="t")
    # registrar_snapshot já normaliza: reintroduz o legado (14 dígitos) à mão, como está na base
    con.execute("UPDATE socio_snapshot SET doc_socio=? WHERE doc_socio=?", (pj14, pj8))
    # colisão: num mês a linha de 8 dígitos já existe ao lado da de 14
    con.execute("INSERT INTO socio_snapshot (fonte_mes,cnpj_basico,doc_socio,nome_norm,ident) "
                "VALUES ('2026-07','11111111',?,'HOLDING','1')", (pj8,))
    for c, d, i in (("11111111", pj14, "1"), ("44444444", pj14, "1"), ("11111111", pf, "2")):
        con.execute("INSERT INTO socios_receita (cnpj_basico,ident,nome_socio,nome_norm,doc_socio,"
                    "qualificacao_cod,fonte_mes) VALUES (?,?,'HOLDING','HOLDING',?,'22','2026-05')",
                    (c, i, d))
    con.execute("INSERT INTO socios_reverso VALUES (?,'HOLDING','HOLDING','11111111','22','2026-05')",
                (pj14,))
    con.execute("INSERT INTO socios_reverso VALUES (?,'MARIA','MARIA','11111111','49','2026-05')", (pf,))
    con.commit()
    diff_snapshots(con)
    return con


def test_migracao_dry_run_so_conta(tmp_path):
    from tools.migrar_socio_pj_raiz import contar
    con = _base_migracao()
    antes = con.execute("SELECT COUNT(*) FROM socio_snapshot").fetchone()[0]
    n = contar(con)
    assert n["socio_snapshot"] == 2 and n["socios_receita"] == 2 and n["socios_reverso"] == 1
    assert con.execute("SELECT COUNT(*) FROM socio_snapshot").fetchone()[0] == antes


def test_migracao_converte_trata_colisao_faz_backup_e_e_idempotente(tmp_path):
    from tools.migrar_socio_pj_raiz import contar, migrar, vinculos_por_mes
    con = _base_migracao()
    vinc_antes = vinculos_por_mes(con)
    bkp = tmp_path / "bkp.csv.gz"
    r = migrar(con, bkp)
    assert all(v == 0 for v in contar(con).values()), r
    assert vinculos_por_mes(con) == vinc_antes, "nenhum vínculo some nem nasce"
    assert r["socio_snapshot"]["apagadas_colisao"] == 1
    assert con.execute("SELECT COUNT(*) FROM socio_historico WHERE status='saiu'").fetchone()[0] == 0
    with gzip.open(bkp, "rt") as f:
        corpo = f.read()
    assert corpo.count("22222222000155") >= 5, "backup traz as linhas de 14 dígitos de cada tabela"
    r2 = migrar(con, tmp_path / "bkp2.csv.gz")
    assert all(t["atualizadas"] == 0 and t["apagadas_colisao"] == 0
               for k, t in r2.items() if isinstance(t, dict) and "atualizadas" in t)


def test_serie_faltantes_so_para_a_frente_e_um_por_mes():
    from tools.socios_serie_historica import faltantes
    disp = ["2026-06-14", "2026-07-12", "2026-08-10", "2026-09-07", "2026-09-21", "2026-10-12"]
    assert faltantes(disp, ["2026-05", "2026-06", "2026-07"]) == ["2026-08-10", "2026-09-21",
                                                                  "2026-10-12"]
    assert faltantes(disp, ["2026-10"]) == []


def test_serie_recusa_ingerir_por_cima_do_legado_de_14_digitos(monkeypatch, tmp_path):
    from tools import socios_serie_historica as ssh
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    criar_schema(con)
    con.execute("INSERT INTO socio_snapshot (fonte_mes,cnpj_basico,doc_socio,nome_norm,ident) "
                "VALUES ('2026-07','11111111','22222222000155','HOLDING','1')")
    con.commit(); con.close()
    monkeypatch.setattr(ssh, "_conectar", lambda: sqlite3.connect(db))
    monkeypatch.setattr(ssh, "ingerir_snapshot", lambda *a, **k: pytest.fail("não podia ingerir"))
    assert ssh.main(["--mes", "2026-08-10"]) == 1
