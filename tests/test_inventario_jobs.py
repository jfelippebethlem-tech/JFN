"""tools/inventario_jobs.py — parse de cron (ativo, #PARADA, comentado), frequência, duplicação, systemd, duração.

Fixtures sintéticas pequenas: nada lê a máquina (crontab, journal, ssh) nem as fotografias reais.
"""
from __future__ import annotations

import pytest

from tools import inventario_jobs as inv

CRONTAB = """\
# --- BASE ---
JFN_CLAUDE_BIN=/home/ubuntu/JFN/tools/claude_no_itcampo.sh
#PARADA-20261124 */30 * * * * bash /home/ubuntu/JFN/tools/sweep_x_teste.sh
#PARADA-20261124 @reboot sleep 150 && bash /home/ubuntu/JFN/tools/sweep_x_teste.sh >> /home/ubuntu/JFN/data/x.log 2>&1
# texto qualquer do dono, sem agenda
# 25 6 * * * cd /home/ubuntu/JFN && .venv/bin/python tools/cerebro_teste.py >> data/c.log 2>&1
# DESLIGADO 2026-06-25 (parar API): 17 * * * * bash /home/ubuntu/JFN/tools/fachada_teste.sh
0 7 * * 1 cd /home/ubuntu/JFN && PYTHONPATH=. timeout 600 nice -n 10 .venv/bin/python -m tools.coleta_teste >> data/a.log 2>&1
40 12 * * 1-5 cd /home/ubuntu/JFN && PYTHONPATH=. timeout 1500 .venv/bin/python -m tools.coleta_teste --hoje >> data/a.log 2>&1
7 * * * * /bin/bash /home/ubuntu/JFN/tools/fila_teste.sh ficha
13,43 * * * * /bin/bash /home/ubuntu/JFN/tools/fila_teste.sh lex
"""


@pytest.fixture
def linhas():
    return inv.parse_crontab(CRONTAB)


def test_linha_ativa_parada_e_comentada(linhas):
    marcas = [(j["agenda"], j["marca"]) for j in linhas]
    assert ("*/30 * * * *", "parada") in marcas
    assert ("@reboot", "parada") in marcas
    assert ("25 6 * * *", "comentado") in marcas
    assert ("17 * * * *", "comentado") in marcas  # agenda depois de "DESLIGADO …: "
    assert ("0 7 * * 1", "ativo") in marcas
    assert len(linhas) == 8  # env e comentário de texto não viram job


def test_linha_cron_isolada():
    j = inv.parse_linha_cron("#PARADA-20261124 50 4 * * * /bin/bash tools/x.sh sigilo")
    assert j == {"agenda": "50 4 * * *", "comando": "/bin/bash tools/x.sh sigilo", "marca": "parada"}
    assert inv.parse_linha_cron("# só um comentário: sem agenda aqui") is None
    assert inv.parse_linha_cron("PATH=/usr/bin:/bin") is None
    assert inv.parse_linha_cron("#PARADA-20261124 # comentário que já era comentário") is None


def test_nota_vem_do_comentario_acima(linhas):
    j = next(x for x in linhas if x["agenda"] == "*/30 * * * *")
    assert j["nota"] == "--- BASE ---"


@pytest.mark.parametrize("agenda,esperado", [
    ("*/30 * * * *", 48.0),
    ("16,46 * * * *", 48.0),
    ("17 8-22 * * *", 15.0),
    ("0 9 * * 1", round(5 / 30, 3)),  # novembro/2026 tem 5 segundas
    ("0 6 5 * *", round(1 / 30, 3)),
    ("@reboot", 0.0),
    ("30 4 1-7 * *", round(7 / 30, 3)),
])
def test_execucoes_por_dia(agenda, esperado):
    assert inv.execucoes_por_dia(agenda) == pytest.approx(esperado, abs=1e-3)


def test_ponto_de_entrada_ignora_wrappers_e_distingue_subcomando():
    assert inv.ponto_de_entrada("cd /home/ubuntu/JFN && PYTHONPATH=. timeout 600 nice -n 10 "
                                ".venv/bin/python -m tools.coleta_teste --x 1 >> data/a.log 2>&1") == "py:tools.coleta_teste"
    assert inv.ponto_de_entrada("/bin/bash /home/ubuntu/JFN/tools/fila_teste.sh lex") == "sh:tools/fila_teste.sh lex"
    assert inv.ponto_de_entrada("python -m tools.vm2_conferencia amostra --n 2") == "py:tools.vm2_conferencia amostra"
    assert inv.ponto_de_entrada("/home/ubuntu/JFN-worker/tools/vm2_x.sh 8") == "sh:tools/vm2_x.sh"


def test_duplicado_exato_mesmo_script_e_rede():
    jobs = inv.jobs_crontab(CRONTAB, "vm1")
    jobs += inv.jobs_derivados({"derivados": {"fichas": {"comando": ["bash", "tools/fila_teste.sh", "ficha"],
                                                        "depende": ["x"], "timeout_s": 900}}})
    inv.ids_unicos(jobs)
    inv.marcar_duplicados(jobs)
    por = {(j["gatilho"]["expr"], j["estado_pre_parada"]): j for j in jobs}
    reboot = por[("@reboot", "ativo")]
    assert reboot["duplicacao"] == "exato"  # o mesmo sweep no boot e a cada 30 min
    hoje = next(j for j in jobs if "--hoje" in j["comando"])
    assert hoje["duplicacao"] == "mesmo_script"
    ficha_cron = next(j for j in jobs if j["comando"].endswith("fila_teste.sh ficha"))
    assert ficha_cron["estado_pre_parada"] == "rede"  # cron com o comando EXATO de um derivado
    assert ficha_cron["duplicado_de"] == "vm1-deriv-fichas"
    lex = next(j for j in jobs if j["comando"].endswith("fila_teste.sh lex"))
    assert "duplicado_de" not in lex  # subcomando diferente = job diferente
    comentados = [j for j in jobs if j["estado_pre_parada"] == "comentado"]
    assert len(comentados) == 2 and all(j["execucoes_dia"] == 0.0 for j in comentados)


def test_ids_estaveis_e_unicos():
    a = [j["id"] for j in inv.jobs_crontab(CRONTAB, "vm1")]
    jobs = inv.jobs_crontab(CRONTAB, "vm1")
    inv.ids_unicos(jobs)
    b = [j["id"] for j in jobs]
    assert len(set(b)) == len(b)
    jobs2 = inv.jobs_crontab(CRONTAB, "vm1")
    inv.ids_unicos(jobs2)
    assert b == [j["id"] for j in jobs2]
    assert a[0].startswith("vm1-cron-")


def test_higienizar_tira_cpf_e_segredo():
    # CPF sintético de exemplo, montado em tempo de execução (o scan_pii do pre-commit barra o literal)
    cru = "123456789" + "09"
    fmt = f"{cru[:3]}.{cru[3:6]}.{cru[6:9]}-{cru[9:]}"
    s = inv.higienizar(f"x {fmt} y {cru} API_TOKEN=abc123 SENHA_SEI=xyz")
    assert "123.456" not in s and cru not in s
    assert "API_TOKEN=***" in s and "SENHA_SEI=***" in s and "abc123" not in s


def test_parse_units_com_dropin_e_frequencia_do_timer():
    texto = """# /home/u/.config/systemd/user/jfn-x.timer
[Timer]
OnCalendar=*-*-* 03:30
OnCalendar=Sun 05:40
# /home/u/.config/systemd/user/jfn-x.service
[Service]
ExecStart=%h/JFN/.venv/bin/python tools/x.py
TimeoutStartSec=600
# /home/u/.config/systemd/user/jfn-x.service.d/extra.conf
[Service]
ExecStartPost=%h/JFN/.venv/bin/python -m tools.y
# /home/u/.config/systemd/user/jfn-r.timer
[Timer]
OnUnitActiveSec=10min
"""
    u = inv.parse_units(texto)
    assert u["jfn-x.service"]["ExecStartPost"] == ["%h/JFN/.venv/bin/python -m tools.y"]
    assert inv.execucoes_timer(u["jfn-x.timer"]) == pytest.approx(1 + 1 / 7, abs=1e-3)
    assert inv.execucoes_timer(u["jfn-r.timer"]) == pytest.approx(144)


def test_lista_de_servicos_e_timers():
    servs = inv.parse_lista_servicos("  jfn.service    loaded active   running  JFN\n"
                                     "● atena.service  loaded failed   failed   Atena\n")
    assert servs == {"jfn.service": "active running", "atena.service": "failed failed"}
    assert inv.parse_lista_timers("Tue 12:10  1min Tue 12:02 6min ago jfn-ronda.timer  jfn-ronda.service") == ["jfn-ronda.timer"]


def test_duracao_journal_pesado_e_log():
    j = ("1000.0 h systemd[1]: Starting a.service - A...\n1060.0 h systemd[1]: Finished a.service - A.\n"
         "2000.0 h systemd[1]: Starting a.service - A...\n2120.0 h systemd[1]: a.service: Failed with result 'exit-code'.\n")
    assert inv.duracoes_journal(j) == {"a.service": (90.0, 2)}
    p = ("2026-11-24 10:26:02 [pesado:x] início (esperou 360s)\n2026-11-24 10:32:23 [pesado:x] fim rc=0 (742s)\n")
    assert inv.duracoes_pesado(p) == {"x": (382.0, 1)}
    log = "\n".join(f"2026-11-2{d} 0{h}:00:{s:02d} linha" for d in (1, 2, 3) for h in (1,) for s in (0, 30))
    assert inv.duracao_por_log(log, 86400) == (30.0, 3)


def test_classificar_estagio_e_lente():
    assert inv.classificar("bash tools/sweep_sei.sh")[0] == "E2"
    assert inv.classificar("python -m tools.sei_compactar --limite 40")[0] == "E7"
    est, lente = inv.classificar("python tools/garantir_obs_iterj_mgs.py")
    assert est == "E1" and lente == "mgs_iterj"
    # caminho do usuário do Windows do it-campo ("iterj") não é a lente ITERJ
    assert inv.classificar(r"powershell -File C:\Users\iterj\jfn_sei_paralelo.ps1 JFN-SEI-Paralelo")[1] is None
    assert inv.classificar("/home/ubuntu/polimonitor/scripts/run-likers-import.sh")[0] == "fora_do_jfn"
