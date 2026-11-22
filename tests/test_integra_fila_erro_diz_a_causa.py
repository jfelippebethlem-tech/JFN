"""O status "erro" da fila tem de vir com a causa. Medido em 18/11/2026: 171 "erro" em 48 h no log da fila
(it-campo + VM-1 + VM-2) e nenhuma linha dizendo o que falhou — a saída do `sei_arquivar` ia para DEVNULL e a da
captura só era lida para SEM ÁRVORE/LOGIN. Log que afirma menos do que o processo sabe custa rodada de diagnóstico."""
import tools.sei_integra_fila as F


class _R:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout = rc, out


def _cenario(monkeypatch, tmp_path, rc1, out1, rc2, out2):
    monkeypatch.setattr(F, "CACHE", tmp_path)
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "arq")
    d = tmp_path / "integra_270089_001815_2023"
    d.mkdir()
    (d / "000.pdf").write_bytes(b"%PDF-1.4")
    saidas = iter([_R(rc1, out1), _R(rc2, out2)])
    monkeypatch.setattr(F.subprocess, "run", lambda cmd, **kw: next(saidas))
    linhas = []
    monkeypatch.setattr(F, "_log", linhas.append)
    return linhas


def test_arquivador_que_falha_deixa_a_causa_no_log(monkeypatch, tmp_path):
    linhas = _cenario(monkeypatch, tmp_path, 0, "baixando 3 docs…\n", 1,
                      "Traceback (most recent call last):\n  File x\nValueError: pdf truncado\n")
    assert F._baixar_e_arquivar("270089/001815/2023", env={}) == "erro"
    assert any("arquivar" in ln and "ValueError: pdf truncado" in ln for ln in linhas), linhas


def test_captura_que_falha_deixa_a_causa_no_log(monkeypatch, tmp_path):
    linhas = _cenario(monkeypatch, tmp_path, 1, "baixando 3 docs…\nRuntimeError: frame detached\n", 0, "")
    assert F._baixar_e_arquivar("270089/001815/2023", env={}) == "erro"
    assert any("captura" in ln and "RuntimeError: frame detached" in ln for ln in linhas), linhas


def test_captura_que_cai_antes_do_primeiro_documento_tambem_diz_a_causa(monkeypatch, tmp_path):
    """18/11/2026, 22h no it-campo: 25 "erro" em ~30 s cada, nenhum com causa — o caminho "caiu antes de baixar
    qualquer documento" só registrava as causas conhecidas (SEM ÁRVORE/LOGIN/cracked)."""
    monkeypatch.setattr(F, "CACHE", tmp_path)
    monkeypatch.setattr(F.subprocess, "run", lambda cmd, **kw: _R(1, "login OK\nplaywright: Target closed\n"))
    linhas = []
    monkeypatch.setattr(F, "_log", linhas.append)
    assert F._baixar_e_arquivar("270089/001815/2023", env={}) == "erro"
    assert any("captura" in ln and "Target closed" in ln for ln in linhas), linhas


def test_erro_do_playwright_mostra_a_mensagem_nao_o_call_log():
    """18/11/2026 23h, it-campo: a causa registrada era "- <ws connected> ws://127.0.0.1:9302/devtools/browser/…" — a
    última linha do `call log` do Playwright, não a mensagem do erro."""
    saida = ("login OK\nplaywright._impl._errors.TargetClosedError: Target page, context or browser has been closed\n"
             "Call log:\n  - <ws connected> ws://127.0.0.1:9302/devtools/browser/8ed76c3c\n")
    assert "TargetClosedError" in F._causa_da_saida(saida)
    assert F._causa_da_saida("baixando 3 docs…\n") == "baixando 3 docs…"
    assert F._causa_da_saida("") == "sem saída"


def test_tempo_por_etapa_vai_ao_registro(monkeypatch, tmp_path):
    """22/11/2026: a fila só sabia o total por processo — onde o tempo vai (login, árvore, lotes, laço, arquivar)
    não se media. A captura imprime `ETAPAS {json}` e a fila grava uma linha por processo."""
    _cenario(monkeypatch, tmp_path, 0, 'login OK\nETAPAS {"login_s": 12.5, "lotes_s": 40.0, "via_pdf": 3}\n', 0, "")
    monkeypatch.setenv("JFN_INTEGRA_ETAPAS", str(tmp_path / "etapas.jsonl"))
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    F._rodar_fila(["270089/001815/2023"], env={}, deadline=None, log=lambda m: None)
    import json
    reg = json.loads((tmp_path / "etapas.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert reg["processo"] == "270089/001815/2023" and reg["status"] == "ok"
    assert reg["login_s"] == 12.5 and reg["via_pdf"] == 3 and "captura_s" in reg and "arquivar_s" in reg
