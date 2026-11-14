

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


def test_gravar_insiste_quando_o_banco_esta_ocupado(monkeypatch):
    # 14/11/2026: "database is locked" na gravação descartava o parecer de LLM já gasto (38 ocorrências no log)
    import sqlite3 as _sq
    import pytest
    import tools.lex_execucao as L
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    chamadas = []

    def falha_duas(con, *a):
        chamadas.append(1)
        if len(chamadas) < 3:
            raise _sq.OperationalError("database is locked")
        return "ok"

    monkeypatch.setattr(L, "_gravar_uma_vez", falha_duas)
    con = _sq.connect(":memory:")
    assert L._gravar(con, "SEI-1", "", {}, {}, None, "m") == "ok" and len(chamadas) == 3

    def sempre(con, *a):
        raise _sq.OperationalError("database is locked")

    monkeypatch.setattr(L, "_gravar_uma_vez", sempre)
    with pytest.raises(_sq.OperationalError):
        L._gravar(con, "SEI-1", "", {}, {}, None, "m")

    def outro(con, *a):
        chamadas.append("x")
        raise _sq.OperationalError("no such table: lex_execucao")

    chamadas.clear()
    monkeypatch.setattr(L, "_gravar_uma_vez", outro)
    with pytest.raises(_sq.OperationalError):
        L._gravar(con, "SEI-1", "", {}, {}, None, "m")
    assert chamadas == ["x"]                      # erro que não é de ocupação não é repetido
