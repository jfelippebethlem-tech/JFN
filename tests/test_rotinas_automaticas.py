# -*- coding: utf-8 -*-
"""Rotinas automáticas do painel (13/11/2026): esqueleto comum, perícia contábil diária, regras da gestão Couto,
confronto CGE × JFN e a rota dos achados dos detectores. Dados 100% SINTÉTICOS (repositório público)."""
import json
import sqlite3
import sys
import types

import pytest

from compliance_agent import rotina_base as RB


# ───────────────────────── esqueleto comum ─────────────────────────

def test_trava_por_arquivo_impede_execucao_simultanea(tmp_path):
    t = tmp_path / "x.lock"
    with RB.trava(t):
        with pytest.raises(RB.TravaOcupada):
            with RB.trava(t):
                pass
    with RB.trava(t):          # solta ao sair
        pass


def test_executar_com_trava_ocupada_sai_zero_sem_rodar(tmp_path, monkeypatch):
    monkeypatch.setattr(RB, "DATA", tmp_path)
    rodou = []
    with RB.trava(tmp_path / "r_teste_ocupada.lock"):
        assert RB.executar("r_teste_ocupada", lambda log: rodou.append(1)) == 0
    assert not rodou


def test_executar_falha_vira_rc_1_e_log_com_data(tmp_path, monkeypatch):
    monkeypatch.setattr(RB, "DATA", tmp_path)

    def quebra(log):
        raise ValueError("boom")
    assert RB.executar("r_teste_falha", quebra) == 1
    linhas = (tmp_path / "r_teste_falha.log").read_text(encoding="utf-8").splitlines()
    assert linhas and all(len(x) > 19 and x[4] == "-" and x[13] == ":" for x in linhas if x and x[0].isdigit())


def test_gravar_json_atomico(tmp_path):
    p = tmp_path / "a" / "b.json"
    RB.gravar_json(p, {"x": "ç"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": "ç"}
    assert not [f for f in p.parent.iterdir() if f.name.startswith(".b.json")]


def _motor_falso(monkeypatch, fn):
    mod = types.ModuleType("compliance_agent.llm.claude_motor")
    mod.pensar = fn
    monkeypatch.setitem(sys.modules, "compliance_agent.llm.claude_motor", mod)
    import compliance_agent.llm as llm
    monkeypatch.setattr(llm, "claude_motor", mod, raising=False)


def test_pensar_sem_motor_devolve_pendente(monkeypatch):
    monkeypatch.setitem(sys.modules, "compliance_agent.llm.claude_motor", None)   # import falha
    r, motivo = RB.pensar("t", "p")
    assert r is None and "ausente" in motivo


@pytest.mark.parametrize("resposta,esperado,tem_motivo", [
    ('{"a": 1}', {"a": 1}, False),
    ({"a": 1}, {"a": 1}, False),
    ((None, "sem cota"), None, True),
    (None, None, True),
    ("não é json", None, True),
])
def test_pensar_aceita_as_formas_do_motor(monkeypatch, resposta, esperado, tem_motivo):
    _motor_falso(monkeypatch, lambda tarefa, prompt, schema=None, **kw: resposta)
    r, motivo = RB.pensar("t", "p", schema={"type": "object"})
    assert r == esperado and bool(motivo) == tem_motivo


def test_pensar_aceita_pensamento_do_motor_e_guarda_o_modelo(monkeypatch):
    class Pensamento:                                   # forma real de compliance_agent.llm.claude_motor
        def __init__(self, texto, dados, modelo):
            self.texto, self.dados, self.modelo = texto, dados, modelo
    _motor_falso(monkeypatch, lambda tarefa, prompt, schema=None, **kw: Pensamento('{"a": 2}', {"a": 2}, "m-teste"))
    r, motivo = RB.pensar("camada_subjetiva", "p", schema={"type": "object"})
    assert r == {"a": 2} and motivo is None and RB.ULTIMO_MODELO == "m-teste"


def test_pensar_none_usa_ultimo_motivo_do_motor(monkeypatch):
    _motor_falso(monkeypatch, lambda *a, **k: None)
    import compliance_agent.llm as llm
    monkeypatch.setattr(llm.claude_motor, "ultimo_motivo", "teto diário da tarefa", raising=False)
    r, motivo = RB.pensar("t", "p")
    assert r is None and motivo == "teto diário da tarefa"


def test_pensar_motor_que_explode_nao_derruba(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("429")
    _motor_falso(monkeypatch, explode)
    r, motivo = RB.pensar("t", "p")
    assert r is None and "429" in motivo


# ───────────────────────── perícia contábil (resumo) ─────────────────────────

def _linha(pc, cat, **kw):
    esfera = kw.pop("esfera", pc.ESTADO)
    base = dict(id=kw.pop("id", cat), categoria=cat, orgao="SECRETARIA X", ug="100100", contrato="1/2025",
                fornecedor="EMPRESA FICTICIA LTDA", fornecedor_doc="00.000.000/0001-00", objeto="SERVICO",
                corte="2026-11-10", fonte_pago="SIAFE — OB Contabilizada")
    base.update(kw)
    return pc._resultado_base(esfera, **base)


def test_resumir_placar_a_maior_duplicidade_e_motivos():
    from compliance_agent import pericia_contabil as pc
    from compliance_agent.pericia_contabil_rotina import resumir
    rs = [
        _linha(pc, "CONFORME", devido=100.0, pago=100.0),
        _linha(pc, "A_MAIOR", id="a", devido=100.0, pago=300.0, diferenca=200.0, subtipo="acima_do_valor_global",
               valor_atualizado=150.0, excesso_global=150.0),
        _linha(pc, "A_MAIOR", id="b", devido=100.0, pago=150.0, diferenca=50.0, subtipo="acima_do_pro_rata",
               obs_mesma_nl=2, valor_mesma_nl=80.0),
        _linha(pc, "INDETERMINADO", motivo="vinculo_ambiguo"),
        _linha(pc, "INDETERMINADO", motivo="vinculo_ambiguo"),
        _linha(pc, "A_MENOR_EM_CURSO", esfera=pc.PREFEITURA, devido=100.0, pago=50.0, diferenca=-50.0),
    ]
    r = resumir(rs)
    e = r["esferas"][pc.ESTADO]
    assert e["n"] == 5 and e["placar"]["A_MAIOR"] == 2 and e["placar"]["INDETERMINADO"] == 2
    assert [x["diferenca"] for x in e["a_maior"]] == [200.0, 50.0]          # maior diferença primeiro
    assert e["duplicidades"]["n_contratos"] == 1 and e["duplicidades"]["valor_repetido"] == 80.0
    assert e["motivos_indeterminado"][0]["motivo"] == "vinculo_ambiguo" and e["motivos_indeterminado"][0]["n"] == 2
    assert pc.PREFEITURA in r["esferas"] and r["esferas"][pc.PREFEITURA]["n"] == 1   # esferas separadas
    assert r["esferas"][pc.PREFEITURA]["duplicidades"]["aferivel"] is False          # não aferível ≠ zero
    assert r["esferas"][pc.PREFEITURA]["duplicidades"]["n_contratos"] is None


def test_resumir_mascara_cpf_em_texto():
    from compliance_agent import pericia_contabil as pc
    from compliance_agent.pericia_contabil_rotina import resumir
    r = resumir([_linha(pc, "A_MAIOR", diferenca=10.0, fornecedor="JOAO 12345678901 MEI", pago=20.0, devido=10.0)])
    assert "12345678901" not in json.dumps(r, ensure_ascii=False)


# ───────────────────────── gestão Couto — regras ─────────────────────────

@pytest.fixture()
def base_couto(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, nl TEXT,
        credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER);
    CREATE TABLE despesa_execucao (ug TEXT, nome_ug TEXT);
    CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT, data_inicio TEXT,
        data_fim TEXT, orgao TEXT, fundamentacao TEXT);
    """)
    c.executemany("INSERT INTO despesa_execucao VALUES (?,?)", [("100100", "SECRETARIA FICTICIA"),
                                                                 ("200200", "TRIBUNAL FICTICIO")])
    obs = [
        ("1", "100100", "10/05/2026", "Contabilizado", "11111111000111", "ALFA SERVICOS LTDA", 9_000_000.0, 2026),
        ("2", "100100", "11/05/2026", "Contabilizado", "22222222000122", "BETA OBRAS LTDA", 2_000_000.0, 2026),
        ("3", "100100", "12/05/2025", "Contabilizado", "22222222000122", "BETA OBRAS LTDA", 5_000_000.0, 2025),
        ("4", "100100", "12/05/2025", "Contabilizado", "33333333000133", "GAMA LTDA", 5_000_000.0, 2025),
        ("5", "100100", "13/05/2026", "Anulado", "11111111000111", "ALFA SERVICOS LTDA", 1_000.0, 2026),
        ("6", "100100", "10/11/2026", "Contabilizado", "22222222000122", "BETA OBRAS LTDA", 10.0, 2026),
    ]
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,NULL,?,?,'SEI-100001/000001/2026',?,?)",
                  [o[:6] + o[6:] for o in obs])
    c.execute("INSERT INTO sancoes_federais VALUES ('CEIS','11.111.111/0001-11','ALFA','Impedimento de licitar',"
              "'2026-01-01',NULL,'ORGAO SANCIONADOR FICTICIO','lei')")
    c.commit()
    c.close()
    return db


def test_regras_calculam_e_fonte_ausente_e_indisponivel(base_couto, tmp_path):
    from compliance_agent import governo_couto_regras as GR
    c = GR.Ctx(base_couto, receita=None, tse=None, dir_tmp=tmp_path)
    try:
        assert c.GFIM == "2026-11-10" and c.G1 == "2026-10-31" and c.B0 == "2025-03-23"
        res = GR.calcular(c)
    finally:
        c.fechar()
    assert set(res) == set(GR.REGRAS)
    d14 = res["D14"]
    assert d14["n_executivo"] == 1 and d14["casos"][0]["pago_ob"] == 9_000_000.0     # Anulada fora da soma
    d10 = res["D10"]
    assert [x["cnpj"] for x in d10["casos"]] == ["11111111000111"]                 # BETA tem histórico
    assert res["D05"]["n"] == 1 and res["D05"]["casos"][0]["tipo"] == "NOVA"
    assert res["D20"]["n"] == 1                                                      # OB anulada contada à parte
    for k in ("D03", "D04", "D13", "D15", "D16", "D19"):                            # fonte ausente
        assert res[k].get("indisponivel") and res[k]["n"] is None                   # INDISPONÍVEL ≠ zero


def test_montar_preserva_top10_e_marca_hipoteses_pendentes(base_couto, tmp_path):
    from compliance_agent import governo_couto_regras as GR
    c = GR.Ctx(base_couto, receita=None, tse=None, dir_tmp=tmp_path)
    try:
        res = GR.calcular(c)
    finally:
        c.fechar()
    anterior = {"achados": [
        {"id": "T01", "camada": "deterministica", "top10": True, "grau": "🔴", "regra_ou_hipotese": "curado"},
        {"id": "H1", "camada": "subjetiva", "grau": "🟡", "regra_ou_hipotese": "hipótese velha",
         "explicacao_inocente": "x", "proximo_passo": "y"},
        {"id": "D05", "camada": "deterministica", "grau": "🟡"},
    ]}
    info = dict(gerado_em="2026-11-15T03:00:00", GFIM="2026-11-10", G1="2026-10-31", B0="2025-03-23", B1="2025-10-31")
    doc = GR.montar(res, anterior=anterior, hipoteses=None, motivo_subj="sem cota", ctx_info=info)
    ids = [x["id"] for x in doc["achados"]]
    assert ids[0] == "T01" and "curadoria" in doc["achados"][0]
    assert ids.count("D05") == 1                                         # regra recalculada, não duplicada
    h = [x for x in doc["achados"] if x["id"] == "H1"][0]
    assert h["pendente"] is True and doc["camada_subjetiva"]["estado"] == "pendente"
    assert all(x.get("explicacao_inocente") for x in doc["achados"] if x.get("tipo") in ("regra", "caso"))
    assert any(x["id"] == "D14" and x["grau"] == "🔴" for x in doc["achados"])
    assert any(x["id"] == "D03" and "INDISPONÍVEL" in x["regra_ou_hipotese"] for x in doc["achados"])


def test_envelope_e_lido_pela_aba(base_couto, tmp_path, monkeypatch):
    from compliance_agent import governo_couto as G
    from compliance_agent import governo_couto_regras as GR
    c = GR.Ctx(base_couto, receita=None, tse=None, dir_tmp=tmp_path)
    try:
        res = GR.calcular(c)
    finally:
        c.fechar()
    info = dict(gerado_em="2026-11-15T03:00:00", GFIM="2026-11-10", G1="2026-10-31", B0="2025-03-23", B1="2025-10-31")
    hip = GR.hipoteses_validas({"hipoteses": [{"id": "H1", "regra_ou_hipotese": "padrão X", "grau": "🟡",
                                               "confianca": "média", "explicacao_inocente": "y", "proximo_passo": "z"}]})
    doc = GR.montar(res, anterior=None, hipoteses=hip, motivo_subj=None, ctx_info=info)
    arq = tmp_path / "s.json"
    RB.gravar_json(arq, doc)
    monkeypatch.setattr(G, "SUSPEITAS", arq)
    p = G._pontos_atencao()
    assert p["estado"] == "ok" and p["por_camada"].get("subjetiva") == 1 and p["por_camada"].get("deterministica")


def test_hipotese_sem_explicacao_inocente_ou_passo_e_descartada():
    from compliance_agent.governo_couto_regras import hipoteses_validas
    h = hipoteses_validas([
        {"regra_ou_hipotese": "ok", "grau": "🔴", "explicacao_inocente": "a", "proximo_passo": "b"},
        {"regra_ou_hipotese": "sem inocente", "grau": "🔴", "explicacao_inocente": "", "proximo_passo": "b"},
        {"regra_ou_hipotese": "sem passo", "grau": "🔴", "explicacao_inocente": "a"},
        {"regra_ou_hipotese": "grau inventado", "grau": "🟢", "explicacao_inocente": "a", "proximo_passo": "b"},
    ])
    assert [x["regra_ou_hipotese"] for x in h] == ["ok"] and h[0]["camada"] == "subjetiva"


def test_extrair_creditos_do_texto_do_doerj():
    from compliance_agent.governo_couto_regras import extrair_creditos
    t = ("DECRETO Nº 50.111, DE 10 DE ABRIL DE 2026 ABRE CRÉDITO SUPLEMENTAR NO VALOR GLOBAL DE R$ 1.234.567,89 "
         "por anulação ... DECRETO Nº 50.112, DE 11 DE ABRIL DE 2026 DISPÕE SOBRE PONTO FACULTATIVO")
    r = extrair_creditos(t)
    assert len(r) == 1 and r[0]["decreto"] == "50111" and r[0]["data"] == "2026-04-10"
    assert r[0]["valor"] == pytest.approx(1234567.89) and r[0]["tipo"] == "suplementar"


# ───────────────────────── CGE × JFN ─────────────────────────

@pytest.mark.parametrize("bruto,esperado", [
    ("SEI-090002/000036/2025", "0900020000362025"), ("090002_000036_2025", "0900020000362025"),
    ("090002/000036/25", "0900020000362025"), ("E-12/123/2020", None), (None, None)])
def test_chave_cge(bruto, esperado):
    from compliance_agent.cge_confronto import chave
    assert chave(bruto) == esperado


def test_confrontar_recall_por_grau_e_indisponivel():
    from compliance_agent.cge_confronto import confrontar
    contr = [{"processo": "100001/000001/2026", "grau": "G1", "valor_contratado": 10.0},
             {"processo": "100001/000002/2026", "grau": "G2", "valor_contratado": 20.0},
             {"processo": "100001/000003/2026", "grau": "G0", "valor_contratado": 5.0}]
    fontes = {"autos": {"1000010000012026": 3}, "ficha": set(), "arvore": set(), "lex": set(), "veredito": set(),
              "fila": {"1000010000022026"}, "detector": {"1000010000022026": [{"detector": "P7", "status": "confirmado"}]},
              "caso": None, "ob": {"1000010000012026": [2, 99.5]}}
    r = confrontar(contr, fontes)
    m = r["metricas"]
    assert m["todas"]["n"] == 3 and m["todas"]["autos_lidos"] == 1 and m["G1+G2"]["com_sinal"] == 1
    assert m["G1+G2"]["com_artefato"] == 2 and m["G0"]["com_artefato"] == 0
    assert m["todas"]["na_fila_sem_leitura"] == 1 and r["linhas"][0]["ob_pago"] == 99.5
    assert r["linhas"][0]["casos"] is None and "caso" in r["fontes_indisponiveis"]   # INDISPONÍVEL ≠ vazio


def test_sem_prova_primaria_vermelho_nao_sobe_como_achado():
    from compliance_agent.governo_couto_regras import ROTULO_PENDENTE, aplicar_verificacao
    x = aplicar_verificacao({"id": "D16", "camada": "deterministica", "tipo": "regra", "grau": "🔴",
                             "regra_ou_hipotese": "TAC acelerou", "prova_primaria": []})
    assert x["verificacao"] == "PENDENTE" and x["grau"] == "⚪" and x["grau_proposto"] == "🔴"
    assert x["regra_ou_hipotese"].startswith(ROTULO_PENDENTE)
    assert aplicar_verificacao(x)["regra_ou_hipotese"].count(ROTULO_PENDENTE) == 1          # idempotente


def test_com_prova_primaria_fica_verificado_e_mantem_grau():
    from compliance_agent.governo_couto_regras import aplicar_verificacao
    x = aplicar_verificacao({"id": "D14-x", "camada": "deterministica", "tipo": "caso", "grau": "🔴",
                             "regra_ou_hipotese": "paga na vigência", "prova_primaria": ["OB 2026OB1 · UG 1"]})
    assert x["verificacao"] == "VERIFICADO" and x["grau"] == "🔴" and "grau_proposto" not in x


def test_hipotese_do_modelo_e_rotulada_e_nunca_fato():
    from compliance_agent.governo_couto_regras import ROTULO_HIPOTESE, aplicar_verificacao
    x = aplicar_verificacao({"id": "H1", "camada": "subjetiva", "tipo": "hipotese", "grau": "🔴",
                             "regra_ou_hipotese": "padrão", "explicacao_inocente": "a", "proximo_passo": "b",
                             "prova_primaria": ["qualquer"]})
    assert x["verificacao"] == "PENDENTE" and x["grau"] == "⚪" and x["regra_ou_hipotese"].startswith(ROTULO_HIPOTESE)
    assert "não é fato" in x["natureza"]


def test_casos_da_regua_citam_a_ob(base_couto, tmp_path):
    from compliance_agent import governo_couto_regras as GR
    c = GR.Ctx(base_couto, receita=None, tse=None, dir_tmp=tmp_path)
    try:
        res = GR.calcular(c)
    finally:
        c.fechar()
    p = res["D14"]["casos"][0]["prova_primaria"]
    assert p[0].startswith("OB 1 · UG 100100 · 2026-05-10") and "CEIS" in p[-1]
    assert res["D14"]["prova_primaria"][0].startswith("amostra conferível")
    assert all("2025-" not in q for q in res["D10"]["casos"][0]["prova_primaria"])   # prova só na janela da regra


def test_confronto_sem_lista_grava_indisponivel(tmp_path, monkeypatch):
    from compliance_agent import cge_confronto as CG
    monkeypatch.setattr(RB, "DATA", tmp_path)
    saida = tmp_path / "cge.json"
    assert CG.main(["--entrada", str(tmp_path / "nao_existe.json"), "--saida", str(saida)]) == 0
    d = json.loads(saida.read_text(encoding="utf-8"))
    assert d["estado"] == "indisponivel" and d["erro"]


# ───────────────────────── rota dos detectores ─────────────────────────

def test_resumir_achados_agrupa_e_mostra_semanal_sem_execucao():
    from rotas.pericias_rotinas import resumir_achados
    linhas = [
        ("100100", "C9", "11111111000111", "x", 0.9, "confirmado", "motivo A 123.456.789-01", "inocente", '{"v": 1}', "", "2026-11-01"),
        ("100100", "C9", "22222222000122", "x", 0.1, "descartado", "", "", None, "", "2026-11-02"),
        ("100100", "P7", "SEI-100001/000001/2026", "d", 0.7, "confirmado", "direta de risco", "", "{}", "", "2026-11-15"),
    ]
    r = resumir_achados(linhas)
    por = {d["detector"]: d for d in r["detectores"]}
    assert por["C9"]["n_confirmado"] == 1 and por["C9"]["por_status"] == {"confirmado": 1, "descartado": 1}
    assert por["P7"]["n_confirmado"] == 1 and por["P7"]["agenda"]
    assert por["EST-VALOR-EXCEDIDO"]["sem_execucao"] and por["EST-VALOR-EXCEDIDO"]["n_confirmado"] is None
    assert "456.789" not in json.dumps(r, ensure_ascii=False)                     # CPF mascarado
    assert r["detectores"][0]["detector"] in ("P7", "EST-VALOR-EXCEDIDO", "EST-ADITIVO-TETO")


def test_rota_de_rotina_sem_arquivo_diz_sem_execucao(tmp_path, monkeypatch):
    from rotas import pericias_rotinas as R
    monkeypatch.setattr(RB, "DATA", tmp_path)
    d = json.loads(R.api_pericia_contabil().body)
    assert d["ok"] and d["estado"] == "sem_execucao"
    RB.gravar_json(tmp_path / "cge_confronto.json", {"estado": "ok", "metricas": {}, "linhas": [], "x": "CPF 123.456.789-01"})
    d = json.loads(R.api_cge_confronto().body)
    assert d["estado"] == "ok" and "456.789" not in json.dumps(d, ensure_ascii=False)
