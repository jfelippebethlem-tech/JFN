"""Captura que CAIU antes de baixar qualquer documento não vira "captura vazia".

15/11/2026: o navegador não abriu no it-campo (WSLg caído). `sei_integra_completa` saiu com erro, o arquivador rodou
mesmo assim e gravou `captura_vazia` — o processo ficou fora da fila por 7 dias e as sessões entraram em laço de
"fila drenada". Falha do método não é fato sobre o processo: sem documento baixado, nada se arquiva."""
import tools.sei_integra_fila as F


class _R:
    def __init__(self, rc):
        self.returncode, self.stdout = rc, ""


def test_falha_sem_documento_nao_chama_o_arquivador(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "CACHE", tmp_path)
    chamadas = []

    def _run(cmd, **kw):
        chamadas.append(cmd[1])
        return _R(1)
    monkeypatch.setattr(F.subprocess, "run", _run)
    assert F._baixar_e_arquivar("270089/001815/2023", env={}) == "erro"
    assert chamadas == ["tools/sei_integra_completa.py"]


def test_falha_com_captura_parcial_ainda_arquiva(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "CACHE", tmp_path)
    d = tmp_path / "integra_270089_001815_2023"
    d.mkdir()
    (d / "000.pdf").write_bytes(b"%PDF-1.4")
    chamadas = []

    def _run(cmd, **kw):
        chamadas.append(cmd[1])
        return _R(1)
    monkeypatch.setattr(F.subprocess, "run", _run)
    assert F._baixar_e_arquivar("270089/001815/2023", env={}) == "erro"
    assert chamadas == ["tools/sei_integra_completa.py", "tools/sei_arquivar.py"]
