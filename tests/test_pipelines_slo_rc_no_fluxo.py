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


def test_frescor_le_tambem_o_log_da_rotina_no_motor(tmp_path, monkeypatch):
    """26/11/2026: na religação a rotina grava em data/logs/fluxo/<rotina>.log; o SLO olhava o mtime do log do cron
    (parado) e dava folha/manutenção/backup/automelhoria como stale de 55 h com tudo rodando no motor."""
    import os
    import time
    (tmp_path / "data" / "logs" / "fluxo").mkdir(parents=True)
    velho = tmp_path / "data" / "folha_cron.log"
    velho.write_text("x"); os.utime(velho, (time.time() - 200 * 3600,) * 2)
    (tmp_path / "data" / "logs" / "fluxo" / "folha_orquestrador.log").write_text("x")
    monkeypatch.setattr(SLO, "BASE", tmp_path)
    assert SLO.idade_saida({"nome": "folha-orquestrador", "arquivo": "data/folha_cron.log"}) < 1
    (tmp_path / "data" / "logs" / "fluxo" / "propagacao_ponte.log").write_text("x")
    assert SLO.idade_saida({"nome": "propagacao", "arquivo": "data/nada.log", "rotina": "propagacao_ponte"}) < 1
    assert SLO.idade_saida({"nome": "sem-nada", "arquivo": "data/nada.log"}) is None
