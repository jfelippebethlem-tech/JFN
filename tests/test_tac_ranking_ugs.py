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


def _base(tmp_path, linhas, com_obs=True, pagas=None):
    """linhas: (ug, nome, valor, observacao). Valor e status vão para o SIAFE (`ob_orcamentaria_siafe`, a fonte de
    pagamento); o espelho (`ordens_bancarias`) guarda só o texto da observação e o nome da UG, casado por número+UG.
    `pagas`: lista de status por linha (padrão 'Contabilizado')."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT,"
                " status TEXT, valor REAL, credor TEXT)")
    col = ", observacao TEXT" if com_obs else ""
    con.execute(f"CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, ug_nome TEXT,"
                f" data_emissao TEXT, valor REAL{col})")
    for i, (ug, nome, valor, obs) in enumerate(linhas):
        num = f"2025OB{i:05d}"
        st = (pagas or [])[i] if pagas and i < len(pagas) else "Contabilizado"
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)",
                    (num, ug, "10/06/2025", st, valor, "00000000000191"))
        v = (num, ug, nome, "2025-06-10", 0.0) + ((obs,) if com_obs else ())
        con.execute(f"INSERT INTO ordens_bancarias VALUES (?,?,?,?,?{',?' if com_obs else ''})", v)
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


def test_valor_vem_do_siafe_e_ob_nao_paga_fica_fora(tmp_path):
    """OB = SIAFE pela régua `_ob_paga`: a anulada não entra no total nem no TAC; o valor do espelho (0,00 aqui) nunca
    é somado."""
    linhas = [("294200", "FSERJ", 300.0, "TERMO DE AJUSTE DE CONTAS"),
              ("294200", "FSERJ", 500.0, "INDENIZACAO"),
              ("294200", "FSERJ", 700.0, "PAGAMENTO CONTRATO 12/2024")]
    r = T.medir(_base(tmp_path, linhas, pagas=["Contabilizado", "Anulado", "Contabilizado"]), min_valor=0)
    u = r["unidades"][0]
    assert (u["n"], u["total"], u["n_tac"], u["total_tac"]) == (2, 1000.0, 1, 300.0)
    assert r["fonte_valor"].startswith("SIAFE")


def test_ob_do_siafe_sem_par_no_espelho_conta_como_sem_observacao(tmp_path):
    p = _base(tmp_path, [("294200", "FSERJ", 400_000_000.0, "INDENIZACAO")])
    con = sqlite3.connect(p)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES "
                "('2025OB99999','294200','11/06/2025','Contabilizado',100.0,'00000000000191')")
    con.commit(); con.close()
    u = T.medir(p, min_valor=0)["unidades"][0]
    assert u["n"] == 2 and u["cobertura"] == "verificado (1/2 OBs com observação)"


def test_ug_que_o_siafe_nunca_leu_e_dita_e_nao_vira_zero(tmp_path):
    p = _base(tmp_path, [("294200", "FSERJ", 400_000_000.0, "CONTRATO")])
    con = sqlite3.connect(p)
    con.execute("INSERT INTO ordens_bancarias VALUES ('2025OB00001','310100','TRANSPORTES','2025-01-02',9e9,'X')")
    con.commit(); con.close()
    r = T.medir(p, min_valor=0)
    assert [u["ug"] for u in r["unidades"]] == ["294200"] and r["ugs_fora_do_siafe"] == ["310100"]


def test_repasse_entre_unidades_e_folha_nao_diluem_a_taxa(tmp_path):
    """O SIAFE traz repasse entre UGs (credor = UG, 6 dígitos) e folha (código 'CG…'); o espelho não. Somá-los
    diluía a taxa de TAC (universo R$ 135 bi → R$ 421 bi em 20/11/2026)."""
    p = _base(tmp_path, [("296100", "FES", 100.0, "INDENIZACAO"), ("296100", "FES", 100.0, "CONTRATO")])
    con = sqlite3.connect(p)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB90001','296100','01/07/2025','Contabilizado',"
                "15000.0,'294200')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB90002','296100','01/07/2025','Contabilizado',"
                "9000.0,'CG0004700')")
    con.commit(); con.close()
    u = T.medir(p, min_valor=0)["unidades"][0]
    assert (u["n"], u["total"], u["pct"]) == (2, 200.0, 50.0)
