# -*- coding: utf-8 -*-
"""it-campo com N sessões SEI: fatias disjuntas na ordem de prioridade, métricas da rodada a partir do log da casa,
erro de método separado de processo restrito, e sessões em árvores diferentes não se tratam como duplicata."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import tools.itcampo_sei_paralelo as P
import tools.sei_integra_fila as F


def test_relatorio_por_degrau_soma_voltas_simultaneas():
    def volta(n, slot, ini, fim, procs):
        return {"sessoes": n, "slot": slot, "inicio": ini, "ts": fim, "aprovados": 1, "procs": procs}
    ok = {"status": "ok", "segundos": 600.0, "docs": 10, "docs_com_teor": 9}
    regs = [volta(4, 1, "2026-11-14 10:00:00", "2026-11-14 10:30:00", {"1/1/1": ok, "1/1/2": ok}),
            volta(4, 2, "2026-11-14 10:00:00", "2026-11-14 10:30:00", {"1/1/3": ok}),
            volta(8, 1, "2026-11-14 10:30:00", "2026-11-14 11:00:00", {"1/1/4": ok})]
    r = P.relatorio(regs)
    assert r[4]["tentados"] == 3 and r[4]["horas"] == 0.5 and r[4]["proc_por_hora"] == 6.0
    assert r[4]["docs_por_hora"] == 60.0 and r[4]["taxa_docs_vazios"] == 0.1
    assert r[8]["voltas"] == 1


def test_metricas_do_log(tmp_path):
    arq, cache = tmp_path / "arq", tmp_path / "cache"
    (arq / "100000_000001_2025").mkdir(parents=True)
    (arq / "100000_000001_2025" / "manifest.json").write_text(json.dumps(
        {"docs": [{"chars": 500}, {"chars": 10}, {"chars": "90"}, {"chars": 0}]}))
    (cache / "integra_100000_000001_2025").mkdir(parents=True)
    (cache / "integra_100000_000001_2025" / "manifest.json").write_text(json.dumps(
        {"total_arvore": 4, "docs": [{"ok": True}, {"ok": True}, {"ok": True}, {"ok": False}]}))
    linhas = [
        "[2026-11-14 10:00:00] ÍNTEGRA 100000/000001/2025 …",
        "[2026-11-14 10:02:00]   100000/000001/2025: ok",
        "[2026-11-14 10:02:05] ÍNTEGRA 100000/000002/2025 …",
        "[2026-11-14 10:03:05]   100000/000002/2025: SEM ÁRVORE (processo não abriu) — RESTRITO: SEI diz 'x' — via=1",
        "[2026-11-14 10:03:05]   100000/000002/2025: sem_arvore",
        "[2026-11-14 10:03:10] ÍNTEGRA 100000/000003/2025 …",
        "[2026-11-14 10:04:10]   100000/000003/2025: sem_arvore",
        "[2026-11-14 10:04:15] ÍNTEGRA 100000/000004/2025 …",
        "[2026-11-14 10:19:15]   100000/000004/2025: timeout",
    ]
    m = P.metricas_do_log(linhas, arq, cache)
    assert m["tentados"] == 4 and m["ok"] == 1 and m["restritos"] == 1
    assert m["erros_metodo"] == 2                       # timeout + sem árvore SEM causa do SEI; restrito não conta
    assert m["docs"] == 4 and m["docs_com_teor"] == 2 and m["taxa_docs_vazios"] == 0.5
    assert m["s_por_doc"] == 30.0
    assert m["procs"]["100000/000001/2025"]["docs_falhos"] == 1


def test_sessao_em_outra_arvore_nao_e_duplicata(tmp_path):
    outra = tmp_path / "s2" / "tools"
    outra.mkdir(parents=True)
    (outra / "sei_integra_fila.py").write_text("import time; time.sleep(30)\n")
    p = subprocess.Popen([sys.executable, "tools/sei_integra_fila.py"], cwd=tmp_path / "s2")
    try:
        # Logo após o fork, antes do exec, /proc/<pid>/cmdline ainda é o do pytest — `_mesmo_worker` responde
        # "duplicata" (o erro seguro, de propósito) e o teste falhava sob carga. Espera o exec, não o resultado.
        import time
        limite = time.monotonic() + 10
        while time.monotonic() < limite and b"sei_integra_fila.py" not in open(f"/proc/{p.pid}/cmdline", "rb").read():
            time.sleep(0.01)
        assert F._mesmo_worker(str(p.pid)) is False
    finally:
        p.kill(); p.wait()
    assert F._mesmo_worker(str(os.getpid())) is True    # sem o script na linha de comando: na dúvida, duplicata


def test_subfatias_da_varredura_cobrem_a_metade_da_vm1_sem_sobrepor():
    """Sessão k de M varre `2(k-1)/2M`: hash ≡ 2(k-1) mod 2M ⇒ par ⇒ dentro da fatia 0/2 da VM-1, nunca na 1/2
    da VM-2, e as M sub-fatias juntas cobrem a 0/2 inteira, sem processo em duas sessões."""
    from tools.sei_sweep import na_minha_fatia
    procs = [f"SEI-{u:06d}/{n:06d}/2025" for u in (80001, 270006, 330005) for n in range(400)]
    m = 4
    for p in procs:
        donos = [k for k in range(1, m + 1) if na_minha_fatia(p, 2 * (k - 1), 2 * m)]
        assert len(donos) == (1 if na_minha_fatia(p, 0, 2) else 0)


def test_freio_de_memoria_tira_uma_sessao_so_depois_de_minutos_seguidos_abaixo_do_piso():
    """14/11/2026 17:22: OOM global no WSL com 8+5 sessões. Varredura sai primeiro; íntegras nunca abaixo de N_MIN."""
    piso = P.PISO_MEM_GB
    n, v, baixos = 8, 5, 0
    for _ in range(P.MINUTOS_ABAIXO_DO_PISO - 1):
        n, v, baixos = P.freio_de_memoria(piso - 1, n, v, baixos)
        assert (n, v) == (8, 5)
    assert P.freio_de_memoria(piso - 1, n, v, baixos) == (8, 4, 0)
    assert P.freio_de_memoria(piso - 1, 8, 0, P.MINUTOS_ABAIXO_DO_PISO - 1) == (7, 0, 0)
    assert P.freio_de_memoria(piso - 1, P.N_MIN, 0, P.MINUTOS_ABAIXO_DO_PISO - 1) == (P.N_MIN, 0, 0)


def test_freio_de_memoria_nao_age_com_folga_nem_sem_leitura():
    """Controle negativo: com folga, ou sem conseguir ler a memória, nada muda e a contagem zera."""
    assert P.freio_de_memoria(P.PISO_MEM_GB + 0.1, 8, 5, 2) == (8, 5, 0)
    assert P.freio_de_memoria(None, 8, 5, 2) == (8, 5, 0)


def test_fila_de_varredura_esgotada_pede_mais_ate_o_teto():
    """14/11/2026 18:06: fila de 120 toda lida ⇒ volta de 0 s em laço. Cresce 4× por pedido; no teto, espera longa."""
    assert P.proxima_fila_v(P.FILA_V_MAX) == 480
    assert P.proxima_fila_v(480) == P.FILA_V_TETO
    assert P.proxima_fila_v(P.FILA_V_TETO) is None


def test_sessao_so_reabre_por_commit_que_mexe_no_codigo_da_captura(monkeypatch):
    def git(saida, rc=0):
        return lambda cmd, **kw: subprocess.CompletedProcess(cmd, rc, stdout=saida, stderr="")
    monkeypatch.setattr(P, "_run", git("static/js/painel.js\ncompliance_agent/pericia_contabil.py\ndocs/X.md\n"))
    assert P.codigo_da_captura_mudou("aaa", "bbb") is False
    monkeypatch.setattr(P, "_run", git("docs/X.md\ntools/sei_reader.py\n"))
    assert P.codigo_da_captura_mudou("aaa", "bbb") is True
    monkeypatch.setattr(P, "_run", git("compliance_agent/sei/ocr_docs.py\n"))
    assert P.codigo_da_captura_mudou("aaa", "bbb") is True
    monkeypatch.setattr(P, "_run", git("", rc=128))            # git não soube dizer: reabre, como antes
    assert P.codigo_da_captura_mudou("aaa", "bbb") is True
    assert P.codigo_da_captura_mudou("aaa", "aaa") is False


def test_teto_do_arquivamento_e_configuravel_e_o_no_usa_uma_hora():
    """14/11/2026: capturas completas de 1.071 e 812 documentos perdidas no teto cravado de 900 s do arquivador."""
    from pathlib import Path
    assert F.TETO_ARQUIVAR_S == int(os.environ.get("INTEGRA_TETO_ARQUIVAR_S", "900"))
    fila = Path(F.__file__).read_text(encoding="utf-8")
    assert "timeout=TETO_ARQUIVAR_S" in fila and "timeout=900," not in fila
    assert '"INTEGRA_TETO_ARQUIVAR_S", "3600"' in Path(P.__file__).read_text(encoding="utf-8")


def test_acelerador_sobe_uma_sessao_so_depois_de_folga_sustentada():
    """Dono, 15/11/2026: "de tempos em tempos avaliar tudo que tiver de memória sobrando pra acelerar". Sobe UMA
    sessão por vez, só com memória E processador folgados por vários minutos seguidos; íntegras primeiro (é o atraso
    de >30 dias), depois varredura; nunca acima dos tetos."""
    folga = P.PISO_MEM_GB + P.FOLGA_SUBIR_GB + 0.1
    n, v, f = 8, 4, 0
    for _ in range(P.MINUTOS_FOLGA_PARA_SUBIR - 1):
        n, v, f = P.acelerador(folga, 6.0, 24, n, v, f, saude=(10, 0))
        assert (n, v) == (8, 4)
    assert P.acelerador(folga, 6.0, 24, n, v, f, saude=(10, 0)) == (9, 4, 0)
    assert P.acelerador(folga, 6.0, 24, P.N_MAX, 4, P.MINUTOS_FOLGA_PARA_SUBIR - 1, saude=(10, 0)) == (P.N_MAX, 5, 0)
    assert P.acelerador(folga, 6.0, 24, P.N_MAX, P.V_MAX, 99, saude=(10, 0)) == (P.N_MAX, P.V_MAX, 0)


def test_acelerador_nao_sobe_sem_folga_de_memoria_cpu_ou_leitura():
    folga = P.PISO_MEM_GB + P.FOLGA_SUBIR_GB + 0.1
    quase = P.MINUTOS_FOLGA_PARA_SUBIR - 1
    assert P.acelerador(P.PISO_MEM_GB + 1, 6.0, 24, 8, 4, quase) == (8, 4, 0)      # memória curta: zera a contagem
    assert P.acelerador(folga, 22.0, 24, 8, 4, quase) == (8, 4, 0)                  # processador cheio
    assert P.acelerador(None, 6.0, 24, 8, 4, quase) == (8, 4, 0)                    # sem leitura: não sobe às cegas


def test_acelerador_desligado_pelo_arquivo_do_dono(tmp_path, monkeypatch):
    """15/11/2026: ventoinha do it-campo à noite — com `.sem_acelerar` nada sobe."""
    flag = tmp_path / ".sem_acelerar"
    flag.touch()
    monkeypatch.setattr(P, "SEM_ACELERAR", flag)
    folga = P.PISO_MEM_GB + P.FOLGA_SUBIR_GB + 0.1
    assert P.acelerador(folga, 1.0, 24, 5, 2, P.MINUTOS_FOLGA_PARA_SUBIR - 1) == (5, 2, 0)


def _rodada(ts, **status):
    procs = {f"{i:06d}/000001/2026": {"status": s} for i, s in enumerate(
        [st for st, q in status.items() for _ in range(q)])}
    return {"ts": ts, "no": "itcampo", "procs": procs}


def test_saude_conta_ok_e_login_so_da_janela_recente():
    agora = P._ts("2026-11-15 18:00:00")
    regs = [_rodada("2026-11-15 17:00:00", ok=9),                       # fora da janela de 30 min
            _rodada("2026-11-15 17:45:00", ok=2, login=1, sem_arvore=4),
            {"ts": "2026-11-15 17:50:00", "modo": "varredura", "cdp": 3}]  # varredura não tem status por processo
    assert P.saude_sei(regs, agora) == (2, 1)


def test_acelerador_nao_le_cpu_ociosa_de_sessao_bloqueada_como_folga():
    """15/11/2026: o SEI recusou o it-campo das 15h em diante (login 100% falho); a CPU ficou ociosa PORQUE nada
    era capturado e o acelerador leu isso como folga — subiu de 12+3 para 12+6 durante o bloqueio, martelando mais."""
    folga = P.PISO_MEM_GB + P.FOLGA_SUBIR_GB + 0.1
    quase = P.MINUTOS_FOLGA_PARA_SUBIR - 1
    assert P.acelerador(folga, 1.0, 24, 12, 3, quase, saude=(0, 40)) == (12, 3, 0)   # só login falho
    assert P.acelerador(folga, 1.0, 24, 12, 3, quase, saude=(0, 0)) == (12, 3, 0)    # nada medido: não sobe às cegas
    assert P.acelerador(folga, 1.0, 24, 12, 3, quase, saude=(10, 5)) == (12, 3, 0)   # 1/3 de login falho
    assert P.acelerador(folga, 1.0, 24, 12, 3, quase, saude=(20, 1)) == (12, 4, 0)


def test_espera_depois_da_volta_nao_gira_em_falso():
    """15/11/2026: com a fila local toda "vazia recente", cada sessão voltava em ~20 s e, a cada volta, pedia fila
    nova à VM-1 por ssh e batia o ponto — 18 sessões levaram a VM-1 (2 vCPU) a carga 19. Volta sem nada tentado espera."""
    assert P.espera_apos_volta(None) == 1200
    assert P.espera_apos_volta({"esgotada": True}) == 60
    assert P.espera_apos_volta({"tentados": 0}) == P.ESPERA_VOLTA_VAZIA_S >= 600
    assert P.espera_apos_volta({"tentados": 3}) == 0
    assert P.espera_apos_volta({"modo": "varredura", "cdp": 2}) == 0


def test_navegador_fixo_da_sessao_porta_janela_e_sem_estrangulamento(tmp_path):
    """Uma janela por sessão, aberta e logada, pequena e fora do caminho do dono ("de um jeito que eu consiga usar o
    computador"); minimizada continua trabalhando (sem estrangulamento de fundo do Chromium)."""
    c1 = P.comando_navegador(tmp_path / "s1", "integras", 1, "/x/chrome")
    c2 = P.comando_navegador(tmp_path / "v1", "varredura", 1, "/x/chrome")
    assert c1[0] == "/x/chrome"
    assert P.porta_cdp("integras", 1) != P.porta_cdp("varredura", 1)
    assert f"--remote-debugging-port={P.porta_cdp('integras', 1)}" in c1
    assert any(a.startswith("--user-data-dir=") and "s1" in a for a in c1)
    for flag in ("--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                 "--disable-backgrounding-occluded-windows"):
        assert flag in c1
    pos = lambda c: next(a for a in c if a.startswith("--window-position="))
    assert pos(c1) != pos(c2)
    tam = next(a for a in c1 if a.startswith("--window-size=")).split("=")[1].split(",")
    # janela estreita escondia o campo de pesquisa do SEI (15/11: 640x480 "não abriu", 1366x900 abriu)
    assert int(tam[0]) >= 1280 and int(tam[1]) >= 800


def test_navegador_fixo_oculto_por_padrao_com_ua_de_desktop(tmp_path, monkeypatch):
    """Dono, 15/11/2026 21h: "a janela do SEI continua interferindo no meu uso… tente uma sessão headless"."""
    monkeypatch.delenv("ITCAMPO_NAVEGADOR_VISIVEL", raising=False)
    c = P.comando_navegador(tmp_path / "s1", "integras", 1, "/x/chrome")
    assert "--headless=new" in c
    ua = next(a for a in c if a.startswith("--user-agent="))
    assert "Headless" not in ua and "Chrome/" in ua
    monkeypatch.setenv("ITCAMPO_NAVEGADOR_VISIVEL", "1")
    assert "--headless=new" not in P.comando_navegador(tmp_path / "s1", "integras", 1, "/x/chrome")
