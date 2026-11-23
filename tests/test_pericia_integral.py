# -*- coding: utf-8 -*-
"""Perícia integral por processo — Claude e cascata DUBLÊS; nenhuma rede, nenhum `claude`, nenhum banco real."""
import json
import sqlite3

import pytest

from compliance_agent import pericia_integral as PI
from compliance_agent.llm import comotor as CM
from compliance_agent.llm import conferencia_opus as CO
from compliance_agent.llm import cruzamento as C
from compliance_agent.llm.claude_motor import Pensamento

TXT_PARECER = ("PARECER JURÍDICO. Trata-se de contratação direta por dispensa emergencial com fundamento no art. 75, "
               "VIII, da Lei 14.133/2021. A justificativa de preço baseou-se em cotação única apresentada pela própria "
               "empresa interessada, sem consulta a painel de preços. Opinamos pela regularidade com ressalvas. ") * 2
TXT_CONTRATO = ("CONTRATO Nº 12/2025. Objeto: prestação de serviços de limpeza hospitalar pelo prazo de 180 dias. "
                "Valor global R$ 1.200.000,00. A CONTRATADA declara-se microempresa. Fiscal do contrato designado. ") * 3


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    monkeypatch.delenv("JFN_CLAUDE_CONTINGENCIA", raising=False)
    monkeypatch.setattr(PI, "DB", tmp_path / "compliance.db")
    monkeypatch.setattr(PI, "ACERVO", tmp_path / "acervo")
    monkeypatch.setattr(PI, "FATOS_DB", tmp_path / "sem_fatos.db")          # nunca o banco real de fatos
    con = sqlite3.connect(tmp_path / "compliance.db")
    con.execute("CREATE TABLE ob_orcamentaria_siafe(processo TEXT, valor REAL, data_emissao TEXT, status TEXT)")
    con.commit()
    con.close()


def _pasta(acervo, nome, docs):
    p = acervo / nome
    (p / "texto").mkdir(parents=True)
    man = {"processo": nome.replace("_", "/"), "docs": []}
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (p / rel).write_text(texto, encoding="utf-8")
        man["docs"].append({"i": str(i), "titulo": titulo, "tipo": "", "fase": "", "texto": rel})
    (p / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return p


def _ob(processo, valor):
    con = sqlite3.connect(PI.DB)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES(?,?,?,?)", (processo, valor, "10/03/2025", "Contabilizado"))
    con.commit()
    con.close()


def _avaliar(pasta, com_llm=False):
    return {"status": "OK", "numero_sei": pasta.name, "modalidade": "dispensa", "cnpj_vencedor": None,
            "achados": [{"origem": "edital", "codigo": "E7", "gravidade": "alta", "diz": "exigência restritiva"}],
            "lacunas_processo": [{"falta": "estudo técnico preliminar"}], "lacunas_captura": [],
            "acatamento": {}, "cadeia": {}, "faixa": "MEDIO", "cobertura": {"captura_integra": True}}


def _sem_evidencia(**kw):
    return {}


def _resposta(graus: dict, achados: dict | None = None):
    eixos = {}
    for e in PI.NOMES_EIXOS:
        g = graus.get(e, 0)
        eixos[e] = {"grau": g, "achados": (achados or {}).get(e, []), "fundamento": "Lei 14.133/2021",
                    "lacunas": [] if g is not None else ["documento não capturado"]}
    return json.dumps({"eixos": eixos, "resumo": "indício, não acusação"}, ensure_ascii=False)


CIT_OK = {"documento": "Parecer", "citacao": "cotação única apresentada pela própria empresa interessada",
          "descricao": "preço de referência sem pesquisa de mercado", "grau": 2, "fundamento": "art. 23 Lei 14.133"}
CIT_INVENTADA = {"documento": "Parecer", "citacao": "o secretário recebeu vantagem indevida da contratada",
                 "descricao": "propina", "grau": 2, "fundamento": "Lei 12.846"}


def _pensar(texto):
    chamadas = []

    def f(tarefa, prompt, **kw):
        chamadas.append({"tarefa": tarefa, **kw})
        if texto is None:
            return None
        return Pensamento(texto=texto, modelo=kw.get("modelo", "claude-opus-5-5"), segundos=1.0, tarefa=tarefa)
    f.chamadas = chamadas
    return f


def _cascata(texto):
    vistos = []

    def f(prompt, sistema="", timeout=45.0, json_saida=True):
        vistos.append(prompt)
        return texto
    f.vistos = vistos
    return f


# ── eixos: constante única ─────────────────────────────────────────────────────────────────────────────
def test_eixos_sao_constante_unica_com_pergunta_e_base():
    assert len(PI.EIXOS) == 10 and len(set(PI.NOMES_EIXOS)) == 10
    for e in PI.EIXOS:
        assert e["nome"] and e["pergunta"] and e["base"]
    _, prompt = PI.montar_prompt({"processo": "SEI-1/1/2025", "bloco": "x", "documentos": "y"})
    for e in PI.EIXOS:
        assert e["nome"] in prompt and e["pergunta"][:30] in prompt


# ── fila ───────────────────────────────────────────────────────────────────────────────────────────────
def test_fila_ordena_por_valor_pago_e_pula_sem_integra_e_ja_periciado():
    a = PI.ACERVO
    _pasta(a, "100001_000001_2025", [("Parecer", TXT_PARECER)])
    _pasta(a, "100001_000002_2025", [("Contrato nº 12/2025", TXT_CONTRATO)])
    _pasta(a, "100001_000003_2025", [("Contrato nº 13/2025", TXT_CONTRATO)])
    _pasta(a, "100001_000005_2025", [("Nota de Empenho Original - NE (1)", TXT_CONTRATO),     # processo financeiro
                                     ("Ordem Bancária 2025OB00001 (2)", TXT_CONTRATO)])
    vazio = _pasta(a, "100001_000004_2025", [("Capa", TXT_CONTRATO)])
    (vazio / "texto" / "000.txt").write_text("[Capa]", encoding="utf-8")       # sem íntegra (só etiqueta)
    _ob("SEI-100001/000001/2025", 10.0)
    _ob("SEI-100001/000002/2025", 900.0)
    _ob("100001/000003/2025", 500.0)
    _ob("SEI-100001/000004/2025", 99999.0)
    _ob("SEI-100001/000005/2025", 88888.0)
    f = PI.fila(10)
    assert [x["numero"] for x in f] == ["SEI-100001/000002/2025", "SEI-100001/000003/2025", "SEI-100001/000001/2025"]
    assert f[0]["pago"] == 900.0 and f[0]["natureza"] == "contratacao"
    # pagamento/repasse não é processo de contratação — só entra sem o filtro de natureza
    assert PI.fila(10, naturezas=None)[0]["numero"] == "SEI-100001/000005/2025"
    # já periciado na versão atual sai; versão antiga volta
    con = sqlite3.connect(PI.DB)
    PI._garantir_tabela(con)
    con.execute("INSERT INTO pericia_integral(rodada,processo,eixo,grau,achados,versao_prompt,criado_em) "
                "VALUES('r','SEI-100001/000002/2025','_global',0,'{}',?,'x')", (PI.VERSAO_PROMPT,))
    con.execute("INSERT INTO pericia_integral(rodada,processo,eixo,grau,achados,versao_prompt,criado_em) "
                "VALUES('r0','SEI-100001/000003/2025','_global',0,'{}','pi-0','x')")
    con.commit()
    con.close()
    assert [x["numero"] for x in PI.fila(10)] == ["SEI-100001/000003/2025", "SEI-100001/000001/2025"]
    assert len(PI.fila(1)) == 1


# ── entrada ────────────────────────────────────────────────────────────────────────────────────────────
def test_entrada_le_por_valor_com_teto_e_ob_como_pagamento():
    p = _pasta(PI.ACERVO, "100001_000001_2025",
               [("Despacho de encaminhamento", "Encaminhe-se ao setor competente para providências. " * 10),
                ("Parecer Jurídico", TXT_PARECER)])
    _ob("SEI-100001/000001/2025", 1234567.8)
    e = PI.montar_entrada(p, avaliar=_avaliar, coletar=_sem_evidencia, teto_chars=400)
    assert e["status"] == "OK"
    assert "Parecer Jurídico" in e["documentos"] and "Despacho de encaminhamento" not in e["documentos"]
    assert e["cobertura"]["docs_fora_do_teto"] >= 1
    assert "R$ 1.234.567,80" in e["bloco"] and "OB" in e["bloco"]
    assert "E7" in e["bloco"]
    assert e["valor_pago"] == pytest.approx(1234567.8)
    c = e["cobertura"]                  # 23/11/2026: o laudo declara o quanto NÃO leu
    assert c["leitura"] == "parcial" and 0 < c["fracao_lida"] < 1 and c["chars_existentes"] > c["chars"]


def test_cobertura_integral_quando_tudo_cabe_e_corte_por_dentro_declarado():
    p = _pasta(PI.ACERVO, "100001_000009_2025", [("Parecer Jurídico", TXT_PARECER)])
    e = PI.montar_entrada(p, avaliar=_avaliar, coletar=_sem_evidencia, teto_chars=10**6)
    assert e["cobertura"]["leitura"] == "integral" and e["cobertura"]["fracao_lida"] == 1.0
    assert e["cobertura"]["docs_cortados_por_dentro"] == 0
    e = PI.montar_entrada(p, avaliar=_avaliar, coletar=_sem_evidencia, teto_chars=60)
    assert e["cobertura"]["docs_cortados_por_dentro"] == 1 and e["cobertura"]["leitura"] == "parcial"


# ── juízo: null, verificação literal ───────────────────────────────────────────────────────────────────
def test_ausencia_de_documento_fica_null_e_nao_irregular():
    fonte = "texto qualquer"
    eixos = PI.interpretar(_resposta({"execucao_fisica": None, "juridico": "indeterminado"}), fonte)
    assert eixos["execucao_fisica"]["grau"] is None and eixos["juridico"]["grau"] is None
    assert eixos["execucao_fisica"]["lacunas"]
    # eixo que o modelo não respondeu também é INDETERMINADO, não ⚪
    so_um = json.dumps({"eixos": {"juridico": {"grau": 0, "achados": []}}})
    assert PI.interpretar(so_um, fonte)["fornecedor"]["grau"] is None


def test_citacao_inventada_derruba_achado_e_grau_sem_prova_vira_indeterminado():
    fonte = TXT_PARECER
    r = _resposta({"economicidade": 2, "anticorrupcao": 2},
                  {"economicidade": [CIT_OK, CIT_INVENTADA], "anticorrupcao": [CIT_INVENTADA]})
    eixos = PI.interpretar(r, fonte)
    assert eixos["economicidade"]["grau"] == 2
    assert [a["citacao"] for a in eixos["economicidade"]["achados"]] == [CIT_OK["citacao"]]
    assert eixos["economicidade"]["descartados"][0]["citacao"] == CIT_INVENTADA["citacao"]
    # 🔴 cuja única prova era inventada não fica 🔴 nem ⚪: fica INDETERMINADO, registrado
    assert eixos["anticorrupcao"]["grau"] is None and eixos["anticorrupcao"]["descartados"]


def test_normalizador_do_comotor_grau_global_e_o_maximo_dos_determinados():
    v, n, _ = CM.NORMALIZADORES["pericia_integral"](_resposta({"juridico": 1, "fornecedor": None}))
    assert n == 1 and v
    assert CM.NORMALIZADORES["pericia_integral"](_resposta({e: None for e in PI.NOMES_EIXOS}))[1] is None
    assert CM.NORMALIZADORES["pericia_integral"]("sem json")[1] is None


# ── ponta a ponta com dublês ───────────────────────────────────────────────────────────────────────────
def _periciar(p, pensar, cascata):
    return PI.periciar(p, pensar=pensar, cascata=cascata, avaliar=_avaliar, coletar=_sem_evidencia, obs={})


def test_cruzamento_por_eixo_e_persistencia_com_historico():
    p = _pasta(PI.ACERVO, "100001_000001_2025", [("Parecer Jurídico", TXT_PARECER)])
    claude = _resposta({"economicidade": 2}, {"economicidade": [CIT_OK]})
    casc = _resposta({"economicidade": 0})
    r = _periciar(p, _pensar(claude), _cascata(casc))
    assert r["status"] == "OK" and r["motor"].startswith("claude:") and r["grau_global"] == 2
    con = C.conectar()
    tarefas = {t for (t,) in con.execute("SELECT DISTINCT tarefa FROM veredito")}
    assert {f"pericia_integral:{e}" for e in PI.NOMES_EIXOS} <= tarefas
    eco = con.execute("SELECT motor, nivel FROM veredito WHERE tarefa='pericia_integral:economicidade' "
                      "ORDER BY motor").fetchall()
    assert eco == [("cascata", 0), ("claude", 2)]
    assert C.revisoes_pendentes()[0]["tarefa"] == "pericia_integral:economicidade"
    # persistência: uma linha por eixo + global; rodar de novo NÃO sobrescreve
    _periciar(p, _pensar(claude), _cascata(casc))
    db = sqlite3.connect(PI.DB)
    n_rodadas = db.execute("SELECT COUNT(DISTINCT rodada) FROM pericia_integral WHERE processo=?",
                           (r["processo"],)).fetchone()[0]
    assert n_rodadas == 2
    row = db.execute("SELECT grau, achados, modelo, provedor, versao_prompt, conferido_opus FROM pericia_integral "
                     "WHERE processo=? AND eixo='economicidade' ORDER BY id DESC", (r["processo"],)).fetchone()
    assert row[0] == 2 and json.loads(row[1])["achados"][0]["citacao"] == CIT_OK["citacao"]
    assert row[3] == "claude" and row[4] == PI.VERSAO_PROMPT and row[5] == 1
    assert db.execute("SELECT COUNT(*) FROM pericia_integral WHERE rodada=(SELECT rodada FROM pericia_integral "
                      "ORDER BY id DESC LIMIT 1)").fetchone()[0] == len(PI.EIXOS) + 1


def test_so_cascata_forca_contingencia_e_enfileira_para_o_opus(monkeypatch):
    _pasta(PI.ACERVO, "100001_000001_2025", [("Parecer Jurídico", TXT_PARECER)])
    _ob("SEI-100001/000001/2025", 50.0)
    env_visto = []
    casc_txt = _resposta({"economicidade": 2}, {"economicidade": [CIT_OK]})

    def casc(prompt, sistema="", timeout=45.0, json_saida=True):
        import os
        env_visto.append(os.environ.get("JFN_CLAUDE_CONTINGENCIA"))
        return casc_txt
    feitos = PI.rodar(1, so_cascata=True, cascata=casc, avaliar=_avaliar, coletar=_sem_evidencia)
    import os
    assert env_visto == ["1"] and os.environ.get("JFN_CLAUDE_CONTINGENCIA") is None
    assert feitos[0]["status"] == "OK" and feitos[0]["conferencia_pendente"] is True
    assert CO.pendente("pericia_integral", "sei:SEI-100001/000001/2025")
    db = sqlite3.connect(PI.DB)
    assert db.execute("SELECT DISTINCT conferido_opus FROM pericia_integral").fetchall() == [(0,)]


def test_aplicador_registrado_e_opus_divergente_vira_nova_rodada():
    assert CO.APLICADORES["pericia_integral"] == "compliance_agent.pericia_integral:aplicar_conferencia"
    p = _pasta(PI.ACERVO, "100001_000001_2025", [("Parecer Jurídico", TXT_PARECER)])
    casc_txt = _resposta({"economicidade": 0})
    r = _periciar(p, _pensar(None), _cascata(casc_txt))
    assert r["conferencia_pendente"] is True
    opus = _resposta({"economicidade": 2}, {"economicidade": [CIT_OK, CIT_INVENTADA]})
    feitos = CO.conferir(5, pensar=_pensar(opus))
    assert feitos[0]["tarefa"] == "pericia_integral" and feitos[0]["aplicado"] == 1
    db = sqlite3.connect(PI.DB)
    rodadas = db.execute("SELECT rodada, MAX(conferido_opus), MIN(conferido_opus) FROM pericia_integral "
                         "GROUP BY rodada ORDER BY MIN(id)").fetchall()
    assert len(rodadas) == 2 and rodadas[0][1:] == (2, 2) and rodadas[1][1:] == (1, 1)
    eco = json.loads(db.execute("SELECT achados FROM pericia_integral WHERE eixo='economicidade' "
                                "ORDER BY id DESC").fetchone()[0])
    assert len(eco["achados"]) == 1 and len(eco["descartados"]) == 1          # Opus também passa pela conferência
    con = C.conectar()
    assert con.execute("SELECT COUNT(*) FROM veredito WHERE tarefa='pericia_integral:economicidade'").fetchone()[0] == 2


def test_aplicador_sem_entrada_na_fila_nao_aplica():
    assert PI.aplicar_conferencia("sei:SEI-9/9/2025", _resposta({}), "claude-opus-5-5", 1) is False
    assert PI.aplicar_conferencia("outro:1", _resposta({}), "claude-opus-5-5", 1) is False


def test_fonte_do_prompt_e_a_entrada_sem_as_instrucoes():
    _, prompt = PI.montar_prompt({"processo": "SEI-1/1/2025", "bloco": "BLOCO-X", "documentos": "DOCS-Y"})
    f = PI._fonte_do_prompt(prompt)
    assert "BLOCO-X" in f and "DOCS-Y" in f and "Lei 14.133" not in f.split("DOCS-Y")[-1]


# ── pi-2: pontos de controle por eixo, regime legal, diligência e hipótese inocente ────────────────────────
def test_cada_eixo_tem_pontos_de_controle_com_id_unico():
    ids = [p["id"] for e in PI.EIXOS for p in e["pontos"]]
    assert all(len(e["pontos"]) >= 3 for e in PI.EIXOS)
    assert len(ids) == len(set(ids))


def test_prompt_pede_regime_e_todos_os_pontos():
    entrada = {"processo": "SEI-1", "bloco": "b", "documentos": "d"}
    _, prompt = PI.montar_prompt(entrada)
    assert '"regime"' in prompt
    for e in PI.EIXOS:
        for p in e["pontos"]:
            assert p["id"] in prompt


def test_pontos_normalizados_e_campos_novos_guardados():
    e0 = PI.EIXOS[0]
    p1, p2 = e0["pontos"][0]["id"], e0["pontos"][1]["id"]
    bruto = {"eixos": {e0["nome"]: {"grau": 0, "achados": [],
                                     "pontos": {p1: "conforme", p2: "talvez", "XX9": "desconforme"},
                                     "diligencias": ["pedir o parecer da PGE"], "hipotese_inocente": "ata anterior"}},
             "regime": "14133", "resumo": "r"}
    eixos = PI.interpretar(json.dumps(bruto), "fonte")
    pts = eixos[e0["nome"]]["pontos"]
    assert pts[p1] == "conforme" and pts[p2] == "indeterminado" and "XX9" not in pts
    assert set(pts) == {p["id"] for p in e0["pontos"]}          # ponto não respondido = indeterminado
    assert eixos[e0["nome"]]["diligencias"] == ["pedir o parecer da PGE"]
    assert eixos[e0["nome"]]["hipotese_inocente"] == "ata anterior"
    assert eixos["_global"]["regime"] == "14133"
    assert PI.interpretar(json.dumps({**bruto, "regime": "lei qualquer"}), "f")["_global"]["regime"] == "indeterminado"


def test_cruzamento_tambem_por_ponto_de_controle():
    e0 = PI.EIXOS[0]
    p1 = e0["pontos"][0]["id"]
    a = {e0["nome"]: {"grau": 1, "achados": [], "pontos": {p1: "desconforme"}}}
    b = {e0["nome"]: {"grau": 0, "achados": [], "pontos": {p1: "conforme"}}}
    PI.cruzar_eixos("SEI-9", a, "claude-opus-5-5", b, "gemini:x")
    con = C.conectar()
    rows = con.execute("SELECT motor, nivel FROM veredito WHERE tarefa=? ORDER BY motor",
                       (f"pericia_integral:{e0['nome']}:{p1}",)).fetchall()
    assert rows == [("cascata", 0), ("claude", 1)]


def test_cascata_longa_cai_no_openrouter_free_de_contexto_longo(monkeypatch):
    """15/11/2026 21h: Gemini sem cota (429 nas 8 chaves) e a cascata padrão sem modelo que coubesse ~65k tokens — a
    perícia ficava SEM o segundo lado e o cruzamento não acontecia. 2º degrau: :free do catálogo com contexto ≥128k."""
    from compliance_agent import direcionamento_cerebro as dc
    from compliance_agent.llm import free_llm, openrouter_catalogo
    monkeypatch.setattr(dc, "_gemini_keys", lambda: [])
    monkeypatch.setattr(openrouter_catalogo, "catalogo", lambda **k: [
        {"id": "pequeno/a:free", "ctx": 32000}, {"id": "grande/b:free", "ctx": 1000000}])
    monkeypatch.setattr(openrouter_catalogo, "escolher_varios", lambda perfil, n=3, **k: ["pequeno/a:free", "grande/b:free"])
    monkeypatch.setattr(free_llm, "_openrouter_key", lambda: "k")
    chamados = []

    def _chat(fl, key, model, msgs):
        chamados.append((model, PI.MAX_TOKENS_SAIDA))
        return '{"eixos": {}}'
    monkeypatch.setattr(PI, "_chat_longo", _chat)
    monkeypatch.setattr(dc, "gerar_sync", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia chegar")))
    txt, modelo = PI._cascata_longa("p" * 1000, "s")
    assert txt == '{"eixos": {}}' and modelo == "openrouter:grande/b:free"
    assert chamados == [("grande/b:free", PI.MAX_TOKENS_SAIDA)]          # o de 32k nem é tentado


def test_chat_longo_recusa_modelo_pago():
    import pytest
    from compliance_agent.llm import free_llm
    with pytest.raises(ValueError):
        PI._chat_longo(free_llm, "k", "nvidia/modelo-pago", [])


def test_calibracao_ab_metade_da_cascata_recebe_exemplos_por_eixo(monkeypatch):
    """Padronização (dono: "batendo claude com as outras IAs para que sejam padronizadas"): metade das chamadas da
    cascata recebe divergências anteriores POR EIXO com o veredito do Claude como referência; a outra metade é o
    controle. O bloco fica FORA da entrada — citação tirada do exemplo não conta como prova.
    Desde 16/11 a fração padrão é 0 (A/B sem diferença); o mecanismo segue válido quando ligado por env."""
    monkeypatch.setattr(PI, "FRACAO_CALIBRACAO", 0.5)
    monkeypatch.setattr(PI.cruzamento, "exemplos",
                        lambda tarefa, k=2, con=None: [{"entrada": f"caso de {tarefa}", "referencia": "veredito=grau 0"}]
                        if tarefa.endswith(":planejamento") else [])
    bloco = PI.bloco_calibracao()
    assert "planejamento" in bloco and "veredito=grau 0" in bloco
    p = _pasta(PI.ACERVO, "100001_000001_2025", [("Parecer Jurídico", TXT_PARECER)])
    vistos = []

    def _casc(prompt, s, t, j):
        vistos.append(prompt)
        return _resposta({"economicidade": 0})
    for sorteio, espera_exemplos in ((0.1, True), (0.9, False)):
        monkeypatch.setattr(PI.random, "random", lambda s=sorteio: s)
        _periciar(p, _pensar(_resposta({"economicidade": 0})), _casc)
        assert ("CALIBRAÇÃO" in vistos[-1]) is espera_exemplos
        assert PI._fonte_do_prompt(vistos[-1]).find("CALIBRAÇÃO") == -1
    con = C.conectar()
    flags = {r[0] for r in con.execute("SELECT com_exemplos FROM veredito WHERE motor='cascata' AND tarefa LIKE 'pericia_integral:%'")}
    assert flags == {0, 1}


def test_regras_de_julgamento_no_prompt_de_todo_modelo():
    """pi-3: regras tiradas das divergências medidas (ausência = lacuna; cronologia só por datas; formal ≤ grau 1;
    grau 2 = ato + norma + efeito; orçamentário compara datas). Ficam FORA da entrada (não são prova)."""
    s, pr = PI.montar_prompt({"processo": "X", "bloco": "b", "documentos": "d"})
    for r in ("R1.", "R2.", "R3.", "R4.", "R5.", "R6.", "R7."):
        assert r in pr
    assert PI._fonte_do_prompt(pr).find("REGRAS DE JULGAMENTO") == -1
    assert PI.VERSAO_PROMPT == "pi-3" and PI.FRACAO_CALIBRACAO == 0.0


def test_veredito_do_eixo_aceita_achado_em_texto():
    """21/11/2026: 2.370 eixos gravados pelo agente Claude Code (18/11) têm `achados` como lista de TEXTO; o aplicador
    da conferência do Opus quebrava (TypeError) e a divergência não era aplicada."""
    assert PI._veredito_eixo({"grau": 1, "achados": ["30% da hora paga como improdutiva sem apontamento"]}) \
        == "grau 1: 30% da hora paga como improdutiva sem apontamento"
    assert PI._veredito_eixo({"grau": 2, "achados": [{"descricao": "sem atesto"}]}) == "grau 2: sem atesto"
    assert PI._veredito_eixo({"grau": None, "achados": []}) == "grau indeterminado"


def test_ponto_no_formato_do_agente_vira_a_regua_da_casa():
    assert PI._status_ponto({"status": "atende", "citacao": "doc 7"}) == "conforme"
    assert PI._status_ponto({"status": "nao_atende"}) == "desconforme"
    assert PI._status_ponto({"status": "nao_se_aplica"}) == "nao_se_aplica"
    assert PI._status_ponto("desconforme") == "desconforme" and PI._status_ponto(None) == "indeterminado"


# ── Fase 6 do plano (23/11/2026): a perícia recebe os FATOS VERIFICADOS da leitura integral ──────────────
def test_entrada_leva_os_fatos_verificados_da_leitura_integral_e_declara(tmp_path, monkeypatch):
    import sqlite3 as _sq
    db = tmp_path / "ev.db"
    c = _sq.connect(db)
    c.executescript("CREATE TABLE fatos(id INTEGER PRIMARY KEY, processo TEXT, doc_id TEXT, tipo TEXT, valor TEXT, "
                    "descricao TEXT, citacao TEXT, estado TEXT, motivo TEXT, motor TEXT, versao TEXT, payload_sha TEXT, "
                    "em TEXT); CREATE TABLE leituras(processo TEXT, estagio TEXT, versao TEXT, chars_existentes INT, "
                    "chars_enviados INT, fracao REAL, leitura TEXT, fatias INT, lote TEXT, em TEXT);")
    proc = "100001/000001/2025"
    c.executemany("INSERT INTO fatos(processo, doc_id, tipo, valor, descricao, citacao, estado, versao, em) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  [(proc, "sei:9", "ressalva", "", "fiscal aponta entrega parcial", "entrega parcial do item 3",
                    "VERIFICADO", "li-2", "x"),
                   (proc, "sei:9", "ressalva", "", "fiscal aponta entrega parcial", "entrega parcial do item 3",
                    "VERIFICADO", "li-2", "x"),                                         # repetido: entra uma vez
                   (proc, "sei:8", "data", "2025-01-02", "assinatura", "02/01/2025", "VERIFICADO", "li-2", "x"),
                   (proc, "sei:7", "valor", "999.00", "inventado", "R$ 999,00", "INDISPONIVEL", "li-2", "x")])
    c.execute("INSERT INTO leituras VALUES(?,?,?,?,?,?,?,?,?,?)", (proc, "leitura_integral", "li-2", 5000, 5000, 1.0,
                                                                   "integral", 1, "lote", "2026-11-23 10:00:00"))
    c.commit()
    monkeypatch.setattr(PI, "FATOS_DB", db)
    p = _pasta(PI.ACERVO, "100001_000001_2025", [("Parecer Jurídico", TXT_PARECER)])
    e = PI.montar_entrada(p, avaliar=_avaliar, coletar=_sem_evidencia)
    assert "FATOS VERIFICADOS" in e["documentos"] and e["documentos"].count("entrega parcial do item 3") == 1
    lista = e["documentos"][e["documentos"].index("FATOS VERIFICADOS DA LEITURA"):]      # lista por tipo (após a linha do tempo)
    assert lista.index("ressalva") < lista.index("02/01/2025")                          # ressalva antes de data
    assert "R$ 999,00" not in e["documentos"]                                          # recusado não entra
    assert e["cobertura"]["fatos_verificados"] == 2 and e["cobertura"]["leitura_integral"] == "integral"


def test_fila_refaz_e_prioriza_quem_ganhou_leitura_integral_depois_da_pericia(tmp_path, monkeypatch):
    import sqlite3 as _sq
    db = tmp_path / "ev.db"
    c = _sq.connect(db)
    c.execute("CREATE TABLE leituras(processo TEXT, estagio TEXT, versao TEXT, chars_existentes INT, chars_enviados INT,"
              " fracao REAL, leitura TEXT, fatias INT, lote TEXT, em TEXT)")
    c.execute("INSERT INTO leituras VALUES('100001/000007/2025','leitura_integral','li-2',1,1,1,'integral',1,'l',"
              "'2026-11-23 12:00:00')")
    c.execute("INSERT INTO leituras VALUES('100001/000008/2025','leitura_integral','li-2',1,1,1,'integral',1,'l',"
              "'2026-11-20 12:00:00')")
    c.commit()
    monkeypatch.setattr(PI, "FATOS_DB", db)
    con = sqlite3.connect(PI.DB)
    PI._garantir_tabela(con)
    for proc in ("SEI-100001/000007/2025", "SEI-100001/000008/2025"):
        con.execute("INSERT INTO pericia_integral(rodada,processo,eixo,grau,achados,versao_prompt,criado_em) "
                    "VALUES('r',?,'_global',0,'{}',?,'2026-11-22T09:00:00')", (proc, PI.VERSAO_PROMPT))
    con.commit()
    refazer = PI._refazer_por_leitura(con)
    con.close()
    assert refazer == {PI._dig("100001/000007/2025")}          # leitura depois da perícia; o outro, antes


def test_linha_do_tempo_do_processo_inteiro_vem_em_ordem_cronologica(tmp_path, monkeypatch):
    import sqlite3 as _sq
    db = tmp_path / "ev.db"
    c = _sq.connect(db)
    c.executescript("CREATE TABLE fatos(id INTEGER PRIMARY KEY, processo TEXT, doc_id TEXT, tipo TEXT, valor TEXT, "
                    "descricao TEXT, citacao TEXT, estado TEXT, versao TEXT); CREATE TABLE leituras(processo TEXT, "
                    "estagio TEXT, versao TEXT, chars_existentes INT, chars_enviados INT, fracao REAL, leitura TEXT, "
                    "fatias INT, lote TEXT, em TEXT);")
    proc = "100001/000002/2025"
    c.executemany("INSERT INTO fatos(processo, doc_id, tipo, valor, descricao, citacao, estado, versao) "
                  "VALUES(?,?,?,?,?,?,'VERIFICADO','li-2')",
                  [(proc, "sei:2", "data", "2025-12-26", "reforço de empenho", "26/12/2025"),
                   (proc, "sei:1", "data", "2025-11-30", "fim dos eventos", "30/11/2025")])
    c.commit()
    monkeypatch.setattr(PI, "FATOS_DB", db)
    texto, info = PI._bloco_fatos("SEI-" + proc)
    assert texto.startswith("LINHA DO TEMPO") and info["linha_do_tempo"] == 2
    assert texto.index("30/11/2025 [sei:1]") < texto.index("26/12/2025 [sei:2]")
