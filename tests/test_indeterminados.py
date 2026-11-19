# -*- coding: utf-8 -*-
"""Laudo de execução sem conclusão (indeterminado / sem_documento_execucao / sem veredito) → POR QUE e o que o resolve.

Frases reais do acervo (18/11/2026). O extrator de processos relacionados só aceita número com PAPEL dito no texto
(ata, contrato, licitação, origem/apensado/referência) ou citado por ≥ 2 documentos; precedente jurídico ("decidido
no processo administrativo…") e decreto não são família.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import indeterminados as I


# ── extrator de processos relacionados ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("texto, numero, papel", [
    ("ATA DE REGISTRO DE PRECOS 0003/2024-03 - PROCESSO ADMINISTRATIVO SEI-030029/002156/2022", "SEI-030029/002156/2022",
     "ata_rp"),
    ("Contrato 95 nº 25/2024 (MAQMÓVEIS) (86206349)         SEI SEI-030001/084333/2024", "SEI-030001/084333/2024",
     "contrato"),
    ("o constante dos autos do processo nº SEI-020002/001547/2022", "SEI-020002/001547/2022", "origem"),
    ("Contrato 036/2022, edital, TR e termos aditivos 1-3 (SEI-020007/002346/2022)", "SEI-020007/002346/2022",
     "contrato"),
    ("Pregão Eletrônico nº 12/2023, processo SEI 260005/448/2023", "SEI-260005/000448/2023", "licitacao"),
    ("Processo de origem: SEI-150001/011978/2024", "SEI-150001/011978/2024", "origem"),
    ("Ref.: Processo n.º SEI-330002/045543/2025 ·Processo Principal n.º SEI-330002/001090/2024",
     "SEI-330002/001090/2024", "origem"),
    ("atender ao Contrato n° 032/2023, Processo Administrativo SEI-080001/015138/2023", "SEI-080001/015138/2023",
     "contrato"),
])
def test_relacionado_com_papel(texto, numero, papel):
    r = I.relacionados(texto, proprio="SEI-999999/000001/2025")
    assert [(x["numero"], x["papel"]) for x in r] == [(numero, papel)]
    assert numero[4:10] in r[0]["trecho"]                                     # trecho literal do autos


@pytest.mark.parametrize("texto", [
    "Decidido no processo administrativo SEI-080002/012819/2024",            # precedente da PGE, não família
    "Decreto nº 45.046/2014. Processo nº SEI-030042/000147/2022",            # norma citada
    "SEI-030001/031633/2024",                                                # número solto, sem papel
    "- a documentação anexada ao processo n° SEI-080001/015475/2023",       # lista de deliberação da CIB
    "Origem 1 - Origem nacional Data Entrega Local Entrega Processo SEI-170002/002642/2022",   # origem do produto
])
def test_sem_papel_ou_precedente_fica_fora(texto):
    assert I.relacionados(texto, proprio="SEI-999999/000001/2025") == []


def test_o_proprio_processo_nao_e_relacionado():
    assert I.relacionados("Referência: Processo nº SEI-030001/016871/2025", proprio="SEI-030001/016871/2025") == []


def test_relacionados_dos_documentos_soma_citacao_solta_repetida():
    docs = [{"titulo": "Despacho", "texto": "ver SEI-030001/031633/2024"},
            {"titulo": "Ofício", "texto": "conforme SEI-030001/031633/2024"},
            {"titulo": "Publicação DOERJ", "texto": "contrato SEI-111111/000001/2024"}]   # página coletiva: fora
    r = I.relacionados_dos_documentos(docs, proprio="SEI-999999/000001/2025")
    assert [(x["numero"], x["papel"], x["n_docs"]) for x in r] == [("SEI-030001/031633/2024", "citado", 2)]


# ── causa ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _d(**kw):
    base = {"estado": "indeterminado", "arquivo": True, "n_docs": 30, "total_arvore": 30, "captura_vazia": False,
            "com_texto": 30, "exec": ["nota_fiscal"], "exec_sem_texto": 0, "pag": ["nota_liquidacao"],
            "contr": [], "sigilo": 0, "ob_n": 3, "relacionados_fora": [], "familia_conclusiva": []}
    base.update(kw)
    return base


def test_causa_sem_arquivo():
    assert I.causas(_d(arquivo=False))[0] == "sem_arquivo"


def test_causa_captura_truncada():
    assert I.causas(_d(n_docs=40, total_arvore=371))[0] == "captura_truncada"


def test_causa_texto_insuficiente_mede_pelo_texto():
    assert I.causas(_d(n_docs=20, com_texto=5))[0] == "sem_texto_ocr"


def test_causa_execucao_so_em_imagem():
    assert I.causas(_d(exec=["medicao"], exec_sem_texto=1))[0] == "execucao_so_em_imagem"


def test_processo_de_empenho_ou_contratacao_aponta_a_familia():
    c = I.causas(_d(estado="sem_documento_execucao", exec=[], pag=[], contr=["contrato"],
                    relacionados_fora=["SEI-1"], familia_conclusiva=[]))
    assert c[0] == "processo_relacionado_fora_do_acervo"
    c = I.causas(_d(estado="sem_documento_execucao", exec=[], pag=[], familia_conclusiva=["SEI-2"]))
    assert c[0] == "execucao_avaliada_na_familia"


def test_captura_integra_sem_execucao_e_lacuna_do_processo():
    """Captura íntegra, sem doc de execução e sem família: falta é DO PROCESSO (pesa como achado), não nossa."""
    c = I.causas(_d(estado="sem_documento_execucao", exec=[], pag=["nota_liquidacao"]))
    assert c[0] == "lacuna_do_processo"


def test_sem_varrer_os_autos_nao_afirma_lacuna_do_processo():
    c = I.causas(_d(estado="sem_documento_execucao", exec=[], autos_lidos=False))
    assert c[0] == "autos_nao_varridos"


def test_ob_nao_ligada_e_causa_secundaria():
    assert "ob_nao_ligada" in I.causas(_d(ob_n=0))


def test_sigilo():
    assert I.causas(_d(sigilo=3, n_docs=10, com_texto=4))[0] == "documento_sigiloso"


# ── fila ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _db(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sei_fila_captura (numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT,"
                " total_pago REAL, n_docs INTEGER, visto_em TEXT)")
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-000001/000001/2024','',"
                "'alvo à mão',5,0,'2026-01-01')")
    con.commit()
    return con


def test_enfileirar_nao_duplica_nem_rebaixa_e_usa_o_pago_do_filho(tmp_path):
    con = _db(tmp_path)
    alvos = [{"numero": "SEI-000001/000001/2024", "papel": "contrato", "filho": "SEI-9/9/2025", "pago_filho": 10.0,
              "estado_filho": "indeterminado"},
             {"numero": "SEI-000002/000002/2024", "papel": "ata_rp", "filho": "SEI-8/8/2025", "pago_filho": 7.5,
              "estado_filho": "sem_documento_execucao"},
             {"numero": "SEI-000002/000002/2024", "papel": "ata_rp", "filho": "SEI-7/7/2025", "pago_filho": 2.5,
              "estado_filho": "indeterminado"}]
    n = I.enfileirar(con, alvos, agora="2026-11-19T00:00:00")
    assert n == 1
    linhas = dict(con.execute("SELECT numero_sei, motivo FROM sei_fila_captura").fetchall())
    assert linhas["SEI-000001/000001/2024"] == "alvo à mão"                    # pedido à mão intacto
    assert linhas["SEI-000002/000002/2024"].startswith(I.MOTIVO)
    pago = con.execute("SELECT total_pago FROM sei_fila_captura WHERE numero_sei='SEI-000002/000002/2024'").fetchone()
    assert pago[0] == 10.0                                                      # soma dos filhos, dado real


# ── fontes externas ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def externas(tmp_path):
    con = sqlite3.connect(tmp_path / "x.db")
    con.executescript("""
        CREATE TABLE contratos_tcerj (id TEXT, sei_norm TEXT, cnpj TEXT, valor_contrato REAL, vig_inicio TEXT,
                                      vig_fim TEXT, fornecedor TEXT, valor_pago REAL);
        CREATE TABLE compras_diretas_tcerj (id TEXT, sei_norm TEXT, valor REAL, fornecedor TEXT,
                                            enquadramento_legal TEXT);
        CREATE TABLE siga_contratos (processo TEXT, id_contrato TEXT, cnpj TEXT, valor REAL, data TEXT, objeto TEXT,
                                     situacao TEXT, valor_pago_siga REAL);
        CREATE TABLE vinculo_ob_contrato (processo_pagamento TEXT, processo_contrato TEXT, contrato_tcerj_id TEXT,
                                          credor TEXT, estado TEXT, ob TEXT);
        CREATE TABLE publicacoes_doerj (id INTEGER PRIMARY KEY, data_publicacao TEXT, tipo_ato TEXT, titulo TEXT,
                                        texto TEXT, orgao TEXT);
        CREATE VIRTUAL TABLE fts_doerj USING fts5(titulo, texto, orgao, tipo_ato, content=publicacoes_doerj,
                                                  content_rowid=id);
    """)
    con.execute("INSERT INTO contratos_tcerj VALUES ('c1','0300290021562022','11222333000144',1000.5,'2022-01-01',"
                "'2023-01-01','EMPRESA A',10)")
    con.execute("INSERT INTO vinculo_ob_contrato VALUES ('030001/084333/2024','030029/002156/2022','c1','x',"
                "'VERIFICADO','2024OB001')")
    con.execute("INSERT INTO vinculo_ob_contrato VALUES ('030001/084333/2024','999999/000001/2022','c9','x',"
                "'PENDENTE','2024OB002')")
    textos = [(1, "EXTRATO DE CONTRATO. Processo SEI-030029/002156/2022. Contratada: EMPRESA A, CNPJ 11.222.333/0001-44"),
              (2, "Ato vizinho. Processo SEI-030029/002156/2022 citado. Contratada: OUTRA, CNPJ 55.666.777/0001-88")]
    for i, t in textos:
        con.execute("INSERT INTO publicacoes_doerj VALUES (?,?,?,?,?,?)", (i, "2026-03-01", "Extrato", "Extrato", t, "SEEDUC"))
    con.execute("INSERT INTO fts_doerj(fts_doerj) VALUES ('rebuild')")
    con.commit()
    return con


def test_fontes_externas_contrato_doerj_com_partes(externas):
    idx = I.Indices(externas)
    ev = I.fontes_externas(idx, "SEI-030029/002156/2022", cnpjs={"11222333000144"}, via="SEI-030001/084333/2024")
    por = {(e["fonte"], e["prova"]): e for e in ev}
    c = por[("TCE-RJ contratos (dados abertos)", "contratos_tcerj.id=c1")]
    assert c["estado"] == "VERIFICADO" and c["numero_sei"] == "SEI-030001/084333/2024"
    assert c["via_processo"] == "SEI-030029/002156/2022" and "1.000,50" in c["resposta"]
    assert por[("DOERJ", "publicacoes_doerj.id=1")]["estado"] == "VERIFICADO"
    assert por[("DOERJ", "publicacoes_doerj.id=2")]["estado"] == "PENDENTE"      # ato vizinho: partes não batem


def test_fontes_externas_cnpj_divergente_e_pendente(externas):
    ev = I.fontes_externas(I.Indices(externas), "SEI-030029/002156/2022", cnpjs={"99999999000199"})
    assert {e["estado"] for e in ev if e["fonte"].startswith("TCE-RJ")} == {"PENDENTE"}


def test_vinculo_so_verificado(externas):
    ev = I.fontes_externas(I.Indices(externas), "SEI-030001/084333/2024")
    vin = [e for e in ev if e["fonte"].startswith("vínculo")]
    assert len(vin) == 1 and "030029/002156/2022" in vin[0]["resposta"]


def test_gravar_evidencias_idempotente(externas):
    ev = I.fontes_externas(I.Indices(externas), "SEI-030029/002156/2022", cnpjs={"11222333000144"})
    assert I.gravar_evidencias(externas, "SEI-030029/002156/2022", ev, agora="t1") == len(ev)
    I.gravar_evidencias(externas, "SEI-030029/002156/2022", ev, agora="t2")
    n, em = externas.execute("SELECT COUNT(*), MAX(em) FROM indeterminado_evidencia").fetchone()
    assert n == len(ev) and em == "t2"


def test_lacunas_dos_agentes(tmp_path):
    (tmp_path / "a.json").write_text('{"processo":"SEI-020001/001026/2025","lacunas":["Contrato 036/2022, edital '
                                     '(SEI-020007/002346/2022)"],"lido":{"nao_lidos":"x"}}', encoding="utf-8")
    (tmp_path / "lote.json").write_text('[{"tag":"x"}]', encoding="utf-8")                 # lote: ignorado
    r = I.lacunas_dos_agentes(tmp_path)
    assert [x["numero"] for x in r["SEI-020001/001026/2025"]] == ["SEI-020007/002346/2022"]


def test_alvos_de_captura_junta_proprio_e_relacionados_por_pago():
    diag = [{"sei": "SEI-1", "estado": "indeterminado", "ob_total": 100.0, "causas": ["sem_arquivo"],
             "relacionados": [], "relacionados_fora": []},
            {"sei": "SEI-2", "estado": "sem_documento_execucao", "ob_total": 50.0,
             "causas": ["processo_relacionado_fora_do_acervo"],
             "relacionados": [{"numero": "SEI-M", "papel": "contrato"}], "relacionados_fora": ["SEI-M"]},
            {"sei": "SEI-3", "estado": "indeterminado", "ob_total": 70.0, "causas": ["juizo_inconclusivo"],
             "relacionados": [{"numero": "SEI-M", "papel": "origem"}], "relacionados_fora": ["SEI-M"]}]
    rel, fila = I.alvos_de_captura(diag)
    assert [(a["numero"], a["filho"]) for a in rel] == [("SEI-M", "SEI-2"), ("SEI-M", "SEI-3")]
    assert [(f["sei"], f["pago"]) for f in fila] == [("SEI-M", 120.0), ("SEI-1", 100.0)]
    assert "SEI-3" not in {f["sei"] for f in fila}                     # juízo inconclusivo não é captura


# ── a fila do drenador SEI lê a fila dos indeterminados ───────────────────────────────────────────────────────────
def test_drenador_le_fila_dos_indeterminados_e_pula_arquivado(tmp_path, monkeypatch):
    import json as _json
    import tools.sei_integra_fila as F
    arq = tmp_path / "sei_arquivo"
    (arq / "100000_000001_2025" / "texto").mkdir(parents=True)
    (arq / "100000_000001_2025" / "texto" / "000_a.txt").write_text("x" * 100, encoding="utf-8")
    (arq / "100000_000001_2025" / "manifest.json").write_text(
        _json.dumps({"docs": [{"chars": 100, "texto": "texto/000_a.txt"}], "gerado_em": "2026-11-01"}), encoding="utf-8")
    (tmp_path / "indeterminados").mkdir()
    (tmp_path / "indeterminados" / "fila_captura.json").write_text(_json.dumps({"fila": [
        {"sei": "SEI-100000/000001/2025"}, {"sei": "SEI-200000/000002/2025"}, {"sei": "lixo"}]}), encoding="utf-8")
    monkeypatch.setattr(F, "ARQUIVO", arq)
    assert F._fila_indeterminados() == ["SEI-200000/000002/2025"]
    (tmp_path / "indeterminados" / "fila_captura.json").write_text("{", encoding="utf-8")
    assert F._fila_indeterminados() == []


def test_leitura_limitada_escolhe_tipos_que_citam_a_mae(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "MAX_DOCS_LIDOS", 2)
    monkeypatch.setattr(I, "MAX_CHARS_DOC", 10)
    for n in ("a", "b", "c"):
        (tmp_path / f"{n}.txt").write_text(n * 50, encoding="utf-8")
    docs = [{"tipo": "outro", "titulo": "A", "texto": "a.txt"}, {"tipo": "despacho", "titulo": "B", "texto": "b.txt"},
            {"tipo": "contrato", "titulo": "C", "texto": "c.txt"}, {"tipo": "contrato", "titulo": "D"}]
    r = I.docs_para_relacionados(tmp_path, docs)
    assert [x["titulo"] for x in r] == ["B", "C"] and r[0]["texto"] == "b" * 10
