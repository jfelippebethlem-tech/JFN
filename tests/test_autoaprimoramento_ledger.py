"""Autoaprimoramento — ledger de verdade de chão, taxonomia de armadilhas, importação e proteção da prova primária
(docs/AUTOAPRIMORAMENTO-JFN.md). 18/11/2026: de 72 laudos de agente conferidos na fonte primária, 51 tinham sido
regravados por juízo sobre o resumo; o laudo anterior de cada conferência não ficava em lugar nenhum."""
import json
import sqlite3

import pytest

import tools.lex_execucao as L
from compliance_agent.autoaprimoramento import armadilhas, importar, ledger

FONTE = "claude:claude-opus-5-5 (agente Claude Code, conferência na fonte primária 18/11) (conferência; antes gemini:x)"
OPUS = "claude-opus-5-5 (conferência Opus 18/11, lote até 85%)"


@pytest.fixture
def auto(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_AUTOAPRIMORAMENTO_DIR", str(tmp_path / "auto"))
    con = ledger.conectar()
    yield con
    con.close()


def test_motor_e_nivel_pela_proveniencia():
    assert ledger.motor_e_nivel(FONTE) == ("claude:fonte-primaria", 2)
    assert ledger.motor_e_nivel("claude:claude-opus-5-5 (sessão Claude Code, conferência manual 18/11 — NE e 120 NF "
                                "lidas) (conferência; antes x)")[1] == 2
    # controle negativo: a sessão que só releu a entrada do prompt NÃO é fonte primária
    assert ledger.motor_e_nivel("claude:claude-opus-5-5 (sessão Claude Code, conferência manual) (conferência; antes "
                                "gemini:gemini-3-flash-preview)") == ("claude-opus:resumo", 1)
    assert ledger.motor_e_nivel(OPUS)[1] == 1 and ledger.motor_e_nivel("gemini · conferido claude:claude-opus-5-5")[1] == 1
    assert ledger.motor_e_nivel("gemini:gemini-3-flash-preview") == ("gemini:gemini-3-flash-preview", 0)
    assert ledger.motor_e_nivel("claude:claude-haiku-5-5@api (+gemini:x)") == ("claude-haiku@api", 0)
    assert ledger.motor_e_nivel("regra:sem_doc_execucao")[1] == -1 and ledger.motor_e_nivel(None) == ("desconhecido", 0)
    assert ledger.antecessor("claude:claude-opus-5-5 (conferência; antes gemini:gemini-3.5-flash)") == "gemini:gemini-3.5-flash"


def test_particao_e_fixa_por_processo():
    a = [ledger.conjunto_de(f"SEI-{i:06d}/000001/2025") for i in range(400)]
    assert a == [ledger.conjunto_de(f"SEI-{i:06d}/000001/2025") for i in range(400)]
    assert 150 < a.count("treino") < 250 and 60 < a.count("validacao") < 140 and 60 < a.count("teste") < 140


def test_versao_e_idempotente_e_regra_nao_entra(auto):
    l = {"execucao_comprovada": "parcial", "nota_risco_execucao": 8, "indicios": ["x"], "resumo": "r"}
    a = ledger.registrar_versao(auto, "SEI-1/1/2025", l, "gemini:x", "t")
    assert a == ledger.registrar_versao(auto, "SEI-1/1/2025", l, "gemini:x", "t")
    assert auto.execute("SELECT COUNT(*) FROM laudo_versao").fetchone()[0] == 1
    assert ledger.registrar_versao(auto, "SEI-1/1/2025", {"nota_risco": None}, "regra:sem_doc_execucao", "t") is None
    assert ledger.registrar_versao(auto, "SEI-1/1/2025", {"nota_risco": 75}, "gemini:x", "t") is None   # fora da escala


def _tres_niveis(con, ns="SEI-1/1/2025"):
    ledger.registrar_versao(con, ns, {"nota_risco": 8, "indicios": ["ausência de OB"]}, "gemini:x", "t", "2026-11-15T10:00:00")
    ledger.registrar_versao(con, ns, {"nota_risco": 7, "indicios": ["atesto genérico"]}, OPUS, "t", "2026-11-18T08:00:00")
    ledger.registrar_versao(con, ns, {"nota_risco": 2, "indicios": [], "duvidas": [
        "Descartado: 'ausência de OB' — SIAFE: 2026OB04197, R$ 17.543,92, 'Processado e Pago'; o campo processo da OB está vazio.",
        "Descartado: empenho R$ 18.000,00 × liquidação R$ 17.757,00 — empenho é limite estimativo.",
        "A verificar: saldo do pedido."]}, FONTE, "t", "2026-11-18T15:00:00")


def test_conciliar_monta_os_pares_e_os_indicios_com_a_armadilha(auto):
    _tres_niveis(auto)
    ledger.conciliar(auto, {"SEI-1/1/2025": 17543.92}, {"SEI-1/1/2025": "aquisicao"})
    pares = set(auto.execute("SELECT nivel_antes, nivel_depois, alto_antes, alto_depois, valor_pago FROM conferencia"))
    assert pares == {(0, 1, 1, 1, 17543.92), (0, 2, 1, 0, 17543.92), (1, 2, 1, 0, 17543.92)}
    ind = dict(auto.execute("SELECT armadilha, desfecho FROM indicio_conferido"))
    assert ind == {"ob_existe_no_siafe": "descartado", "empenho_estimativo": "descartado"}   # 'A verificar' não é descarte
    assert ledger.conciliar(auto)["pares_novos"] == 0                                        # idempotente


def test_laudo_fraco_posterior_a_conferencia_nao_vira_par(auto):
    """Controle negativo: o sweep reavaliou o processo DEPOIS da conferência (outra captura) — não é o laudo conferido."""
    ledger.registrar_versao(auto, "SEI-2/2/2025", {"nota_risco": 3}, FONTE, "t", "2026-11-18T15:00:00")
    ledger.registrar_versao(auto, "SEI-2/2/2025", {"nota_risco": 9}, "gemini:x", "t", "2026-11-19T10:00:00")
    ledger.conciliar(auto)
    assert auto.execute("SELECT COUNT(*) FROM conferencia").fetchone()[0] == 0


def test_rotulo_prefere_a_fonte_primaria_e_nao_conta_o_mesmo_laudo_duas_vezes(auto):
    _tres_niveis(auto, "SEI-000001/000001/2025")
    ns = "SEI-000001/000001/2025"
    ledger.registrar_versao(auto, ns, {"nota_risco": 8}, "desconhecido", "log")          # mesmo laudo, só a nota
    ledger.conciliar(auto)
    r = ledger._rotulos(auto, ("treino", "validacao", "teste"), 1, False)
    assert len(r) == 1 and r[0]["nivel_rotulo"] == 2 and r[0]["alto_verificado"] == 0 and r[0]["motor"] == "gemini:x"


def test_teste_congelado_tem_orcamento_de_consultas(auto):
    with pytest.raises(ValueError):
        ledger.rotulos(auto, ("teste",))
    for _ in range(4):
        ledger.consultar_teste(auto, "eu", "medir")
    with pytest.raises(PermissionError):
        ledger.consultar_teste(auto, "eu", "medir de novo")
    assert auto.execute("SELECT COUNT(*) FROM consulta_teste").fetchone()[0] == 4


@pytest.mark.parametrize("texto,porque,esperado", [
    ("ausência de OB", "SIAFE: 2026OB04197 paga em 14/04/2026", "ob_existe_no_siafe"),
    ("diferença de R$ 18,65", "= 1,2% (retenção de IRRF)", "retencao_tributaria"),
    ("NF cancelada", "termo de cancelamento e NF substituta nos autos", "nf_cancelada_substituta"),
    ("data de emissão futura", "2026 não é futura: já ocorreu", "data_futura"),
    ("ausência de contrato/TR", "processo é só de PAGAMENTO; a contratação corre em processo próprio", "tipo_processo_sem_execucao"),
    ("ausência de atesto", "os autos têm o ARM nº 165/26 (doc 127398625)", "documento_existe_nos_autos"),
    ("pico de R$ 13,6 mi em 15 dias", "medição detalhada confirma o quantitativo", armadilhas.NAO_CLASSIFICADA),
])
def test_classificar_armadilha(texto, porque, esperado):
    assert armadilhas.classificar(texto, porque) == esperado


def test_padrao_de_indicio_fraco_positivo_e_negativo():
    assert armadilhas.do_indicio("indício a verificar: ausência de Ordem Bancária nos autos") == "ob_existe_no_siafe"
    assert armadilhas.do_indicio("Ausência de planilha de medição detalhada") == "ausencia_no_recorte"
    # negativos: leu a OB / achado material presente
    assert armadilhas.do_indicio("divergência entre a NF e a ordem bancária de retenção") is None
    assert armadilhas.do_indicio("BDI de 17,34% na memória × 25,00% na planilha de medição") is None
    assert armadilhas.do_indicio("ausência de Ordem Bancária", ativas=("ausencia_no_recorte",)) == "ausencia_no_recorte"


def test_taxonomia_cresce_por_descarte_recorrente_em_processos_distintos():
    d = [{"numero_sei": f"SEI-{i}", "armadilha": armadilhas.NAO_CLASSIFICADA,
          "porque": "glosa aplicada pela fiscalização abateu o valor medido"} for i in range(3)]
    c = armadilhas.candidatas(d)
    assert c and c[0]["processos"] == 3 and len(c[0]["exemplos"]) == 3
    # controle negativo: o mesmo processo três vezes não é padrão; nem descarte já classificado
    assert armadilhas.candidatas([{**d[0]}] * 3) == []
    assert armadilhas.candidatas([{**x, "armadilha": "ocr_digito"} for x in d]) == []


def _bases(tmp_path):
    comp, fila = tmp_path / "c.db", tmp_path / "f.db"
    c = sqlite3.connect(comp)
    c.execute("CREATE TABLE lex_execucao (numero_sei TEXT PRIMARY KEY, objeto TEXT, execucao_comprovada TEXT, coerencia TEXT, "
              "nota_risco INT, indicios TEXT, duvidas TEXT, resumo TEXT, modelo TEXT, em TEXT)")
    c.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, nl TEXT, processo TEXT, credor TEXT, nome_credor TEXT, "
              "valor REAL, status TEXT, status_envio TEXT, data_emissao TEXT)")
    c.executemany("INSERT INTO lex_execucao VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("SEI-100001/000001/2025", "aquisição de material", "parcial", "x", 7, "[]", "[]", "resumo do opus", OPUS, "2026-11-18T16:00:00"),
        ("SEI-100001/000002/2025", "obra", "sim", "x", 2, "[]", '["Descartado: \'ausência de OB\' — SIAFE: 2026OB00009 paga"]',
         "fonte", FONTE, "2026-11-18T15:00:00"),
        ("SEI-100001/000003/2025", "obra", "parcial", "x", 5, "[]", "[]", "outro", OPUS, "2026-11-18T16:00:00")])
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?)", [
        ("2026OB00001", "2026NL00001", "SEI-100001/000001/2025", "12345678000199", "ACME", 100.0, "Contabilizado", None, "01/02/2026"),
        ("2026OB00007", "2026NL00007", "SEI-100001/000003/2025", "12345678000199", "ACME", 50.0, "Contabilizado", None, "01/02/2026"),
        ("2026OB00007", "2026NL00008", "SEI-100001/000001/2025", "12345678000199", "ACME", 50.0, "Contabilizado", None, "01/02/2026")])
    c.commit(); c.close()
    f = sqlite3.connect(fila)
    f.execute("CREATE TABLE fila(item TEXT, tarefa TEXT, status TEXT, motor TEXT, resposta TEXT, criado_em TEXT, "
              "modelo_opus TEXT, resposta_opus TEXT, conferido_em TEXT)")
    f.execute("INSERT INTO fila VALUES ('sei:SEI-100001/000002/2025','pericia_execucao','conferido','gemini:x',?,?,?,?,?)",
              (json.dumps({"execucao_comprovada": "nao", "nota_risco_execucao": 9, "indicios": ["ausência de OB"]}),
               "2026-11-15T10:00:00", "claude-opus-5-5",
               json.dumps({"execucao_comprovada": "parcial", "nota_risco_execucao": 7, "indicios": ["atesto genérico"]}),
               "2026-11-18T08:00:00"))
    f.commit(); f.close()
    return comp, fila


def test_importar_reconstroi_a_cadeia_e_acusa_fonte_primaria_regravada(auto, tmp_path):
    comp, fila = _bases(tmp_path)
    ag = tmp_path / "ag"; ag.mkdir()
    laudo = {"execucao_comprovada": "sim", "nota_risco_execucao": 2, "indicios": [], "duvidas": [], "resumo": "x"}
    (ag / "p1.json").write_text(json.dumps({**laudo, "resumo": "OB 2026OB00001 (NL 2026NL00001) paga"}))    # 1 processo só
    (ag / "p2.json").write_text(json.dumps({**laudo, "resumo": "OB 2026OB00007 paga"}))                     # 2 processos: ambíguo
    (ag / "p3.json").write_text(json.dumps({**laudo, "resumo": "sem nada que identifique"}))
    (ag / "p4.json").write_text(json.dumps({**laudo, "resumo": "por arquivo .ns"})); (ag / "p4.ns").write_text("SEI-100001/000003/2025\n")
    r = importar.tudo(auto, compliance_db=comp, fila_db=fila, cruz_db=tmp_path / "nao_existe.db",
                      log_lote=tmp_path / "nao_existe.log", pastas_agentes=[ag])
    assert r["fila"] == 1 and r["agentes"]["importados"] == 2 and len(r["agentes"]["sem_processo"]) == 2
    # os dois laudos de agente estão sobre linhas vigentes do Opus-resumo: prova primária regravada
    assert r["agentes"]["sobrescritos"] == ["SEI-100001/000001/2025", "SEI-100001/000003/2025"]
    cadeia = set(auto.execute("SELECT nivel_antes, nivel_depois, nota_antes, nota_depois FROM conferencia "
                              "WHERE numero_sei='SEI-100001/000002/2025'"))
    assert cadeia == {(0, 1, 9, 7), (0, 2, 9, 2), (1, 2, 7, 2)}
    assert auto.execute("SELECT valor_pago, tipo_processo FROM conferencia WHERE numero_sei='SEI-100001/000001/2025'"
                        ).fetchone() == (150.0, "aquisicao")
    assert importar.tudo(auto, compliance_db=comp, fila_db=fila, cruz_db=tmp_path / "n.db", log_lote=tmp_path / "n.log",
                         pastas_agentes=[ag])["pares_novos"] == 0


def _lex(modelo):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE lex_execucao (numero_sei TEXT PRIMARY KEY, objeto TEXT, tem_prestacao_contas INT, tem_fiscalizacao INT, "
              "tem_relatorio_fotografico INT, tem_atesto_recebimento INT, tem_nota_fiscal INT, tem_medicao INT, "
              "execucao_comprovada TEXT, coerencia TEXT, nota_risco INT, indicios TEXT, duvidas TEXT, resumo TEXT, "
              "modelo TEXT, em TEXT)")
    c.execute("INSERT INTO lex_execucao (numero_sei, execucao_comprovada, nota_risco, indicios, duvidas, resumo, modelo, em) "
              "VALUES ('SEI-1/1/2025','sim',2,'[]','[]','lido na fonte',?,'2026-11-18T15:00:00')", (modelo,))
    return c


RESP = json.dumps({"execucao_comprovada": "parcial", "nota_risco_execucao": 7, "indicios": ["atesto genérico"], "resumo": "resumo"})


def test_prova_primaria_nao_e_regravada_por_juizo_sobre_o_resumo(auto):
    c = _lex(FONTE)
    assert L.aplicar_conferencia("sei:SEI-1/1/2025", RESP, "claude-opus-5-5", 0, con=c) is False
    assert L.aplicar_conferencia("sei:SEI-1/1/2025", "sem laudo", "claude-opus-5-5", 1, con=c) is False   # nem a proveniência
    fl = {k: 0 for k in L._SINAIS}
    L._gravar_uma_vez(c, "SEI-1/1/2025", "obj", fl, json.loads(RESP), 7, "gemini:gemini-3-flash-preview")  # sweep
    assert c.execute("SELECT nota_risco, resumo, modelo FROM lex_execucao").fetchone() == (2, "lido na fonte", FONTE)
    # nada se perde: o laudo recusado e o vigente estão no ledger
    origens = {r[0] for r in auto.execute("SELECT origem FROM laudo_versao")}
    assert origens == {"gancho:lex_execucao", "recusado:prova-primaria-vigente"}


def test_controle_negativo_conferencia_normal_regrava_e_guarda_o_anterior(auto):
    c = _lex("gemini:gemini-3-flash-preview")
    assert L.aplicar_conferencia("sei:SEI-1/1/2025", RESP, "claude-opus-5-5", 0, con=c) is True
    assert c.execute("SELECT nota_risco FROM lex_execucao").fetchone()[0] == 7
    assert auto.execute("SELECT motor, nota, resumo FROM laudo_versao").fetchall() == [
        ("gemini:gemini-3-flash-preview", 2, "lido na fonte")]
    # fonte primária substitui fonte primária (nova leitura dos autos)
    c2 = _lex(FONTE)
    assert L.aplicar_conferencia("sei:SEI-1/1/2025", RESP, "claude-opus-5-5 (agente Claude Code, conferência na fonte "
                                 "primária 19/11)", 0, con=c2) is True
