# -*- coding: utf-8 -*-
"""Aba "Governo Couto" — dados sintéticos (nenhum nome, CPF ou processo real)."""
import json
import sqlite3

import pytest

from compliance_agent import governo_couto as G

# ── DOERJ sintético: um decreto numerado, um citado, um do governador anterior, um de pessoal ──────────────
_DOE_DECRETOS = """ATOS DO GOVERNADOR EM EXERCÍCIO
DECRETO Nº 50.900 DE 09 DE ABRIL DE 2026
ABRE CRÉDITO SUPLEMENTAR A DIVERSOS ÓRGÃOS, NO VA-
LOR GLOBAL DE R$ 1.234.567,89 PARA REFORÇO DE DOTAÇÕES.
O GOVERNADOR DO ESTADO DO RIO DE JANEIRO, EM EXERCÍCIO, no uso de suas atribuições,
D E C R E T A :
Art. 1º - Fica aberto crédito, conforme o Decreto nº 40.000, de 01 de janeiro de 2007.
Rio de Janeiro, 09 de abril de 2026
FULANO GOVERNANTE DE TESTE
Governador em Exercício
DECRETO Nº 50.901 DE 10 DE ABRIL DE 2026
DISPÕE SOBRE A REALIZAÇÃO DE AUDITO- RIA NA GESTÃO DAS SECRETARIAS.
O GOVERNADOR DO ESTADO DO RIO DE JANEIRO, EM EXERCÍCIO,
Rio de Janeiro, 10 de abril de 2026
FULANO GOVERNANTE DE TESTE
Governador em Exercício
"""
_DOE_ANTERIOR = """DECRETO Nº 50.800 DE 20 DE MARÇO DE 2026
DISPÕE SOBRE COISA ANTERIOR.
O GOVERNADOR DO ESTADO DO RIO DE JANEIRO,
Rio de Janeiro, 20 de março de 2026
CICRANO ANTERIOR
Governador
DECRETO Nº 50.902, DE 23 DE MARÇO DE 2026, QUE ALTERA O DECRETO Nº 1.
"""
_DOE_PESSOAL = """ATOS DO GOVERNADOR EM EXERCÍCIO
DECRETO DE 24 DE MARÇO DE 2026
O GOVERNADOR DO ESTADO DO RIO DE JANEIRO, EM EXERCÍCIO, no uso de suas atribuições,
R E S O LV E :
EXONERAR, a pedido, BELTRANO DE EXEMPLO, ID FUNCIONAL Nº 1111, do cargo de Secretário de Estado, sím-
bolo SE, da Secretaria de Estado de Testes. Processo nº SEI-000000/000001/2026.
Rio de Janeiro, 24 de março de 2026
FULANO GOVERNANTE DE TESTE
Governador em exercício
DECRETO DE 24 DE MARÇO DE 2026
O GOVERNADOR DO ESTADO DO RIO DE JANEIRO, EM EXERCÍCIO,
R E S O LV E :
NOMEAR SICRANA FICTICIA, ID FUNCIONAL Nº 2222, para exercer o cargo de Secretária de Estado, símbolo SE,
da Secretaria de Estado de Testes. Processo nº SEI-000000/000001/2026.
NOMEAR ASSESSOR QUALQUER, para exercer o cargo em comissão de Assessor, símbolo DAS-7, da Secretaria X.
Rio de Janeiro, 24 de março de 2026
FULANO GOVERNANTE DE TESTE
Governador em exercício
"""


@pytest.fixture
def bases(tmp_path, monkeypatch):
    db, ach, ab = tmp_path / "c.db", tmp_path / "a.db", tmp_path / "d.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE publicacoes_doerj (id INTEGER PRIMARY KEY, data_publicacao, orgao, tipo_ato, titulo, "
              "texto, url_fonte)")
    c.executemany("INSERT INTO publicacoes_doerj VALUES (?,?,?,?,?,?,?)", [
        (1, "2026-04-10", "", "decreto", "DECRETO Nº 50.900", _DOE_DECRETOS, "http://doe.exemplo/1"),
        (2, "2026-03-23", "", "decreto", "DECRETO Nº 50.800", _DOE_ANTERIOR, "http://doe.exemplo/2"),
        (3, "2026-03-24", "", "nomeação", "Parte I", _DOE_PESSOAL, "http://doe.exemplo/3"),
        (4, "2026-05-02", "SECRETARIA X", "outros", "Parte I | RESOLUÇÃO Nº 1 INSTAURA AUDITORIA",
         "RESOLUÇÃO Nº 1 INSTAURA AUDITORIA nos termos do Decreto nº 50.254, de 14 de abril de 2026.",
         "http://doe.exemplo/4"),
    ])
    c.execute("CREATE VIRTUAL TABLE fts_doerj USING fts5(titulo, texto, orgao, tipo_ato, content=publicacoes_doerj,"
              " content_rowid=id)")
    c.execute("INSERT INTO fts_doerj(fts_doerj) VALUES ('rebuild')")
    c.execute("CREATE TABLE contratos_tcerj (id, processo, sei_norm, data_contratacao, valor_contrato, status, unidade,"
              " objeto, fornecedor, cnpj, criterio_julgamento)")
    c.executemany("INSERT INTO contratos_tcerj VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        ("a", "SEI-1", "1", "2026-04-01T00:00:00.000", 1000.0, "Ativo", "SEX - SECRETARIA X", "OBRA", "ALFA LTDA",
         "11111111000111", "Menor Preço"),
        ("f", "SEI-6", "6", "2026-04-02T00:00:00.000", 0.0, "Ativo", "SEX - SECRETARIA X", "PATROCÍNIO",
         "FULANO MEI 98765432100", "55555555000155", "Menor Preço"),          # MEI: CPF dentro do NOME
        ("b", "SEI-2", "2", "2026-05-01T00:00:00.000", 500.0, "Ativo", "SEX - SECRETARIA X", "EMERGENCIAL", "BETA",
         "22222222000122", "Menor Preço"),
        ("c", "SEI-3", "3", "2026-06-01T00:00:00.000", 300.0, "Em Aberto", "SEY - SECRETARIA Y", "SHOW", "PESSOA",
         "12345678901", "Menor Preço"),
        ("d", "SEI-4", "4", "2026-03-01T00:00:00.000", 9999.0, "Ativo", "SEX - SECRETARIA X", "ANTES", "GAMA",
         "33333333000133", "Menor Preço"),                                   # antes da gestão: fora
        ("e", "SEI-5", "5", "2026-07-01T00:00:00.000", 777.0, "Cancelado", "SEX - SECRETARIA X", "X", "DELTA",
         "44444444000144", "Menor Preço"),                                   # cancelado: fora do total
    ])
    c.execute("CREATE TABLE compras_diretas_tcerj (sei_norm, afastamento, enquadramento_legal)")
    c.executemany("INSERT INTO compras_diretas_tcerj VALUES (?,?,?)", [
        ("2", "Dispensa de Licitação", "Lei n 14.133/2021, Art. 75, VIII"),
        ("3", "Inexigibilidade - 14.133/2021", "Lei n 14.133/2021, Art. 74, II")])
    c.execute("CREATE TABLE contrato_aditivo (numero_controle_pncp, sequencial_termo, numero_termo, objeto, "
              "valor_acrescido, data_assinatura, tipo_termo, processo)")
    c.executemany("INSERT INTO contrato_aditivo VALUES (?,?,?,?,?,?,?,?)", [
        ("p1", 1, "1º TA", "prazo", 50.0, "2026-04-02", "Termo Aditivo", "SEI-9"),
        ("p2", 1, "1º TA", "valor", 70.0, "2026-01-02", "Termo Aditivo", "SEI-8")])
    c.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, credor, nome_credor,"
              " valor, exercicio, processo, coletado_em)")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,'2026-11-01')", [
        ("1OB1", "100100", "10/04/2026", "Contabilizado", "11111111000111", "ALFA LTDA", 400.0, 2026, "SEI-1"),
        ("1OB2", "100100", "11/04/2026", "Anulado", "11111111000111", "ALFA LTDA", 9000.0, 2026, "SEI-1"),
        ("1OB3", "200100", "12/05/2026", "Contabilizado", "12345678901", "PESSOA", 100.0, 2026, "SEI-3"),
        ("1OB4", "100100", "01/03/2026", "Contabilizado", "11111111000111", "ALFA LTDA", 5000.0, 2026, "SEI-1"),
        ("1OB5", "100100", "10/04/2025", "Contabilizado", "11111111000111", "ALFA LTDA", 250.0, 2025, "SEI-0"),
        ("1OB6", "100100", "20/12/2025", "Contabilizado", "11111111000111", "ALFA LTDA", 8000.0, 2025, "SEI-0"),
    ])
    c.execute("CREATE TABLE penalidades_tcerj (id, processo, tipo, valor, orgao, data_sessao)")
    c.executemany("INSERT INTO penalidades_tcerj VALUES (?,?,?,?,?,?)", [
        ("t1", "TCE/1", "MULTA", 10.0, "SECRETARIA X", "2026-05-05T00:00:00.000"),
        ("t2", "TCE/2", "MULTA", 99.0, "SECRETARIA X", "2026-01-05T00:00:00.000")])
    c.execute("CREATE TABLE pericia_fornecedor (cnpj, ug, favorecido, grau, total_pago, achados_json)")
    c.execute("INSERT INTO pericia_fornecedor VALUES ('11111111000111','100100','ALFA LTDA','🟡',400.0,'[]')")
    c.commit()
    a = sqlite3.connect(ach)
    a.execute("CREATE TABLE achado_detector (ug, detector, processo, score, motivo, status)")
    a.execute("INSERT INTO achado_detector VALUES ('100100','C8','22222222000122',0.7,'sócio servidor','confirmado')")
    a.commit()
    d = sqlite3.connect(ab)
    d.execute("CREATE TABLE da_despesa (ug, orgao, nome_orgao, posicao, valor_empenhado)")
    d.executemany("INSERT INTO da_despesa VALUES (?,?,?,?,?)", [
        ("100100", "10", "Secretaria X", "12/2025", 1.0), ("200100", "20", "Secretaria Y", "12/2025", 1.0)])
    d.commit()
    for x in (c, a, d):
        x.close()
    monkeypatch.setattr(G, "DB", db)
    monkeypatch.setattr(G, "DB_ACHADOS", ach)
    monkeypatch.setattr(G, "DB_ABERTOS", ab)
    monkeypatch.setattr(G, "SUSPEITAS", tmp_path / "suspeitas.json")
    monkeypatch.setattr(G, "VAULT_CASOS", tmp_path / "casos")
    G._CACHE.clear()
    return G


# ── parsers ────────────────────────────────────────────────────────────────────────────────────────────────
def test_decreto_numerado_so_o_assinado_pelo_governador_e_na_gestao(bases):
    ds = bases.extrair_decretos(_DOE_DECRETOS + _DOE_ANTERIOR)
    assert [d["numero"] for d in ds] == ["50.900", "50.901"]     # 50.800 é do anterior; 50.902 é só citado
    d = ds[0]
    assert d["data"] == "2026-04-09" and d["categoria"] == "orçamentário"
    assert d["ementa"].startswith("ABRE CRÉDITO SUPLEMENTAR") and "VALOR GLOBAL" in d["ementa"]  # hífen de linha
    assert d["valor_ementa"] == pytest.approx(1234567.89)
    assert ds[1]["categoria"] == "auditoria e controle" and "AUDITORIA" in ds[1]["ementa"]


def test_ato_de_pessoal_so_primeiro_escalao(bases):
    atos = bases.extrair_atos_pessoal(_DOE_PESSOAL)
    assert [(a["ato"], a["nome"]) for a in atos] == [("EXONERAR", "BELTRANO DE EXEMPLO"),
                                                      ("NOMEAR", "SICRANA FICTICIA")]
    assert atos[0]["data"] == "2026-03-24" and "Secretaria de Estado de Testes" in atos[0]["orgao"]


def test_cpf_sempre_mascarado():
    assert G.doc_exibivel("12345678901")[0] == "CPF"
    assert "12345678901" not in G.doc_exibivel("12345678901")[1]
    assert G.doc_exibivel("11111111000111") == ("CNPJ", "11111111000111")
    assert "123.456.789-01" not in G.mascarar_texto("CPF 123.456.789-01 no texto")


# ── blocos ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_montar_recorta_pela_gestao_e_declara_fonte(bases):
    r = bases.montar()
    assert r["ok"] and r["gestao"]["inicio"] == "2026-03-23" and r["gestao"]["interina"] is True
    for bloco in ("atos", "contratacoes", "execucao", "controle", "pontos_atencao"):
        assert r[bloco].get("fonte") and r[bloco].get("cobertura") is not None, bloco
    atos = r["atos"]
    assert [d["numero"] for d in atos["decretos"]] == ["50.900", "50.901"]
    assert atos["decretos"][0]["url"] == "http://doe.exemplo/1"
    assert len(atos["pessoal"]) == 2 and atos["n_orcamentarios"] == 1


def test_contratacoes_modalidade_cancelado_e_detectores(bases):
    c = bases.montar()["contratacoes"]
    assert "98765432100" not in json.dumps(bases.montar())                  # CPF no nome do MEI mascarado
    assert c["n"] == 4 and c["valor"] == pytest.approx(1800.0)      # fora: antes da gestão e cancelado
    assert c["n_cancelados"] == 1
    mods = {m["modalidade"]: m["n"] for m in c["por_modalidade"]}
    assert mods == {"Licitação ou sem registro de contratação direta": 2, "Dispensa — emergencial (art. 75, VIII)": 1,
                    "Inexigibilidade": 1}
    por_id = {x["processo"]: x for x in c["lista"]}
    assert por_id["SEI-2"]["marcas"][0]["fonte"] == "detector"       # achado confirmado do detector
    assert por_id["SEI-1"]["marcas"][0]["grau"] == "🟡"               # perícia do fornecedor
    pf = por_id["SEI-3"]
    assert pf["doc_tipo"] == "CPF" and "12345678901" not in json.dumps(c)
    assert c["aditivos"]["n"] == 1 and c["aditivos"]["valor_acrescido"] == pytest.approx(50.0)


def test_execucao_so_ob_contabilizada_do_siafe_e_comparacao(bases):
    e = bases.montar()["execucao"]
    assert e["pago"] == pytest.approx(500.0)                 # anulada e OB de antes da gestão ficam fora
    assert e["n_obs"] == 2 and e["fim"] == "2026-05-12"
    assert e["anterior"]["pago"] == pytest.approx(250.0)     # 23/03–12/05 de 2025; dezembro fica fora
    org = {o["orgao"]: o for o in e["por_orgao"]}
    assert org["10"]["nome"] == "Secretaria X" and org["10"]["pago"] == pytest.approx(400.0)
    assert "12345678901" not in json.dumps(e)
    assert e["n_nao_contabilizadas"] == 1


def test_controle_auditorias_e_tce(bases):
    k = bases.montar()["controle"]
    assert len(k["auditorias_50254"]["itens"]) >= 1 and k["auditorias_50254"]["itens"][0]["url"]
    assert k["tce"]["n"] == 1 and k["tce"]["valor"] == pytest.approx(10.0)
    assert k["tce_decisoes"]["estado"] == "indisponivel"
    assert k["pericias"]["n"] == 1                          # credor pago no período com perícia 🟡


def test_pontos_de_atencao_ausente_e_presente(bases):
    p = bases.montar()["pontos_atencao"]
    assert p["estado"] == "em_andamento" and p["itens"] == []
    bases.SUSPEITAS.write_text(json.dumps([
        {"id": "x1", "camada": "deterministica", "regra_ou_hipotese": "regra", "grau": "🟡", "orgao": "SEX",
         "processo": "SEI-1", "valor_ob": 10.0, "fonte": "SIAFE", "explicacao_inocente": "pode ser regular",
         "proximo_passo": "ler"},
        {"id": "x2", "camada": "subjetiva", "regra_ou_hipotese": "hip", "grau": "🔴", "orgao": "SEY",
         "processo": "SEI-2", "valor_ob": None, "fonte": "DOERJ", "explicacao_inocente": "",
         "proximo_passo": "ler", "nota": "CPF 123.456.789-01"}]), encoding="utf-8")
    p = bases.montar()["pontos_atencao"]
    assert p["estado"] == "ok" and [i["id"] for i in p["itens"]] == ["x2", "x1"]      # 🔴 primeiro
    assert p["itens"][0]["explicacao_inocente"]           # nunca vazia: placeholder honesto
    assert p["por_camada"] == {"deterministica": 1, "subjetiva": 1}
    assert "123.456.789-01" not in json.dumps(p)


def test_pontos_de_atencao_arquivo_corrompido_nao_vira_vazio(bases):
    bases.SUSPEITAS.write_text("{quebrado", encoding="utf-8")
    p = bases.montar()["pontos_atencao"]
    assert p["estado"] == "erro" and p["erro"]


def test_bloco_quebrado_vira_indisponivel_sem_derrubar_a_aba(bases, monkeypatch):
    def _quebra(*a, **k):
        raise sqlite3.OperationalError("no such table: ob_orcamentaria_siafe")
    monkeypatch.setattr(bases, "_execucao", _quebra)
    bases._CACHE.clear()
    r = bases.montar()
    assert r["ok"] and r["execucao"]["estado"] == "indisponivel" and "ob_orcamentaria" in r["execucao"]["erro"]
    assert r["placar"]["pago"] is None                     # INDISPONÍVEL ≠ 0


def test_rota_devolve_payload_e_rele_pontos(bases, monkeypatch, tmp_path):
    from rotas import governo_couto as R
    from rotas import investigacao as inv
    monkeypatch.setattr(inv, "_CACHE_DIR", tmp_path / "cache")           # nunca escrever no data/ real
    monkeypatch.setattr(inv, "_cache", {})
    r = json.loads(R.api_governo_couto().body)
    assert r["ok"] and r["pontos_atencao"]["estado"] == "em_andamento"
    bases.SUSPEITAS.write_text(json.dumps([{"id": "z", "camada": "subjetiva", "grau": "🟡"}]), encoding="utf-8")
    r = json.loads(R.api_governo_couto().body)                           # base em cache, pontos relidos
    assert r["pontos_atencao"]["estado"] == "ok" and r["placar"]["pontos_atencao"] == 1


def test_placar(bases):
    p = bases.montar()["placar"]
    assert p["decretos"] == 2 and p["contratacoes"] == 4 and p["pago"] == pytest.approx(500.0)
    assert p["diretas"] == 2 and p["nomeacoes"] == 1 and p["exoneracoes"] == 1


def test_pontos_de_atencao_aceita_envelope_achados(bases):
    """A análise grava {"achados": [...]} com metadados ao lado — tem de aparecer, não virar vazio."""
    bases.SUSPEITAS.write_text(json.dumps({"titulo": "t", "n_achados": 1, "achados": [
        {"id": "a1", "camada": "deterministica", "regra_ou_hipotese": "regra", "grau": "🟡", "orgao": "SEX",
         "processo": "SEI-1", "valor_ob": 1.0, "fonte": "SIAFE", "explicacao_inocente": "x", "proximo_passo": "y"}]}),
        encoding="utf-8")
    p = bases.montar()["pontos_atencao"]
    assert p["estado"] == "ok" and [i["id"] for i in p["itens"]] == ["a1"]
