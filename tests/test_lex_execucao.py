

def test_contestado_revisto_sem_documento_sai_da_fila(tmp_path, monkeypatch):
    # 14/11/2026: contestado pelo SIAFE sem documento de execução voltava ao topo a cada rodada (~53 processos)
    import sqlite3 as _sq
    import tools.lex_execucao as L
    monkeypatch.setattr(L, "_REVISTOS_SEM_DOC", tmp_path / "rev.json")
    monkeypatch.setattr(L, "mapa_obs_siafe", lambda con, ns: {L._chave_processo(n): {"total": 1.0} for n in ns})
    con = _sq.connect(":memory:")
    con.execute("CREATE TABLE lex_execucao (numero_sei TEXT, indicios TEXT, resumo TEXT, nota_risco REAL, em TEXT)")
    con.execute("INSERT INTO lex_execucao VALUES ('SEI-300000/000001/2024','ausência de ordem bancária','',5,'2026-10-01T10:00')")
    assert L._contestados_por_siafe(con) == ["SEI-300000/000001/2024"]
    L._marcar_revisto_sem_doc("SEI-300000/000001/2024")
    assert L._contestados_por_siafe(con) == []
