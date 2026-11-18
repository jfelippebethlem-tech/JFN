# -*- coding: utf-8 -*-
"""ACEITE da arquitetura de certeza (docs/ARQUITETURA-DE-CERTEZA.md): as seis falhas reais de 18/11/2026, cada uma
com controle POSITIVO (a falha é barrada/acusada) e NEGATIVO (o caso legítimo passa). Sem rede, sem LLM, sem tocar
em data/: tudo em tmp_path."""
import json
import sqlite3
import time

import pytest

from compliance_agent.certeza import citacoes, config, fatos, grafo, orquestrador, portoes

AGILE = "iss_nao_retido:00801512000157:180100"


@pytest.fixture()
def cz(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CERTEZA_DIR", str(tmp_path / "certeza"))
    for k in ("SINCRONIZAR", "CEREBRO", "GATILHOS", "KILL"):
        monkeypatch.delenv(f"JFN_CERTEZA_{k}", raising=False)
    con = fatos.conectar()
    yield con
    con.close()


def _fato(fid, valor, unidade="BRL", **k):
    return {"fato_id": fid, "valor": valor, "unidade": unidade, "estado": "VERIFICADO", "nivel_prova": 2,
            "fonte": "NFS-e × OB SIAFE", "consulta": "data/iss_nao_retido.json › por_fornecedor › iss_nao_retido",
            "data_ref": "2026-11-18T18:37:43", "hash_fonte": "abc", "produtor": "teste", "rotulo": "ISS não retido — AGILE × UG 180100",
            "meta": {"apelidos": ["AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA."], "termos": ["ISS"], "superados": []}, **k}


def _duas_medicoes(cz):
    """1ª medição manual (35 / R$ 2.270.009,39) e a do detector (38 / R$ 2.437.189,45), como em 18/11."""
    for valor, n in ((2270009.39, 35), (2437189.45, 38)):
        for fid, v, un in ((AGILE + ":valor", valor, "BRL"), (AGILE + ":processos", n, "contagem")):
            vig = fatos.vigente(cz, fid)
            r = fatos.registrar(cz, _fato(fid, v, un), vig["hash_versao"] if vig else None)
            assert r["status"] in ("novo", "atualizado"), r


def _varrer(cz, tmp_path, texto, **k):
    pasta = tmp_path / "vault"
    pasta.mkdir(exist_ok=True)
    (pasta / "agile.md").write_text(texto, encoding="utf-8")
    return citacoes.varrer(cz, {"vault": {"pasta": str(pasta), "glob": "*.md", "sincronizar": True}}, **k)


# ════════════════════ FALHA 1 — mesmo fato, números diferentes ════════════════════

def test_f1_nota_que_repete_o_valor_superado_e_acusada(cz, tmp_path):
    _duas_medicoes(cz)
    v = _varrer(cz, tmp_path, "# AGILE\n\nA SEEDUC não reteve o ISS: R$ 2.270.009,39 de ISS em 35 processos da AGILE.\n")
    tipos = {(d["tipo"], d["fato_id"], d["encontrado"], d["esperado"]) for d in v["divergencias"]}
    assert ("mencao_a_valor_superado", AGILE + ":valor", "R$ 2.270.009,39", "R$ 2.437.189,45") in tipos
    assert ("mencao_a_valor_superado", AGILE + ":processos", "35", "38") in tipos
    assert v["divergencias"][0]["local"] == "agile.md:3"          # arquivo e linha: QUAIS, não quantos


def test_f1_controle_negativo_nota_atualizada_historico_e_numero_alheio(cz, tmp_path):
    _duas_medicoes(cz)
    texto = ("ISS da AGILE: R$ 2.437.189,45 em 38 processos (supera a 1ª medição de 35 e R$ 2.270.009,39).\n"
             "Histórico: a 1ª medição do ISS da AGILE deu R$ 2.270.009,39 em 35 processos. <!--fato-historico-->\n"
             "Outro assunto: o contrato tem 35 postos de vigilância.\n"                       # 35 sem AGILE + ISS
             "A comissão de emissão da AGILE analisou 35 processos de outro tema.\n"         # "ISS" dentro de palavra não é o termo
             "A AGILE recebeu R$ 12.270.009,39 no exercício; ISS à parte.\n")                 # outro número, não o superado
    assert _varrer(cz, tmp_path, texto.replace("\n", "\n\n"))["divergencias"] == []


def test_f1_paragrafo_com_quebra_dura_de_linha_resto_antigo_ao_lado_do_numero_novo(cz, tmp_path):
    """O caso real da nota da AGILE em 18/11: o parágrafo já diz 38, mas uma frase adiante ficou 'Em 35\nprocessos'."""
    _duas_medicoes(cz)
    texto = ("1. **ISS que a NF manda reter e a SEEDUC não retém: 38 processos** (supera a 1ª medição de 35/35). As NFS-e da AGILE vêm de\n"
             "   Duque de Caxias e marcam \"ISSQN Retido: Sim\" (5%). Em 35\n"
             "   processos (2023–2025), a OB = bruto − INSS − IRRF, exatamente.\n"
             "   - **R$ 2.437.189,45 de ISS** sobre R$ 48.743.788,63 brutos (a 1ª medição dava R$ 2.270.009,39).\n")
    d = _varrer(cz, tmp_path, texto)["divergencias"]
    assert [(x["fato_id"], x["encontrado"], x["local"]) for x in d] == [(AGILE + ":processos", "35", "agile.md:2")]


def test_f1_citacao_por_id_diverge_e_so_sincroniza_com_a_chave(cz, tmp_path, monkeypatch):
    _duas_medicoes(cz)
    velho = f"ISS não retido: **R$ 2.270.009,39**<!--fato:{AGILE}:valor--> em 35<!--fato:{AGILE}:processos--> processos.\n"
    v = _varrer(cz, tmp_path, velho, aplicar=True)                # chave desligada: acusa e NÃO escreve
    assert sorted(d["tipo"] for d in v["divergencias"]) == ["citacao_divergente", "citacao_divergente"]
    assert v["sincronizados"] == 0 and (tmp_path / "vault" / "agile.md").read_text(encoding="utf-8") == velho
    monkeypatch.setenv("JFN_CERTEZA_SINCRONIZAR", "1")
    v = _varrer(cz, tmp_path, velho, aplicar=True)
    novo = (tmp_path / "vault" / "agile.md").read_text(encoding="utf-8")
    assert v["sincronizados"] == 2 and v["divergencias"] == []
    assert novo == f"ISS não retido: **R$ 2.437.189,45**<!--fato:{AGILE}:valor--> em 38<!--fato:{AGILE}:processos--> processos.\n"
    assert _varrer(cz, tmp_path, novo, aplicar=True)["sincronizados"] == 0        # idempotente
    v = _varrer(cz, tmp_path, "valor R$ 1,00<!--fato:nao:existe:valor-->\n")
    assert [d["tipo"] for d in v["divergencias"]] == ["citacao_de_fato_inexistente"]


def test_f1_kill_desliga_a_sincronizacao(cz, tmp_path, monkeypatch):
    _duas_medicoes(cz)
    monkeypatch.setenv("JFN_CERTEZA_SINCRONIZAR", "1")
    (config.dados() / "KILL").write_text("teste", encoding="utf-8")
    velho = f"R$ 2.270.009,39<!--fato:{AGILE}:valor-->\n"
    assert _varrer(cz, tmp_path, velho, aplicar=True)["sincronizados"] == 0


def test_f1_indice_do_cerebro_que_serve_trecho_antigo_e_acusado(cz, tmp_path):
    _duas_medicoes(cz)
    sup = {"cerebro": {"busca": True}}
    antigo = [{"source": "vault", "path": "casos/agile.md", "heading": "Padrões", "snippet": "R$ 2.270.009,39 de ISS em 35 processos"}]
    v = citacoes.varrer(cz, sup, buscar=lambda q, k: antigo)
    assert [d["tipo"] for d in v["divergencias"]] == ["indice_do_cerebro_serve_valor_superado"]
    atual = [{"source": "vault", "path": "casos/agile.md", "snippet": "R$ 2.437.189,45 (supera R$ 2.270.009,39)"}]
    assert citacoes.varrer(cz, sup, buscar=lambda q, k: atual)["divergencias"] == []

    def fora(q, k):
        raise OSError("cérebro fora do ar")
    v = citacoes.varrer(cz, sup, buscar=fora)                     # não respondeu ≠ sem divergência
    assert v["indisponiveis"] and "cerebro_indice" not in v["superficies_lidas"]


def test_f1_divergencia_aberta_curada_reincidiu_e_superficie_muda_nao_cura(cz):
    d = [{"tipo": "mencao_a_valor_superado", "fato_id": AGILE + ":valor", "superficie": "vault", "local": "agile.md:3",
          "encontrado": "R$ 2.270.009,39", "esperado": "R$ 2.437.189,45"}]
    assert citacoes.conciliar(cz, d, ["vault"])["novas"] == 1
    assert citacoes.conciliar(cz, [{**d[0], "local": "agile.md:9"}], ["vault"]) == {"novas": 0, "reincidiram": 0, "curadas": 0, "abertas": 1}
    assert citacoes.conciliar(cz, [], [])["abertas"] == 1          # vault não foi lido neste ciclo: segue aberta
    assert citacoes.conciliar(cz, [], ["vault"])["curadas"] == 1
    r = citacoes.conciliar(cz, d, ["vault"])
    assert r["reincidiram"] == 1 and citacoes.abertas(cz)[0]["reincidencias"] == 1


def _mapa_iss(tmp_path, registros_agile=38, publicado=38):
    reg = [{"credor": "00801512000157", "ug": "180100", "classe": "ISS_NAO_RETIDO", "estado": "VERIFICADO",
            "processo": f"SEI-{i}", "iss_nao_retido": 100.0} for i in range(registros_agile)]
    reg.append({"credor": "00801512000157", "ug": "180100", "classe": "ISS_NAO_RETIDO", "estado": "PENDENTE", "processo": "SEI-x",
                "iss_nao_retido": 999.0})
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "iss.json").write_text(json.dumps({
        "gerado_em": "2026-11-18T18:37:43", "registros": reg,
        "por_fornecedor": [{"credor": "00801512000157", "ug": "180100", "nome_credor": "AGILE CORP", "processos_iss_nao_retido": publicado,
                            "iss_nao_retido": publicado * 100.0},
                           {"credor": "999", "ug": "1", "nome_credor": "SEM ACHADO", "processos_iss_nao_retido": 0, "iss_nao_retido": 0.0}]}),
        encoding="utf-8")
    bloco = {"id": "iss_nao_retido:{credor}:{ug}", "arquivo": "data/iss.json", "lista": "por_fornecedor", "data_ref": "gerado_em",
             "filtro": {"campo": "processos_iss_nao_retido", "min": 1}, "rotulo": "ISS — {nome_credor}", "fonte": "NFS-e × OB",
             "nivel_prova": 2, "estado": "VERIFICADO", "apelidos": ["{nome_credor}"], "termos": ["ISS"],
             "medidas": {"valor": {"campo": "iss_nao_retido", "unidade": "BRL"}, "processos": {"campo": "processos_iss_nao_retido", "unidade": "contagem"}},
             "superados": {"00801512000157:180100": {"valor": 2270009.39, "processos": 35}},
             "reconcilia": {"lista": "registros", "onde": {"credor": "$credor", "ug": "$ug", "classe": "ISS_NAO_RETIDO", "estado": "VERIFICADO"},
                            "medidas": {"valor": {"soma": "iss_nao_retido"}, "processos": {"distintos": "processo"}}}}
    return {"fontes": {}, "derivados": {"iss": {"nome": "ISS", "depende": ["x"], "comando": ["x"], "fatos": [bloco]}}, "cerebro": []}


def test_f1_derivado_cujo_agregado_nao_bate_com_o_detalhe_e_acusado(cz, tmp_path):
    props, erros = fatos.extrair(_mapa_iss(tmp_path, registros_agile=37, publicado=38), raiz=tmp_path)
    assert not erros and {p["fato_id"] for p in props} == {AGILE + ":valor", AGILE + ":processos"}   # filtro tirou o de 0
    rc = {p["fato_id"]: p["_reconcilia"]["esperado"] for p in props}
    assert rc == {AGILE + ":valor": 3700.0, AGILE + ":processos": 37}                                # PENDENTE fica fora da soma
    ok, _ = fatos.extrair(_mapa_iss(tmp_path, 38, 38), raiz=tmp_path)
    assert all(p["_reconcilia"]["esperado"] == p["valor"] for p in ok)
    assert ok[0]["meta"]["superados"] == [2270009.39] and ok[1]["meta"]["superados"] == [35]


def test_f1_ciclo_inteiro_mesmo_numero_em_todo_lugar(cz, tmp_path):
    """Ponta a ponta sem rede: derivado → fato → nota citando por id → o derivado muda → a nota é acusada."""
    cfg = _mapa_iss(tmp_path, 38, 38)
    nota = tmp_path / "vault"
    nota.mkdir()
    cfg["certeza"] = {"superficies": {"vault": {"pasta": str(nota), "glob": "*.md"}}}
    k = dict(cfg=cfg, compliance_db=tmp_path / "nao_existe.db", cz=cz, estado_prop={"ok": False}, raiz=tmp_path, buscar=None,
             cron="", gravar=False)
    est = orquestrador.ciclo(**k)
    f = {x["id"]: x for x in est["fatos"]}[AGILE + ":valor"]
    assert f["valor_fmt"] == "R$ 3.800,00" and f["estado"] == "VERIFICADO" and f["nivel_prova"] == 2
    assert f["proveniencia"]["hash_fonte"] and f["proveniencia"]["data_ref"] == "2026-11-18T18:37:43"
    assert any("compliance.db" in x for x in est["indisponiveis"]) and est["contratos"]["estado"] == "INDISPONIVEL"
    (nota / "agile.md").write_text(f"ISS: {f['citar']}\n", encoding="utf-8")
    assert orquestrador.ciclo(**k)["resumo"]["divergencias_abertas"] == 0
    orquestrador.ciclo(**{**k, "cfg": {**_mapa_iss(tmp_path, 40, 40), "certeza": cfg["certeza"]}})    # o detector mediu de novo
    est = orquestrador.ciclo(**{**k, "cfg": {**_mapa_iss(tmp_path, 40, 40), "certeza": cfg["certeza"]}})
    assert [(d["tipo"], d["encontrado"], d["esperado"]) for d in est["divergencias"]] == [("citacao_divergente", "R$ 3.800,00", "R$ 4.000,00")]
    assert {x["id"]: x for x in est["fatos"]}[AGILE + ":valor"]["versoes"] == 2


# ════════════════════ FALHA 2 — sobrescrita por lote que leu no início ════════════════════

CONTRATO_LEX = {"tabela": "lex_execucao", "chave": ["numero_sei"], "colunas": {"nota_risco": {"tipo": "int", "min": 0, "max": 10}},
                "proveniencia": ["modelo", "em"],
                "nivel_prova": {"coluna": "modelo", "funcao": "compliance_agent.autoaprimoramento.ledger:nivel_gravado"}}
FONTE = "agente Claude Code (fonte primária: íntegra SEI + OB SIAFE)"
OPUS = "claude-opus (conferência do Opus sobre o resumo)"


def _lex(tmp_path):
    con = sqlite3.connect(tmp_path / "c.db", isolation_level=None)
    con.execute("CREATE TABLE lex_execucao(numero_sei TEXT PRIMARY KEY, nota_risco INTEGER, resumo TEXT, modelo TEXT, em TEXT)")
    con.execute("INSERT INTO lex_execucao VALUES ('SEI-1', 8, 'laudo de volume', 'gemini-3-flash', '2026-11-18T08:00:00')")
    return con


def test_f2_lote_que_leu_no_inicio_nao_regrava_por_cima(tmp_path):
    con = _lex(tmp_path)
    assert portoes.nivel_da_linha(CONTRATO_LEX, {"modelo": FONTE}) == 2 and portoes.nivel_da_linha(CONTRATO_LEX, {"modelo": OPUS}) == 1
    _, ficha_do_lote = portoes.ler(con, CONTRATO_LEX, {"numero_sei": "SEI-1"})        # o lote monta a lista de alvos
    # … horas depois um agente confere na fonte primária e grava (ele leu agora)
    _, ficha = portoes.ler(con, CONTRATO_LEX, {"numero_sei": "SEI-1"})
    fonte = {"numero_sei": "SEI-1", "nota_risco": 3, "resumo": "conferido nos autos", "modelo": FONTE, "em": "2026-11-18T15:00:00"}
    assert portoes.escrever(con, CONTRATO_LEX, fonte, ficha)["gravado"]
    recusas = []
    opus = {"numero_sei": "SEI-1", "nota_risco": 8, "resumo": "Opus sobre o resumo", "modelo": OPUS, "em": "2026-11-18T16:00:00"}
    ver = portoes.escrever(con, CONTRATO_LEX, opus, ficha_do_lote, recusas.append)   # o lote chega com a ficha velha
    falhas = {r["regra"] for r in ver["regras"] if not r["ok"]}
    assert not ver["gravado"] and falhas == {"P7 não regride", "P8 leu antes"} and recusas[0]["chave"] == {"numero_sei": "SEI-1"}
    assert con.execute("SELECT resumo, modelo FROM lex_execucao").fetchone() == ("conferido nos autos", FONTE)
    # mesmo relendo AGORA, juízo mais fraco não substitui prova primária (P7)
    _, agora = portoes.ler(con, CONTRATO_LEX, {"numero_sei": "SEI-1"})
    ver = portoes.escrever(con, CONTRATO_LEX, opus, agora)
    assert not ver["gravado"] and {r["regra"] for r in ver["regras"] if not r["ok"]} == {"P7 não regride"}
    # escrita sem leitura nenhuma também é recusada
    assert not portoes.escrever(con, CONTRATO_LEX, {**fonte, "resumo": "x"}, None)["gravado"]


def test_f2_controle_negativo_quem_leu_agora_e_tem_prova_igual_ou_maior_grava(tmp_path):
    con = _lex(tmp_path)
    _, f1 = portoes.ler(con, CONTRATO_LEX, {"numero_sei": "SEI-1"})
    opus = {"numero_sei": "SEI-1", "nota_risco": 7, "resumo": "Opus", "modelo": OPUS, "em": "2026-11-18T10:00:00"}
    assert portoes.escrever(con, CONTRATO_LEX, opus, f1)["gravado"]                    # 0 → 1 sobe
    _, f2 = portoes.ler(con, CONTRATO_LEX, {"numero_sei": "SEI-1"})
    fonte = {**opus, "modelo": FONTE, "resumo": "autos", "nota_risco": 2}
    assert portoes.escrever(con, CONTRATO_LEX, fonte, f2)["gravado"]                   # 1 → 2 sobe
    _, f3 = portoes.ler(con, CONTRATO_LEX, {"numero_sei": "SEI-1"})
    assert portoes.escrever(con, CONTRATO_LEX, {**fonte, "resumo": "nova leitura dos autos"}, f3)["gravado"]   # 2 → 2
    novo = {"numero_sei": "SEI-2", "nota_risco": 1, "resumo": "primeiro laudo", "modelo": "gemini", "em": "2026-11-18T10:00:00"}
    assert portoes.escrever(con, CONTRATO_LEX, novo, None)["gravado"]                  # linha nova não exige leitura
    regra = {**opus, "modelo": "regra: sem documento de execução"}                    # regra não é juízo: fora da hierarquia
    assert portoes.nivel_da_linha(CONTRATO_LEX, regra) is None


def test_f2_fotografia_acusa_regressao_de_qualquer_escritor_e_guarda_o_laudo(cz, tmp_path):
    con = _lex(tmp_path)
    con.execute("UPDATE lex_execucao SET modelo=?, resumo='conferido nos autos', nota_risco=3", (FONTE,))
    cts = {"lex_execucao": CONTRATO_LEX}
    assert portoes.fotografar(con, cz, cts)["lex_execucao"] == {"linhas": 1, "por_nivel": {"2": 1}, "regrediram_agora": 0,
                                                              "sumiram_agora": 0, "regressoes_abertas": 0}
    assert portoes.fotografar(con, cz, cts)["lex_execucao"]["regrediram_agora"] == 0       # nada mudou: nada acusa
    con.execute("UPDATE lex_execucao SET modelo=?, resumo='Opus por cima', nota_risco=8", (OPUS,))   # escritor SEM portão
    r = portoes.fotografar(con, cz, cts)["lex_execucao"]
    assert r["regrediram_agora"] == 1 and r["regressoes_abertas"] == 1
    chave, antes, depois, conteudo = cz.execute("SELECT chave, nivel_antes, nivel_depois, conteudo_antes FROM regressao").fetchone()
    assert (chave, antes, depois) == ("SEI-1", 2, 1) and json.loads(conteudo)["resumo"] == "conferido nos autos"
    assert portoes.fotografar(con, cz, cts)["lex_execucao"] == {**r, "regrediram_agora": 0}     # não acusa duas vezes
    con.execute("UPDATE lex_execucao SET modelo=?, resumo='reaplicado'", (FONTE,))
    assert portoes.fotografar(con, cz, cts)["lex_execucao"]["regressoes_abertas"] == 0         # reaplicou: curada
    con.execute("DELETE FROM lex_execucao")
    assert portoes.fotografar(con, cz, cts)["lex_execucao"]["sumiram_agora"] == 1              # prova primária apagada


def test_f2_fato_exige_a_versao_lida_e_o_registro_e_so_acrescimo(cz):
    f = _fato(AGILE + ":valor", 2270009.39)
    assert fatos.registrar(cz, f, None)["status"] == "novo"
    lida = fatos.vigente(cz, f["fato_id"])["hash_versao"]
    assert fatos.registrar(cz, {**f, "valor": 2437189.45}, lida)["status"] == "atualizado"
    r = fatos.registrar(cz, {**f, "valor": 2300000.00}, lida)           # produtor que leu ANTES da atualização
    assert r["status"] == "recusado" and [x["regra"] for x in r["regras"] if not x["ok"]] == ["P8 leu antes"]
    assert fatos.registrar(cz, {**f, "valor": 1.0}, None)["status"] == "recusado"                 # não leu nada
    assert fatos.vigente(cz, f["fato_id"])["valor"] == 2437189.45
    assert cz.execute("SELECT COUNT(*) FROM recusa").fetchone()[0] == 2
    agora = fatos.vigente(cz, f["fato_id"])["hash_versao"]
    r = fatos.registrar(cz, {**f, "valor": 2437189.45, "nivel_prova": 1, "estado": "PENDENTE"}, agora)
    assert r["status"] == "recusado" and [x["regra"] for x in r["regras"] if not x["ok"]] == ["P7 não regride"]
    assert fatos.registrar(cz, {**f, "valor": 2437189.45, "hash_fonte": "outra"}, agora)["status"] == "igual"   # mesma medida: confirma
    assert [h["valor"] for h in fatos.historico(cz, f["fato_id"])] == [2270009.39, 2437189.45]
    with pytest.raises(sqlite3.IntegrityError, match="só acréscimo"):
        cz.execute("UPDATE fato_versao SET valor=1")
    with pytest.raises(sqlite3.IntegrityError, match="só acréscimo"):
        cz.execute("DELETE FROM fato_versao")


# ════════════════════ FALHA 3 — número inventado (total_pago = 1e12 para furar a fila) ════════════════════

CONTRATO_FILA = {"tabela": "sei_fila_captura", "chave": ["numero_sei"], "proveniencia": ["motivo", "visto_em"],
                 "colunas": {"total_pago": {"monetaria": True, "min": 0, "max": 2.0e10}}}


def _fila(tmp_path):
    con = sqlite3.connect(tmp_path / "f.db", isolation_level=None)
    con.execute("CREATE TABLE sei_fila_captura(numero_sei TEXT PRIMARY KEY, motivo TEXT, total_pago REAL, visto_em TEXT)")
    return con


@pytest.mark.parametrize("valor", [1e12, 1e9, 1e10, 9.9e11, -5.0, float("inf"), float("nan")])
def test_f3_valor_inventado_nao_entra_como_fato(cz, valor):
    r = fatos.registrar(cz, _fato("fila:SEI-1:total_pago", valor, max=5e10, min=0), None)
    assert r["status"] == "recusado" and "P2 tipo e faixa" in [x["regra"] for x in r["regras"] if not x["ok"]]


@pytest.mark.parametrize("valor", [385799673.52, 0.0, 1500000000.0, 1234567890.12])
def test_f3_controle_negativo_valor_real_entra(cz, valor):
    assert fatos.registrar(cz, _fato("fila:SEI-1:total_pago", valor), None)["status"] == "novo"


def test_f3_fato_sem_proveniencia_e_recusado(cz):
    for campo in ("fonte", "consulta", "data_ref", "hash_fonte", "produtor"):
        r = fatos.registrar(cz, {**_fato("a:b:c", 10.0), campo: " "}, None)
        assert [x["regra"] for x in r["regras"] if not x["ok"]] == ["P3 proveniência"], campo
    assert fatos.registrar(cz, {**_fato("Sem Identidade", 10.0)}, None)["status"] == "recusado"


def test_f3_fila_portao_auditoria_e_gatilho(tmp_path, monkeypatch):
    con = _fila(tmp_path)
    linha = {"numero_sei": "SEI-1", "motivo": "recaptura", "total_pago": 1e12, "visto_em": "2026-11-18"}
    ver = portoes.escrever(con, CONTRATO_FILA, linha, None)                       # PREVENTIVO (código novo)
    assert not ver["gravado"] and "máximo" in ver["regras"][0]["detalhe"]
    assert portoes.escrever(con, CONTRATO_FILA, {**linha, "total_pago": 385799673.52}, None)["gravado"]
    assert not portoes.escrever(con, CONTRATO_FILA, {"numero_sei": "SEI-9", "motivo": "", "total_pago": 1.0, "visto_em": "x"}, None)["gravado"]
    assert portoes.auditar(con, {"fila": CONTRATO_FILA}) == []                    # tabela limpa: nada a acusar
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-2', 'prioridade', 1e12, '2026-11-18')")   # escritor antigo, sem portão
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-3', NULL, 10, '2026-11-18')")
    aud = {(a["regra"], a["n"]) for a in portoes.auditar(con, {"fila": CONTRATO_FILA})}             # DETECTIVO
    assert aud == {("P2 tipo e faixa", 1), ("P3 proveniência", 1)}
    assert portoes.auditar(con, {"x": {"tabela": "nao_existe", "chave": ["k"]}})[0]["n"] is None    # contrato cego ≠ sem violação
    con.execute("DELETE FROM sei_fila_captura WHERE numero_sei IN ('SEI-2','SEI-3')")
    for ddl in portoes.ddl_gatilhos("sei_fila_captura", CONTRATO_FILA):           # PREVENTIVO no banco (qualquer escritor)
        con.execute(ddl)
    for sql in ("INSERT INTO sei_fila_captura VALUES ('SEI-4','p',1e12,'d')", "INSERT OR IGNORE INTO sei_fila_captura VALUES ('SEI-4','p',1e12,'d')",
                "INSERT OR REPLACE INTO sei_fila_captura VALUES ('SEI-1','p',1e12,'d')", "UPDATE sei_fila_captura SET total_pago=1e12",
                "UPDATE sei_fila_captura SET total_pago=-1"):
        with pytest.raises(sqlite3.IntegrityError, match="fora do contrato"):
            con.execute(sql)
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-5','p',174407051.98,'d')")
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-6','p',NULL,'d')")
    assert con.execute("SELECT COUNT(*), MAX(total_pago) FROM sei_fila_captura").fetchone() == (3, 385799673.52)
    assert portoes.ddl_gatilhos("lex", {"tabela": "lex_execucao", "chave": ["numero_sei"]}) == []
    with pytest.raises(ValueError):
        portoes.ddl_gatilhos("x", {"tabela": "t; DROP TABLE x", "chave": ["k"]})


# ════════════════════ FALHA 4 — status ambíguo ('Enviado ao Banco' contado como pago) ════════════════════

def _ob(tmp_path):
    db = tmp_path / "ob.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob(numero_ob TEXT, status TEXT, status_envio TEXT, valor REAL)")
    con.executemany("INSERT INTO ob VALUES (?,?,?,?)", [("1", "Contabilizado", "Processado e Pago", 100.0), ("2", "Contabilizado", "Processado e Pago", 50.0),
                                                        ("3", "Contabilizado", "Enviado ao Banco", 70.0), ("4", "Contabilizado", "Parcialmente Pago", 5.0)])
    con.commit()
    bloco = {"id": "siafe_ob:contabilizada:{envio}", "sql": "SELECT status_envio AS envio, COUNT(*) AS n, SUM(valor) AS valor FROM ob GROUP BY 1",
             "rotulo": "OB — '{envio}'", "fonte": "SIAFE", "natureza": "pago", "nivel_prova": 2,
             "estado_por": {"campo": "envio", "padrao": "PENDENTE", "mapa": {"Processado e Pago": "VERIFICADO", "Parcialmente Pago": "A CONFERIR"}},
             "base_por": {"campo": "envio", "padrao": "ob_contabilizada_sem_confirmacao", "mapa": {"Processado e Pago": config.BASE_PAGO_CONFIRMADO}},
             "medidas": {"valor": {"campo": "valor", "unidade": "BRL"}}}
    return con, {"fontes": {"siafe_ob": {"nome": "OB", "fatos": [bloco]}}, "derivados": {}, "cerebro": []}


def test_f4_cada_status_e_um_fato_com_o_seu_estado(cz, tmp_path):
    ro, cfg = _ob(tmp_path)
    props, erros = fatos.extrair(cfg, ro)
    assert not erros and fatos.registrar_lote(cz, props)["novo"] == 3
    v = {f["fato_id"]: (f["valor"], f["estado"], f["base"]) for f in fatos.vigentes(cz)}
    assert v == {"siafe_ob:contabilizada:Processado_e_Pago:valor": (150.0, "VERIFICADO", "ob_contabilizada_confirmada"),
                 "siafe_ob:contabilizada:Enviado_ao_Banco:valor": (70.0, "PENDENTE", "ob_contabilizada_sem_confirmacao"),
                 "siafe_ob:contabilizada:Parcialmente_Pago:valor": (5.0, "A CONFERIR", "ob_contabilizada_sem_confirmacao")}
    assert all(f["consulta"].startswith("SELECT status_envio") and f["hash_fonte"] for f in fatos.vigentes(cz))


def test_f4_pago_verificado_sem_envio_confirmado_e_recusado(cz):
    f = _fato("ob:x:valor", 70.0, natureza="pago", base="ob_contabilizada_sem_confirmacao")
    r = fatos.registrar(cz, f, None)
    assert r["status"] == "recusado" and [x["regra"] for x in r["regras"] if not x["ok"]] == ["P6 pagamento"]
    assert fatos.registrar(cz, {**f, "estado": "PENDENTE"}, None)["status"] == "novo"            # o mesmo valor, dito como PENDENTE
    assert fatos.registrar(cz, _fato("ob:y:valor", 70.0, natureza="pago", base=config.BASE_PAGO_CONFIRMADO), None)["status"] == "novo"
    assert fatos.registrar(cz, _fato("ob:z:valor", None, estado="INDISPONIVEL"), None)["status"] == "novo"   # INDISPONÍVEL sem valor
    assert fatos.registrar(cz, _fato("ob:w:valor", 0.0, estado="INDISPONIVEL"), None)["status"] == "recusado"   # INDISPONÍVEL ≠ 0
    assert fatos.formatar(None, "BRL") == "INDISPONÍVEL"


def test_f4_fonte_ausente_e_erro_declarado_nunca_zero(cz, tmp_path):
    cfg = _mapa_iss(tmp_path)
    (tmp_path / "data" / "iss.json").unlink()
    props, erros = fatos.extrair(cfg, raiz=tmp_path, cz=cz)
    assert props == [] and erros[0]["no"] == "iss" and "FileNotFoundError" in erros[0]["erro"]
    assert cz.execute("SELECT n, erro FROM extracao").fetchone()[0] is None
    (tmp_path / "data" / "iss.json").write_text("{quebrado", encoding="utf-8")
    assert fatos.extrair(cfg, raiz=tmp_path)[1]
    _, cfg_sql = _ob(tmp_path)
    assert "sem conexão" in fatos.extrair(cfg_sql, None)[1][0]["erro"]


# ════════════════════ FALHA 5 — fonte nova que não suja nada (re-perícia que não acontecia) ════════════════════

def recapturados_teste(_ro):
    return ["SEI-1", "SEI-2", "SEI-3"]


def _estado_prop(cfg, **der):
    return {"ok": True, "estado": "ok",
            "fontes": [{"id": f, "manual": "sonda" not in d, "mudou_em": 1.0, "erro": None, "alimenta": []} for f, d in cfg["fontes"].items()],
            "derivados": [{"id": i, "ultimo_fim": time.time(), "ultimo_estado": "ok", "falhas": 0, "sujo": False, "sujo_desde": None,
                           **der.get(i, {})} for i in cfg["derivados"]]}


def test_f5_grafo_doente_cada_defeito_e_listado(tmp_path):
    cfg = {"fontes": {"sei_arquivado": {"nome": "captura", "sonda": {"sql": "x"}}, "sei_lex": {"nome": "laudo", "sonda": {"sql": "x"}},
                      "orfa": {"nome": "ninguém lê", "sonda": {"sql": "x"}}, "muda": {"nome": "sem sonda, sem emissor"}},
           "derivados": {"painel": {"nome": "p", "depende": ["sei_lex", "muda"], "comando": ["{py}", "-m", "a.b"], "intervalo_min_s": 600},
                         "nunca": {"nome": "n", "depende": ["sei_lex"], "comando": ["x"], "onde": "aba", "efeito": {"arquivo": "data/nao_existe.json"}}},
           "externos": {"lex": {"nome": "perícia", "depende": ["sei_arquivado"], "publica": "sei_lex", "cron": "fila.sh lex",
                                "atraso": {"funcao": "tests.test_certeza_aceite:recapturados_teste", "teto": 2}},
                        "torto": {"nome": "t", "depende": ["nao_existe"], "publica": "tambem_nao"}},
           "cerebro": []}
    ep = _estado_prop(cfg, painel={"sujo": True, "sujo_desde": time.time() - 30 * 3600},
                      nunca={"ultimo_fim": None, "ultimo_estado": None})
    a = grafo.auditar(cfg, ep, tmp_path, cron="# 13 * * * * fila.sh lex\n", ro=object())["achados"]
    assert a["fonte_sem_consumidor"] == ["orfa"] and a["fonte_sem_sonda_nem_emissor"] == ["muda"]
    assert a["derivado_nunca_rodou"] == ["nunca"] and a["derivado_sem_efeito_verificavel"] == ["painel"]
    assert a["derivado_sem_consumidor"] == ["painel"] and a["derivado_atrasado"][0].startswith("painel: sujo há 30")
    assert a["externo_sem_agendamento"] == ["lex: 'fila.sh lex' não está agendado"]            # linha comentada não agenda
    assert a["externo_atrasado"][0].startswith("lex: 3 item(ns)")
    assert sorted(a["erro_de_mapa"]) == ["externo torto: depende de 'nao_existe', que não existe",
                                         "externo torto: publica 'tambem_nao', que não é fonte"]


def test_f5_controle_negativo_grafo_sao_e_grafo_cego(tmp_path):
    cfg = {"fontes": {"sei_arquivado": {"nome": "captura", "sonda": {"sql": "x"}}, "sei_lex": {"nome": "laudo", "sonda": {"sql": "x"}},
                      "decisao": {"nome": "manual de propósito", "manual": True}},
           "derivados": {"painel": {"nome": "p", "depende": ["sei_lex", "decisao"], "comando": ["x"], "onde": "aba", "efeito": {"arquivo": "e.json"}}},
           "externos": {"lex": {"nome": "perícia", "depende": ["sei_arquivado"], "publica": "sei_lex", "cron": "fila.sh lex",
                                "atraso": {"funcao": "tests.test_certeza_aceite:recapturados_teste", "teto": 3}}},
           "cerebro": []}
    (tmp_path / "e.json").write_text("{}", encoding="utf-8")
    r = grafo.auditar(cfg, _estado_prop(cfg), tmp_path, cron="13,43 * * * * /bin/bash fila.sh lex\n", ro=object())
    assert r["resumo"]["graves"] == 0 and not r["achados"]["fonte_sem_consumidor"] and not r["achados"]["externo_atrasado"]
    cego = grafo.auditar(cfg, {"ok": False}, tmp_path, cron=None, ro=None)                     # sem despachante e sem crontab
    assert "derivado_nunca_rodou" not in cego["achados"] and len(cego["indisponiveis"]) >= 2   # não medido ≠ zero


def test_f5_mapa_real_fecha_a_cadeia_e_a_certeza_e_folha():
    """O config/propagacao.yaml de verdade: sem erro, externos ligados a fontes reais, blocos de fato bem formados, e
    nada depende do derivado `certeza` (não há realimentação: o ciclo não se reaciona)."""
    from compliance_agent import propagacao
    cfg = propagacao.carregar()
    r = grafo.auditar(cfg, {"ok": False}, cron=None)
    assert r["achados"]["erro_de_mapa"] == [] and r["achados"]["fonte_sem_sonda_nem_emissor"] == []
    assert not [i for i, d in cfg["derivados"].items() if "certeza" in d.get("depende", [])]
    assert cfg["externos"]["lex_execucao"]["publica"] == "sei_lex" and "sei_arquivado" in cfg["externos"]["lex_execucao"]["depende"]
    ids = set()
    for no, i, b in fatos.blocos(cfg):
        assert b["id"].split(":")[0] == b["id"].split(":")[0].lower() and b.get("fonte") and b.get("medidas"), (no, i)
        assert ("arquivo" in b) != ("sql" in b), (no, i)
        assert "estado" in b or "estado_por" in b, (no, i)
        assert "nivel_prova" in b or "nivel_por" in b, (no, i)
        assert b["id"] not in ids, f"id de fato repetido: {b['id']}"
        ids.add(b["id"])
        for m in b["medidas"].values():
            assert m["unidade"] in config.UNIDADES
    assert len(ids) >= 4
    for cid, c in cfg["contratos"].items():
        portoes.ddl_gatilhos(cid, c)                                                            # nomes válidos
        assert c["tabela"] and c["chave"]


# ════════════════════ FALHA 6 — certeza: 🔴/🟡 e VERIFICADO só com prova primária ════════════════════

@pytest.mark.parametrize("extra", [{"nivel_prova": 1}, {"nivel_prova": 0}, {"estado": "PENDENTE", "nivel_prova": 1, "graduacao": "🔴"},
                                   {"estado": "A CONFERIR", "nivel_prova": 0, "graduacao": "🟡"}])
def test_f6_verificado_ou_graduacao_sem_prova_primaria_e_recusado(cz, extra):
    r = fatos.registrar(cz, {**_fato("achado:x:risco", 9, "indice"), **extra}, None)
    assert r["status"] == "recusado" and [x["regra"] for x in r["regras"] if not x["ok"]] == ["P5 prova primária"]


@pytest.mark.parametrize("extra", [{"nivel_prova": 2, "graduacao": "🔴"}, {"estado": "PENDENTE", "nivel_prova": 0},
                                   {"estado": "A CONFERIR", "nivel_prova": 1, "confianca": 0.31}])
def test_f6_controle_negativo(cz, extra):
    assert fatos.registrar(cz, {**_fato("achado:x:risco", 9, "indice"), **extra}, None)["status"] == "novo"


def test_f6_laudo_alto_sem_fonte_nao_sai_verificado_e_carrega_a_taxa(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_AUTOAPRIMORAMENTO_DIR", str(tmp_path / "auto"))
    (tmp_path / "auto").mkdir()
    con = _lex(tmp_path)
    con.executemany("INSERT INTO lex_execucao VALUES (?,?,?,?,?)", [("SEI-2", 9, "", OPUS, ""), ("SEI-3", 8, "", FONTE, ""),
                                                                    ("SEI-4", 3, "", "gemini-3-flash", ""), ("SEI-5", 0, "", "regra: sem doc", "")])
    r = orquestrador.laudos(con)
    assert r["calibracao"] == "INDISPONIVEL" and r["risco_alto_verificado_sem_prova_primaria"] == []
    n = {x["nivel_prova"]: x for x in r["por_nivel"]}
    assert n[0]["risco_alto"] == 1 and n[0]["sem_taxa"] == 1 and n[0]["esperados_confirmar"] == 0     # sem taxa ≠ taxa zero
    assert n[2] == {"nivel_prova": 2, "quem": "fonte primária", "laudos": 1, "risco_alto": 1, "esperados_confirmar": 1, "sem_taxa": 0}
    (tmp_path / "auto" / "calibracao.json").write_text(json.dumps(
        {"opus_resumo": {"claude-opus:resumo": {"alta": {"n": 26, "k": 8, "p": 0.315, "lo": 0.154, "hi": 0.499}}}, "motores_fracos": {}}), encoding="utf-8")
    from compliance_agent.correlacao_sei import estado_do_laudo
    assert estado_do_laudo(OPUS, 9)[0] != "VERIFICADO" and estado_do_laudo(FONTE, 8)[0] == "VERIFICADO"
