"""Teste passo a passo de quantas sessões SEI o it-campo sustenta (dono, 15/11/2026: "veja passo a passo quantas
sessões funcionam simultaneamente")."""
import tools.itcampo_degraus as D

LOG = """[2026-11-15 21:00:10] ÍNTEGRA 1 …
[2026-11-15 21:02:00]   270001/000001/2024: ok
[2026-11-15 21:03:00]   270001/000002/2024: login
[2026-11-15 21:04:00]   270001/000003/2024: sem_arvore
[2026-11-15 20:59:00]   270001/000004/2024: ok
[2026-11-15 21:02:59]   270001/000002/2024: LOGIN FALHOU
"""


def test_conta_status_por_processo_so_desde_o_inicio_do_degrau():
    assert D.contar(LOG, "2026-11-15 21:00:00") == {"ok": 1, "login": 1, "sem_arvore": 1}


def test_veredito_do_degrau():
    assert D.veredito({"ok": 2}, conexao=True) == "saudavel"
    assert D.veredito({"ok": 2, "login": 1}, conexao=True) == "degradou"
    assert D.veredito({"ok": 5}, conexao=False) == "degradou"            # conexão caiu = o volume passou do limite
    assert D.veredito({"erro": 3}, conexao=True) == "degradou"            # 3+ tentativas sem nenhum ok
    assert D.veredito({}, conexao=True) == "sem_dados"
    assert D.veredito({"sem_arvore": 1}, conexao=True) == "sem_dados"
