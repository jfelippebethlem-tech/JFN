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
