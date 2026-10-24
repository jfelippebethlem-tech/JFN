# -*- coding: utf-8 -*-
"""Loop de automelhoria de TUDO: problema novo abre, sumiço do sinal cura, volta depois de curado reincide,
e sensor que não mede vira problema — nunca 'ok'."""
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
