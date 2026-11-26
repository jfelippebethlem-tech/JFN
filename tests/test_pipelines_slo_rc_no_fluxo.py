"""Religação O9.0 (26/11/2026): no motor, `pipelines_slo --alerta` saía rc=1 por haver SLO vermelho (o próprio achado
do monitor) → 5 tentativas → quarentena → E18 BLOQUEADO. Rodar e registrar é o efeito; vermelho não é falha do job."""
import tools.pipelines_slo as SLO


def _vermelho(monkeypatch):
    monkeypatch.setattr(SLO, "checar", lambda: [{"nome": "x", "grupo": "g", "status": "stale", "idade_h": 9,
                                                  "slo_h": 1, "nota": ""}])


def test_sem_flag_vermelho_sai_1(monkeypatch):
    _vermelho(monkeypatch)
    monkeypatch.setattr(SLO.sys, "argv", ["pipelines_slo"])
    assert SLO.main() == 1


def test_no_fluxo_vermelho_sai_0(monkeypatch):
    _vermelho(monkeypatch)
    monkeypatch.setattr(SLO.sys, "argv", ["pipelines_slo", "--rc-zero"])
    assert SLO.main() == 0
