# -*- coding: utf-8 -*-
"""Identidade de pessoa entre bases — homônimo desambiguado por OUTROS DADOS, nunca só pelo nome.

Controle POSITIVO: mesmo CPF parcial (na janela certa da fonte) + nome único → VERIFICADO.
Controles NEGATIVOS: CPF parcial incompatível → HOMÔNIMO; nome comum sem CPF → INDETERMINADO (não é
achado); faixa etária impossível → HOMÔNIMO; fonte sem janela aferida → nunca compara.

E o fim-a-fim de `socio_na_folha` numa base sintética: o sócio do Executivo (GESPERJ, janela 4–9) que a
régua antiga (3–8 para toda folha) descartava como homônimo agora é VERIFICADO; o do TJRJ (sem CPF)
fica indeterminado; a empresa paga pelo próprio órgão do vínculo acende o art. 9º.

Nota sobre "município": a folha estadual não publica município de residência nem de lotação por
servidor (só o órgão), então o segundo dado convergente aqui é a prevalência do nome e o CPF de outra
fonte — declarado no módulo, não fingido.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import identidade_pessoa as ip


# ─────────────────── camada 1: CPF posicional ─────────────────────────────────────────────────

def test_janela_do_QSA_e_4_a_9():
    assert ip.posicoes_qsa("***364817**") == {4: "3", 5: "6", 6: "4", 7: "8", 8: "1", 9: "7"}


def test_janela_da_folha_depende_da_fonte():
    assert set(ip.posicoes_folha("XX364817XXX", "gesperj_estado")) == {4, 5, 6, 7, 8, 9}
    assert set(ip.posicoes_folha("XX036481XXX", "dprj_transparencia")) == {3, 4, 5, 6, 7, 8}


def test_DPRJ_publicou_4_a_9_em_jan_abr_2018():
    """Exceção medida: nos 4 meses a DPRJ usou a janela do QSA; antes e depois, 3–8."""
    assert set(ip.posicoes_folha("XX878107XXX", "dprj_transparencia", "2018-02")) == {4, 5, 6, 7, 8, 9}
    assert set(ip.posicoes_folha("XX287810XXX", "dprj_transparencia", "2018-05")) == {3, 4, 5, 6, 7, 8}
    q = ip.posicoes_qsa("***878107**")
    assert ip.comparar_cpf(q, ip.posicoes_folha("XX878107XXX", "dprj_transparencia", "2018-03"))[0] == ip.COMPATIVEL
    assert ip.comparar_cpf(q, ip.posicoes_folha("XX287810XXX", "dprj_transparencia", "2019-01"))[0] == ip.COMPATIVEL


def test_fonte_sem_janela_aferida_nao_vira_comparacao():
    """Presumir a janela é o erro que a casa cometeu três vezes."""
    assert ip.posicoes_folha("XX364817XXX", "tjrj_anexo8") == {}
    assert ip.posicoes_folha("XX364817XXX", "fonte_nova") == {}


def test_mesma_pessoa_casa_nas_duas_janelas():
    q = ip.posicoes_qsa("***364817**")
    assert ip.comparar_cpf(q, ip.posicoes_folha("XX364817XXX", "gesperj_estado")) == (ip.COMPATIVEL, 6)
    assert ip.comparar_cpf(q, ip.posicoes_folha("XX036481XXX", "dprj_transparencia")) == (ip.COMPATIVEL, 5)


def test_regressao_janela_errada_para_o_executivo():
    """A régua antiga lia GESPERJ como 3–8: a mesma pessoa virava homônimo."""
    q = ip.posicoes_qsa("***364817**")
    errado = {3 + k: ch for k, ch in enumerate("364817")}   # GESPERJ lido como 3–8
    assert ip.comparar_cpf(q, errado)[0] == ip.INCOMPATIVEL
    assert ip.comparar_cpf(q, ip.posicoes_folha("XX364817XXX", "gesperj_estado"))[0] == ip.COMPATIVEL


def test_mascara_nunca_expoe_digito_que_a_receita_nao_expoe():
    assert ip.mascarar("***364817**") == "***.364.817-**"
    assert ip.mascarar("") == "CPF não informado no QSA"


# ─────────────────── selo ─────────────────────────────────────────────────────────────────────

def _cl(**kw):
    base = dict(doc_qsa="***364817**", cpf_folha="XX364817XXX", fonte_folha="gesperj_estado",
                n_folha_nome=1, n_qsa_nome=1, faixa_etaria="5", vinculo="EFETIVO")
    base.update(kw)
    return ip.classificar(**base)


def test_controle_POSITIVO_cpf_compativel_e_nome_unico_e_verificado():
    r = _cl()
    assert r["selo"] == ip.VERIFICADO
    assert "6 dígitos" in r["motivo"] and "nome único" in r["motivo"]


def test_NEGATIVO_cpf_incompativel_e_homonimo():
    r = _cl(cpf_folha="XX999999XXX")
    assert r["selo"] == ip.HOMONIMO and "outra pessoa" in r["motivo"]


def test_NEGATIVO_nome_comum_sem_CPF_nao_vira_achado():
    """Folha do TJRJ não publica CPF: nem nome raro, nem comum — INDETERMINADO, dizendo o que falta."""
    for n in (1, 40):
        r = _cl(cpf_folha="", fonte_folha="tjrj_anexo8", n_folha_nome=n, n_qsa_nome=n)
        assert r["selo"] == ip.INDETERMINADO
        assert "TJRJ" in r["falta"]


def test_cpf_compativel_mas_nome_comum_e_so_provavel_com_a_chance_declarada():
    r = _cl(n_folha_nome=5, n_qsa_nome=2)
    assert r["selo"] == ip.PROVAVEL and "acaso" in r["motivo"]


def test_faixa_etaria_impossivel_descarta_mesmo_com_cpf_compativel():
    assert _cl(faixa_etaria="1")["selo"] == ip.HOMONIMO
    # pensionista criança existe: não descarta
    assert _cl(faixa_etaria="1", vinculo="PENSIONISTA")["selo"] == ip.VERIFICADO


def test_faixa_compativel_nao_conta_como_convergencia():
    """Acende em ~99% da base — mede a base, não a pessoa."""
    assert _cl(n_folha_nome=5, n_qsa_nome=2, faixa_etaria="5")["selo"] == ip.PROVAVEL


def test_cpf_completo_de_outra_fonte_converge_so_quando_acrescenta_posicao():
    # DPRJ mostra a posição 3, que o QSA não mostra; o CPF completo confere nela → convergente
    r = _cl(cpf_folha="XX036481XXX", fonte_folha="dprj_transparencia", n_folha_nome=5, n_qsa_nome=2,
            cpf_resolvido="12036481700")
    assert r["selo"] == ip.VERIFICADO and "outra fonte" in r["motivo"]
    # CPF completo que diverge da folha derruba
    r = _cl(cpf_folha="XX036481XXX", fonte_folha="dprj_transparencia", cpf_resolvido="12936481700")
    assert r["selo"] == ip.HOMONIMO


# ─────────────────── fim a fim: socio_na_folha numa base sintética ────────────────────────────

@pytest.fixture()
def base(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE registros_folha (nome TEXT, cpf TEXT, orgao_nome TEXT, cargo TEXT, vinculo TEXT,
                                      fonte TEXT, competencia TEXT, matricula TEXT);
        CREATE TABLE socios_fornecedor (cnpj TEXT, socio_nome TEXT, socio_doc TEXT, qualificacao TEXT,
                                        cpf_resolvido TEXT);
        CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, n_obs INT, total_pago REAL);
        CREATE TABLE socios_receita (cnpj_basico TEXT, nome_socio TEXT, doc_socio TEXT, data_entrada TEXT,
                                     faixa_etaria TEXT);
        CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, credor TEXT, valor REAL,
                                            status TEXT, status_envio TEXT, tipo_regularizacao TEXT);
        CREATE TABLE ob_reemitida (ob TEXT, ug TEXT);
    """)
    folha = [
        # Executivo, janela 4–9: a régua antiga (3–8) descartava como homônimo
        ("CARLOS ALBERTO ZUQUIM", "XX364817XXX", "SECRETARIA DE ESTADO DE EDUCACAO", "PROFESSOR", "EFETIVO",
         "gesperj_estado", "2026-06", "1"),
        ("CARLOS ALBERTO ZUQUIM", "XX364817XXX", "SECRETARIA DE ESTADO DE EDUCACAO", "PROFESSOR", "EFETIVO",
         "gesperj_estado", "2026-09", "1"),
        # homônimo: mesmo nome, CPF diferente
        ("JOSE DA SILVA", "XX111111XXX", "SECRETARIA DE ESTADO DE SAUDE", "MEDICO", "EFETIVO",
         "gesperj_estado", "2026-06", "2"),
        # TJRJ sem CPF: só o nome
        ("MARIA DAS GRACAS LIMA", "", "TRIBUNAL DE JUSTICA", "ANALISTA", "", "tjrj_anexo8", "2026-05", ""),
    ]
    con.executemany("INSERT INTO registros_folha VALUES (?,?,?,?,?,?,?,?)", folha)
    socios = [("11111111000111", "Carlos Alberto Zuquim", "***364817**", "49-Sócio-Administrador", None),
              ("22222222000122", "JOSE DA SILVA", "***555555**", "Sócio-Administrador", None),
              ("33333333000133", "MARIA DAS GRACAS LIMA", "***777777**", "Sócio", None),
              ("44444444000144", "PEDRO PRESIDENTE", "***364817**", "Presidente", None)]
    con.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?)", socios)
    con.executemany("INSERT INTO favorecido_resumo VALUES (?,?,?,?)", [
        ("11111111000111", "ZUQUIM SERVICOS LTDA", 2, 1000.0), ("22222222000122", "SILVA LTDA", 1, 10.0),
        ("33333333000133", "LIMA ME", 1, 10.0), ("44444444000144", "Aa Ce Barao Do Rio Branco", 1, 5.0)])
    con.execute("INSERT INTO socios_receita VALUES ('11111111','CARLOS ALBERTO ZUQUIM','***364817**','20190301','5')")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?)", [
        ("2026OB1", "180100", "11111111000111", 1234567.89, "Contabilizado", "", ""),
        ("2026OB2", "296100", "11111111000111", 1000.00, "Contabilizado", "", ""),
        ("2026OB3", "180100", "11111111000111", 999.0, "Cancelado", "", "")])
    con.commit()
    con.close()
    return str(p)


def test_fim_a_fim_camadas(base):
    from compliance_agent import socio_na_folha as snf
    d = snf.calcular(base)
    ps = d["por_selo"]
    assert [x["nome"] for x in ps[ip.VERIFICADO]] == ["Carlos Alberto Zuquim"]
    assert [x["nome"] for x in ps[ip.HOMONIMO]] == ["JOSE DA SILVA"]
    assert [x["nome"] for x in ps[ip.INDETERMINADO]] == ["MARIA DAS GRACAS LIMA"]
    # associação de apoio a escola: fora do escopo, CONTADA
    assert d["fora_do_escopo"] == {"entidade_sem_fins_ou_estatal": 1}
    z = ps[ip.VERIFICADO][0]
    assert z["cpf_mascarado"] == "***.364.817-**"
    assert z["vinculos"][0]["periodo"] == ["2026-06", "2026-09"]
    e = z["empresas"][0]
    assert e["data_entrada"] == "01/03/2019"
    # só OB paga conta; a do mesmo órgão (SEEDUC 180100) acende o art. 9º
    assert e["ob_siafe"]["total"] == pytest.approx(1235567.89)
    assert z["mesmo_orgao"] is True and z["ob_mesmo_orgao"] == pytest.approx(1234567.89)


def test_para_api_nunca_poe_par_so_por_nome_na_lista(base):
    from compliance_agent import socio_na_folha as snf
    api = snf.para_api(snf.calcular(base))
    assert {x["selo"] for x in api["pessoas"]} <= {ip.VERIFICADO, ip.PROVAVEL}
    assert all(a["selo"] in (ip.VERIFICADO, ip.PROVAVEL) for a in api["achados"])
    assert api["n_indeterminado"] == 1 and api["homonimos_descartados"] == 1 and api["n_art9"] == 1
