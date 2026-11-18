"""Laudo conferido carrega o TEXTO do Opus, mesmo quando o nível coincide (18/11/2026: SEI-260005/011066/2025 —
nível alto nos dois, mas o fundamento do outro modelo era 'falta de fotos' e o do Opus a desproporção de R$ 16,4 mi
num mês contra ~R$ 3,8 mi/mês do contrato; o aplicador marcava VERIFICADO mantendo o fundamento não endossado)."""
import json
import sqlite3

import tools.lex_execucao as L


def _con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE lex_execucao (numero_sei TEXT, objeto TEXT, tem_prestacao_contas INT, tem_fiscalizacao INT, "
              "tem_relatorio_fotografico INT, tem_atesto_recebimento INT, tem_nota_fiscal INT, tem_medicao INT, "
              "execucao_comprovada TEXT, coerencia TEXT, nota_risco INT, indicios TEXT, duvidas TEXT, resumo TEXT, "
              "modelo TEXT, em TEXT)")
    c.execute("INSERT INTO lex_execucao (numero_sei, execucao_comprovada, nota_risco, indicios, resumo, modelo) "
              "VALUES ('SEI-1/1/2025','parcial',8,'[\"falta de fotos\"]','sem fotos','gemini:x')")
    return c


def test_concordancia_de_nivel_guarda_o_texto_do_opus():
    c = _con()
    resp = json.dumps({"execucao_comprovada": "parcial", "nota_risco_execucao": 7,
                       "indicios": ["pago no mês 4,3× o mensal"], "resumo": "desproporção material"})
    assert L.aplicar_conferencia("sei:SEI-1/1/2025", resp, "claude-opus", 1, con=c)
    ex, nota, ind, res, mod = c.execute("SELECT execucao_comprovada, nota_risco, indicios, resumo, modelo "
                                        "FROM lex_execucao").fetchone()
    assert nota == 7 and "4,3×" in ind and res == "desproporção material"
    assert "claude" in mod and "concordou" in mod
