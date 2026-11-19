# -*- coding: utf-8 -*-
"""cpf_corpus (dados abertos do TSE) + união das fontes em resolver_multi: anti-homônimo e nada de CPF em log."""
import sqlite3

from compliance_agent import cpf_corpus as cc
from compliance_agent.resolucao_cpf import _dv_cpf, confirmar_cpf, resolver_multi


def _cpf(base9: str) -> str:
    return base9 + _dv_cpf(base9)


A = _cpf("123456789")       # middle6 = 456789
B = _cpf("987456789")       # mesmo middle6, outra pessoa


def test_cpf_valido_rejeita_dv_errado_mascara_e_repetido():
    assert cc.cpf_valido(A) == A
    assert cc.cpf_valido(A[:9] + ("00" if A[9:] != "00" else "11")) == ""
    assert cc.cpf_valido("***456789**") == ""
    assert cc.cpf_valido("XX456789XXX") == ""
    assert cc.cpf_valido("11111111111") == ""
    assert cc.cpf_valido("-4") == ""


def test_pares_layout_2022_e_2016_preferem_nome_da_receita():
    l22 = [{"NR_CPF_CNPJ_DOADOR": A, "NM_DOADOR": "JOAO DA SLIVA", "NM_DOADOR_RFB": "JOÃO DA SILVA",
            "NR_CPF_CANDIDATO": B, "NM_CANDIDATO": "MARIA SOUZA LIMA"}]
    got = set(cc.pares_de_linhas(l22))
    assert (A, "JOAO DA SILVA", "doador") in got and (B, "MARIA SOUZA LIMA", "candidato") in got
    l16 = [{"CPF/CNPJ do fornecedor": A, "Nome do fornecedor": "X", "Nome do fornecedor (Receita Federal)": "JOAO DA SILVA"}]
    assert list(cc.pares_de_linhas(l16)) == [(A, "JOAO DA SILVA", "fornecedor")]
    # CNPJ e #NULO não entram
    assert list(cc.pares_de_linhas([{"NR_CPF_CNPJ_DOADOR": "12345678000199", "NM_DOADOR": "EMPRESA LTDA"}])) == []


def test_ponte_titulo_exige_mesmo_titulo_e_mesmo_nome():
    tit: dict = {}
    cc.indexar_titulos([{"NR_TITULO_ELEITORAL_CANDIDATO": "012345678901", "NR_CPF_CANDIDATO": A,
                         "NM_CANDIDATO": "JOAO DA SILVA"}], tit)
    ok = list(cc.ponte_titulo([{"NR_TITULO_ELEITORAL_CANDIDATO": "012345678901", "NM_CANDIDATO": "JOAO DA SILVA"}], tit))
    assert ok == [(A, "JOAO DA SILVA", "candidato_por_titulo")]
    # mesmo título, nome diferente → não liga
    assert list(cc.ponte_titulo([{"NR_TITULO_ELEITORAL_CANDIDATO": "012345678901", "NM_CANDIDATO": "PEDRO ALVES"}], tit)) == []
    # título com dois CPFs conhecidos (erro de base) → não liga
    cc.indexar_titulos([{"NR_TITULO_ELEITORAL_CANDIDATO": "012345678901", "NR_CPF_CANDIDATO": B,
                         "NM_CANDIDATO": "JOAO DA SILVA"}], tit)
    assert list(cc.ponte_titulo([{"NR_TITULO_ELEITORAL_CANDIDATO": "012345678901", "NM_CANDIDATO": "JOAO DA SILVA"}], tit)) == []


def test_gravar_e_indice(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    assert cc.gravar(con, [(A, "JOAO DA SILVA", "candidato")], "tse_candidatos", 2020) == 1
    assert cc.gravar(con, [(A, "JOAO DA SILVA", "candidato")], "tse_candidatos", 2020) == 0   # idempotente
    con.close()
    idx = cc.carregar_indice(db)
    assert idx[("JOAO DA SILVA", "456789")] == {A}
    m = cc.medir(sqlite3.connect(db))
    assert m["pares"] == 1 and A not in str(m)          # medição nunca expõe CPF


def test_resolver_multi_corpus_resolve_e_mascara_que_nao_bate_rejeita():
    idx = {("JOAO DA SILVA", "456789"): {A}}
    r = resolver_multi("João da Silva", "***456789**", pf_idx={}, tse_idx={}, sei_idx={}, corpus_idx=idx)
    assert r["resolvido"] and r["cpf"] == A and r["fonte"] == "tse_dados_abertos"
    # máscara do QSA com outros 6 dígitos: o corpus não responde por ela
    r2 = resolver_multi("João da Silva", "***456780**", pf_idx={}, corpus_idx=idx)
    assert not r2["resolvido"]
    assert not confirmar_cpf("João da Silva", A, "***456780**")["confirmado"]


def test_resolver_multi_fontes_divergentes_sao_homonimos_e_nao_resolvem():
    pf = {("JOAO DA SILVA", "456789"): {A}}
    corpus = {("JOAO DA SILVA", "456789"): {B}}
    r = resolver_multi("JOAO DA SILVA", "***456789**", pf_idx=pf, corpus_idx=corpus)
    assert not r["resolvido"] and "ambíguo" in r["motivo"] and r["cpf"] == ""
    # concordando, confirma e lista as duas fontes
    r2 = resolver_multi("JOAO DA SILVA", "***456789**", pf_idx=pf, corpus_idx=pf)
    assert r2["resolvido"] and r2["fontes"] == ["favorecidos_pf", "tse_dados_abertos"]


def test_sem_cpf_mascara_qualquer_cpf_no_texto():
    t = cc.sem_cpf(f"consulta {A} e {A[:3]}.{A[3:6]}.{A[6:9]}-{A[9:]} ok")
    assert A not in t and "***.456.789-**" in t


def test_confirmar_humano_rejeita_mascara_que_nao_bate_e_registro_nao_tem_cpf(tmp_path, monkeypatch):
    import tools.desmascarar_cpf_externo as de
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT, "
                "socio_doc TEXT, qualificacao TEXT, cpf_resolvido TEXT, cpf_fonte TEXT, cpf_confianca REAL, "
                "cpf_resolvido_em TEXT, cpf_pos3a9 TEXT)")
    con.execute("INSERT INTO socios_fornecedor (cnpj, socio_nome, socio_nome_norm, socio_doc) VALUES "
                "('12345678000199','JOAO DA SILVA','JOAO DA SILVA','***456789**')")
    con.commit()
    con.close()
    monkeypatch.setattr(de, "_DB", db)
    homonimo = _cpf("123456780")                     # middle6 456780 ≠ máscara 456789
    r = de.confirmar_humano("12345678000199", "João da Silva", homonimo, "tjrj_humano")
    assert not r["gravado"] and "HOMÔNIMO" in r["motivo"]
    r = de.confirmar_humano("12345678000199", "João da Silva", A, "tjrj_humano")
    assert r["gravado"] and A not in str(r)
    con = sqlite3.connect(db)
    assert con.execute("SELECT cpf_resolvido FROM socios_fornecedor").fetchone()[0] == A
    reg = con.execute("SELECT * FROM cpf_consulta_externa").fetchall()
    assert [x[4] for x in reg] == ["REJEITADO", "CONFIRMADO"]
    assert A not in str(reg) and homonimo not in str(reg)


def test_executar_recusa_sem_fonte_autorizada(monkeypatch, capsys):
    import tools.desmascarar_cpf_externo as de
    assert de.FONTES_AUTORIZADAS == {}
    monkeypatch.setattr("sys.argv", ["x", "--executar", "--nome", "JOAO DA SILVA", "--doc", "***456789**"])
    assert de.main() == 3
    assert "RECUSADO" in capsys.readouterr().out


def test_log_da_camada_externa_nunca_tem_cpf():
    from compliance_agent import cpf_externo as ce

    class Prov:
        nome = "fake"

        def nome_por_cpf(self, cpf):
            return {"ok": True, "nome": "JOAO DA SILVA" if cpf == A else "OUTRO NOME", "motivo": ""}

        def cpfs_por_nome(self, nome):
            return {"ok": True, "cpfs": [B, A], "motivo": ""}
    linhas: list[str] = []
    r = ce.desmascarar_nome_cpf("JOAO DA SILVA", "***456789**", Prov(), log=linhas.append)
    assert r.resolvido is False and "ambíguo" in r.motivo   # A e B batem nome + 6 do meio: homônimos
    ce.desmascarar_cpf_nome("JOAO DA SILVA", "***456789**", Prov(), max_consultas=5, pausa=0, log=linhas.append)
    txt = "\n".join(linhas)
    assert A not in txt and B not in txt and "***.456.789-**" in txt


def test_regua_cpf_completo_do_socio_e_camada_mas_nao_verifica_servidor_sem_cpf():
    from compliance_agent import identidade_pessoa as ip
    r = ip.classificar(doc_qsa="***456789**", cpf_folha="", fonte_folha="tjrj_anexo8", n_folha_nome=1,
                       n_qsa_nome=1, cpf_resolvido=A)
    assert r["selo"] == ip.INDETERMINADO and "falta só o CPF do servidor" in r["falta"]
    assert any(c["camada"] == "cpf_completo_socio" for c in r["camadas"])
    assert A not in str(r)
    # CPF "resolvido" que não bate a máscara do QSA não vira camada
    r2 = ip.classificar(doc_qsa="***456780**", cpf_folha="", fonte_folha="tjrj_anexo8", n_folha_nome=1,
                        n_qsa_nome=1, cpf_resolvido=A)
    assert not any(c["camada"] == "cpf_completo_socio" for c in r2["camadas"])


def test_importar_corpus_de_outra_maquina_e_idempotente(tmp_path):
    from tools.tse_cpf_corpus import importar
    ext = tmp_path / "ext.db"
    c1 = sqlite3.connect(ext)
    cc.gravar(c1, [(A, "JOAO DA SILVA", "candidato")], "tse_candidatos", 2020)
    c1.close()
    dst = sqlite3.connect(tmp_path / "dst.db")
    assert importar(dst, str(ext)) == 1
    assert importar(dst, str(ext)) == 0


def test_pares_siafe_so_cpf_valido_de_credor_pf():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, nome_credor TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?)",
                    [(A, "João da Silva"), ("12345678901", "DV ERRADO SILVA"), ("12345678000199", "EMPRESA LTDA")])
    got = list(cc.pares_siafe(con))
    assert got == [(A, "JOAO DA SILVA", "credor_ob")] or (cc.cpf_valido("12345678901") and len(got) == 2)
