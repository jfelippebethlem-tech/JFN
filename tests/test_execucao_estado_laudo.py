"""Laudo de execução com proveniência e estado (regra 9) — 18/11/2026: 92% dos 7.919 laudos eram de outro modelo
sem conferência do Claude, e o relatório de fornecedor os mostrava sem dizer; o Opus rebaixou 91% dos 'risco alto'."""
from compliance_agent.correlacao_sei import estado_do_laudo


def test_estado_do_laudo():
    assert estado_do_laudo("claude:claude-sonnet-5-5 (+gemini:x)")[0] == "VERIFICADO"
    assert estado_do_laudo("gemini · conferido claude:claude-opus-5-5")[0] == "VERIFICADO"
    assert estado_do_laudo("regra:sem_doc_execucao")[0] == "REGRA"
    e, txt = estado_do_laudo("gemini:gemini-3-flash-preview")
    assert e == "PENDENTE" and "gemini" in txt and "Opus" in txt
    assert estado_do_laudo(None)[0] == "PENDENTE" and estado_do_laudo("desconhecido")[0] == "PENDENTE"


def test_execucao_de_fornecedor_le_o_pago_do_siafe_e_casa_o_processo(tmp_path, monkeypatch):
    """Regra 'OB = SIAFE' (não o espelho TFE): pago por processo vem de ob_orcamentaria_siafe, sem a devolvida; o
    processo 'SEI-330002/031566/24' do SIAFE casa com o laudo '330002/031566/2024'."""
    import sqlite3
    from compliance_agent import correlacao_sei as C
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, credor TEXT, processo TEXT, valor REAL, "
                "status TEXT, status_envio TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)", [
        ("1", "12345678000199", "SEI-330002/031566/24", 100.0, "Contabilizado", None),
        ("2", "12345678000199", "sei-330002/31566/2024", 50.0, "Contabilizado", None),
        ("3", "12345678000199", "SEI-330002/031566/24", 999.0, "Contabilizado", "Erro no Pagamento"),
        ("4", "12345678000199", "SEI-111111/000001/2025", 10.0, "Cancelado", None)])
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, numero_sei TEXT, valor REAL)")
    con.execute("INSERT INTO ordens_bancarias VALUES ('12345678000199', '999999/000009/2020', 5000.0)")  # só no TFE
    con.execute("CREATE TABLE lex_execucao (numero_sei TEXT, execucao_comprovada TEXT, nota_risco INT, resumo TEXT, "
                "indicios TEXT, em TEXT, modelo TEXT)")
    con.execute("INSERT INTO lex_execucao VALUES ('330002/031566/2024','nao',7,'sem atesto','','2026-11-01','gemini')")
    con.commit()
    monkeypatch.setattr(C, "_DB", db)
    r = C.execucao_de_fornecedor("12.345.678/0001-99")
    assert len(r) == 1
    assert r[0]["total"] == 150.0 and r[0]["n_obs"] == 2 and r[0]["exec"] == "nao" and r[0]["estado"] == "PENDENTE"
