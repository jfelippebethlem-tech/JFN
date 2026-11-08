# -*- coding: utf-8 -*-
"""O parecer de um processo não pode sobrescrever o anterior em silêncio: o que entrou e o que saiu fica."""
import json
import sqlite3

from compliance_agent import processo_360 as P


def _out(achados, grau="medio", score=50.0):
    return {"status": "OK", "numero_sei": "SEI-1/2/2025", "score": score, "score100": score,
            "grau": {"grau": grau}, "faixa": "x", "achados": achados, "lacunas_processo": [],
            "lacunas_captura": [], "docs_chave": [], "acatamento": {}, "escalada": {}, "cobertura": {}}


def test_historico_guarda_so_mudanca_e_o_que_entrou_e_saiu(tmp_path):
    con = sqlite3.connect(tmp_path / "c.db")
    a1 = {"codigo": "A1_CONTRATO_ANTES_DO_PARECER", "evidencia": "Contrato 1"}
    a2 = {"codigo": "X_PAGAMENTO_SEM_ATESTACAO", "evidencia": "NL 9"}
    assert P.gravar(_out([a1]), con)
    assert P.gravar(_out([a1]), con)                       # rodada sem mudança: não vira linha
    assert P.gravar(_out([a2], grau="alto", score=80.0), con)
    rows = con.execute("select entraram_json, sairam_json, grau_antes, score100_antes "
                       "from processo_avaliacao_hist order by rowid").fetchall()
    assert len(rows) == 2
    assert json.loads(rows[0][0]) == ["A1_CONTRATO_ANTES_DO_PARECER|Contrato 1"] and rows[0][2] is None
    assert json.loads(rows[1][0]) == ["X_PAGAMENTO_SEM_ATESTACAO|NL 9"]
    assert json.loads(rows[1][1]) == ["A1_CONTRATO_ANTES_DO_PARECER|Contrato 1"]
    assert rows[1][2:] == ("medio", 50.0)


def test_mesmo_codigo_em_peca_diferente_e_outro_achado():
    e, s = P.diff_achados([{"codigo": "C9", "evidencia": "doc 1"}], [{"codigo": "C9", "evidencia": "doc 2"}])
    assert e == ["C9|doc 2"] and s == ["C9|doc 1"]
