"""26/11/2026: fonte única da coleta para os estágios fora da VM-1 (E6/E9/E10/E11/E16 liam um snapshot que só existia
na VM-1 — «fonte SIAFE ausente» em toda conferência do E6 — e congelado em 24/11)."""
import sqlite3

from compliance_agent.fluxo import fonte_coleta as FC


def test_ordem_env_renovada_parada(tmp_path, monkeypatch):
    ren, par, env = tmp_path / "ren.db", tmp_path / "par.db", tmp_path / "env.db"
    monkeypatch.setattr(FC, "RENOVADA", ren)
    monkeypatch.setattr(FC, "PARADA", par)
    monkeypatch.delenv(FC.ENV, raising=False)
    assert FC.caminho() == ren and not FC.disponivel() and FC.capacidades() == {}     # nada: nomeia a preferida
    par.write_bytes(b"x")
    assert FC.caminho() == par and FC.capacidades() == {"fonte_coleta": FC.VAGAS}
    ren.write_bytes(b"x")
    assert FC.caminho() == ren                                     # renovada vence o snapshot congelado
    env.write_bytes(b"x")
    monkeypatch.setenv(FC.ENV, str(env))
    assert FC.caminho() == env


def test_distribuir_faz_copia_consistente_e_md5(tmp_path, monkeypatch):
    vivo = tmp_path / "vivo.db"
    c = sqlite3.connect(vivo)
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (42)")
    c.commit()
    c.close()
    monkeypatch.setattr(FC, "RENOVADA", tmp_path / "out" / "compliance.db")
    r = FC.distribuir(vivo, nos={})
    assert r["md5"] == FC._md5(FC.RENOVADA) and r["nos"] == {}
    assert sqlite3.connect(FC.RENOVADA).execute("SELECT x FROM t").fetchone() == (42,)


def test_estagios_que_leem_a_coleta_declaram_a_capacidade():
    """Quem lê a coleta dentro do job declara `fonte_coleta` — o nó sem o arquivo não reserva."""
    from compliance_agent.fluxo import grafo as G
    g = G.carregar()
    for ek in ("E6", "E9", "E10", "E11", "E16"):
        assert FC.CAPACIDADE in g.estagios[ek].recursos, ek


def test_vm1_e_produtora_nao_anuncia(tmp_path, monkeypatch):
    """A VM-1 tem o compliance.db VIVO e gera a cópia; não guarda a cópia (disco 86%) e não anuncia: nenhum estágio
    nativo na VM-1 lê o retrato velho da parada."""
    par = tmp_path / "par.db"
    par.write_bytes(b"x")
    monkeypatch.setattr(FC, "PARADA", par)
    monkeypatch.setattr(FC, "RENOVADA", tmp_path / "ren.db")
    monkeypatch.delenv(FC.ENV, raising=False)
    assert FC.capacidades("vm1") == {} and FC.capacidades("vm2") == {"fonte_coleta": FC.VAGAS}


def test_renovada_velha_nao_e_anunciada(tmp_path, monkeypatch):
    """Cópia renovada com mais de 48 h: o nó deixa de anunciar (o planejador mostra BLOQUEADO) — nunca lê velho calado."""
    import os
    import time
    ren = tmp_path / "ren.db"
    ren.write_bytes(b"x")
    monkeypatch.setattr(FC, "RENOVADA", ren)
    monkeypatch.setattr(FC, "PARADA", tmp_path / "par.db")
    monkeypatch.delenv(FC.ENV, raising=False)
    assert FC.capacidades("vm2") == {"fonte_coleta": FC.VAGAS}
    velho = time.time() - 49 * 3600
    os.utime(ren, (velho, velho))
    assert FC.capacidades("vm2") == {}


def test_publicar_gz_no_proprio_no(tmp_path, monkeypatch):
    """publicar(gz): o nó recebe o .gz, confere o md5, descompacta, quick_check e troca atômica."""
    import gzip
    import sqlite3
    db = tmp_path / "fonte.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (7)")
    c.commit()
    c.close()
    gz = tmp_path / "fonte.db.gz"
    gz.write_bytes(gzip.compress(db.read_bytes()))
    destino = tmp_path / "no" / "compliance.db"
    r = FC.instalar_gz(gz, FC._md5(gz), destino)
    assert r == "ok" and sqlite3.connect(destino).execute("SELECT x FROM t").fetchone() == (7,)
    assert FC.instalar_gz(gz, "0" * 32, destino).startswith("md5 divergente")
