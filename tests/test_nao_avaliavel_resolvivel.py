# -*- coding: utf-8 -*-
"""`nao_avaliavel` só quando FALTA dado — nunca quando o dado está em casa ou a regra não incide.

Medido em 11/11/2026 em `data/achados.db`: 5.247 itens `nao_avaliavel`. Uma parte grande não era
falta de dado nenhum:

* X7 — 1.082 contratos com aditivo e NENHUMA recomposição: o card "não se aplica". Isso é juízo
  determinado (descartado), como o X9 já fazia para supressão; gravar `nao_avaliavel` inflava a
  fatia "sem dado" em 1.082.
* C6 — 317 fornecedores com QSA cujos sócios simplesmente não aparecem como doadores nos 542.244
  registros de `doacoes_eleitorais`. Busca feita e vazia = resultado (descartado), não "faltam".
* C7/C8 — 285 cada: `sancoes_federais`, `siga_sancoes` e `registros_folha` estavam na base e o
  contexto do órgão não os entregava.
* J3 — 50 certames com valor estimado no edital e vencedor no PNCP sem `ordem_classificacao`.

O que exige COLETA NOVA continua `nao_avaliavel`, mas o motivo passa a dizer o que falta e de que
fonte viria — senão a fila de coleta não tem como ser montada a partir do registro.
"""
from __future__ import annotations

import pathlib
import sqlite3

import pytest

from compliance_agent import varredura_orgaos as V
from compliance_agent.detectores import REGISTRO


# ───────────────────────────── X7: não se aplica = descartado ─────────────────────────────────

def test_x7_sem_recomposicao_e_descartado_nao_se_aplica():
    r = REGISTRO["X7"].avaliar({"processo": "P-1", "valor_inicial": 1_000_000.0,
                                "aditivos": [{"tipo": "valor", "valor": 10.0},
                                             {"tipo": "prazo"}]})
    assert r.status == "descartado" and r.score == 0.0
    assert "não se aplica" in r.motivo_refutacao
    assert not r.motivo_refutacao.startswith("nao_avaliavel")


def test_x7_sem_aditivo_algum_continua_nao_avaliavel():
    assert REGISTRO["X7"].avaliar({"processo": "P-1"}).status == "nao_avaliavel"


# ───────────────────────────── C6: busca feita e vazia = descartado ───────────────────────────

def test_c6_qsa_com_base_consultada_sem_doacao_e_descartado():
    r = REGISTRO["C6"].avaliar({"processo": "11222333000144", "qsa": [{"nome": "FULANO DE TAL"}],
                                "doacoes": [],
                                "doacoes_consultadas_em": "doacoes_eleitorais (2018, 2022)"})
    assert r.status == "descartado" and r.score == 0.0
    assert "doacoes_eleitorais (2018, 2022)" in r.motivo_refutacao


def test_c6_sem_qsa_continua_nao_avaliavel_mesmo_com_base_consultada():
    r = REGISTRO["C6"].avaliar({"processo": "X", "qsa": [], "doacoes": [],
                                "doacoes_consultadas_em": "doacoes_eleitorais"})
    assert r.status == "nao_avaliavel"
    assert "socios_fornecedor" in r.motivo_refutacao     # diz de onde viria o QSA


def test_c6_doacoes_sem_marca_de_consulta_continua_nao_avaliavel():
    """Lista vazia sem a marca de consulta pode ser chamador que não buscou — não é juízo."""
    r = REGISTRO["C6"].avaliar({"processo": "X", "qsa": [{"nome": "A B"}], "doacoes": []})
    assert r.status == "nao_avaliavel"


# ───────────────────────────── C7: sanções ────────────────────────────────────────────────────

def test_c7_proibido_de_contratar_do_siga_e_impeditiva():
    r = REGISTRO["C7"].avaliar({
        "processo": "X", "data_referencia": "2024-05-01",
        "sancoes": [{"cadastro": "SIGA-RJ", "data_inicio": "2023-01-01", "data_fim": None,
                     "categoria": "Lei Federal 8.429/92, art. 12º (Proibido de Contratar)"}]})
    assert r.status == "confirmado" and r.valores["n_impeditivas"] == 1


def test_c7_data_proxy_nao_afirma_violacao_objetiva():
    """A data é a 1ª OB, não a assinatura: o grau desce um nível e o teste vira não aferível."""
    ctx = {"processo": "X", "data_referencia": "2024-05-01",
           "data_referencia_origem": "1ª OB do credor na UG (proxy)",
           "sancoes": [{"cadastro": "CEIS", "categoria": "Impedimento de licitar",
                        "data_inicio": "2024-01-01", "data_fim": "2025-01-01"}]}
    r = REGISTRO["C7"].avaliar(ctx)
    assert r.status == "confirmado"
    assert r.score < 1.0 and r.valores["teste_objetivo"] == "nao_aferivel"
    assert "proxy" in r.evidencia[0]


def test_c7_sancao_de_vigencia_incerta_e_nao_avaliavel_com_fonte():
    r = REGISTRO["C7"].avaliar({
        "processo": "X", "data_referencia": "2024-05-01", "sancoes": [],
        "sancoes_vigencia_incerta": [{"cadastro": "SIGA-RJ", "data_inicio": "2023-01-01",
                                      "categoria": "Lei 10.520/02 art. 7º (Impedimento)"}]})
    assert r.status == "nao_avaliavel"
    assert "SIGA" in r.motivo_refutacao and "término" in r.motivo_refutacao


def test_c7_sem_sancao_e_descartado():
    r = REGISTRO["C7"].avaliar({"processo": "X", "data_referencia": "2024-05-01", "sancoes": []})
    assert r.status == "descartado"


# ───────────────────────────── contexto do fornecedor (órgão) ─────────────────────────────────

_DDL = """
CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT,
    credor TEXT, nome_credor TEXT, processo TEXT, re TEXT, valor REAL, exercicio INTEGER,
    status TEXT);
CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT,
    socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT, cpf_resolvido TEXT);
CREATE TABLE doacoes_eleitorais (id INTEGER, cpf_cnpj_doador TEXT, nome_doador TEXT,
    nome_candidato TEXT, cargo_candidato TEXT, partido TEXT, uf TEXT, valor REAL,
    ano_eleicao INTEGER);
CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT, categoria TEXT,
    data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT, fundamentacao TEXT);
CREATE TABLE siga_sancoes (id_sancao TEXT, nome TEXT, doc TEXT, tipo_doc TEXT,
    enquadramento TEXT, data_efetivacao TEXT, orgao_apenador TEXT, status TEXT, visto_em TEXT);
CREATE TABLE registros_folha (id INTEGER, pessoa_id INTEGER, cpf TEXT, nome TEXT,
    orgao_codigo TEXT, orgao_nome TEXT, cargo TEXT, vinculo TEXT, competencia TEXT,
    remuneracao_bruta REAL, remuneracao_liquida REAL, abonos REAL, descontos REAL, fonte TEXT,
    created_at TEXT, matricula TEXT);
"""
_CNPJ = "11222333000144"


@pytest.fixture()
def base(tmp_path):
    caminho = tmp_path / "compliance.db"
    con = sqlite3.connect(caminho)
    con.executescript(_DDL)
    # data_emissao é TEXTO DD/MM/AAAA: o min() lexicográfico daria 01/10/2024, a 1ª é 16/12/2022
    for i, d in enumerate(("01/10/2024", "16/12/2022", "05/03/2023")):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"OB{i}", "133100", d, _CNPJ, "ACME", "P", "RE", 100.0, 2024, "PAGO"))
    con.execute("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?,?)",
                (_CNPJ, "ACME", "JOSÉ DA SILVA", "jose da silva", "***364817**",
                 "Sócio-Administrador", "2026-01-01", None))
    con.execute("INSERT INTO doacoes_eleitorais VALUES (1,'99999999999','OUTRA PESSOA','C','D',"
                "'P','RJ',10.0,2022)")
    con.commit()
    con.close()
    return caminho


def _ctx(base):
    V._INDICE_FOLHA.clear()
    return V.contexto_fornecedor(V.abrir_leitura(str(base)), _CNPJ, "133100")


def test_ctx_marca_doacoes_consultadas_quando_ha_qsa_e_busca_vazia(base):
    ctx = _ctx(base)
    assert "doacoes" not in ctx or ctx["doacoes"] == []
    assert "doacoes_eleitorais" in ctx["doacoes_consultadas_em"] and "2022" in ctx[
        "doacoes_consultadas_em"]


def test_ctx_data_referencia_e_a_primeira_ob_em_ordem_cronologica(base):
    ctx = _ctx(base)
    assert ctx["data_referencia"] == "2022-12-16"
    assert "proxy" in ctx["data_referencia_origem"]
    assert ctx["pagamentos"]["primeira_data"] == "2022-12-16"


def test_ctx_traz_sancoes_federais_e_siga(base):
    con = sqlite3.connect(base)
    con.execute("INSERT INTO sancoes_federais VALUES ('CEIS',?,'ACME','Impedimento',"
                "'2020-01-01','2021-01-01','X','RJ','',''); ", (_CNPJ,))
    con.execute("INSERT INTO siga_sancoes VALUES ('1','ACME',?,'cnpj',"
                "'Lei Federal Nº 8.666/93, art. 87, Inc. III. (Suspensão)','10/01/2022','SEFAZ',"
                "'Vigente','2026-11-09')", (_CNPJ,))
    con.execute("INSERT INTO siga_sancoes VALUES ('2','ACME',?,'cnpj',"
                "'Lei Federal Nº 10.520/02, art. 7º. (Impedimento)','10/01/2021','SEFAZ',"
                "'Decorrido','2026-11-09')", (_CNPJ,))
    con.execute("INSERT INTO siga_sancoes VALUES ('3','ACME',?,'cnpj',"
                "'Lei Federal Nº 8.666/93, art. 87, Inc. II. (Multa)','10/01/2021','SEFAZ',"
                "'Multado','2026-11-09')", (_CNPJ,))
    con.commit()
    con.close()
    ctx = _ctx(base)
    cads = sorted(s["cadastro"] for s in ctx["sancoes"])
    assert cads == ["CEIS", "SIGA-RJ"]
    siga = next(s for s in ctx["sancoes"] if s["cadastro"] == "SIGA-RJ")
    assert siga["data_inicio"] == "2022-01-10" and siga["data_fim"] is None
    # 'Decorrido' sem data final e iniciado antes da referência: vigência incerta, declarada
    assert len(ctx["sancoes_vigencia_incerta"]) == 1
    r = REGISTRO["C7"].avaliar(dict(ctx, processo=_CNPJ))
    assert r.status == "confirmado"           # a suspensão vigente basta


def test_ctx_sem_sancao_alguma_vira_descartado_no_c7(base):
    r = REGISTRO["C7"].avaliar(dict(_ctx(base), processo=_CNPJ))
    assert r.status == "descartado"


def test_ctx_traz_socios_e_servidores_para_o_c8(base):
    con = sqlite3.connect(base)
    # a folha mostra D3-D8; o fragmento comum D4-D8 = '36481' casa com a RFB '364817'
    con.execute("INSERT INTO registros_folha (id, cpf, nome, orgao_nome, cargo, vinculo, fonte) "
                "VALUES (1,'XX036481XXX','Jose da Silva','SEEDUC','PROFESSOR','EFETIVO','gesperj')")
    con.execute("INSERT INTO registros_folha (id, cpf, nome, orgao_nome, cargo, vinculo, fonte) "
                "VALUES (2,'XX000000XXX','MARIA SOUZA','SES','MEDICO','EFETIVO','gesperj')")
    con.commit()
    con.close()
    ctx = _ctx(base)
    assert ctx["socios"][0]["qualificacao"] == "Sócio-Administrador"
    assert [s["nome"] for s in ctx["servidores"]] == ["Jose da Silva"]
    r = REGISTRO["C8"].avaliar(dict(ctx, processo=_CNPJ))
    assert r.status == "confirmado"


def test_ctx_folha_vazia_para_o_qsa_e_juizo_descartado(base):
    r = REGISTRO["C8"].avaliar(dict(_ctx(base), processo=_CNPJ))
    assert r.status == "descartado"


def test_ctx_sem_tabela_de_folha_nao_entrega_servidores(tmp_path):
    caminho = tmp_path / "min.db"
    con = sqlite3.connect(caminho)
    con.executescript("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, ug_emitente TEXT, "
                      "valor REAL, exercicio INTEGER, data_emissao TEXT);"
                      "CREATE TABLE socios_fornecedor (cnpj TEXT, socio_nome TEXT, "
                      "socio_doc TEXT, cpf_resolvido TEXT, qualificacao TEXT);")
    con.execute("INSERT INTO socios_fornecedor VALUES (?, 'A B', NULL, NULL, 'Sócio')", (_CNPJ,))
    con.commit()
    con.close()
    V._INDICE_FOLHA.clear()
    ctx = V.contexto_fornecedor(V.abrir_leitura(str(caminho)), _CNPJ, "133100")
    assert "servidores" not in ctx and "sancoes" not in ctx
    assert "doacoes_consultadas_em" not in ctx


# ───────────────────────────── J3: valor homologado pareado por item ──────────────────────────

def _base_certame(tmp_path, itens_json, resultados):
    caminho = tmp_path / "c.db"
    con = sqlite3.connect(caminho)
    con.executescript("""
        CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT,
            municipio TEXT, modalidade INTEGER, objeto TEXT, data_pub TEXT, item INTEGER,
            fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
            ordem_classificacao INTEGER, porte_fornecedor INTEGER);
        CREATE TABLE edital_documento (numero_controle_pncp TEXT, ano INTEGER, orgao_cnpj TEXT,
            objeto TEXT, material_servico TEXT, valor_estimado REAL, texto TEXT, itens_json TEXT);
    """)
    con.execute("INSERT INTO edital_documento VALUES ('C-1',2025,'O','obj','S',?,NULL,?)",
                (sum(i["valorTotal"] for i in __import__("json").loads(itens_json)), itens_json))
    for item, cnpj, valor, cls in resultados:
        con.execute("INSERT INTO pncp_resultado VALUES ('C-1','O','ORG','RJ','RIO',6,'obj',"
                    "'2025-01-01',?,?,'F',?,?,1)", (item, cnpj, valor, cls))
    con.commit()
    con.close()
    ro = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    return ro


def test_j3_pareia_item_homologado_sem_classificacao(tmp_path):
    from compliance_agent.varredura_certames_ctx import montar_contexto
    itens = ('[{"numeroItem": 1, "valorTotal": 1000.0, "situacaoCompraItemNome": "Homologado"},'
             ' {"numeroItem": 2, "valorTotal": 500.0, "situacaoCompraItemNome": "Homologado"}]')
    ctx = montar_contexto(_base_certame(tmp_path, itens, [(1, "A", 800.0, None),
                                                          (2, "B", 450.0, None)]), "C-1")
    assert ctx["valor_homologado"] == pytest.approx(1250.0)
    assert ctx["valor_estimado"] == pytest.approx(1500.0)
    r = REGISTRO["J3"].avaliar(ctx)
    assert r.status != "nao_avaliavel"


def test_j3_nao_pareia_quando_falta_resultado_de_algum_item(tmp_path):
    """Homologado parcial contra estimado total inventaria desconto — não preenche."""
    from compliance_agent.varredura_certames_ctx import montar_contexto
    itens = ('[{"numeroItem": 1, "valorTotal": 1000.0, "situacaoCompraItemNome": "Homologado"},'
             ' {"numeroItem": 2, "valorTotal": 500.0, "situacaoCompraItemNome": "Homologado"}]')
    ctx = montar_contexto(_base_certame(tmp_path, itens, [(1, "A", 800.0, None)]), "C-1")
    assert "valor_homologado" not in ctx


def test_j3_nao_pareia_item_com_dois_resultados_sem_classificacao(tmp_path):
    from compliance_agent.varredura_certames_ctx import montar_contexto
    itens = '[{"numeroItem": 1, "valorTotal": 1000.0, "situacaoCompraItemNome": "Homologado"}]'
    ctx = montar_contexto(_base_certame(tmp_path, itens, [(1, "A", 800.0, None),
                                                          (1, "B", 900.0, None)]), "C-1")
    assert "valor_homologado" not in ctx


# ───────────────────────────── o que exige coleta: motivo com a fonte ─────────────────────────

@pytest.mark.parametrize("det, ctx, fonte", [
    ("J3", {"processo": "C", "valor_homologado": 10.0}, "edital_documento"),
    ("J3", {"processo": "C", "valor_estimado": 10.0}, "pncp_resultado"),
    ("X8", {"processo": "K", "vigencia_fim": "2025-01-01", "aditivos": [{"tipo": "valor"}]},
     "dataAssinatura"),
    ("J2", {"processo": "C", "propostas": [{"cnpj": "A", "valor": 1.0, "classificacao": 1}]},
     "ata de julgamento"),
    ("E1", {"processo": "C"}, "coletor_edital"),
    ("E7", {"processo": "C"}, "coletor_edital"),
    ("P1", {"processo": "C"}, "coletor_edital"),
    ("P2", {"processo": "C"}, "pesquisa de preços"),
    ("P3", {"processo": "C"}, "pncp_resultado"),
    ("C9", {"processo": "C", "tac": {"cobertura": "INDISPONIVEL (sem pagamentos)", "n": 0}},
     "ordens_bancarias"),
])
def test_nao_avaliavel_por_coleta_diz_o_que_falta_e_a_fonte(det, ctx, fonte):
    r = REGISTRO[det].avaliar(ctx)
    assert r.status == "nao_avaliavel"
    assert fonte in r.motivo_refutacao, r.motivo_refutacao


# ───────────────────────────── reprocessamento dirigido ───────────────────────────────────────

def test_reprocessar_simulado_nao_grava_e_resolve_c6_c7(base, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "reproc", pathlib.Path(__file__).resolve().parent.parent / "tools"
        / "reprocessar_nao_avaliavel.py")
    reproc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reproc)

    ach = V.abrir_achados(str(tmp_path / "achados.db"))
    for det in ("C6", "C7"):
        ach.execute("INSERT INTO achado_detector (ug, detector, processo, status) "
                    "VALUES ('133100', ?, ?, 'nao_avaliavel')", (det, _CNPJ))
    ach.commit()
    V._INDICE_FOLHA.clear()
    conta = reproc.reprocessar(V.abrir_leitura(str(base)), ach, escopos=("ug",), log=lambda *_: 0)
    assert conta[("C6", "descartado")] == 1 and conta[("C7", "descartado")] == 1
    assert ach.execute("SELECT COUNT(*) FROM achado_detector WHERE status='nao_avaliavel'"
                       ).fetchone()[0] == 2, "simulação não pode gravar"
