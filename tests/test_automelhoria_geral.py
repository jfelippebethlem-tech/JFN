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
    monkeypatch.setattr(R, "lacunas_tfe", lambda exercicio=None: [])
    ps = A.sensor_dados_siafe()
    assert ps[0]["assinatura"] == "dados:siafe_dias_no_plato" and "21/10/2026=992" in ps[0]["detalhe"]
    assert "siafe_recoletar_dias.py --auto" in ps[0]["remediar"]


def test_sensor_dados_aponta_lacuna_do_tfe(monkeypatch):
    import tools.siafe_recoletar_dias as R
    monkeypatch.setattr(R, "suspeitos", lambda exercicio=None: [])
    monkeypatch.setattr(R, "lacunas_tfe", lambda exercicio=None: [("01/09/2026", 1235), ("18/09/2026", 1177)])
    (p,) = A.sensor_dados_siafe()
    assert p["assinatura"] == "dados:siafe_lacunas_tfe" and "01/09/2026=1235" in p["detalhe"]
    assert "2.412 OBs" in p["titulo"] and "--tfe --auto" in p["remediar"]


def test_lacuna_tfe_casa_numero_e_ug_e_nao_insiste_no_residuo(tmp_path, monkeypatch):
    """Lacuna = OB do espelho sem par (número + UG) no SIAFE. Dia já recolhido só volta se a lacuna crescer."""
    import sqlite3
    import tools.siafe_recoletar_dias as R
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("create table ordens_bancarias (numero_ob text, ug_codigo text, data_emissao text, "
                "categoria text, exercicio text)")
    con.execute("create table ob_orcamentaria_siafe (numero_ob text, ug_emitente text)")
    for i in range(40):
        con.execute("insert into ordens_bancarias values (?, '180100', '2026-09-01', 'tfe_ob', '2026')",
                    (f"2026OB{i:05d}",))
    for i in range(10):    # 10 no SIAFE pela mesma UG; 5 com o número certo mas OUTRA UG não contam
        con.execute("insert into ob_orcamentaria_siafe values (?, '180100')", (f"2026OB{i:05d}",))
    for i in range(10, 15):
        con.execute("insert into ob_orcamentaria_siafe values (?, '999900')", (f"2026OB{i:05d}",))
    con.execute("insert into ordens_bancarias values ('2026OB99999', '180100', '2026-09-02', 'tfe_ob', '2026')")
    con.commit(); con.close()
    monkeypatch.setattr(R, "TFE_VERIFICADOS", tmp_path / "t.json")
    assert R.lacunas_tfe(2026, db, minimo=1) == [("01/09/2026", 30), ("02/09/2026", 1)]
    assert R.lacunas_tfe(2026, db, minimo=30) == [("01/09/2026", 30)]
    (tmp_path / "t.json").write_text('{"01/09/2026": {"falta_depois": 30}}')
    assert R.lacunas_tfe(2026, db, minimo=1) == [("02/09/2026", 1)], "resíduo igual ao da última visita não volta"
    (tmp_path / "t.json").write_text('{"01/09/2026": {"falta_depois": 20}}')
    assert R.lacunas_tfe(2026, db, minimo=1)[0] == ("01/09/2026", 30), "lacuna que cresceu volta"


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


def test_dispensado_que_volta_nao_reincide(tmp_path):
    """30/10/2026: o dono mandou esquecer o TFE. O serviço falha toda segunda e já estava 'curado' — sem isto a
    volta do sinal viraria REINCIDIU (com aviso) antes de a dispensa ser aplicada."""
    fila = tmp_path / "f.json"
    sig = "systemd:jfn-tfe-ob.service"
    A.conciliar([_p("jfn-tfe-ob.service", "systemd")], fila, agora=1_000)
    A.conciliar([], fila, agora=2_000)                                    # curado
    r = A.conciliar([_p("jfn-tfe-ob.service", "systemd")], fila, agora=3_000, dispensados={sig})
    assert r["reincidiu"] == [] and r["fila"][sig]["status"] == "dispensado"
    r = A.conciliar([], fila, agora=4_000, dispensados={sig})
    assert sig not in r["curados"] and r["fila"][sig]["status"] == "dispensado"


def test_tfe_dispensado_pelo_dono(monkeypatch):
    monkeypatch.setattr(A, "dispensados_slo", lambda: {"slo:likers-import"})
    assert {"systemd:jfn-tfe-ob.service", "slo:likers-import"} <= A.dispensados_dono()


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
        stderr, returncode = "", 0
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(A, "_ultimo_erro", lambda u: "RuntimeError: TFE recusou o IP de origem da VM (...)")
    [p] = A.sensor_systemd()
    assert p["remediar"] == "" and "OuvERJ" in p["acao_humana"]


def test_systemctl_sem_barramento_e_sensor_cego_nao_zero(monkeypatch):
    """04/11/2026: no cron, `systemctl --user` sem XDG_RUNTIME_DIR dava "Failed to connect to bus" (rc=1)
    e a saída vazia virava "nenhum serviço em falha" — o jfn-pncp-resultados ficou 3 dias em falha fora da fila."""
    class _R:
        stdout, stderr, returncode = "", "Failed to connect to bus: No medium found", 1
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: _R())
    problemas, medidos = A.sentir({"systemd": A.sensor_systemd})
    assert medidos["systemd"] is None and "bus" in problemas[0]["detalhe"]


def test_systemctl_recebe_o_barramento_da_sessao(monkeypatch):
    visto = {}

    class _R:
        stdout, stderr, returncode = "", "", 0

    def run(cmd, **k):
        visto["env"] = k.get("env") or {}
        return _R()
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(A.subprocess, "run", run)
    assert A.sensor_systemd() == []
    assert visto["env"].get("XDG_RUNTIME_DIR", "").startswith("/run/user/")


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


def test_mfa_sem_codigo_remedia_pela_retentativa_diurna(tmp_path, monkeypatch):
    """Laudo 13/11/2026: o remédio rodava o diário de madrugada e pedia código MFA a quem dormia. Falha de MFA
    usa `siafe_runner retentar`, que só dispara de dia e avisa o dono antes."""
    import os
    data = tmp_path / "data"; (data / "sei_cache").mkdir(parents=True)
    monkeypatch.setattr(A, "DATA", data)
    (data / "sei_cache" / "siafe_runner_ultimo.json").write_text(json.dumps({"ok": False, "erro": "mfa_sem_codigo"}))
    env = tmp_path / ".env"; env.write_text("x"); os.utime(env, (1_000, 1_000))
    rem = {p["assinatura"]: p for p in A.sensor_siafe()}["siafe:diario"]["remediar"]
    assert "siafe_runner retentar" in rem and "siafe_runner diario" not in rem


def test_carimbo_de_senha_recusada_tira_o_remedio_do_diario(tmp_path, monkeypatch):
    """O último diário pode ter rodado ANTES de o erro ser nomeado ('login_falhou'): o carimbo manda."""
    import os
    data = tmp_path / "data"; (data / "sei_cache").mkdir(parents=True)
    monkeypatch.setattr(A, "DATA", data)
    (data / "sei_cache" / "siafe_runner_ultimo.json").write_text(json.dumps({"ok": False, "erro": "login_falhou"}))
    env = tmp_path / ".env"; env.write_text("x"); os.utime(env, (1_000, 1_000))
    assert {p["assinatura"]: p for p in A.sensor_siafe()}["siafe:diario"]["remediar"]
    (data / ".siafe_dreno_credencial_2").touch()
    assert {p["assinatura"]: p for p in A.sensor_siafe()}["siafe:diario"]["remediar"] == ""


def test_parecer_que_oscila_vira_problema_do_detector(tmp_path):
    """Achado que sai e VOLTA no mesmo processo em 3+ processos = leitura instável do detector."""
    import json
    import sqlite3
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("create table processo_avaliacao_hist (numero_sei text, avaliado_em text, entraram_json text, "
                "sairam_json text)")
    ch = "FZ1_ATESTO_ANTES_DO_FIM_DO_PERIODO|Atestado 1"
    for i, num in enumerate(("A", "B", "C", "D")):
        seq = [[ch], [], [ch]] if num != "D" else [[ch], [], []]       # D saiu e não voltou: não oscila
        sai = [[], [ch], []]
        for k in range(3):
            con.execute("insert into processo_avaliacao_hist values (?, datetime('now', ?), ?, ?)",
                        (num, f"-{10 - k} hours", json.dumps(seq[k]), json.dumps(sai[k])))
    con.commit(); con.close()
    (p,) = A.sensor_pareceres(db)
    assert p["assinatura"] == "pareceres:oscila_FZ1_ATESTO_ANTES_DO_FIM_DO_PERIODO"
    assert "3 processos" in p["titulo"] and "D" not in p["detalhe"].split(", ")


def test_sem_historico_nao_acusa(tmp_path):
    import sqlite3
    sqlite3.connect(tmp_path / "c.db").close()
    assert A.sensor_pareceres(tmp_path / "c.db") == []


def test_lacuna_tfe_colheita_no_plato_nao_vira_visita(tmp_path, monkeypatch):
    """18/09/2026: colheu 979 sem estourar e a lacuna não mexeu — o dia foi cortado, não visitado."""
    import asyncio
    import json
    import compliance_agent.siafe_ob_orcamentaria as M
    import tools.siafe_recoletar_dias as R
    monkeypatch.setattr(R, "TFE_VERIFICADOS", tmp_path / "t.json")
    monkeypatch.setattr(R, "_faltas_tfe", lambda ex, dia=None: {dia: 1177})

    async def cortado(ex, d):
        return {"ok": True, "estouro": False, "ingeridas": 979}

    async def completo(ex, d):
        return {"ok": True, "estouro": True, "ingeridas": 3199}
    monkeypatch.setattr(M, "coletar_por_data", cortado)
    asyncio.run(R.recoletar_tfe(["18/09/2026"], 2026))
    assert not (tmp_path / "t.json").exists()
    monkeypatch.setattr(M, "coletar_por_data", completo)
    asyncio.run(R.recoletar_tfe(["01/09/2026"], 2026))
    assert json.loads((tmp_path / "t.json").read_text())["01/09/2026"]["ingeridas"] == 3199


def test_remedio_roda_com_o_barramento_da_sessao(tmp_path, monkeypatch):
    visto = {}
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(A.subprocess, "Popen", lambda *a, **k: visto.update(k))
    A._executar_destacado("systemctl --user restart x.service", tmp_path / "r.log")
    assert visto["env"]["XDG_RUNTIME_DIR"].startswith("/run/user/")


def test_sensor_voz_acusa_falha_recente_config_e_venv(tmp_path):
    import time
    h = tmp_path / ".hermes"
    (h / "logs").mkdir(parents=True)
    (h / ".env").write_text("OUTRA=1\n", encoding="utf-8")
    agora = time.mktime(time.strptime("2026-11-06 17:00:00", "%Y-%m-%d %H:%M:%S"))
    (h / "logs" / "agent.log").write_text(
        "2026-11-04 10:00:00,1 INFO gateway.run: Voice transcription failed for velho.ogg\n"
        "2026-11-06 16:55:05,3 INFO gateway.run: Voice transcription failed for novo.ogg\n", encoding="utf-8")
    sig = {p["assinatura"] for p in A.sensor_voz(h, tmp_path / "nao_existe", agora)}
    assert sig == {"voz:stt-venv", "voz:config", "voz:falhou"}


def test_sensor_voz_verde_quando_configurado_e_sem_falha(tmp_path):
    import time
    h = tmp_path / ".hermes"
    (h / "logs").mkdir(parents=True)
    (h / ".env").write_text("HERMES_LOCAL_STT_COMMAND=/x/python stt.py {input_path}\n", encoding="utf-8")
    (h / "logs" / "agent.log").write_text(
        "2026-11-01 10:00:00,1 INFO gateway.run: Voice transcription failed for velho.ogg\n", encoding="utf-8")
    py = tmp_path / "python"
    py.write_text("")
    agora = time.mktime(time.strptime("2026-11-06 17:00:00", "%Y-%m-%d %H:%M:%S"))
    assert A.sensor_voz(h, py, agora) == []


def test_avaliar_maquinas_ociosa_sobrecarga_e_indisponivel():
    from tools.automelhoria_geral import avaliar_maquinas
    itc_ok = {"cpu_pct": 70, "win_disp_gb": 5, "piso_gb": 3, "maquina": {"gpu": {"util_pct": 99}}}
    assert avaliar_maquinas((2.0, 2), (2.0, 2), itc_ok) == []
    a = {p["assinatura"] for p in avaliar_maquinas((6.0, 2), (0.4, 2), None)}
    assert a == {"maquinas:vm1:sobrecarga", "maquinas:vm2:ociosa", "maquinas:itcampo:sem_medida"}
    itc_parado = {"cpu_pct": 10, "win_disp_gb": 20, "piso_gb": 3, "maquina": {"gpu": {"util_pct": 0}}}
    a = {p["assinatura"] for p in avaliar_maquinas(None, (2.0, 2), itc_parado)}
    assert a == {"maquinas:vm1:sem_medida", "maquinas:itcampo:gpu_ociosa", "maquinas:itcampo:cpu_ociosa"}


def test_itcampo_ociosa_fecha_o_laco_pela_fila_de_ocr():
    """Ociosa só é problema quando há trabalho parado: fila velha → alimentar; fila vazia e nova → nada;
    fila cheia com GPU parada → trabalhador quebrado, escala (sem remédio automático)."""
    from tools.automelhoria_geral import FILA_OCR_VELHA_S, avaliar_maquinas

    def itc(restantes, gpu=0, cpu=10):
        return {"cpu_pct": cpu, "win_disp_gb": 20, "piso_gb": 3,
                "maquina": {"gpu": {"util_pct": gpu}, "ocr_gpu": {"restantes": restantes}}}

    def so_itc(r):
        return {p["assinatura"]: p for p in r if "itcampo" in p["assinatura"]}

    velha = so_itc(avaliar_maquinas((2.0, 2), (2.0, 2), itc(0), (88, FILA_OCR_VELHA_S + 1)))
    assert "tools.sei_ocr_gpu_fila" in velha["maquinas:itcampo:gpu_ociosa"]["remediar"]
    ausente = so_itc(avaliar_maquinas((2.0, 2), (2.0, 2), itc(0), None))
    assert ausente["maquinas:itcampo:gpu_ociosa"]["remediar"]
    assert so_itc(avaliar_maquinas((2.0, 2), (2.0, 2), itc(0), (0, 60))) == {}          # sem trabalho: não é problema
    cheia = so_itc(avaliar_maquinas((2.0, 2), (2.0, 2), itc(340), (0, 60)))
    assert set(cheia) == {"maquinas:itcampo:gpu_parada_com_fila", "maquinas:itcampo:cpu_ociosa"}
    assert not cheia["maquinas:itcampo:gpu_parada_com_fila"]["remediar"]                 # quebrado → dono, não remédio
    nao_puxou = so_itc(avaliar_maquinas((2.0, 2), (2.0, 2), itc(0), (88, 600)))
    assert "maquinas:itcampo:gpu_fila_nao_puxada" in nao_puxou and not nao_puxou["maquinas:itcampo:gpu_fila_nao_puxada"]["remediar"]
    assert so_itc(avaliar_maquinas((2.0, 2), (2.0, 2), itc(340, gpu=97, cpu=80), (0, 60))) == {}


def test_fila_ocr_conta_linhas_e_idade(tmp_path):
    from tools.automelhoria_geral import _fila_ocr
    f = tmp_path / "fila.txt"
    assert _fila_ocr(arq=f) is None
    f.write_text("integra_a/001.pdf\n\nintegra_a/002.pdf\n")
    n, idade = _fila_ocr(agora=f.stat().st_mtime + 120, arq=f)
    assert n == 2 and 119 < idade < 121


def test_avaliar_precisao_por_detector():
    from tools.automelhoria_geral import avaliar_precisao
    a = [p["assinatura"] for p in avaliar_precisao([("d3", 610, 346), ("d7", 793, 7), ("pouco", 10, 9)])]
    assert a == ["detector:fp:d3"]


# ── decisão 7 (20/11/2026): o canal reabre SÓ para o item escalado, uma vez, com entrega conferida ───────────
class _Telegram:
    """Dublê do Telegram: guarda o que seria enviado; `resposta` imita a API (ou o silêncio)."""

    def __init__(self, resposta=None):
        self.enviados, self.resposta = [], resposta

    def __call__(self, texto):
        self.enviados.append(texto)
        return self.resposta if self.resposta is not None else {"ok": True, "result": {"message_id": 100 + len(self.enviados)}}


def _fila_escalada(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getloadavg", lambda: (0.5, 0, 0))
    r = A.conciliar([_rem("x"), _rem("y"), A._p("ci", "z", "titulo z")], tmp_path / "fila.json", agora=1_000)
    for t in (1_000, 1_000 + A.INTERVALO_S, 1_000 + 2 * A.INTERVALO_S):   # 2 remédios sem cura → x e y escalam
        A.remediar(r["fila"], agora=t, executar=lambda c, l: None)
    r["fila"]["slo:y"]["status"] = "curado"                                # curado não avisa
    return r["fila"]


def test_so_o_escalado_aberto_e_avisado_marcado_e_uma_vez(tmp_path, monkeypatch):
    fila = _fila_escalada(tmp_path, monkeypatch)
    tg = _Telegram()
    assert A.avisar_escalados(fila, enviar=tg) == ["slo:x"]
    (txt,) = tg.enviados
    assert txt.startswith("🆘 ESCALADO") and "titulo x" in txt and "2× sem cura" in txt
    assert fila["slo:x"]["escalado_msg_id"] == 101 and fila["slo:x"]["escalado_avisado"]
    assert A.avisar_escalados(fila, enviar=tg) == [] and len(tg.enviados) == 1   # uma vez por item
    assert "ci:z" not in "".join(tg.enviados)                                    # não escalado: segue calado


def test_ok_sem_message_id_nao_conta_como_entregue(tmp_path, monkeypatch):
    # o silêncio devolve {"ok": True, "silenciado": True} SEM enviar (memória telegram-silencio-devolve-ok)
    fila = _fila_escalada(tmp_path, monkeypatch)
    for falsa in ({"ok": True, "silenciado": True}, {"ok": False, "error": "x"}, {}):
        assert A.avisar_escalados(fila, enviar=_Telegram(falsa)) == []
        assert "escalado_avisado" not in fila["slo:x"]                          # tenta de novo na próxima rodada
    assert A.avisar_escalados(fila, enviar=_Telegram()) == ["slo:x"]


def test_main_avisa_escalado_e_mantem_o_resto_em_silencio(tmp_path, monkeypatch):
    import json
    import sys
    fila = _fila_escalada(tmp_path, monkeypatch)
    fila_p = tmp_path / "fila.json"
    fila_p.write_text(json.dumps(fila))
    monkeypatch.setattr(A, "FILA", fila_p)
    conciliar = A.conciliar                           # o padrão `fila_path=FILA` foi fixado na definição
    monkeypatch.setattr(A, "conciliar", lambda p, dispensados=frozenset(): conciliar(p, fila_p, dispensados=dispensados))
    monkeypatch.setattr(A, "RELATORIOS", tmp_path / "rel")
    monkeypatch.setattr(A, "dispensados_dono", lambda: set())
    novo = A._p("ci", "novo", "problema novo")
    monkeypatch.setattr(A, "sentir", lambda: ([_rem("x"), A._p("ci", "z", "titulo z"), novo], {}))
    monkeypatch.setattr(A, "remediar", lambda f: {"feitos": [], "escalados": [], "adiados": []})
    tg, gerais, silenciados = _Telegram(), [], []
    from compliance_agent import siafe_coord
    from compliance_agent.notifications import silencio
    monkeypatch.setattr(siafe_coord, "enviar_ao_dono", tg)
    monkeypatch.setattr(siafe_coord, "notificar", gerais.append)
    monkeypatch.setattr(silencio, "silenciar", lambda t, origem="": silenciados.append(t) or True)
    monkeypatch.setattr(sys, "argv", ["automelhoria_geral"])
    assert A.main() == 0
    assert len(tg.enviados) == 1 and "titulo x" in tg.enviados[0]               # o escalado passou
    assert gerais == [] and silenciados == []            # a novidade nem é montada: fechada na origem (O8.4)
    assert json.loads(fila_p.read_text())["slo:x"]["escalado_msg_id"] == 101


def test_itcampo_ocioso_2h_so_com_duas_horas_cobertas_e_todas_ociosas():
    from datetime import datetime as dt
    agora = dt(2026, 11, 22, 3, 0, 0).timestamp()

    def hist(cpus, decisao="memória do WSL 4.1 GB < 4.5", fim_min=0):
        n = len(cpus)
        return [{"t": dt.fromtimestamp(agora - (fim_min + (n - 1 - i) * 15) * 60).strftime("%Y-%m-%d %H:%M:%S"),
                 "ok": True, "win_cpu": c, "decisao": decisao, "disparou": False} for i, c in enumerate(cpus)]

    ocioso = A.avaliar_itcampo_ocioso(hist([30] * 9), agora)                 # 2 h cobertas, tudo < 50%
    assert [p["assinatura"] for p in ocioso] == ["maquinas:itcampo:ocioso_2h"]
    assert "wslconfig" in ocioso[0]["acao_humana"]                           # a memória decidiu a maioria
    assert not ocioso[0].get("remediar")                                     # sem remédio = nunca escala ao Telegram
    assert A.avaliar_itcampo_ocioso(hist([30] * 8 + [70]), agora) == []      # uma leitura ocupada basta
    assert A.avaliar_itcampo_ocioso(hist([30] * 5), agora) == []             # só 1 h de medida: não conclui
    assert A.avaliar_itcampo_ocioso(hist([30] * 9, fim_min=45), agora) == []  # vigia parado: não conclui
    sem = A.avaliar_itcampo_ocioso(hist([30] * 9, decisao="1ª leitura ociosa (espera a 2ª)"), agora)
    assert "fila" in sem[0]["acao_humana"]
    falhas = [dict(m, ok=False) for m in hist([30] * 9)]
    assert A.avaliar_itcampo_ocioso(falhas, agora) == []                     # INDISPONÍVEL nunca vira "ocioso"


# ─── sensor "plataforma" (plano de reescrita 23/11/2026: os achados dos planos externos viram vigília permanente) ───

def test_cobertura_de_leitura_baixa_acusa_e_completa_cura():
    p = A.avaliar_cobertura_leitura(total=1_000, alcancavel=173, procs=100, procs_cortados=77)
    assert [x["assinatura"] for x in p] == ["plataforma:cobertura_leitura"]
    assert "17,3%" in p[0]["titulo"] and "77" in p[0]["detalhe"]
    assert A.avaliar_cobertura_leitura(total=1_000, alcancavel=1_000, procs=100, procs_cortados=0) == []
    assert A.avaliar_cobertura_leitura(total=0, alcancavel=0, procs=0, procs_cortados=0) == []


def test_disco_de_outra_maquina():
    assert A.avaliar_disco("vm2", 96.0)[0]["assinatura"] == "plataforma:disco_vm2"
    assert A.avaliar_disco("vm2", 79.0) == []


def test_fila_que_cresce_mais_do_que_esvazia():
    p = A.avaliar_vazao_fila("conferencia_opus", entrada_7d=5_000, saida_7d=330, pendentes=5_750)
    assert p and p[0]["assinatura"] == "plataforma:vazao_conferencia_opus"
    assert A.avaliar_vazao_fila("conferencia_opus", entrada_7d=300, saida_7d=320, pendentes=5_750) == []
    assert A.avaliar_vazao_fila("conferencia_opus", entrada_7d=50, saida_7d=0, pendentes=40) == []   # fila pequena


def _rod(ts, proc, arvore, seg):
    return {"ts": ts, "procs": {proc: {"status": "ok", "arvore": arvore, "segundos": seg}}}


def test_recaptura_sem_novidade_mede_tempo_nao_contagem():
    rods = [_rod("2026-11-20 01:00:00", "A", 10, 100), _rod("2026-11-20 02:00:00", "A", 10, 100),
            _rod("2026-11-20 03:00:00", "A", 12, 100), _rod("2026-11-20 04:00:00", "B", 5, 100)]
    frac, n = A.fracao_recaptura_igual(rods)
    assert n == 1 and abs(frac - 0.25) < 1e-9            # 1 recaptura igual de 4 capturas, 100 s de 400 s
    assert A.avaliar_recaptura(frac, n)[0]["assinatura"] == "plataforma:recaptura_igual"
    assert A.avaliar_recaptura(0.04, 3) == []


def test_cache_do_opus_desperdicado():
    p = A.avaliar_cache_opus(cache_escrito=1_300_000, cache_lido=90_000, chamadas=12)
    assert p and p[0]["assinatura"] == "plataforma:cache_opus"
    assert A.avaliar_cache_opus(cache_escrito=100_000, cache_lido=900_000, chamadas=12) == []
    assert A.avaliar_cache_opus(cache_escrito=1_000, cache_lido=0, chamadas=3) == []          # amostra pequena


# ─── O9.0 frente B (26/11/2026): remédio antigo só com pedido explícito ───────────────────────────────────────────
# O `/melhorias agora` do Yoda (~/.hermes/plugins/jfn-automelhoria) chama `automelhoria_geral.py --sem-aviso`, SEM o
# `--sem-remediar` do job do fluxo: lançava destacados os remédios do pipelines.yaml (despachante `propagacao ciclo`
# → E9/E10, `qualidade juiz` → assinatura, siafe_runner…) por fora da liberação e do ritmo. Remediar virou opt-in.
def _main_com_argv(tmp_path, monkeypatch, argv):
    import sys
    monkeypatch.setattr(A, "FILA", tmp_path / "fila.json")
    monkeypatch.setattr(A, "RELATORIOS", tmp_path / "rel")
    monkeypatch.setattr(A, "dispensados_dono", lambda: set())
    monkeypatch.setattr(A, "sentir", lambda: ([_rem("x")], {}))
    monkeypatch.setattr(A, "avisar_escalados", lambda fila: [])
    chamadas = []
    monkeypatch.setattr(A, "remediar", lambda f: chamadas.append(f) or {"feitos": [], "escalados": [], "adiados": []})
    monkeypatch.setattr(sys, "argv", ["automelhoria_geral", *argv])
    assert A.main() == 0
    return chamadas


def test_sem_pedido_explicito_nao_lanca_remedio(tmp_path, monkeypatch):
    assert _main_com_argv(tmp_path, monkeypatch, ["--sem-aviso"]) == []          # o /melhorias agora do Yoda
    assert _main_com_argv(tmp_path, monkeypatch, []) == []                       # chamada à mão / cron antigo
    assert _main_com_argv(tmp_path, monkeypatch, ["--sem-remediar"]) == []       # o job do fluxo (compatível)


def test_remediar_so_com_a_bandeira(tmp_path, monkeypatch):
    assert len(_main_com_argv(tmp_path, monkeypatch, ["--remediar"])) == 1


def test_sensor_do_motor_agrupa_falhas_e_aponta_a_familia():
    """26/11/2026 (dono: «isso o módulo de automelhoria já deveria ter feito»): as falhas da religação eram de famílias
    já conhecidas (SQLite travado, teto de memória/tempo, arquivo noutro nó, dependência ausente) e só apareceram
    quando estouraram. O sensor `motor` agrupa as falhas do próprio motor e aponta a família e a 1ª providência."""
    import tools.automelhoria_geral as AG
    linhas = [("confirmar_ocr", "quarentena", "pressao", "morto pelo governador: ['mem full 6.9 > 5']")] * 3 + \
             [("texto", "fila", "erro", "RuntimeError: 1/2/2026: manifesto da captura ilegível em /home/x/integra_1 "
                                       "([Errno 2] No such file or directory)")] * 4 + \
             [("arvore", "quarentena", "permanente", "[fora_de_alcance] SEI respondeu RESTRITO")] * 9 + \
             [("arvore", "fila", "parada", "supervisor parado (SIGTERM)")] * 5 + \
             [("ocr", "fila", "erro", "algo inédito 0xdeadbeef")]
    ps = {p["assinatura"]: p for p in AG.problemas_motor(linhas)}
    assert len(ps) == 2                                  # restrito, parada e caso único (sem quarentena) não entram
    fam = {p["titulo"] for p in ps.values()}
    assert any("teto do recurso" in t and "3×" in t for t in fam)
    assert any("lido noutro" in t and "4×" in t for t in fam)
    assert all(p["acao_humana"] and not p["remediar"] for p in ps.values())
