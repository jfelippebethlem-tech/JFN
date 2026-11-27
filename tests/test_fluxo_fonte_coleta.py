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
