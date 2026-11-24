# -*- coding: utf-8 -*-
"""O4.12 — analítico em Parquet + DuckDB (tools/analitico_parquet): exportação conferida, paridade SQLite × DuckDB,
régua OB paga idêntica, data ISO, guarda da VM-1 e do disco, envelope pequeno com md5 (E10 → E15).

Fixtures sintéticas pequenas. Sem duckdb (ou sem a extensão sqlite dele) no venv → pula."""
import hashlib
import json
import sqlite3

import pytest

duckdb = pytest.importorskip("duckdb")

from tools import analitico_parquet as ap  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _extensao_sqlite():
    try:
        c = duckdb.connect()
        c.execute("INSTALL sqlite; LOAD sqlite;")
        c.close()
    except duckdb.Error as e:
        pytest.skip(f"extensão sqlite do DuckDB indisponível: {e}")


PJ_A, PJ_B, PJ_C = "11222333000181", "22333444000150", "33444555000120"
PF = "12345678900"                     # 11 dígitos, DV inválido de propósito (fixture)


def _fonte(p):
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT,
        status_envio TEXT, tipo_regularizacao TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL,
        exercicio INTEGER, PRIMARY KEY (numero_ob, ug_emitente, exercicio));
    CREATE TABLE ob_reemitida (ob TEXT NOT NULL, ug TEXT NOT NULL, valor REAL, PRIMARY KEY (ob, ug)) WITHOUT ROWID;
    CREATE TABLE ordens_bancarias (id INTEGER PRIMARY KEY, numero_ob TEXT, data_emissao DATE, ug_codigo TEXT,
        favorecido_cpf TEXT, valor FLOAT, exercicio INTEGER, raw_json TEXT);
    CREATE TABLE ob_anomaly (ob_id INTEGER PRIMARY KEY, score REAL);
    CREATE TABLE ne_siafe (numero TEXT, ug_emitente TEXT, exercicio INTEGER, data_emissao TEXT, valor REAL);
    CREATE TABLE nl_siafe (numero TEXT, ug_emitente TEXT, exercicio INTEGER, data_emissao TEXT, valor REAL);
    CREATE TABLE penalidades_tcerj (id TEXT PRIMARY KEY, orgao TEXT, valor REAL);
    """)
    obs = []
    n = 0
    for ex in (2024, 2025):
        for ug in ("100100", "200200"):
            for i, cred in enumerate((PJ_A, PJ_B, PJ_C, PF, "CG0001", "44555666000190", "55666777000140")):
                n += 1
                obs.append((f"{ex}OB{n:05d}", ug, f"{(i % 28) + 1:02d}/{(n % 12) + 1:02d}/{ex}", "Contabilizado", "",
                            "", cred, f"Credor {i}", f"SEI-{ug}/{n:06d}/{ex}", 250000.0 * (i + 1) + 0.1, ex))
    obs += [("2025OB90001", "100100", "31/12/2025", "Anulado", "", "", PJ_A, "x", "SEI-1/2/2025", 9e9, 2025),
            ("2025OB90002", "100100", "2025-12-01", "Contabilizado", "", "", PJ_A, "x", "SEI-1/2/2025", 7.0, 2025),
            ("2025OB90003", "100100", "01/12/2025", "Contabilizado", "Erro no Pagamento", "", PJ_A, "x", "", 5e8, 2025),
            ("2025OB90004", "100100", "02/12/2025", "Contabilizado", "", "Pagamento Complementar", PJ_B, "x", "", 4e8,
             2025),
            ("2025OB90005", "200200", "03/12/2025", "Contabilizado", "", "", PJ_C, "x", "SEI-9/9/2025", 3e8, 2025),
            ("", "200200", "04/12/2025", "Contabilizado", "", "", PJ_C, "x", "", 2e8, 2025),
            ("2023OB00001", "200200", "05/05/2023", "Contabilizado", "", "", PJ_C, "x", "SEI-9/9/2023", 1.5, None)]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?)", obs)
    con.execute("INSERT INTO ob_reemitida VALUES ('2025OB90005', '200200', 3e8)")
    tfe = [(k, f"OB{k}", f"{2023 + k % 3}-0{1 + k % 9}-10", ("100100", "200200", "300300")[k % 3],
            (PJ_A, PJ_B, PF)[k % 3], 1000.5 * k, 2023 + k % 3, '{"grande": "' + "x" * 50 + '"}') for k in range(1, 61)]
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?,?,?,?)", tfe)
    con.executemany("INSERT INTO ob_anomaly VALUES (?,?)", [(k, (k % 10) / 10) for k in range(1, 61, 2)])
    con.executemany("INSERT INTO ne_siafe VALUES (?,?,?,?,?)", [("2025NE1", "100100", 2025, "10/01/2025", 1.0),
                                                                  ("2024NE1", "100100", 2024, "lixo", 2.0)])
    con.execute("INSERT INTO nl_siafe VALUES ('2025NL1', '100100', 2025, '11/01/2025', 1.0)")
    con.execute("INSERT INTO penalidades_tcerj VALUES ('p1', 'SECRETARIA X', 10.0)")
    con.commit()
    con.close()
    return p


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    d = tmp_path_factory.mktemp("analitico")
    fonte = _fonte(d / "compliance.db")
    man = ap.exportar(fonte, d / "parquet" / "snap", threads=1, memoria="512MB", estimativa_bytes=0)
    return fonte, d / "parquet" / "snap", man


def test_exportar_confere_linhas_sha_e_exclui_raw_json(base):
    fonte, pq, man = base
    sq = sqlite3.connect(fonte)
    for t, info in man["tabelas"].items():
        assert info["linhas_parquet"] == info["linhas_fonte"] == sq.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        assert all(len(a["sha256"]) == 64 for a in info["arquivos"])
    assert "raw_json" not in man["tabelas"]["ordens_bancarias"]["colunas"]
    assert man["tabelas"]["ordens_bancarias"]["excluidas"] == ["raw_json"]
    # particionado por exercício (inclusive a partição dos sem exercício), com a coluna dentro do arquivo
    dirs = {p.name for p in (pq / "ob_orcamentaria_siafe").iterdir()}
    assert {"exercicio=2024", "exercicio=2025"} <= dirs and len(dirs) == 3
    assert man["schema"]["alembic"]["head_no_codigo"]
    assert ap.conferir_manifesto(pq)["ok"]


def test_data_iso_igual_a_expr_iso_e_fora_do_formato_vira_null(base):
    _, pq, _ = base
    dk = ap.conectar_parquet(pq, threads=1, memoria="512MB")
    m = dict(dk.execute("SELECT numero_ob, data_emissao_iso FROM ob_orcamentaria_siafe "
                        "WHERE numero_ob IN ('2025OB90001', '2025OB90002')").fetchall())
    assert m == {"2025OB90001": "2025-12-31", "2025OB90002": None}      # 'AAAA-MM-DD' cru NÃO é DD/MM/AAAA → NULL
    assert dk.execute("SELECT data_emissao_iso FROM ne_siafe WHERE numero='2024NE1'").fetchone()[0] is None
    assert dk.execute("SELECT exercicio FROM ob_orcamentaria_siafe WHERE numero_ob='2023OB00001'").fetchone()[0] is None
    dk.close()


def test_paridade_das_10_consultas(base):
    fonte, pq, _ = base
    r = ap.paridade(fonte, pq, threads=1, memoria="512MB")
    assert len(r["consultas"]) == 10
    for nome, c in r["consultas"].items():
        assert c["veredito"] != "DIVERGE", (nome, c["exemplos"])
        assert c["linhas_sqlite"] > 0, nome
    # a régua canônica está no SQL: anulada, devolvida, complementar, reemitida e sem número ficam fora
    for termo in ("Contabilizado", "Erro no Pagamento", "Pagamento Complementar", "ob_reemitida", "numero_ob"):
        assert termo in r["regua_ob_paga"]


def test_regua_do_parquet_e_a_mesma_da_fonte(base):
    from compliance_agent.dominio.pagamento import ob_paga_sql
    fonte, pq, _ = base
    dk = ap.conectar_parquet(pq, threads=1, memoria="512MB")
    assert ap.regua_ob_paga_duck(dk) == ob_paga_sql(sqlite3.connect(fonte))
    dk.close()


def test_comparar_distingue_flutuante_de_divergencia():
    assert ap.comparar([("a", 1.0)], [("a", 1.0)])["veredito"] == "IGUAL"
    assert ap.comparar([("a", 0.1 + 0.2)], [("a", 0.3)])["veredito"] == "IGUAL_TOLERANCIA_FLUTUANTE"
    d = ap.comparar([("a", 1.0), ("b", 2.0)], [("a", 1.0), ("b", 2.5)])
    assert d["veredito"] == "DIVERGE" and d["divergentes"] == 1 and d["exemplos"]
    assert ap.comparar([("a",)], [("a",), ("b",)])["veredito"] == "DIVERGE"
    assert ap.comparar([(None, "x")], [(None, "x")])["veredito"] == "IGUAL"


def test_destino_existente_e_recusado(base, tmp_path):
    fonte, pq, _ = base
    with pytest.raises(SystemExit):
        ap.exportar(fonte, pq, estimativa_bytes=0)


def test_sha_adulterado_aparece_na_conferencia(base, tmp_path):
    import shutil
    _, pq, _ = base
    copia = tmp_path / "copia"
    shutil.copytree(pq, copia)
    alvo = next((copia / "ob_anomaly").glob("*.parquet"))
    alvo.write_bytes(alvo.read_bytes() + b"x")
    r = ap.conferir_manifesto(copia)
    assert not r["ok"] and r["divergentes"] == ["ob_anomaly/dados.parquet"]


def test_recusa_vm1_e_disco(tmp_path):
    with pytest.raises(SystemExit):
        ap.recusar_vm1("jfn-core")
    ap.recusar_vm1("JFN-Agent-2")
    with pytest.raises(SystemExit):
        ap.conferir_disco(tmp_path / "x" / "y", 0, limite=0.0)
    assert ap.conferir_disco(tmp_path, 0, limite=1.0)["uso_depois"] <= 1.0


def test_cli_recusa_duckdb_na_vm1(monkeypatch, tmp_path):
    monkeypatch.setenv("JFN_ANALITICO_HOST", "jfn-core")
    with pytest.raises(SystemExit):
        ap.main(["conferir", "--parquet", str(tmp_path)])


def test_materializar_e_aplicar_com_md5(base, tmp_path):
    _, pq, _ = base
    saida, painel = tmp_path / "saida", tmp_path / "painel"
    r = ap.materializar(pq, saida)
    assert set(r) == set(ap.VISOES)
    for v, info in r.items():
        b = (saida / f"{v}.json").read_bytes()
        assert hashlib.md5(b).hexdigest() == info["md5"] and len(b) < 200_000
        assert (saida / f"{v}.json.md5").read_text().split()[0] == info["md5"]
    env = json.loads((saida / "dependencia_fornecedores.json").read_text())
    docs = {d["top_doc"] for d in env["dados"]}
    assert PF not in docs and PJ_A in docs                       # CPF sai mascarado no envelope (LGPD)
    assert env["fonte"]["manifesto_sha256"] == ap.sha256_arquivo(pq / "manifesto.json")
    assert ap.aplicar(saida / "captura_orgaos.json", painel)["estado"] == "APLICADO"
    assert ap.aplicar(saida / "captura_orgaos.json", painel)["estado"] == "INALTERADO"
    instalado = (painel / "captura_orgaos.json").read_bytes()
    (saida / "captura_orgaos.json").write_bytes(b'{"adulterado": true}')
    assert ap.aplicar(saida / "captura_orgaos.json", painel)["estado"] == "RECUSADO"
    assert (painel / "captura_orgaos.json").read_bytes() == instalado     # recusado não toca o instalado
