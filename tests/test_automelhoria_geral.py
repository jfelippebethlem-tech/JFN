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
