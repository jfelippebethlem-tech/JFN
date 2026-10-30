# -*- coding: utf-8 -*-
"""Loop de automelhoria de TUDO: problema novo abre, sumiço do sinal cura, volta depois de curado reincide,
e sensor que não mede vira problema — nunca 'ok'."""
import json

import tools.automelhoria_geral as A


def _p(sig, area="slo"):
    return A._p(area, sig, f"titulo {sig}")


def test_ciclo_aberto_curado_reincidiu(tmp_path):
    fila = tmp_path / "fila.json"
    r = A.conciliar([_p("x")], fila, agora=1_000)
    assert r["novos"] == ["slo:x"] and r["fila"]["slo:x"]["status"] == "aberto"
    r = A.conciliar([], fila, agora=2_000)                       # o sensor voltou ao verde
    assert r["curados"] == ["slo:x"] and r["fila"]["slo:x"]["status"] == "curado"
    r = A.conciliar([_p("x")], fila, agora=3_000)                # e o problema voltou
    assert r["reincidiu"] == ["slo:x"] and r["fila"]["slo:x"]["status"] == "REINCIDIU"


def test_problema_persistente_nao_e_novo_de_novo(tmp_path):
    fila = tmp_path / "fila.json"
    A.conciliar([_p("x")], fila, agora=1_000)
    r = A.conciliar([_p("x")], fila, agora=2_000)
    assert r["novos"] == [] and r["reincidiu"] == [] and r["fila"]["slo:x"]["rodadas"] == 2


def test_sensor_quebrado_vira_problema_nao_ok():
    def quebra():
        raise RuntimeError("gh sem rede")
    problemas, medidos = A.sentir({"ci": quebra, "bom": lambda: []})
    assert medidos == {"ci": None, "bom": 0}
    assert [p["assinatura"] for p in problemas] == ["sensor:ci"]


def test_resumo_poe_reincidencia_primeiro(tmp_path):
    fila = tmp_path / "fila.json"
    A.conciliar([_p("a"), _p("b", "ci")], fila, agora=1_000)
    A.conciliar([_p("a")], fila, agora=2_000)
    r = A.conciliar([_p("a"), _p("b", "ci")], fila, agora=3_000)
    txt = A.resumo(r["fila"])
    assert txt.index("REINCIDIU") < txt.index("titulo a")


def _rem(sig="x"):
    return A._p("slo", sig, f"titulo {sig}", remediar="echo conserta")


def test_remedio_roda_respeita_intervalo_e_escala(tmp_path, monkeypatch):
    monkeypatch.setattr(A.os if hasattr(A, "os") else __import__("os"), "getloadavg", lambda: (0.5, 0, 0))
    fila_p, cmds = tmp_path / "fila.json", []
    exe = lambda cmd, log: cmds.append(cmd)
    r = A.conciliar([_rem()], fila_p, agora=1_000)
    assert A.remediar(r["fila"], agora=1_000, executar=exe)["feitos"] == ["slo:x"]
    assert A.remediar(r["fila"], agora=2_000, executar=exe)["feitos"] == []          # dentro das 20 h
    assert A.remediar(r["fila"], agora=1_000 + A.INTERVALO_S, executar=exe)["feitos"] == ["slo:x"]
    out = A.remediar(r["fila"], agora=1_000 + 3 * A.INTERVALO_S, executar=exe)      # 2 tentativas, não curou
    assert out["feitos"] == [] and out["escalados"] == ["slo:x"]
    assert cmds == ["echo conserta", "echo conserta"]


def test_cura_e_creditada_ao_remedio_e_reincidencia_rearma(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getloadavg", lambda: (0.5, 0, 0))
    fila_p = tmp_path / "fila.json"
    r = A.conciliar([_rem()], fila_p, agora=1_000)
    A.remediar(r["fila"], agora=1_000, executar=lambda c, l: None)
    fila_p.write_text(__import__("json").dumps(r["fila"]))
    r = A.conciliar([], fila_p, agora=5_000)
    assert r["fila"]["slo:x"]["curado_por"] == "remédio automático"
    r = A.conciliar([_rem()], fila_p, agora=9_000)
    assert r["fila"]["slo:x"]["status"] == "REINCIDIU" and r["fila"]["slo:x"]["acoes"] == []


def test_carga_alta_adia_sem_executar(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getloadavg", lambda: (9.0, 0, 0))
    r = A.conciliar([_rem()], tmp_path / "f.json", agora=1_000)
    out = A.remediar(r["fila"], agora=1_000, executar=lambda c, l: (_ for _ in ()).throw(AssertionError("rodou")))
    assert out["adiados"] == ["slo:x"]


def test_sem_remedio_nao_age(tmp_path):
    r = A.conciliar([A._p("ci", "b", "CI vermelho", acao_humana="ver log")], tmp_path / "f.json", agora=1_000)
    assert A.remediar(r["fila"], agora=1_000, executar=lambda c, l: None)["feitos"] == []
    assert "👤 ver log" in A.resumo(r["fila"])


def test_executar_destacado_aceita_variavel_de_ambiente(tmp_path, monkeypatch):
    """1º teste ao vivo (24/10): `nice -n 10 PYTHONPATH=. …` falhava e o remédio nunca rodava."""
    import time as _t
    monkeypatch.setattr(A, "_REPO", tmp_path)
    log = tmp_path / "r.log"
    A._executar_destacado("X=ok; echo valor=$X", log)
    for _ in range(50):
        if "valor=ok" in log.read_text():
            break
        _t.sleep(0.1)
    assert "valor=ok" in log.read_text()


def test_sensor_rem_transforma_passo_degradado_em_problema(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(A, "DATA", tmp_path)
    (tmp_path / "hermes_metacognicao_ultimo.json").write_text(json.dumps(
        {"reflexao": "ok", "auto_melhoria_erro": "pool LLM saturado", "rag_rebuild": True}))
    ps = A.sensor_rem()
    assert [p["assinatura"] for p in ps] == ["rem:auto_melhoria_erro"]
    assert "auto_melhoria" in ps[0]["titulo"] and ps[0]["acao_humana"]


def test_sensor_dados_aponta_platô_com_remedio(monkeypatch):
    import tools.siafe_recoletar_dias as R
    monkeypatch.setattr(R, "suspeitos", lambda exercicio=None: [("21/10/2026", 992)])
    ps = A.sensor_dados_siafe()
    assert ps[0]["assinatura"] == "dados:siafe_dias_no_plato" and "21/10/2026=992" in ps[0]["detalhe"]
    assert "siafe_recoletar_dias.py --auto" in ps[0]["remediar"]


def test_plato_ignora_dia_ja_verificado(tmp_path, monkeypatch):
    import sqlite3
    import tools.siafe_recoletar_dias as R
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("create table ob_orcamentaria_siafe (exercicio int, data_emissao text)")
    con.executemany("insert into ob_orcamentaria_siafe values (2026, ?)",
                    [("21/10/2026",)] * 992 + [("20/10/2026",)] * 500 + [("19/10/2026",)] * 996)
    con.commit(); con.close()
    monkeypatch.setattr(R, "VERIFICADOS", tmp_path / "v.json")
    assert R.suspeitos(2026, db) == [("21/10/2026", 992), ("19/10/2026", 996)]
    (tmp_path / "v.json").write_text('{"19/10/2026": {}}')
    assert R.suspeitos(2026, db) == [("21/10/2026", 992)]


def test_recoleta_parcial_nao_vira_verificado(tmp_path, monkeypatch):
    """17/03/2026: colheu 879 com 998 na base e sem estouro — não prova o dia."""
    import asyncio
    import json
    import types
    import tools.siafe_recoletar_dias as R
    monkeypatch.setattr(R, "VERIFICADOS", tmp_path / "v.json")
    monkeypatch.setattr(R, "INCONCLUSIVOS", tmp_path / "i.json")      # nunca o arquivo real de data/
    monkeypatch.setattr(R, "_ULT_INCONCLUSIVO", {})
    monkeypatch.setattr(R, "_contar", lambda d, e: 998)
    falso = types.SimpleNamespace()

    async def parcial(ex, d):
        return {"ok": True, "estouro": False, "ingeridas": 879}

    async def subdividiu(ex, d):
        return {"ok": True, "estouro": True, "ingeridas": 996}
    import compliance_agent.siafe_ob_orcamentaria as M
    monkeypatch.setattr(M, "coletar_por_data", parcial)
    asyncio.run(R.recoletar(["17/03/2026"], 2026))
    assert not (tmp_path / "v.json").exists() or "17/03/2026" not in json.loads((tmp_path / "v.json").read_text())
    monkeypatch.setattr(M, "coletar_por_data", subdividiu)
    asyncio.run(R.recoletar(["19/10/2026"], 2026))
    assert "19/10/2026" in json.loads((tmp_path / "v.json").read_text())
    del falso


def test_colheita_estavel_em_duas_rodadas_verifica_o_dia(tmp_path, monkeypatch):
    """17/03/2026: 879 duas vezes com 998 na base — a visão por data é completa; o excesso vem de outras coletas."""
    import asyncio
    import json
    import tools.siafe_recoletar_dias as R
    import compliance_agent.siafe_ob_orcamentaria as M
    monkeypatch.setattr(R, "VERIFICADOS", tmp_path / "v.json")
    monkeypatch.setattr(R, "INCONCLUSIVOS", tmp_path / "i.json")
    monkeypatch.setattr(R, "_ULT_INCONCLUSIVO", {})
    monkeypatch.setattr(R, "_contar", lambda d, e: 998)

    async def colhe(ex, d):
        return {"ok": True, "estouro": False, "ingeridas": 879}
    monkeypatch.setattr(M, "coletar_por_data", colhe)
    asyncio.run(R.recoletar(["17/03/2026"], 2026))                  # 1ª leitura: inconclusivo
    assert not (tmp_path / "v.json").exists()
    asyncio.run(R.recoletar(["17/03/2026"], 2026))                  # 2ª igual: estável → verificado
    v = json.loads((tmp_path / "v.json").read_text())["17/03/2026"]
    assert v["ingeridas"] == 879 and v["base"] == 998 and "estável" in v["nota"]


def test_polimonitor_processo_parado_tem_remedio(monkeypatch):
    import json
    import subprocess as sp
    saida = json.dumps([{"name": "bond-worker", "pm2_env": {"status": "errored", "restart_time": 7}},
                        {"name": "politimonitor", "pm2_env": {"status": "online"}}])
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, saida, ""))
    ps = A.sensor_polimonitor()
    assert [p["assinatura"] for p in ps] == ["polimonitor:bond-worker"]
    assert ps[0]["remediar"].endswith("pm2 restart bond-worker")


def test_polimonitor_le_jlist_com_aviso_de_versao(monkeypatch):
    """30/10/2026: depois de `npm i -g pm2`, o `pm2 jlist` imprime o aviso "In-memory PM2 is out-of-date" ANTES do
    JSON e o sensor ficava cego (JSONDecodeError)."""
    import json
    import subprocess as sp
    saida = (">>>> In-memory PM2 is out-of-date, do:\n>>>> $ pm2 update\nIn memory PM2 version: 7.0.4\n"
             "Local PM2 version: 7.1.1\n\n" + json.dumps([{"name": "bond-worker", "pm2_env": {"status": "stopped"}}]))
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, saida, ""))
    assert [p["assinatura"] for p in A.sensor_polimonitor()] == ["polimonitor:bond-worker"]


def test_dispensado_pelo_dono_sai_da_fila_sem_virar_curado(tmp_path):
    """28/10/2026: o dono mandou esquecer os curtidores do Instagram. O item não pode virar 'curado'
    (mentira: nada foi consertado) nem continuar 'aberto' cobrando uma decisão que ele já tomou."""
    fila = tmp_path / "f.json"
    A.conciliar([_p("x", "slo")], fila, agora=1_000)
    sig = next(iter(json.loads(fila.read_text())))
    r = A.conciliar([], fila, agora=2_000, dispensados={sig})
    assert r["fila"][sig]["status"] == "dispensado" and sig not in r["curados"]
    txt = A.resumo(r["fila"])
    assert "0 aberto(s)" in txt and "Dispensados pelo dono" in txt


def test_slo_dispensado_nao_alarma(tmp_path, monkeypatch):
    import yaml
    import tools.pipelines_slo as SLO
    p = tmp_path / "pipelines.yaml"
    p.write_text(yaml.safe_dump({"pipelines": [
        {"nome": "a", "arquivo": "x.log", "max_stale_h": 1, "dispensado": "dono"},
        {"nome": "b", "arquivo": "y.log", "max_stale_h": 1}]}), encoding="utf-8")
    monkeypatch.setattr(SLO, "CFG", p)
    monkeypatch.setattr(SLO, "BASE", tmp_path)
    st = {r["nome"]: r["status"] for r in SLO.checar()}
    assert st == {"a": "dispensado", "b": "ausente"}      # dispensar um não cala os outros


def test_fila_que_so_acumula_vira_problema(tmp_path):
    """28/10/2026: lex_feedback com 3.068 abertas e 0 resolvidas desde junho — produtor sem consumidor."""
    import sqlite3
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE lex_feedback (id INTEGER, resolvido INTEGER, resolvido_em TEXT)")
    con.executemany("INSERT INTO lex_feedback VALUES (?, 0, NULL)", [(i,) for i in range(150)])
    con.commit()
    r = A.sensor_filas(db)
    assert [p["assinatura"] for p in r] == ["filas:lex_feedback"]
    con.execute("UPDATE lex_feedback SET resolvido = 1, resolvido_em = '2999-01-01' WHERE id < 5")
    con.commit(); con.close()
    assert A.sensor_filas(db) == []          # alguém está fechando: a fila tem consumidor


def test_causa_externa_nao_reinicia_servico(monkeypatch):
    """28/10/2026: o TFE recusa o IP da VM; reiniciar não cura e cada falha re-avisa o dono pelo OnFailure."""
    class _R:
        stdout = "jfn-tfe-ob.service loaded failed failed X\n"
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(A, "_ultimo_erro", lambda u: "RuntimeError: TFE recusou o IP de origem da VM (...)")
    [p] = A.sensor_systemd()
    assert p["remediar"] == "" and "OuvERJ" in p["acao_humana"]


def test_login_que_voltou_depois_do_disjuntor_cura(tmp_path, monkeypatch):
    """28/10/2026: um soluço de login às 13:36 deixava o SIAFE 1 'quebrado' por 24 h no vigia."""
    import os
    import time
    monkeypatch.setattr(A, "DATA", tmp_path)
    (tmp_path / "sei_cache").mkdir()
    (tmp_path / "sei_cache" / "siafe_runner_ultimo.json").write_text(json.dumps({"ok": True}))
    av = tmp_path / ".siafe_dreno_aviso_login_1"
    av.touch()
    os.utime(av, (time.time() - 3600,) * 2)
    assert [p["assinatura"] for p in A.sensor_siafe() if "login" in p["assinatura"]] == ["siafe:login_sistema_1"]
    (tmp_path / ".siafe_dreno_login_ok_1").touch()
    assert not [p for p in A.sensor_siafe() if "login" in p["assinatura"]]


def test_senha_recusada_vira_acao_do_dono_sem_remedio(tmp_path, monkeypatch):
    """30/10/2026: 'Usuário e/ou senha incorretos'. Remédio automático = rodar o diário de novo = mais um login
    errado (o caminho do bloqueio da conta). Senha é do dono: item humano, sem remédio."""
    import os
    data = tmp_path / "data"; (data / "sei_cache").mkdir(parents=True)
    monkeypatch.setattr(A, "DATA", data)
    (data / "sei_cache" / "siafe_runner_ultimo.json").write_text(json.dumps(
        {"ok": False, "erro": "senha_incorreta", "detail": "SIAFE recusou usuário/senha"}))
    env = tmp_path / ".env"; env.write_text("x"); os.utime(env, (1_000, 1_000))
    (data / ".siafe_dreno_credencial_1").touch()
    ps = {p["assinatura"]: p for p in A.sensor_siafe()}
    assert ps["siafe:diario"]["remediar"] == "" and "SIAFE_PASS" in ps["siafe:diario"]["acao_humana"]
    assert "SIAFE_PASS" in ps["siafe:credencial_1"]["acao_humana"]
    os.utime(env)                                    # o dono atualizou o .env depois do carimbo
    assert "siafe:credencial_1" not in {p["assinatura"] for p in A.sensor_siafe()}
