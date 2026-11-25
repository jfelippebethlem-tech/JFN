# -*- coding: utf-8 -*-
"""O8.1 (pedido do dono, 24/11): guardião e painel_vigia absorvidos — sensor `db.integridade` (trava própria, alerta
uma vez por incidente), remédios `painel_shm`/`painel_travado` com a SALVAGUARDA (banco corrompido ⇒ nunca reinicia;
nunca laço de restart) e a migração cron → fluxo (`tools/cron_para_fluxo.py`), que só comenta o que tem rotina."""
import fcntl
from datetime import datetime, timezone

import pytest

from compliance_agent.fluxo import grafo as G
from compliance_agent.fluxo import remedios as R
from compliance_agent.fluxo import sensores as S
from tools import cron_para_fluxo as C
from tools import rotinas_infra as I


class Relogio:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _mundo(corpos: dict, qc=("ok", ""), cura=True, relogio=None):
    """Mundo falso: `corpos` = caminho → (http, corpo); depois do restart, `cura` decide o que as rotas devolvem."""
    estado = {"reinicios": 0, "corpos": dict(corpos)}

    def sondar(c):
        return estado["corpos"].get(c, (200, "{}"))

    def reiniciar():
        estado["reinicios"] += 1
        if cura:
            estado["corpos"] = {}
        return True, ""

    m = R.Mundo(sondar=sondar, quick_check=lambda: qc, reiniciar=reiniciar, esperar_painel=lambda: cura,
                agora=relogio or Relogio())
    return m, estado


MAL = (500, '{"erro": "database disk image is malformed"}')


# ── salvaguarda do painel_shm ──────────────────────────────────────────────────────────────────────────────────
def test_painel_shm_nada_a_fazer_sem_malformed(tmp_path):
    m, st = _mundo({})
    assert R.painel_shm(m, tmp_path)["acao"] == "nada" and st["reinicios"] == 0


def test_painel_shm_nao_reinicia_com_banco_corrompido(tmp_path):
    m, st = _mundo({"/api/ugs": MAL}, qc=("*** in database main ***\nPage 7: btreeInitPage() returns error", ""))
    r = R.painel_shm(m, tmp_path)
    assert r["acao"] == "nao_reinicia" and "CORROMPIDO" in r["motivo"] and st["reinicios"] == 0


def test_painel_shm_nao_reinicia_sem_medir_a_integridade(tmp_path):
    m, st = _mundo({"/api/ugs": MAL}, qc=(None, "outra quick_check em curso (trava ocupada)"))
    r = R.painel_shm(m, tmp_path)
    assert r["acao"] == "nao_reinicia" and "NÃO foi medida" in r["motivo"] and st["reinicios"] == 0


def test_painel_shm_reinicia_uma_vez_com_arquivo_integro_e_nunca_em_laco(tmp_path):
    rel = Relogio()
    m, st = _mundo({"/api/comparador/economia": MAL}, relogio=rel)
    assert R.painel_shm(m, tmp_path)["acao"] == "curado" and st["reinicios"] == 1
    # o -shm morre de novo 5 min depois: dentro do resfriamento NÃO reinicia — escala
    st["corpos"] = {"/api/comparador/economia": MAL}
    rel.t += 300
    r = R.painel_shm(m, tmp_path)
    assert r["acao"] == "escalar" and st["reinicios"] == 1
    rel.t += R.RESFRIAMENTO_S                                               # passado o resfriamento, pode de novo
    assert R.painel_shm(m, tmp_path)["acao"] == "curado" and st["reinicios"] == 2


def test_painel_shm_restart_que_nao_cura_escala(tmp_path):
    m, st = _mundo({"/api/ugs": MAL}, cura=False)
    assert R.painel_shm(m, tmp_path)["acao"] == "escalar" and st["reinicios"] == 1


# ── painel_travado (regra das 2 falhas do painel_vigia) ────────────────────────────────────────────────────────
def test_painel_travado_confirma_na_segunda_e_respeita_resfriamento(tmp_path):
    rel = Relogio()
    m, st = _mundo({"/painel": (None, "")}, relogio=rel)
    assert R.painel_travado(m, tmp_path)["acao"] == "confirmar" and st["reinicios"] == 0
    assert R.painel_travado(m, tmp_path)["acao"] == "curado" and st["reinicios"] == 1
    st["corpos"] = {"/painel": (None, "")}
    rel.t += 60
    R.painel_travado(m, tmp_path)
    assert R.painel_travado(m, tmp_path)["acao"] == "escalar" and st["reinicios"] == 1
    m2, st2 = _mundo({"/painel": (303, "")})
    assert R.painel_travado(m2, tmp_path)["acao"] == "nada"
    assert not (tmp_path / R.MARCA_FALHA_PAINEL).exists()                   # resposta boa zera a 1ª falha


def test_estado_do_sensor_do_painel_duas_seguidas():
    assert S.painel_estado(True, 5) == (0, None)
    assert S.painel_estado(False, 0) == (1, "DEGRADADO")
    assert S.painel_estado(False, 1) == (2, "BLOQUEADO")


# ── db.integridade ─────────────────────────────────────────────────────────────────────────────────────────────
def test_incidente_abre_uma_vez_e_fecha_quando_volta(tmp_path):
    marca = tmp_path / "m.alertado"
    assert S.incidente(marca, True) == ""
    assert S.incidente(marca, False) == "novo" and marca.exists()
    assert S.incidente(marca, False) == "aberto"                            # 2ª medida ruim: não alerta de novo
    assert S.incidente(marca, True) == "encerrado" and not marca.exists()
    assert S.incidente(marca, False) == "novo"                              # próximo incidente volta a alertar


def test_db_integridade_ok_corrompido_e_trava_ocupada(tmp_path, monkeypatch):
    import sqlite3
    dados = tmp_path / "data"
    dados.mkdir()
    db = dados / "compliance.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    monkeypatch.setenv("JFN_DATA_DIR", str(dados))
    ctx = S.Ctx(no="vm1", con=None, agora=datetime.now(timezone.utc), raiz=tmp_path)
    r = S.g_integridade(ctx)[0]
    assert r.nome == "db.integridade" and r.valor == 1.0 and r.forcado is None
    # trava ocupada (outro quick_check, ex.: o do remédio): não mediu — nunca "ok"
    trava = tmp_path / S.TRAVA_QUICK_CHECK
    with trava.open("a") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        r = S.g_integridade(ctx)[0]
    assert r.valor is None and "trava ocupada" in r.motivo
    # quick_check ruim ⇒ BLOQUEADO + incidente novo (uma vez)
    monkeypatch.setattr(S, "quick_check_ro", lambda db, trava, timeout_s=900: ("Page 3 is never used", 0.1, ""))
    r1, r2 = S.g_integridade(ctx)[0], S.g_integridade(ctx)[0]
    assert r1.valor == 0.0 and r1.forcado == "BLOQUEADO" and r1.rotulos["incidente"] == "novo"
    assert r2.rotulos["incidente"] == "aberto"
    slo = S.carregar_slos().por_sensor()["db.integridade"][1]
    assert S.avaliar(slo, r1.valor, r1.forcado)[0] == "BLOQUEADO"


# ── cron → fluxo ───────────────────────────────────────────────────────────────────────────────────────────────
CRONTAB = """# cabeçalho
JFN_X=1
@reboot sleep 20 && rm -f /x/JFN/data/browser.lock
*/5 * * * * /x/polimonitor/scripts/run-likers-import.sh >> /x/l.log 2>&1
50 3 * * 0 bash /x/JFN/tools/backup_compliance.sh >> /x/b.log 2>&1
#PARADA-20261124 0 5 * * * python -m compliance_agent.siafe_runner diario
1-59/5 * * * * /x/JFN/tools/guardiao_db_malformed.sh
20 4 * * * cd /x/JFN && xvfb-run -a /opt/s/python tools/zelador/mediafire_sessao.py >> m.log 2>&1
25 3 * * * cd /x/vault && git add -A && git commit -qm backup
7 7 * * * /x/algo/desconhecido.sh
"""


def test_classificar_o_crontab():
    migrar = sorted(x.rotina for x in C.classificar(CRONTAB) if x.classe == "migrar")
    assert migrar == ["backup_compliance", "mediafire_sessao", "remediar_painel_shm"]
    por_classe = {}
    for x in C.classificar(CRONTAB):
        por_classe.setdefault(x.classe, []).append(x)
    assert len(por_classe["fora_do_jfn"]) == 2 and len(por_classe["fica_no_cron"]) == 1
    assert len(por_classe["parada"]) == 1 and len(por_classe["desconhecida"]) == 1


def test_comentar_so_o_que_tem_rotina_ativa_e_desfazer_volta_igual():
    rot = {"backup_compliance": True, "remediar_painel_shm": True, "mediafire_sessao": False}
    novo, alvo = C.comentar(CRONTAB, rot, "#FLUXO-20261124 ")
    assert sorted(x.rotina for x in alvo) == ["backup_compliance", "remediar_painel_shm"]
    assert "#FLUXO-20261124 50 3 * * 0 bash" in novo and "#FLUXO-20261124 1-59/5" in novo
    assert "\n20 4 * * * cd /x/JFN && xvfb-run" in novo                     # inativa: fica no cron
    assert "\n*/5 * * * * /x/polimonitor" in novo and "\n25 3 * * * cd /x/vault" in novo   # fora do JFN: intocadas
    assert sum(x.classe == "migrada" for x in C.classificar(novo)) == 2
    volta, n = C.descomentar(novo, "#FLUXO-20261124")
    assert n == 2 and volta == CRONTAB
    assert C.descomentar(novo, "#FLUXO-20991231")[1] == 0                   # outra marca: não mexe


def test_comentar_recusa_tudo_se_falta_rotina():
    with pytest.raises(ValueError, match="ausente"):
        C.comentar(CRONTAB, {"backup_compliance": True}, "#FLUXO-20261124 ")


def test_toda_rotina_do_mapa_existe_no_yaml_real_e_origens_sairam_do_fora():
    g = G.carregar()
    for _trecho, rid in C.CRON_VM1:
        assert rid in g.rotinas, rid
    for rid in C.TIMERS_VM2.values():
        assert rid in g.rotinas, rid
    fora = {o for f in g.fora for o in f.origem}
    for o in ("vm1-cron-logrotate", "vm2-timer-jfn-logrotate", "vm1-cron-rsync", "vm1-cron-graphify-out",
              "vm1-cron-nuvens-manter-vivas-sh", "vm1-cron-painel-vigia-sh"):
        assert o not in fora, o
    assert "vm1-cron-vault" in fora                                         # backup do vault: fora do JFN
    for rid in ("remediar_painel_shm", "remediar_painel_travado", "graphify_retencao", "graph_report_brain",
                "logrotate_vm1", "logrotate_vm2", "nuvens_manter_vivas"):
        r = g.rotinas[rid]
        assert r.efeito.log_contem and r.trava and r.volta is not None and r.agenda, rid
    assert "guardiao_db_malformed" not in g.rotinas                         # virou sensor + remédio


def test_retencao_do_graphify_mantem_os_3_mais_novos():
    nomes = ["2026-11-01", "2026-11-03", "2026-11-02", "2026-11-04", "GRAPH_REPORT.md", "cache"]
    assert I.snapshots_a_apagar(nomes) == ["2026-11-01"]
    assert I.snapshots_a_apagar(nomes[:3]) == []
