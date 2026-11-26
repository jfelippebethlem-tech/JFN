# -*- coding: utf-8 -*-
"""Supervisor do motor de fluxo (O1.8): o job "eco" ponta a ponta em ESQUEMA TEMPORÁRIO, com o handler em
subprocesso, e a CATRACA — o supervisor nunca roda handler no próprio processo (§3.3, lição do lane contínuo)."""
import ast
import json
import os
from pathlib import Path

import pytest

from compliance_agent.fluxo import fila, governador, supervisor as S
from compliance_agent.fluxo import grafo as grafo_mod
from tests.fluxo_pg import DSN, chave_lock, con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures

PACOTE = Path(S.__file__).resolve().parent
# o que roda dentro do processo do supervisor: nenhum destes pode importar a camada de aplicação (os handlers)
DO_SUPERVISOR = ("supervisor.py", "planejador.py", "fila.py", "governador.py", "schema.py", "__main__.py",
                 "__init__.py")


def _importados(caminho: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes.update(a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
    return nomes


@pytest.mark.parametrize("arquivo", DO_SUPERVISOR)
def test_catraca_supervisor_nao_importa_handler(arquivo):
    proibidos = {n for n in _importados(PACOTE / arquivo)
                 if n.startswith("compliance_agent.aplicacao") or n.endswith("fluxo.executar")}
    assert not proibidos, f"{arquivo} importa {proibidos}: handler só roda no filho (compliance_agent.fluxo.executar)"


def test_comando_isolado_com_systemd_e_sem():
    lim = S.limites_do_job(["cpu_leve", "cpu_pesado"])
    assert lim == ("3G", 30, 3600)                                         # o mais folgado de memória e tempo
    c = S.montar_comando("rodar", Path("/t/e.json"), Path("/t/s.json"), lim, "systemd", python="/py")
    assert c[:5] == ["systemd-run", "--user", "--scope", "--quiet", "--slice=jfn-coletor.slice"]
    assert "MemoryMax=3G" in c and "CPUWeight=30" in c
    assert "Wants=jfn-egress.service" in c and "After=jfn-egress.service" in c     # O0.4: regra antes do job
    assert c[-6:] == ["/py", "-m", "compliance_agent.fluxo.executar", "rodar", "/t/e.json", "/t/s.json"]
    s = S.montar_comando("rodar", Path("/t/e.json"), Path("/t/s.json"), lim, "subprocesso", python="/py")
    assert "systemd-run" not in s and s[-6] == "/py"
    if s[0] == "timeout":
        assert s[:4] == ["timeout", "-k", "10", "3600"]
    assert S.limites_do_job(["llm"], {"timeout_s": 5})[2] == 5


def _sup(esquema, isolamento="subprocesso", **kw):
    return S.Supervisor(no="teste", dsn=DSN, esquema=esquema, slots={"cpu_leve": 2}, grafo={},
                        isolamento=isolamento, chave_lideranca=chave_lock(), medir=lambda: governador.Medida(), **kw)


@precisa_pg
def test_eco_ponta_a_ponta_em_subprocesso(con, esquema_tmp):
    fila.enfileirar(con, "eco", "eco:e2e", correlation_id="cid-e2e")
    sup = _sup(esquema_tmp)
    try:
        r = sup.uma_volta()
        assert r["lancados"] == 1
        tot = sup.drenar(120)
    finally:
        sup.fechar()
    assert tot["feito"] == 1, tot
    estado, efeito = con.execute("SELECT estado, efeito FROM jobs WHERE chave = 'eco:e2e'").fetchone()
    assert estado == "feito"
    pid, ficha = con.execute("SELECT (rotulos->>'pid')::int, (rotulos->>'ficha')::bigint FROM metricas "
                             "WHERE id = %s", (efeito["metrica_id"],)).fetchone()
    assert pid != os.getpid()                                              # CATRACA: o handler rodou em outro PID
    assert ficha == con.execute("SELECT ficha FROM jobs WHERE chave = 'eco:e2e'").fetchone()[0]
    assert con.execute("SELECT fonte, chave, detalhe->>'correlation_id' FROM eventos").fetchone() == (
        "eco", "eco:e2e", "cid-e2e")
    no = con.execute("SELECT capacidades->>'isolamento', psi->>'estado' FROM nos WHERE no = 'teste'").fetchone()
    assert no == ("subprocesso", "folga")


@precisa_pg
def test_efeito_nao_conferido_volta_e_esgotado_vira_falhou_efeito(con, esquema_tmp):
    fila.enfileirar(con, "eco", "eco:mente", {"falhar_efeito": True}, max_tentativas=2)
    sup = _sup(esquema_tmp)
    try:
        sup.uma_volta()
        tot = sup.drenar(120)
        assert tot["volta_efeito"] == 1, tot                               # 1.2: volta com backoff
        assert fila.estado_de(con, "eco:mente") == "fila"
        con.execute("UPDATE jobs SET disponivel_em = now()")
        sup.uma_volta()
        tot = sup.drenar(120)
    finally:
        sup.fechar()
    assert tot["falhou_efeito"] == 1, tot
    assert con.execute("SELECT estado, erro_tipo, erro_resumo FROM jobs").fetchone() == (
        "falhou_efeito", "efeito", "efeito não conferido (a conferência não disse por quê)")
    assert con.execute("SELECT count(*) FROM eventos").fetchone()[0] == 0


@precisa_pg
def test_estagio_desconhecido_vai_a_quarentena(con, esquema_tmp):
    fila.enfileirar(con, "nao_existe", "nao_existe:1")
    sup = _sup(esquema_tmp)
    try:
        sup.uma_volta()
        tot = sup.drenar(120)
    finally:
        sup.fechar()
    assert tot["falhou"] == 1
    assert con.execute("SELECT estado, erro_tipo FROM jobs").fetchone() == ("quarentena", "permanente")


@precisa_pg
def test_supervisor_morto_no_meio_nao_perde_o_job(con, esquema_tmp):
    """O nó cai com o job reservado: o lease vence, o planejador (outro nó) devolve à fila e o job termina lá."""
    fila.enfileirar(con, "eco", "eco:queda")
    morto = _sup(esquema_tmp, prazo_s=2)
    morto.uma_volta()
    for f in list(morto.filhos):                                           # a máquina caiu: filho e supervisor somem
        S.Supervisor._matar(f)
    morto.filhos.clear()
    morto.fechar()
    con.execute("UPDATE jobs SET prazo = now() - interval '1 second'")
    vivo = _sup(esquema_tmp)
    try:
        r = vivo.uma_volta()                                               # líder: recupera o lease vencido
        assert r["planejador"]["recuperados"] == 1
        con.execute("UPDATE jobs SET disponivel_em = now()")               # pula o backoff
        vivo.uma_volta()
        tot = vivo.drenar(120)
    finally:
        vivo.fechar()
    assert tot["feito"] == 1
    assert con.execute("SELECT estado, tentativas FROM jobs").fetchone() == ("feito", 2)


@precisa_pg
def test_contido_nao_lanca(con, esquema_tmp):
    fila.enfileirar(con, "eco", "eco:contido")
    sup = S.Supervisor(no="teste", dsn=DSN, esquema=esquema_tmp, slots={"cpu_leve": 2}, grafo={},
                       isolamento="subprocesso", chave_lideranca=chave_lock(),
                       medir=lambda: governador.Medida(cpu_some=90))
    try:
        assert sup.uma_volta()["lancados"] == 0
    finally:
        sup.fechar()
    assert fila.estado_de(con, "eco:contido") == "fila"


@precisa_pg
@pytest.mark.skipif(not S.systemd_disponivel(), reason="systemd do usuário não aceita escopo transitório aqui")
def test_eco_ponta_a_ponta_em_escopo_systemd(con, esquema_tmp):
    fila.enfileirar(con, "eco", "eco:systemd")
    sup = _sup(esquema_tmp, isolamento="systemd")
    try:
        sup.uma_volta()
        tot = sup.drenar(120)
    finally:
        sup.fechar()
    assert tot["feito"] == 1, tot


def test_escopo_com_nome_e_morto_inteiro(monkeypatch):
    """Religação O9.0 (25/11/2026): o `timeout` matou só o executar e o despachante antigo, lançado destacado por um
    remédio, ficou órfão no escopo (1 GB, horas). O escopo do job ganha nome e é morto INTEIRO ao encerrar o job."""
    lim = S.limites_do_job(["cpu_leve"])
    c = S.montar_comando("rodar", Path("/t/e.json"), Path("/t/s.json"), lim, "systemd", python="/py",
                         unidade="jfn-job-7-3-rodar")
    assert "--unit=jfn-job-7-3-rodar" in c and c.index("--unit=jfn-job-7-3-rodar") < c.index("--")
    chamadas = []
    monkeypatch.setattr(S.subprocess, "run", lambda argv, **k: chamadas.append(argv))
    S.matar_escopo("jfn-job-7-3-rodar")
    assert chamadas == [["systemctl", "--user", "kill", "--signal=SIGKILL", "jfn-job-7-3-rodar.scope"]]
    chamadas.clear()
    S.matar_escopo(None)
    assert chamadas == []


@precisa_pg
def test_yaml_mudado_recarrega_a_quente_e_ressincroniza_a_agenda(con, esquema_tmp, tmp_path, monkeypatch):
    """Religação O9.0 (26/11/2026): o supervisor lia o yaml só no boot e a agenda guardava `timeout_s` congelado no
    payload — 8 tetos corrigidos no yaml nunca chegaram às rodadas agendadas (pcrj_sei_ingest 5× rc=124 com 960 s).
    Yaml mudado ⇒ recarrega grafo/contrato/tetos/ritmos e ressincroniza a agenda, sem reiniciar (jobs longos vivos)."""
    from compliance_agent.fluxo import planejador as PL
    arq = tmp_path / "fluxo.yaml"
    arq.write_text(Path(grafo_mod.CAMINHO).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(grafo_mod, "CAMINHO", arq)
    sup = S.Supervisor(no="vm1", dsn=DSN, esquema=esquema_tmp, isolamento="subprocesso",
                       chave_lideranca=chave_lock(), medir=lambda: governador.Medida())
    try:
        g0 = grafo_mod.carregar(arq)
        PL.sincronizar_agenda(sup.con, g0.agenda_linhas() + g0.agenda_nativa())
        sup.con.execute("UPDATE agenda SET ativo = true")
        assert sup.recarregar_grafo_se_mudou() is None                         # nada mudou
        texto = arq.read_text(encoding="utf-8")
        arq.write_text(texto.replace("timeout_s: 2400 ", "timeout_s: 2401 ", 1), encoding="utf-8")
        r = sup.recarregar_grafo_se_mudou(sincronizar=True)
        assert r and r["agenda"]["atualizadas"] >= 1
        t = con.execute(f'SELECT payload->>\'timeout_s\' FROM "{esquema_tmp}".agenda '
                        "WHERE payload->>'rotina' = 'sei_rj_catalogo'").fetchone()[0]
        assert t == "2461"
        # 26/11: a recarga desativava as agendas dos estágios NATIVOS (e18_observar_*, e17_*) — fora de agenda_linhas()
        assert r["agenda"]["desativadas"] == 0
        assert con.execute(f'SELECT bool_and(ativo) FROM "{esquema_tmp}".agenda').fetchone()[0]
        arq.write_text("isto: [não é yaml válido", encoding="utf-8")                # inválido: mantém o anterior
        assert sup.recarregar_grafo_se_mudou()["erro"]
        assert sup.grafo                                                        # o grafo anterior segue em uso
    finally:
        sup.fechar()


@precisa_pg
def test_teto_adaptativo_vigente_limita_o_do_yaml(con, esquema_tmp):
    """26/11/2026: o teto de logins no SEI é decidido pela medida (fluxo.teto_adaptativo); o supervisor usa o MENOR
    entre o do yaml e o vigente — sem decisão vigente vale o yaml."""
    sup = _sup(esquema_tmp, tetos={"sei_rj_ip": 6})
    try:
        assert sup.tetos_efetivos()["sei_rj_ip"] == 6
        con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'teto_adaptativo', 2, %s)",
                    (json.dumps({"etiqueta": "sei_rj_ip"}),))
        sup._teto_lido_em = 0.0
        assert sup.tetos_efetivos()["sei_rj_ip"] == 2
    finally:
        sup.fechar()
