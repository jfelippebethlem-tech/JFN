"""Autoaprimoramento — calibração por motor e faixa de nota (docs/AUTOAPRIMORAMENTO-JFN.md). Medido em 18/11/2026: de 517
laudos 'risco alto' de modelos de volume, 8 seguiram altos depois de conferidos; do que o Opus manteve alto lendo o
resumo, cerca de um terço se confirmou na fonte primária."""
import pytest

from compliance_agent.autoaprimoramento import calibracao, ledger
from compliance_agent.correlacao_sei import estado_do_laudo

FONTE = "claude:claude-opus-5-5 (agente Claude Code, conferência na fonte primária 18/11) (conferência; antes gemini:x)"
OPUS = "claude-opus-5-5 (conferência Opus 18/11, lote até 85%)"


def _rot(motor, nota, k, n):
    return [{"motor": motor, "nota": nota, "alto_verificado": int(i < k)} for i in range(n)]


def test_jeffreys_cobre_a_taxa_e_e_deterministico():
    p, lo, hi = calibracao.jeffreys(8, 517)
    assert 0.005 < lo < 8 / 517 < hi < 0.035 and abs(p - 8.5 / 518) < 1e-9
    assert calibracao.jeffreys(8, 517) == (p, lo, hi)
    p0, lo0, hi0 = calibracao.jeffreys(0, 8)                      # zero em oito NÃO é zero: o teto fica alto
    assert lo0 < 0.01 and hi0 > 0.2


def test_tabela_e_celula_que_responde():
    tab = calibracao.tabela(_rot("gemini:a", 8, 1, 40) + _rot("groq", 8, 0, 3) + _rot("gemini:a", 5, 0, 2))
    assert tab["gemini:a"]["alta"]["n"] == 40 and tab["todos"]["alta"]["n"] == 43
    assert calibracao.prob(tab, "gemini:a", 9)["motor"] == "gemini:a"
    assert calibracao.prob(tab, "groq", 7)["motor"] == "todos"          # 3 laudos não falam pelo motor
    assert calibracao.prob(tab, "gemini:a", 5) is None                  # faixa sem amostra mínima: INDISPONÍVEL
    assert calibracao.prob(tab, "gemini:a", None) is None


def test_brier_bss_e_avaliacao_fora_da_amostra():
    treino = _rot("m", 8, 2, 100)
    valid = _rot("m", 8, 1, 50)
    r = calibracao.avaliar(calibracao.tabela(treino), valid, 0.02)
    assert r["n"] == 50 and r["brier_calibrada"] < 0.03 < r["brier_verbalizada"]
    assert calibracao.bss([(0.9, 1), (0.1, 0)]) > 0 > calibracao.bss([(0.1, 1), (0.9, 0)])    # positivo e negativo
    assert calibracao.bss([(0.5, 1), (0.5, 1)]) is None and calibracao.brier([]) is None


@pytest.fixture
def auto(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_AUTOAPRIMORAMENTO_DIR", str(tmp_path / "auto"))
    con = ledger.conectar()
    yield con
    con.close()


def _par(con, i, fraco, opus=None, fonte=None):
    ns = f"SEI-{i:06d}/000001/2025"
    ledger.registrar_versao(con, ns, {"nota_risco": fraco}, "gemini:a", "t", "2026-11-15T10:00:00")
    if opus is not None:
        ledger.registrar_versao(con, ns, {"nota_risco": opus}, OPUS, "t", "2026-11-18T08:00:00")
    if fonte is not None:
        ledger.registrar_versao(con, ns, {"nota_risco": fonte}, FONTE, "t", "2026-11-18T15:00:00")


def test_duas_fases_combina_os_estratos_e_declara_indisponivel(auto):
    for i in range(100):                      # 100 altos fracos: o Opus mantém 10
        _par(auto, i, 8, opus=7 if i < 10 else 3, fonte=(8 if i < 5 else 3) if i < 10 else (3 if i < 30 else None))
    ledger.conciliar(auto)
    todos = ("treino", "validacao", "teste")
    d = calibracao.duas_fases(auto, todos)
    # 10% × 5/10 + 90% × 0/20 ≈ 5% (com o meio a mais da posterior), intervalo cobrindo
    assert d["fraco_alto_opus_manteve"] == [10, 100] and d["opus_alto_fonte_confirmou"] == [5, 10]
    assert d["opus_baixo_fonte_achou_alto"] == [0, 20] and d["lo"] < 0.06 < d["hi"] and 0.04 < d["p"] < 0.12
    auto.execute("DELETE FROM conferencia WHERE nivel_antes=1")
    assert "indisponivel" in calibracao.duas_fases(auto, todos)          # sem ouro, não inventa


def test_calibrar_grava_a_tabela_e_nao_toca_o_teste(auto):
    for i in range(300):
        _par(auto, i, 8, opus=7 if i % 20 == 0 else 4)
    ledger.conciliar(auto)
    c = calibracao.calibrar(auto)
    assert c["n_treino"] + c["n_validacao"] < 300 and c["validacao"]["brier_calibrada"] < c["validacao"]["brier_verbalizada"]
    assert calibracao.carregar()["motores_fracos"]["gemini:a"]["alta"]["n"] == c["n_treino"] + c["n_validacao"]
    assert auto.execute("SELECT COUNT(*) FROM consulta_teste").fetchone()[0] == 0
    assert c["certificadas"] == []


def test_certificada_so_com_limite_inferior_alto():
    bom = {"motores_fracos": calibracao.tabela(_rot("x", 9, 60, 60)), "opus_resumo": {}}
    assert [c["motor"] for c in calibracao.certificadas(bom)] == ["todos", "x"] or \
        {c["motor"] for c in calibracao.certificadas(bom)} == {"todos", "x"}
    ruim = {"motores_fracos": {}, "opus_resumo": calibracao.tabela(_rot("claude-opus:resumo", 7, 8, 26))["claude-opus:resumo"]}
    assert calibracao.certificadas(ruim) == []                          # 8/26 confirmados: não sai sem ir à fonte


def test_confianca_e_estado_do_laudo_por_nivel_de_prova():
    cal = {"motores_fracos": calibracao.tabela(_rot("gemini:a", 8, 1, 40)),
           "opus_resumo": calibracao.tabela(_rot("claude-opus:resumo", 7, 8, 26))["claude-opus:resumo"]}
    f = calibracao.confianca(FONTE, 8, cal)
    assert f["estado"] == "VERIFICADO_NA_FONTE"
    o = calibracao.confianca(OPUS, 7, cal)
    assert o["estado"] == "A_CONFERIR_NA_FONTE" and o["n"] == 26 and "8 seguiram altos" in o["texto"]
    g = calibracao.confianca("gemini:a", 9, cal)
    assert g["estado"] == "A_CONFERIR_NA_FONTE" and g["p_confirma"] < 0.1
    assert calibracao.confianca("groq", 9, cal)["texto"].count("modelos de volume") == 1      # célula de todos
    assert calibracao.confianca(OPUS, 4, cal)["estado"] is None                               # não é risco alto
    assert calibracao.confianca("gemini:a", 8, {})["p_confirma"] is None                      # sem tabela: INDISPONÍVEL
    assert "INDISPONÍVEL" in calibracao.confianca("gemini:a", 8, {})["texto"]


def test_estado_do_laudo_com_nota(auto):
    assert estado_do_laudo(OPUS, 7)[0] == "A CONFERIR"            # risco alto do Opus sobre o resumo não é VERIFICADO
    assert estado_do_laudo(FONTE, 8)[0] == "VERIFICADO" and "fonte primária" in estado_do_laudo(FONTE, 8)[1]
    assert estado_do_laudo("gemini:x", 8)[0] == "PENDENTE"
    assert estado_do_laudo(OPUS, 4)[0] == "VERIFICADO"            # controle negativo: nota baixa segue como era
    assert estado_do_laudo(OPUS)[0] == "VERIFICADO"               # e a chamada antiga, sem nota, não mudou
