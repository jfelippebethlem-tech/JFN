# -*- coding: utf-8 -*-
"""Gestão Couto — correções da revisão cética de 13/11/2026 (`~/vault/notas/revisao-cetica-2026-11-13.md` §6.1/§6.2).
Base sintética: nenhum nome, CPF ou CNPJ real."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import governo_couto_regras as GR

NOVA, FILIAL, VELHA = "11111111000111", "22222222000299", "22222222000122"
SANC_FED, SANC_RJ, SANC_PRAZO = "33333333000133", "44444444000144", "55555555000155"
SOCIO_OK, SOCIO_HOM, SOCIO_ALERJ = "66666666000166", "77777777000177", "88888888000188"


@pytest.fixture()
def base(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, nl TEXT,
        credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER, gd TEXT, status_envio TEXT);
    CREATE TABLE ordens_bancarias (numero_ob TEXT, ug_codigo TEXT, valor REAL);
    CREATE TABLE despesa_execucao (ug TEXT, nome_ug TEXT);
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT, abrangencia TEXT,
        esfera_sancionador TEXT, data_publicacao TEXT);
    CREATE TABLE agente_publico_societario (nome_norm TEXT, nome_socio TEXT, doc_socio TEXT, cnpj_basico TEXT,
        qualif_cod TEXT, origem TEXT, cargo TEXT, vinculo TEXT, orgao TEXT, comissionado INTEGER, construido_em TEXT);
    CREATE TABLE registros_folha (nome TEXT, cpf TEXT, fonte TEXT);
    CREATE TABLE contratos_tcerj (processo TEXT, sei_norm TEXT, data_contratacao TEXT, valor_contrato REAL,
        status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT, cnpj TEXT);
    CREATE TABLE publicacoes_doerj (data_publicacao TEXT, texto TEXT);
    """)
    c.execute("INSERT INTO despesa_execucao VALUES ('100100','SECRETARIA FICTICIA')")
    O = "INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,NULL,?,?,'SEI-100001/000001/2026',?,?,?,?)"
    c.executemany(O, [
        # NOVA: R$ 6 mi pagos; uma linha-fantasma SEM número repete a OB (não pode somar)
        ("2026OB00001", "100100", "10/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026, "", ""),
        ("", "100100", "10/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026, "", ""),
        # e uma OB devolvida pelo banco (TFE 0,00) com a reemissão já contada acima
        ("2026OB00002", "100100", "09/05/2026", "Contabilizado", NOVA, "NOVA LTDA", 6_000_000.0, 2026,
         "2026GD00001", "Erro no Pagamento"),
        # FILIAL de raiz que já recebia em 2022 — não é credor sem histórico
        ("2022OB00009", "100100", "10/05/2022", "Contabilizado", VELHA, "VELHA SA", 1_000.0, 2022, "", ""),
        ("2026OB00003", "100100", "11/05/2026", "Contabilizado", FILIAL, "VELHA SA FILIAL", 7_000_000.0, 2026, "", ""),
        ("2026OB00004", "100100", "12/05/2026", "Contabilizado", SANC_FED, "FED LTDA", 500_000.0, 2026, "", ""),
        ("2026OB00005", "100100", "12/05/2026", "Contabilizado", SANC_RJ, "RJ LTDA", 400_000.0, 2026, "", ""),
        ("2026OB00006", "100100", "12/05/2026", "Contabilizado", SANC_PRAZO, "PRAZO LTDA", 300_000.0, 2026, "", ""),
        ("2026OB00007", "100100", "12/05/2026", "Contabilizado", SOCIO_OK, "SOCIO OK LTDA", 200_000.0, 2026, "", ""),
        ("2026OB00008", "100100", "12/05/2026", "Contabilizado", SOCIO_HOM, "HOMONIMO LTDA", 200_000.0, 2026, "", ""),
        ("2026OB00010", "100100", "12/05/2026", "Contabilizado", SOCIO_ALERJ, "ALERJ LTDA", 200_000.0, 2026, "", ""),
        ("2026OB00011", "100100", "10/11/2026", "Contabilizado", VELHA, "VELHA SA", 10.0, 2026, "", ""),
    ])
    c.execute("INSERT INTO ordens_bancarias VALUES ('2026OB00002','100100',0.0)")
    S = "INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    c.executemany(S, [
        ("CEIS", SANC_FED, "FED", "Suspensão", "2026-04-01", "2027-04-01", "Instituto Federal Ficticio", "RJ", "p",
         "LEI 8666 - ART. 87, III", "No órgão sancionador", "FEDERAL", None),
        ("CEIS", SANC_RJ, "RJ", "Impedimento/proibição de contratar com prazo determinado", "2026-04-01",
         "2027-04-01", "Secretaria de Estado Ficticia", "RJ", "p", "LEI 14133 - ART. 156, III",
         "Em todos os Poderes da Esfera do órgão sancionador", "ESTADUAL", None),
        ("CEIS", SANC_PRAZO, "PRAZO", "Impedimento/proibição de contratar com prazo determinado", "2026-04-01",
         None, "Secretaria de Estado Ficticia", "RJ", "p", "LEI 14133 - ART. 156, III",
         "Em todos os Poderes da Esfera do órgão sancionador", "ESTADUAL", None),
    ])
    A = "INSERT INTO agente_publico_societario VALUES (?,?,?,?,'49',?,'ASSESSOR','COMISSIONADO','SECRETARIA',1,'x')"
    c.executemany(A, [
        ("FULANO FICTICIO DA SILVA", "FULANO FICTICIO DA SILVA", "***456789**", SOCIO_OK[:8], "folha_estado"),
        ("BELTRANO FICTICIO SOUZA", "BELTRANO FICTICIO SOUZA", "***111111**", SOCIO_HOM[:8], "folha_estado"),
        ("SICRANO FICTICIO LIMA", "SICRANO FICTICIO LIMA", "***222222**", SOCIO_ALERJ[:8], "alerj"),
    ])
    c.executemany("INSERT INTO registros_folha VALUES (?,?,?)", [
        ("FULANO FICTICIO DA SILVA", "XX456789XXX", "gesperj_estado"),        # Executivo: dígitos 4–9 → confere
        ("BELTRANO FICTICIO SOUZA", "XX999999XXX", "gesperj_estado"),         # outra pessoa com o mesmo nome
    ])
    C = "INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?,?,?,?)"
    c.executemany(C, [
        # registrado no 3º dia, mas o DOERJ diz que a ATA foi assinada em fevereiro
        ("SEI-100001/000010/2026", "1000010000102026", "2026-03-25", 43_000_000.0, "Ativo", "UNIDADE X",
         "REGISTRO DE PREÇOS PARA EVENTOS", "FORN ATA", NOVA),
        # registrado no 5º dia, assinado antes da gestão (DOERJ)
        ("SEI-100001/000011/2026", "1000010000112026", "2026-03-27", 9_000_000.0, "Ativo", "UNIDADE X",
         "OBRA DE CONTENÇÃO", "FORN ANTES", FILIAL),
        # assinado de fato na gestão
        ("SEI-100001/000012/2026", "1000010000122026", "2026-03-30", 1_000_000.0, "Ativo", "UNIDADE X",
         "SERVIÇO DE LIMPEZA", "FORN GESTAO", VELHA),
    ])
    c.executemany("INSERT INTO publicacoes_doerj VALUES (?,?)", [
        ("2026-03-20", "EXTRATO DE ATA DE REGISTRO DE PREÇOS Nº 1/2026 PROCESSO Nº SEI-100001/000010/2026 "
                       "OBJETO: EVENTOS DATA DA ASSINATURA: 24/02/2026"),
        ("2026-04-14", "EXTRATO DE CONTRATO PROCESSO SEI-100001/000011/2026 OBJETO: OBRA "
                       "DATA DA ASSINATURA: 10/03/2026 VALOR R$ 9.000.000,00"),
    ])
    c.commit()
    c.close()
    return db


@pytest.fixture()
def ctx(base, tmp_path):
    c = GR.Ctx(base, receita=None, tse=None, dir_tmp=tmp_path)
    yield c
    c.fechar()


def test_ob_sem_numero_e_devolvida_nao_somam(ctx):
    d10 = {x["cnpj"]: x for x in GR.d10(ctx)["casos"]}
    assert d10[NOVA]["pago_ob"] == pytest.approx(6_000_000.0)       # nem a linha sem número nem a devolvida


def test_sem_historico_pela_raiz_do_cnpj_desde_2021(ctx):
    assert FILIAL not in {x["cnpj"] for x in GR.d10(ctx)["casos"]}  # a raiz recebeu em 2022


def test_d14_so_conta_sancao_vigente_com_alcance_sobre_o_estado(ctx):
    r = GR.d14(ctx)
    assert {x["cnpj"] for x in r["casos"]} == {SANC_RJ}
    assert r["n_sem_alcance"] == 1 and r["soma_sem_alcance"] == pytest.approx(500_000.0)   # suspensão do IFRJ-like


def test_d13_exige_digitos_visiveis_do_cpf(ctx):
    r = GR.d13(ctx)
    assert [x["cnpj_basico"] for x in r["casos"]] == [SOCIO_OK[:8]]
    assert r["n_homonimos_descartados"] == 1 and r["n_cnpj_nao_testavel"] == 1


def test_cpf_confere_respeita_a_posicao_por_fonte():
    assert GR.cpf_confere("***456789**", "XX456789XXX", "gesperj_estado") is True     # dígitos 4–9
    assert GR.cpf_confere("***456789**", "XX345678XXX", "dprj_transparencia") is True  # dígitos 3–8: sobreposição 4–8
    assert GR.cpf_confere("***456789**", "XX456789XXX", "dprj_transparencia") is False
    assert GR.cpf_confere("***456789**", "XX456789XXX", "fonte_sem_aferir") is None
    assert GR.cpf_confere("***456789**", None, "gesperj_estado") is None


def test_contrato_da_gestao_usa_a_data_do_doerj_e_tira_ata(ctx):
    r = GR.d08_09(ctx)["D08"]
    assert [x["processo"] for x in r["casos"]] == ["SEI-100001/000012/2026"]
    a = GR.ato_do_contrato(ctx, "1000010000112026", "", "2026-03-27")
    assert a["data"] == "2026-03-10" and a["fonte"].startswith("DOERJ")
    assert GR.ato_do_contrato(ctx, "1000010000102026", "", "2026-03-25")["nao_contrato"] is True


def test_curadoria_manual_nao_carrega_vermelho_fixo_e_refutado_vira_branco():
    t01 = GR.curar_top10({"id": "T01", "grau": "🔴", "estado_verificacao": "PARCIAL", "regra_ou_hipotese": "D14 · X"})
    assert t01["grau"] == "🟡" and t01["grau_proposto"] == "🔴" and t01["top10"] is True
    assert t01["regra_ou_hipotese"] == "PARCIAL · D14 · X"                 # o estado vai no próprio título
    t05 = GR.curar_top10({"id": "T05", "grau": "🟡", "estado_verificacao": "REFUTADO", "regra_ou_hipotese": "D14 · Y"})
    assert t05["grau"] == "⚪" and t05["regra_ou_hipotese"].startswith("REFUTADO · ")
    # mesmo SUSTENTADO não vira 🔴 por curadoria: o 🔴 é da régua determinística (caso D14 com contrato na vigência)
    t03 = GR.curar_top10({"id": "T03", "grau": "🔴", "estado_verificacao": "SUSTENTADO", "regra_ou_hipotese": "Z",
                          "prova_primaria": ["DOERJ 01/01/2026"]})
    assert t03["grau"] == "🟡"


def test_curadoria_sem_estado_de_verificacao_e_pendente_e_branca():
    x = GR.curar_top10({"id": "T09", "grau": "🟡", "regra_ou_hipotese": "título antigo com número"})
    assert x["estado_verificacao"] == "PENDENTE" and x["grau"] == "⚪"
    assert x["regra_ou_hipotese"].startswith("PENDENTE · ")
    assert GR.curar_top10({"id": "T1", "estado_verificacao": "INVENTADO", "grau": "🟡"})["estado_verificacao"] == "PENDENTE"


def test_verificacao_do_top10_segue_o_estado_e_nao_o_numero_do_processo():
    par = GR.aplicar_verificacao(GR.curar_top10({"id": "T02", "grau": "🟡", "estado_verificacao": "PARCIAL",
                                                 "processo": "SEI-1/2026", "regra_ou_hipotese": "A"}))
    assert par["verificacao"] == "PENDENTE" and par["regra_ou_hipotese"] == "PARCIAL · A"
    assert par["prova_primaria"] == []                      # processo citado não é prova primária
    sus = GR.aplicar_verificacao(GR.curar_top10({"id": "T03", "grau": "🟡", "estado_verificacao": "SUSTENTADO",
                                                 "regra_ou_hipotese": "B", "prova_primaria": ["OB 1 (SIAFE)"]}))
    assert sus["verificacao"] == "VERIFICADO" and sus["regra_ou_hipotese"] == "SUSTENTADO · B"
    assert GR.aplicar_verificacao(sus) == sus               # idempotente


def test_montar_le_a_curadoria_e_nao_preserva_titulo_antigo():
    anterior = {"achados": [{"id": "T01", "top10": True, "grau": "🟡", "regra_ou_hipotese": "R$ 999 mi refutado"}]}
    info = dict(gerado_em="2026-11-15T03:00:00", GFIM="2026-11-10", G1="2026-10-31", B0="2025-03-23", B1="2025-10-31")
    sem = GR.montar({}, anterior=anterior, hipoteses=None, motivo_subj="x", ctx_info=info, curadoria=None)
    assert not [x for x in sem["achados"] if x.get("top10")] and sem["curadoria"]["estado"] == "ausente"
    cur = [{"id": "T01", "grau": "🟡", "estado_verificacao": "PARCIAL", "regra_ou_hipotese": "novo",
            "explicacao_inocente": "i", "proximo_passo": "p"}]
    com = GR.montar({}, anterior=anterior, hipoteses=None, motivo_subj="x", ctx_info=info, curadoria=cur)
    t = [x for x in com["achados"] if x.get("top10")]
    assert [x["regra_ou_hipotese"] for x in t] == ["PARCIAL · novo"] and com["curadoria"]["estado"] == "ok"


def test_reaplicar_curadoria_troca_so_o_top10(tmp_path):
    saida = tmp_path / "s.json"
    GR.gravar_json(saida, {"achados": [{"id": "T01", "top10": True, "grau": "🟡", "regra_ou_hipotese": "velho"},
                                       {"id": "D05", "camada": "deterministica", "grau": "🟡", "verificacao": "VERIFICADO",
                                        "regra_ou_hipotese": "regra"}],
                           "por_verificacao": {"VERIFICADO": 2}, "n_achados": 2})
    cur = tmp_path / "c.json"
    GR.gravar_json(cur, {"itens": [{"id": "T01", "grau": "🟡", "estado_verificacao": "REFUTADO",
                                    "regra_ou_hipotese": "novo", "explicacao_inocente": "i", "proximo_passo": "p"}]})
    assert GR.reaplicar_curadoria(saida, cur) == 1
    d = GR.ler_json(saida)
    assert [x["id"] for x in d["achados"]] == ["T01", "D05"]
    assert d["achados"][0]["regra_ou_hipotese"] == "REFUTADO · novo" and d["achados"][0]["grau"] == "⚪"
    assert d["por_verificacao"] == {"PENDENTE": 1, "VERIFICADO": 1} and d["n_achados"] == 2


def test_d18_veredito_fachada_sem_registro_do_juizo_nao_e_confirmado(base, tmp_path):
    con = sqlite3.connect(base)
    con.executescript("""CREATE TABLE fantasma_score (cnpj TEXT, score INTEGER, classificacao TEXT);
        CREATE TABLE fachada_veredito (cnpj TEXT, status TEXT, veredito_raw TEXT);""")
    con.executemany("INSERT INTO fachada_veredito VALUES (?,?,?)", [(NOVA, "fachada", ""),
                                                                    (FILIAL, "fachada", "fachada — sede vazia (vistoria)")])
    con.commit()
    con.close()
    c = GR.Ctx(base, receita=None, tse=None, dir_tmp=tmp_path)
    try:
        r = {x["cnpj"]: x for x in GR.d18(c)["casos"]}
    finally:
        c.fechar()
    assert r[NOVA]["fachada_confirmada"] is False and r[FILIAL]["fachada_confirmada"] is True


def test_d18_score_alto_sem_fachada_registrada_nao_e_vermelho():
    res = {"D18": {"n": 1, "casos": [{"cnpj": NOVA, "credor": "X", "pago_ob": 1.0, "fantasma_alto": True, "score": 95,
                                      "fachada_confirmada": False}]}}
    a = [x for x in GR.achados_deterministicos(res) if x["id"].startswith("D18")]
    assert all(x["grau"] != "🔴" for x in a)


def test_aba_le_o_estado_da_curadoria_e_nao_o_rebaixa_a_agregado():
    from compliance_agent import governo_couto as G
    par = GR.aplicar_verificacao(GR.curar_top10({"id": "T02", "grau": "🟡", "estado_verificacao": "PARCIAL",
                                                 "regra_ou_hipotese": "A", "revisao": {"nota": "valor reduzido"}}))
    v, motivo = G._verificacao(par)
    assert v == "PENDENTE" and "PARCIAL" in motivo and "valor reduzido" in motivo
    sus = GR.aplicar_verificacao(GR.curar_top10({"id": "T03", "estado_verificacao": "SUSTENTADO", "grau": "🟡",
                                                 "regra_ou_hipotese": "B", "prova_primaria": ["DOERJ"]}))
    v, motivo = G._verificacao(sus)
    assert v == "VERIFICADO" and "SUSTENTADO" in motivo


def test_prova_de_ob_declara_o_que_ficou_fora_da_lista():
    """Pente fino 17/11/2026: o 🔴 D14 (Sinais críticos do Início) somava 5 OB na janela (R$ 235.487,10) e a prova
    listava só as 3 maiores, sem dizer que havia mais — corte silencioso. A lista segue curta; o resto é declarado."""
    from types import SimpleNamespace
    obs = [(47_000.0, f"2026OB0000{i}", "999999", f"2026-0{i}-10") for i in range(4, 9)]
    c = SimpleNamespace(_idx_ob={NOVA: obs}, GFIM="2026-12-31")
    p = GR.Ctx.refs_ob(c, NOVA, d0="2026-03-23")
    assert len([x for x in p if x.startswith("OB ")]) == 3
    assert p[-1] == "e mais 2 OB Contabilizada(s) na janela (R$ 94.000,00) — 5 OB, R$ 235.000,00 no total"
    assert GR.Ctx.refs_ob(c, NOVA, d0="2026-03-23", limite=5)[-1].startswith("OB ")      # nada cortado, nada declarado


# ───────────── juiz de qualidade 15/11/2026: D04 (SUB-02/03), D05 (SUB-03), D14 (SUB-02/03) ─────────────

def _ctx_de(base, tmp_path):
    return GR.Ctx(base, receita=None, tse=None, dir_tmp=tmp_path)


def test_d04_so_ob_do_ano_contra_o_teto_e_tolerancia_de_20_por_cento_testada(base, tmp_path):
    epp_tol = "12121212000112"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT, "
                "capital_social REAL, porte_cod TEXT, porte_txt TEXT, fonte_mes TEXT)")
    con.executemany("INSERT INTO empresas_cadastro VALUES (?,'X','2062',1000,'',?,'2026-10')", [
        (NOVA[:8], "Empresa de Pequeno Porte"),       # R$ 6,0 mi = 1,25× o teto EPP → caso
        (VELHA[:8], "Microempresa"),                  # raiz da FILIAL: R$ 7 mi → caso (e contrato de contexto)
        (SANC_RJ[:8], "Microempresa"),                # R$ 400 mil = 1,11× → tolerância, à parte
        (SANC_PRAZO[:8], "Microempresa"),             # R$ 300 mil < teto → nada
        (epp_tol[:8], "Empresa de Pequeno Porte"),    # R$ 5,5 mi = 1,15× → tolerância
    ])
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB00090','100100','10/06/2026','Contabilizado',NULL,"
                "?,'TOL LTDA','SEI-100001/000001/2026',5500000.0,2026,'','')", (epp_tol,))
    # OB de 2025 do caso NOVA não entra na conta do ano-calendário
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB00090','100100','10/06/2025','Contabilizado',NULL,"
                "?,'NOVA LTDA','SEI-100001/000001/2025',9000000.0,2025,'','')", (NOVA,))
    con.commit()
    con.close()
    c = _ctx_de(base, tmp_path)
    try:
        r = GR.d04(c)
    finally:
        c.fechar()
    casos = {x["cnpj_basico"]: x for x in r["casos"]}
    assert set(casos) == {NOVA[:8], VELHA[:8]}
    assert casos[NOVA[:8]]["pago_ano"] == pytest.approx(6_000_000.0) and casos[NOVA[:8]]["teto"] == 4_800_000.0
    assert casos[NOVA[:8]]["limite_tolerancia"] == pytest.approx(5_760_000.0)
    assert {x["cnpj_basico"] for x in r["tolerancia_casos"]} == {SANC_RJ[:8], epp_tol[:8]}
    assert r["n_tolerancia"] == 2 and r["soma_tolerancia"] == pytest.approx(5_900_000.0)
    # valor da regra = só OB do ano dos casos; contrato (valor global) é contexto, nunca somado
    assert r["valor_ob"] == pytest.approx(6_000_000.0 + 7_000_010.0)
    assert r["n_contratos"] == 1 and "contexto" in r["contratos_natureza"]
    for t in ("2026", "R$ 360.000,00", "R$ 4.800.000,00", "1,2×", "tolerância", "valor global não é receita anual"):
        assert t in r["resumo"], t
    ino = r["explicacao_inocente"]
    assert "TESTADO" in ino and "NÃO TESTADO" in ino and "§9º-A" in ino and "2026-10" in ino
    a = {x["id"]: x for x in GR.achados_deterministicos({"D04": r})}
    assert a["D04"]["explicacao_inocente"] == ino and a["D04"]["valor_ob"] == r["valor_ob"]


def test_d05_cada_caso_traz_o_instrumento_ou_nao_localizado(base, tmp_path):
    so = "13131313000113"
    con = sqlite3.connect(base)
    con.execute("INSERT INTO despesa_execucao VALUES ('200200','AUTARQUIA DE OBRAS FICTICIA')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB00091','200200','10/06/2026','Contabilizado',NULL,"
                "?,'SOZINHA LTDA','SEI-200001/000009/2026',11000000.0,2026,'','')", (so,))
    con.execute("INSERT INTO contratos_tcerj VALUES ('SEI-100001/000077/2026','1000010000772026','2026-04-01',"
                "20000000.0,'Ativo','SF - SECRETARIA FICTICIA','OBRA','VELHA SA',?)", (FILIAL,))
    con.execute("CREATE TABLE compras_diretas_tcerj (processo TEXT, sei_norm TEXT, ano_processo INTEGER, valor REAL, "
                "objeto TEXT, afastamento TEXT, enquadramento_legal TEXT, unidade TEXT, fornecedor TEXT)")
    con.execute("INSERT INTO compras_diretas_tcerj VALUES ('SEI-100001/000001/2026','1000010000012026',2026,6000000.0,"
                "'SERVIÇO','Dispensa de Licitação','Lei 14.133/2021, Art. 75, VIII','SF - SECRETARIA FICTICIA','NOVA LTDA')")
    con.commit()
    con.close()
    c = _ctx_de(base, tmp_path)
    try:
        r = GR.d05(c)
    finally:
        c.fechar()
    i = {x["cnpj"]: x["instrumento"] for x in r["casos"]}
    assert i[NOVA]["situacao"] == "direta" and i[NOVA]["via"] == "processo das OB"
    assert "Art. 75, VIII" in i[NOVA]["modalidade"]
    assert i[FILIAL]["situacao"] == "contrato" and i[FILIAL]["via"] == "CNPJ e unidade"
    assert i[FILIAL]["processo"] == "SEI-100001/000077/2026" and i[FILIAL]["valor"] == 20_000_000.0
    assert i[so]["situacao"] == "nao_localizado" and "não é zero" in i[so]["motivo"]
    assert (r["n_instrumento_localizado"], r["n_instrumento_contrato"], r["n_instrumento_direta"],
            r["n_instrumento_nao_localizado"]) == (2, 1, 1, 1)
    assert "localizado no espelho do TCE-RJ em 2 de 3" in r["resumo"] and "não é zero" in r["resumo"]
    a = {x["id"]: x for x in GR.achados_deterministicos({"D05": r})}
    assert a[f"D05-200200-{so}"]["explicacao_inocente"].startswith("instrumento: não localizado")
    assert "TESTADO" in a["D05"]["explicacao_inocente"]


def test_d05_espelho_ausente_e_indisponivel_nao_nao_localizado(base, tmp_path):
    con = sqlite3.connect(base)
    con.execute("DROP TABLE contratos_tcerj")
    con.commit()
    con.close()
    c = _ctx_de(base, tmp_path)
    try:
        r = GR.d05(c)
    finally:
        c.fechar()
    assert r["n"] and all(x["instrumento"]["situacao"] == "indisponivel" for x in r["casos"])
    assert r["n_instrumento_indisponivel"] == r["n"] and "INDISPONÍVEL" in r["resumo"]


def _d14_com_competencia(base, obs, fundamentacao="LEI 14133 - ART. 156, IV", contrato_antes=True):
    inid = "94949494000194"
    con = sqlite3.connect(base)
    con.execute("ALTER TABLE ob_orcamentaria_siafe ADD COLUMN competencia TEXT")
    con.executemany("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, credor, "
                    "nome_credor, processo, valor, exercicio, gd, status_envio, competencia) "
                    "VALUES (?,'100100',?,'Contabilizado',?,'INID LTDA','SEI-100001/000050/2025',?,2026,'','',?)",
                    [(n, dt, inid, v, comp) for n, dt, v, comp in obs])
    con.execute("INSERT INTO sancoes_federais VALUES ('CEIS',?,'INID','Declaração de Inidoneidade com prazo determinado',"
                "'2026-06-01','2029-06-01','Secretaria de Estado Ficticia','RJ','5000000-00.2026.4.04.0000',?,"
                "'Todas as Esferas em todos os Poderes','ESTADUAL',NULL)", (inid, fundamentacao))
    if contrato_antes:
        con.execute("INSERT INTO contratos_tcerj VALUES ('SEI-100001/000050/2025','1000010000502025','2025-12-10',"
                    "1.0,'Ativo','UNIDADE X','SERVIÇO','INID',?)", (inid,))
    con.commit()
    con.close()
    return inid


def test_d14_testa_competencia_anterior_ex_nunc_e_alcance(base, tmp_path):
    inid = _d14_com_competencia(base, [("2026OB00100", "20/06/2026", 100_000.0, "05/2026"),
                                       ("2026OB00101", "25/06/2026", 50_000.0, "06/2026"),
                                       ("2026OB00102", "10/07/2026", 300_000.0, "07/2026")])
    c = _ctx_de(base, tmp_path)
    try:
        res = {"D14": GR.d14(c)}
        GR.anexar_provas(c, res)
    finally:
        c.fechar()
    x = {k["cnpj"]: k for k in res["D14"]["casos"]}[inid]
    t = x["teste_inocente"]
    cp = t["competencia"]
    assert cp["estado"] == "TESTADO" and cp["reconcilia_com_caso"] is True
    assert cp["anterior"] == {"n_ob": 1, "valor": 100_000.0} and cp["mes_do_inicio"]["n_ob"] == 1
    assert cp["posterior"] == {"n_ob": 1, "valor": 300_000.0}
    assert t["ex_nunc"]["n_ob_contrato_anterior"] == 3 and t["explica_tudo"] is False
    assert t["alcance"]["abrangencia_ceis"] == "Todas as Esferas em todos os Poderes"
    a = {k["id"]: k for k in GR.achados_deterministicos(res)}[f"D14-{inid}-2026-06-01"]
    assert a["grau"] == "🟡"                                   # o teste não explica tudo: o grau não cai (nem sobe)
    assert "R$ 450.000,00 em 3 OB de 2026-06-20 a 2026-07-10" in a["regra_ou_hipotese"]
    assert "TESTADO — serviço anterior" in a["explicacao_inocente"] and "ex nunc" in a["explicacao_inocente"]
    assert "Todas as Esferas em todos os Poderes" in a["explicacao_inocente"]


def test_d14_competencia_toda_anterior_rebaixa_o_caso_a_branco(base, tmp_path):
    inid = _d14_com_competencia(base, [("2026OB00100", "20/06/2026", 100_000.0, "04/2026"),
                                       ("2026OB00101", "25/06/2026", 50_000.0, "05/2026")], contrato_antes=False)
    c = _ctx_de(base, tmp_path)
    try:
        a = {k["id"]: k for k in GR.achados_deterministicos({"D14": GR.d14(c)})}[f"D14-{inid}-2026-06-01"]
    finally:
        c.fechar()
    assert a["grau"] == "⚪" and "anterior" in a["motivo_grau"]


def test_d14_alcance_escreve_o_que_a_fundamentacao_implica(base, tmp_path):
    inid = _d14_com_competencia(base, [("2026OB00100", "20/06/2026", 1.0, "07/2026")],
                                fundamentacao="LEI 8429 - ART. 12 - IMPROBIDADE ADMINISTRATIVA")
    c = _ctx_de(base, tmp_path)
    try:
        x = {k["cnpj"]: k for k in GR.d14(c)["casos"]}[inid]
    finally:
        c.fechar()
    assert "ente lesado" in x["teste_inocente"]["alcance"]["implicacao"]
    assert x["teste_inocente"]["alcance"]["processo"] == "5000000-00.2026.4.04.0000"


def test_d14_sem_coluna_competencia_e_indisponivel():
    t = {"teste_inocente": {"competencia": {"estado": "INDISPONÍVEL", "motivo": "sem a coluna"}}}
    assert "INDISPONÍVEL" in GR.explicar_teste_d14(t) and "não testado" in GR.explicar_teste_d14(t)
    assert GR._competencia("06/2026") == (2026, 6) and GR._competencia("01/02/2023") == (2023, 2)
    assert GR._competencia("13/2026") is None and GR._competencia("") is None
