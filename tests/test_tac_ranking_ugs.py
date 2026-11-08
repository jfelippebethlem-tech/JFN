# -*- coding: utf-8 -*-
"""Um percentual sozinho não sustenta afirmação nenhuma — a régua é COMPARATIVA.

`detector_tac.tac_por_ug` sempre respondeu por UMA unidade, dentro do `/orgao`: dava para saber
que a Fundação Saúde paga 27% do que movimenta por TAC/indenização, e não dava para saber se 27%
é muito. Medido em 2026-08-04, comparando as 56 unidades acima de R$ 300 mi:

    mediana ............................................  0,3%
    294200 FUNDAÇÃO SAÚDE .............................. 27,0%  (R$ 2,81 bi de R$ 10,41 bi)
    310100 Secretaria de Transportes ...................  15,8%
    296100 FUNDO ESTADUAL DA SAÚDE (3× maior) ..........   2,8%

Noventa vezes a mediana — e não é "a saúde sendo assim": a outra unidade de saúde, três vezes
maior, paga 2,8%. É a prevalência que decide o eixo.

A definição de TAC NÃO é reescrita aqui: usa-se a regex canônica de `detector_tac`, sob pena de
duas definições divergirem em silêncio.
"""
import sqlite3

from tools import tac_ranking_ugs as T


def _base(tmp_path, linhas, com_obs=True):
    """linhas: (ug, nome, valor, observacao)."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    col = ", observacao TEXT" if com_obs else ""
    con.execute(f"CREATE TABLE ordens_bancarias (ug_codigo TEXT, ug_nome TEXT, valor REAL{col})")
    for ln in linhas:
        con.execute(f"INSERT INTO ordens_bancarias VALUES (?,?,?{',?' if com_obs else ''})",
                    ln if com_obs else ln[:3])
    con.commit(); con.close()
    return p


def test_a_regex_canonica_reconhece_as_tres_formas(tmp_path):
    linhas = [("294200", "FSERJ", 100.0, "TERMO DE AJUSTE DE CONTAS 1/2024"),
              ("294200", "FSERJ", 100.0, "INDENIZACAO POR SERVICO PRESTADO"),
              ("294200", "FSERJ", 100.0, "RECONHECIMENTO DE DIVIDA 2023"),
              ("294200", "FSERJ", 700.0, "PAGAMENTO CONTRATO 12/2024")]
    r = T.medir(_base(tmp_path, linhas), min_valor=0)
    u = r["unidades"][0]
    assert u["n_tac"] == 3 and u["total_tac"] == 300.0 and u["pct"] == 30.0


def test_unidade_pequena_nao_lidera_o_ranking(tmp_path):
    """Uma unidade que pagou R$ 2 mi, sendo R$ 1 mi por TAC, "lidera" com 50% e não diz nada."""
    linhas = [("999999", "Miúda", 1_000.0, "INDENIZACAO"),
              ("294200", "FSERJ", 1_000_000_000.0, "CONTRATO")]
    r = T.medir(_base(tmp_path, linhas), min_valor=300_000_000.0)
    assert [u["ug"] for u in r["unidades"]] == ["294200"]


def test_sem_observacao_e_INDISPONIVEL_nunca_zero_por_cento(tmp_path):
    """Unidade sem o campo em que o marcador vive não "paga 0% por TAC" — ela não foi medida."""
    linhas = [("294200", "FSERJ", 400_000_000.0, None)]
    r = T.medir(_base(tmp_path, linhas), min_valor=0)
    assert r["unidades"][0]["cobertura"].startswith("INDISPONIVEL")


def test_coluna_observacao_ausente_declara_o_limite(tmp_path):
    linhas = [("294200", "FSERJ", 400_000_000.0, None)]
    r = T.medir(_base(tmp_path, linhas, com_obs=False), min_valor=0)
    assert r["indisponivel"] is True and "observacao" in r["motivo"]


def test_base_ausente_nao_levanta(tmp_path):
    assert T.medir(tmp_path / "nao_existe.db")["indisponivel"] is True


def test_mediana_entra_no_resultado(tmp_path):
    """Sem a mediana o número da unidade não tem contra o que ser lido."""
    linhas = [("A", "a", 400_000_000.0, "INDENIZACAO"),
              ("B", "b", 400_000_000.0, "CONTRATO"),
              ("C", "c", 400_000_000.0, "CONTRATO")]
    r = T.medir(_base(tmp_path, linhas), min_valor=0)
    assert r["mediana_pct"] == 0.0 and r["unidades"][0]["pct"] == 100.0
