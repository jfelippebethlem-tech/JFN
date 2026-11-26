# -*- coding: utf-8 -*-
"""
automelhoria_geral — o loop de automelhoria de TUDO: uma fila única, com cura e reincidência medidas.

POR QUE EXISTE. A casa tinha sensores espalhados e nenhum laço fechado entre eles. Medido em 24/10/2026:
  · o CI ficou vermelho de 12/10 a 24/10 (lint) e escondia 6 testes quebrados — ninguém olhava;
  · o diário do SIAFE morreu 4 madrugadas e só o SLO (123 h) acusou, sem conexão com o dreno que o causou;
  · o dreno repetiu 3.721 "SEM GANHO" e o login do SIAFE 1 caiu em 13/09 sem alarme;
  · o Yoda falhou com o dono desde agosto e nenhum sensor via conversa.
Cada sensor avisava (ou não) por conta própria; nenhum dizia se o conserto PEGOU.

O CICLO (determinístico, sem LLM; roda no cron e sob demanda pelo /melhorias do Yoda):
  1. SENTE — SLO das rotinas (config/pipelines.yaml), CI do GitHub, catracas da casa, serviços systemd
     falhos, ronda (API/LLM), SIAFE (diário, disjuntor de login, conflitos do dreno) e a fila de falhas
     de conversa do Yoda (tools/yoda_autoauditoria.py).
  2. CONCILIA numa fila única por assinatura: problema novo → `aberto`; problema que sumiu → `curado`
     (o sensor voltou ao verde: é a verificação do EFEITO, não da ação); curado que volta → `REINCIDIU`.
  3. AVISA no Telegram só com novidade (novo ou reincidente). Dia sem novidade = silêncio.
  4. RELATA no vault (aprendizados/automelhoria/) e responde ao /melhorias do Yoda.

Sensor que não conseguiu medir NÃO vira "ok": vira o problema `sensor:<nome>` — INDISPONÍVEL ≠ 0.

Uso:
  python tools/automelhoria_geral.py                # sente, concilia, relata, avisa se houver novidade
  python tools/automelhoria_geral.py --resumo       # só lê a fila (rápido) — é o que o /melhorias mostra
  python tools/automelhoria_geral.py --sem-aviso
  python tools/automelhoria_geral.py --remediar     # SÓ à mão: lança os remédios antigos (destacados, fora do fluxo)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DATA = _REPO / "data"
FILA = DATA / "automelhoria_fila.json"
RELATORIOS = Path.home() / "vault" / "aprendizados" / "automelhoria"
CATRACAS = ["tests/test_catraca_excepts.py", "tests/test_divida_except_pass.py",
            "tests/test_catraca_nao_pode_ser_tolerada.py", "tests/test_capacidade_pronta_tem_superficie.py",
            "tests/test_catraca_modulo_sem_chamador.py",     # construído, testado, nunca rodado (20/11/2026)
            # regras de qualidade (docs/REGRAS-DE-QUALIDADE.md) — `test_regra_registro` cobra que todas estejam aqui
            "tests/test_regra_registro.py", "tests/test_regra_catracas.py", "tests/test_regra_inventario.py",
            "tests/test_regra_motores.py", "tests/test_regra_controles_detector.py",
            "tests/test_regra_controles_sinteticos.py", "tests/test_regra_verificadores.py",
            "tests/test_regra_sensores.py", "tests/test_regra_juiz.py"]
# unidades do desktop gráfico da VM que falham sem efeito sobre o JFN — não são problema da casa
_SYSTEMD_RUIDO = {"xfce4-notifyd.service"}

logger = logging.getLogger(__name__)


def _p(area: str, chave: str, titulo: str, detalhe: str = "", remediar: str = "", acao_humana: str = "",
       ao_dono: str = "") -> dict:
    """`remediar` = comando SEGURO que o loop executa sozinho; `acao_humana` = o que só gente resolve;
    `ao_dono` = ⚖️/🔒 (jurídico-contábil / irreversível-voltado-para-fora): só com ✅ do dono, nunca automático."""
    return {"assinatura": f"{area}:{chave}", "area": area, "titulo": titulo, "detalhe": detalhe[:300],
            "remediar": "" if ao_dono else remediar, "acao_humana": acao_humana, "ao_dono": ao_dono}


# Diagnóstico medido (sonda de 24/10/2026), para a ação humana não ser genérica.
_ACAO_LOGIN = {"1": "SIAFE 1 (www5, 2016-2023): NullPointerException intermitente no RootMenuParser ao montar o menu. "
                    "Medido em 29/10/2026: depois dele, o re-login no MESMO contexto reabria a sessão quebrada "
                    "(login.jsp → errorDisplay), enquanto um contexto limpo recebia o formulário — desde então o "
                    "re-login limpa os cookies do www5. Se persistir com sessão nova: ler os `erros` por tentativa "
                    "no log do par antes de qualquer outra hipótese"}
_ACAO_CONFLITO = {"326100_2025": "recoleta limpa de 24/10 devolveu 0 em TODAS as fatias (UG+Número 2025OB*) para um "
                                  "par com 1.310 OBs na base, coletadas pelo mesmo caminho em 15/08; o login é o mesmo "
                                  "do dreno que funciona — depurar o filtro com print da tela"}
_ACAO_SENHA = ("o SIAFE recusou a senha (sonda de 30/10/2026: 'Usuário e/ou senha incorretos'; ou senha expirada). "
               "Conferir/trocar a senha no SIAFE e atualizar SIAFE_PASS no ~/JFN/.env — dreno e diário voltam sozinhos")
_DIARIO_SIAFE = "PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_runner diario >> data/siafe_runner_cron.log 2>&1"
# MFA sem resposta (laudo 13/11/2026): rodar o diário de madrugada pede código a quem dorme. A retentativa diurna
# só dispara entre 8h e 21h, se o dia ainda não teve coleta, e avisa o dono 10 min antes.
_RETENTAR_SIAFE = "PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_runner retentar 10 >> data/siafe_runner_cron.log 2>&1"


# ─────────────────────────── sensores (cada um devolve a lista de problemas AGORA) ───────────────────────────

def sensor_slo() -> list[dict]:
    sys.path.insert(0, str(_REPO))
    from tools.pipelines_slo import checar
    import yaml
    cfg = {c["nome"]: c for c in yaml.safe_load((_REPO / "config" / "pipelines.yaml").read_text())["pipelines"]}
    return [_p("slo", it["nome"], f"rotina {it['nome']} {it['status']}",
               f"idade {it['idade_h']} h · SLO {it['slo_h']} h",
               remediar=cfg.get(it["nome"], {}).get("remediar", ""),
               acao_humana=cfg.get(it["nome"], {}).get("acao_humana", ""))
            for it in checar() if it["status"] in ("stale", "ausente")]


def sensor_ci() -> list[dict]:
    br = subprocess.run(["git", "branch", "--show-current"], cwd=_REPO, capture_output=True, text=True,
                        timeout=20).stdout.strip()
    # CI DESLIGADO pelo dono em 15/11/2026 (e-mails): a última execução é de antes e ficaria "vermelha" para sempre.
    # Execução de commit que não é mais o HEAD do remoto não diz nada do código de hoje → só vale a do HEAD.
    head = subprocess.run(["git", "rev-parse", f"origin/{br}"], cwd=_REPO, capture_output=True, text=True,
                          timeout=20).stdout.strip()
    r = subprocess.run(["gh", "run", "list", "-b", br, "-L", "8", "--json", "conclusion,status,headSha,name"],
                       cwd=_REPO, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"gh run list: {(r.stderr or r.stdout).strip()[:120]}")
    runs = [x for x in json.loads(r.stdout or "[]") if x.get("status") == "completed"
            and x.get("conclusion") not in ("skipped", "cancelled")]
    if runs and head and runs[0]["headSha"] != head:
        return []
    if runs and runs[0]["conclusion"] != "success":
        return [_p("ci", br, f"CI vermelho em {br}", f"commit {runs[0]['headSha'][:8]} · {runs[0]['name'][:60]}",
                   acao_humana="conserto de código: `gh run view <id> --log-failed` diz o teste/lint que quebrou")]
    return []


def sensor_catracas() -> list[dict]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *CATRACAS],
                       cwd=_REPO, capture_output=True, text=True, timeout=600)
    falhas = [ln.split(" ", 1)[1].split(" - ")[0] for ln in r.stdout.splitlines() if ln.startswith("FAILED ")]
    if r.returncode not in (0, 1):
        raise RuntimeError(f"pytest rc={r.returncode}: {r.stdout[-160:]}")
    return [_p("catraca", f, f"catraca vermelha: {f.split('::')[-1]}", f,
               acao_humana="conserto de código: a mensagem da catraca diz o que cresceu e onde") for f in falhas]


def _env_sessao() -> dict:
    """O cron não tem o barramento da sessão: sem XDG_RUNTIME_DIR, `systemctl --user` responde
    "Failed to connect to bus" e a saída vazia parecia "nenhum serviço em falha" (04/11/2026)."""
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    return env


def sensor_systemd() -> list[dict]:
    r = subprocess.run(["systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend"],
                       capture_output=True, text=True, timeout=30, env=_env_sessao())
    if r.returncode != 0:          # INDISPONÍVEL ≠ 0: o sentir() registra o sensor como cego
        raise RuntimeError(f"systemctl rc={r.returncode}: {(r.stderr or '').strip()[:160]}")
    unid = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
    out = []
    for u in unid:
        if u in _SYSTEMD_RUIDO:
            continue
        erro = _ultimo_erro(u)
        externa = next((a for chave, a in _CAUSA_EXTERNA.items() if chave in erro), "")
        # causa EXTERNA conhecida: reiniciar não cura e cada falha re-dispara o OnFailure no Telegram do dono
        out.append(_p("systemd", u, f"serviço {u} em falha", erro,
                      remediar="" if externa else f"systemctl --user restart {u}", acao_humana=externa))
    return out


# erro do journal → decisão que só o dono toma (medido; nada aqui é palpite)
_CAUSA_EXTERNA = {"recusou o IP": "a SEFAZ recusa o IP da VM (AS31898 Oracle) no TFE. WARP reinstalado em 29/10/2026 "
                                  "(jfn-warp.service, SOCKS5 127.0.0.1:25344) e MEDIDO: o egress da Cloudflare "
                                  "(104.28.198.103) também é recusado. Restam: chamado na OuvERJ ou um exit node "
                                  "residencial no Tailscale. Não é crítico: OB = SIAFE; o TFE é espelho"}


def _ultimo_erro(unidade: str) -> str:
    """A CAUSA no próprio item ("TFE recusou o IP…"), não só "em falha" — quem lê o /melhorias decide sem abrir o journal."""
    try:
        j = subprocess.run(["journalctl", "--user", "-u", unidade, "-n", "40", "--no-pager", "-o", "cat"],
                           capture_output=True, text=True, timeout=20, env=_env_sessao()).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    erros = [ln.strip() for ln in j if re.match(r"^\s*[\w.]*(Error|Exception)\b", ln.strip())]
    return erros[-1][:200] if erros else ""


def sensor_ronda() -> list[dict]:
    d = json.loads((DATA / "ronda_state.json").read_text(encoding="utf-8"))
    out = []
    if not d.get("ativo", True):
        out.append(_p("ronda", "servico", "jfn.service fora do ar (ronda)"))
    if not d.get("api_ok", True):
        out.append(_p("ronda", "api", "API do JFN sem resposta (ronda)", f"falhas seguidas: {d.get('api_fails')}"))
    if not d.get("llm_ok", True):
        out.append(_p("ronda", "llm", "LLM do JFN sem resposta (ronda)"))
    return out


def _exercicios_perfil_restrito() -> dict[int, str]:
    """Exercícios do SIAFE 1 em que a conta só enxerga a PRÓPRIA UG (a base tem 1 UG só). Mesma regra do dreno."""
    import sqlite3
    con = sqlite3.connect(f"file:{DATA / 'compliance.db'}?mode=ro", uri=True)
    try:
        return dict(con.execute("SELECT exercicio, MIN(ug_emitente) FROM ob_orcamentaria_siafe WHERE exercicio <= 2023 "
                                "GROUP BY exercicio HAVING COUNT(DISTINCT ug_emitente) = 1").fetchall())
    finally:
        con.close()


def sensor_siafe() -> list[dict]:
    out = []
    ult = json.loads((DATA / "sei_cache" / "siafe_runner_ultimo.json").read_text(encoding="utf-8"))
    if not ult.get("ok"):
        # senha recusada: rodar o diário de novo é mais um login errado (o caminho do bloqueio da conta)
        c2 = DATA / ".siafe_dreno_credencial_2"      # o diário é SIAFE 2; o carimbo vale até o .env mudar
        cred = ult.get("erro") in ("senha_incorreta", "senha_expirada") or (
            c2.exists() and c2.stat().st_mtime > (DATA.parent / ".env").stat().st_mtime)
        out.append(_p("siafe", "diario", "coleta diária do SIAFE falhou",
                      f"{ult.get('erro')} — {ult.get('detail', '')}",
                      remediar="" if cred else (_RETENTAR_SIAFE if str(ult.get("erro") or "").startswith("mfa_")
                                                else _DIARIO_SIAFE),
                      acao_humana=_ACAO_SENHA if cred else ""))
    for sis in ("1", "2"):
        c = DATA / f".siafe_dreno_credencial_{sis}"           # carimbado pelo dreno; o .env novo destrava
        if c.exists() and c.stat().st_mtime > (DATA.parent / ".env").stat().st_mtime:
            out.append(_p("siafe", f"credencial_{sis}", f"SIAFE {sis} recusou a senha (dreno parado)",
                          acao_humana=_ACAO_SENHA))
        av, ok = DATA / f".siafe_dreno_aviso_login_{sis}", DATA / f".siafe_dreno_login_ok_{sis}"
        # um login que deu certo DEPOIS do disjuntor cura (28/10/2026: soluço às 13:36 seguia "quebrado" por 24 h)
        if av.exists() and time.time() - av.stat().st_mtime < 86400 and not (
                ok.exists() and ok.stat().st_mtime > av.stat().st_mtime):
            out.append(_p("siafe", f"login_sistema_{sis}", f"login do SIAFE {sis} quebrado (disjuntor do dreno)",
                          acao_humana=_ACAO_LOGIN.get(sis, "investigar o login com sonda que lê a tela sem clicar "
                                                                  "em popup; nunca culpar WAF")))
    q = DATA / "siafe_dreno_quarentena.json"
    if q.exists():
        restritos = _exercicios_perfil_restrito()
        for par, e in json.loads(q.read_text(encoding="utf-8")).items():
            ug, _, ano = par.partition("_")
            if ano.isdigit() and int(ano) in restritos and ug != restritos[int(ano)]:
                continue      # não é conflito de coleta: o exercício só expõe a UG da própria conta (dreno já pula)
            if e.get("n", 0) >= 99:
                out.append(_p("siafe", f"conflito_{par}", f"dreno: conflito checkpoint × medidor em {par}",
                              e.get("motivo", ""), acao_humana=_ACAO_CONFLITO.get(
                                  par, "conferir checkpoint uggrande_* contra o medidor")))
    return out


def sensor_yoda() -> list[dict]:
    """Só o que pede ação: reincidência de conserto, ou falha aberta vista nos últimos 7 dias."""
    f = DATA / "yoda_melhorias_fila.json"
    if not f.exists():
        return []
    out, recente = [], time.time() - 7 * 86400
    for sig, it in json.loads(f.read_text(encoding="utf-8")).items():
        if it.get("status") == "REINCIDIU" or (it.get("status") == "aberto" and it.get("ultimo_ts", 0) > recente):
            out.append(_p("yoda", sig, f"Yoda: {it['tipo']} — “{it['exemplo']['pedido'][:60]}”",
                          f"{it['n']}× · último {it['ultimo']}",
                          acao_humana="consertar e marcar com yoda_autoauditoria --resolver … --licao … "
                                      "(a lição entra na memória do Yoda)"))
    return out


def sensor_rem() -> list[dict]:
    """Sono REM do Hermes (jfn-metacognicao, 06:50): cada passo que degradou (`*_erro`) é um problema."""
    f = DATA / "hermes_metacognicao_ultimo.json"
    if not f.exists():
        return []          # a rodada que não acontece é pega pelo SLO `hermes-sono-rem`
    res = json.loads(f.read_text(encoding="utf-8"))
    return [_p("rem", k, f"sono REM do Hermes: passo {k.removesuffix('_erro')} degradado", str(v),
               acao_humana="ver `journalctl --user -u jfn-metacognicao` — o passo caiu, os outros seguiram")
            for k, v in res.items() if k.endswith("_erro")]


def sensor_dados_siafe() -> list[dict]:
    """Qualidade do DADO: dia do SIAFE parado no platô do teto (975–999 OBs) ainda não verificado. O remédio
    recoleta com o verificador corrigido e marca o dia como verificado (tools/siafe_recoletar_dias.py)."""
    from tools.siafe_recoletar_dias import lacunas_tfe, suspeitos
    out = []
    sus = suspeitos()
    if sus:
        out.append(_p("dados", "siafe_dias_no_plato", f"{len(sus)} dia(s) do SIAFE parados no platô do teto",
                      ", ".join(f"{d}={n}" for d, n in sus[:6]),
                      remediar="PYTHONPATH=. .venv/bin/python tools/siafe_recoletar_dias.py --auto --max 3 "
                               ">> data/siafe_recoletar_dias.log 2>&1"))
    # O espelho TFE como gabarito (dono, 30/10/2026): dia em que ele publica OB que o SIAFE não tem é dia a recolher.
    lac = lacunas_tfe()
    if lac:
        out.append(_p("dados", "siafe_lacunas_tfe",
                      f"{len(lac)} dia(s) com OB no espelho TFE e fora do SIAFE ({sum(n for _, n in lac):,} OBs)".replace(",", "."),
                      ", ".join(f"{d}={n}" for d, n in lac[:6]),
                      remediar="PYTHONPATH=. .venv/bin/python tools/siafe_recoletar_dias.py --tfe --auto --max 3 "
                               ">> data/siafe_recoletar_dias.log 2>&1"))
    return out


def sensor_vm() -> list[dict]:
    """A VM (2 vCPU, 11,6 GB) é o teto de tudo: disco cheio derruba SQLite/WAL; memória baixa derruba browser."""
    import shutil
    out = []
    du = shutil.disk_usage("/")
    pct = 100 * du.used / du.total
    if pct >= 90:
        out.append(_p("vm", "disco", f"disco em {pct:.0f}% ({du.free / 2**30:.0f} GB livres)",
                      acao_humana="maiores: ~/JFN/data/sei_cache (26 GB), ~/.npm (14 GB, cache regenerável), "
                                  "~/.cache (9 GB — NÃO apagar ms-playwright nem uv). "
                                  "Apagar só com ordem do dono"))
    mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in Path("/proc/meminfo").read_text().splitlines()[:5]}
    if mem.get("MemAvailable", 10**9) < 700 * 1024:
        out.append(_p("vm", "memoria", f"memória disponível baixa ({mem['MemAvailable'] // 1024} MB)",
                      acao_humana="ver quem está pesado (`ps aux --sort=-rss | head`); 1 pesado por vez"))
    return out


def sensor_polimonitor() -> list[dict]:
    """Polimonitor/Bond (pm2): processo fora de `online` vira problema; o remédio é `pm2 restart`."""
    # caminho ABSOLUTO: o cron não tem ~/.npm-global/bin no PATH — a 1ª rodada do cron deixou o sensor cego
    pm2 = shutil.which("pm2") or str(Path.home() / ".npm-global" / "bin" / "pm2")
    r = subprocess.run([pm2, "jlist"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"pm2 jlist rc={r.returncode}")
    out = []
    # após `npm i -g pm2` sem `pm2 update`, o jlist imprime o aviso de versão ANTES do JSON (30/10/2026)
    texto = r.stdout or "[]"
    for proc in json.loads(texto[texto.find("\n[") + 1:] if not texto.lstrip().startswith("[") else texto):
        st = proc.get("pm2_env", {}).get("status")
        if st != "online":
            out.append(_p("polimonitor", proc["name"], f"processo pm2 {proc['name']} {st}",
                          f"reinícios: {proc.get('pm2_env', {}).get('restart_time')}",
                          remediar=f"{pm2} restart {proc['name']}"))
    return out


_PAINEL = ("lista", "siafe/stats", "fontes/frescor")      # rotas que o dono e o Yoda usam


def sensor_painel() -> list[dict]:
    """Painel/API do JFN: rota fora do ar (≠200) ou lenta (> 8 s, cache frio) vira problema. Lento tem remédio
    (o pré-aquecimento do cron); fora do ar é humano (a ronda já religa o serviço quando ele cai)."""
    import urllib.error
    import urllib.request
    out = []
    for rota in _PAINEL:
        t0 = time.time()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:8000/api/{rota}", timeout=20) as resp:
                cod = resp.status
        except urllib.error.HTTPError as exc:
            cod = exc.code
        except (urllib.error.URLError, TimeoutError) as exc:
            # tempo esgotado é CACHE FRIO, não rota quebrada: medido 24/10 logo após reiniciar o jfn.service,
            # /fontes/frescor levou 46 s frio (carga 6,4) e 0,006 s em seguida. O remédio é o pré-aquecimento.
            # Conexão recusada NÃO é cache frio: é a API fora do ar.
            frio = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
            cod = 200 if frio else f"fora do ar ({type(getattr(exc, 'reason', exc)).__name__})"
        dt = time.time() - t0
        if cod != 200:
            out.append(_p("painel", rota, f"rota /api/{rota} respondeu {cod}",
                          acao_humana="ver `journalctl --user -u jfn` — a rota quebrou, não é lentidão"))
        elif dt > 8:
            out.append(_p("painel", f"lento_{rota}", f"rota /api/{rota} lenta ({dt:.1f} s)",
                          remediar="bash tools/prewarm_painel.sh"))
    return out


# FILAS DE FEEDBACK: canal que só ACUMULA é produtor sem consumidor. Medido em 28/10/2026: `lex_feedback` tinha
# 3.068 dificuldades abertas, 0 resolvidas desde 18/06 (~500/mês) — e a nota regerada dele no vault ainda
# poluía o RAG. O sensor não julga cada item; acusa a FILA que cresce sem ninguém fechar.
_FILAS = [("lex_feedback", "dificuldades do Lex/JFN", "SELECT COUNT(*) FROM lex_feedback WHERE resolvido = 0",
           "SELECT COUNT(*) FROM lex_feedback WHERE resolvido = 1 AND resolvido_em >= ?",
           "triar por `contexto` (670 são do loop de perícia SEI): fechar em lote o que já foi resolvido ou é "
           "ruído, e dar um consumidor ao resto — `UPDATE lex_feedback SET resolvido=1, resolvido_em=…`")]
FILA_MIN_ABERTOS = 100


def sensor_filas(db: Path | None = None, agora: float | None = None) -> list[dict]:
    import sqlite3
    db = db or DATA / "compliance.db"
    desde = datetime.fromtimestamp((agora or time.time()) - 30 * 86400).isoformat(timespec="seconds")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = []
    try:
        for tabela, nome, q_abertos, q_resolvidos, acao in _FILAS:
            abertos = con.execute(q_abertos).fetchone()[0]
            resolvidos = con.execute(q_resolvidos, (desde,)).fetchone()[0]
            if abertos >= FILA_MIN_ABERTOS and resolvidos == 0:
                out.append(_p("filas", tabela, f"fila sem consumidor: {nome}",
                              f"{abertos} aberto(s), 0 resolvido(s) em 30 dias", acao_humana=acao))
    finally:
        con.close()
    return out


# PARECER QUE OSCILA (dono, 30/10/2026: "comparando com os pareceres anteriores… aprendizado contínuo"). O
# histórico do 360 (`processo_avaliacao_hist`) guarda o que cada reavaliação pôs e tirou. Achado que ENTRA, SAI e
# VOLTA no mesmo processo é leitura instável — o detector depende de algo que muda entre rodadas (ordem da árvore,
# teto de texto, captura parcial) — e cada oscilação é um parecer que disse coisas diferentes sobre os mesmos autos.
OSCILA_MIN_PROCESSOS = 3


def sensor_pareceres(db: Path | None = None) -> list[dict]:
    import sqlite3
    db = db or DATA / "compliance.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT numero_sei, entraram_json, sairam_json FROM processo_avaliacao_hist "
                           "WHERE avaliado_em >= datetime('now', '-30 days') ORDER BY numero_sei, avaliado_em").fetchall()
    except sqlite3.OperationalError:
        return []                     # histórico ainda não criado: nada a comparar
    finally:
        con.close()
    saiu: set[tuple[str, str]] = set()
    oscilou: dict[str, set[str]] = {}
    for num, ent, sai in rows:
        for chave in json.loads(sai or "[]"):
            saiu.add((num, chave))
        for chave in json.loads(ent or "[]"):
            if (num, chave) in saiu:               # já tinha saído deste processo e voltou
                oscilou.setdefault(chave.split("|")[0], set()).add(num)
    return [_p("pareceres", f"oscila_{cod}", f"achado {cod} oscila entre reavaliações ({len(ps)} processos)",
               ", ".join(sorted(ps)[:5]),
               acao_humana="abrir 2 processos da lista, comparar as duas leituras e achar o que muda entre "
                           "rodadas (ordem da árvore, teto de texto, captura) — consertar o detector, com teste")
            for cod, ps in sorted(oscilou.items()) if len(ps) >= OSCILA_MIN_PROCESSOS]


_HERMES = Path.home() / ".hermes"
_STT_PY = Path.home() / "stt-venv" / "bin" / "python"
_ACAO_VOZ = ("STT do Yoda roda FORA do venv do Hermes (hermes update apagou o faster-whisper em 06/11/2026): "
             "~/stt-venv + ~/stt-venv/hermes_stt.py, ligado por HERMES_LOCAL_STT_COMMAND no ~/.hermes/.env. "
             "Recriar: uv venv --python 3.12 ~/stt-venv && VIRTUAL_ENV=~/stt-venv uv pip install faster-whisper 'av<14'")


def sensor_voz(hermes: Path = _HERMES, stt_py: Path = _STT_PY, agora: float | None = None) -> list[dict]:
    """Voz do Yoda: configuração presente, ambiente presente e nenhuma falha de transcrição nas últimas 24 h."""
    out = []
    if not stt_py.exists():
        out.append(_p("voz", "stt-venv", "Yoda: ambiente de transcrição de voz sumiu", str(stt_py), acao_humana=_ACAO_VOZ))
    env = (hermes / ".env").read_text(encoding="utf-8")
    if not re.search(r"^HERMES_LOCAL_STT_COMMAND=\S", env, re.M):
        out.append(_p("voz", "config", "Yoda: HERMES_LOCAL_STT_COMMAND sumiu do .env", acao_humana=_ACAO_VOZ))
    limite = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((agora or time.time()) - 86400))
    log = hermes / "logs" / "agent.log"
    falhas = [ln for ln in (log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else [])
              if "Voice transcription failed" in ln and ln[:19] >= limite]
    if falhas:
        out.append(_p("voz", "falhou", f"Yoda não transcreveu {len(falhas)} áudio(s) nas últimas 24 h",
                      falhas[-1][:300], acao_humana=_ACAO_VOZ))
    return out


def sensor_qualidade() -> list[dict]:
    """Regras de qualidade (docs/REGRAS-DE-QUALIDADE.md) sobre o DADO SERVIDO: proveniência e variação das
    manchetes, constância entre superfícies, casos do vault, respostas do Yoda, motores sem efeito, juiz subjetivo.
    Um item por (regra, sistema) — o detalhe fica em data/qualidade_estado.json e no painel de conformidade.
    Sensor de qualidade cego vira `sensor:qualidade.<nome>` (INDISPONÍVEL ≠ 0)."""
    from compliance_agent.qualidade import sensores as _q
    return [_p(i["area"], i["chave"], i["titulo"], i["detalhe"], acao_humana=i["acao_humana"])
            for i in _q.para_automelhoria(_q.rodar())]


def sensor_autoaprimoramento(pasta: Path | None = None, db: Path | None = None, agora: float | None = None) -> list[dict]:
    """Autoaprimoramento da perícia (docs/AUTOAPRIMORAMENTO-JFN.md): prova primária regravada por juízo mais fraco,
    kill switch ligado e ledger parado. Sem ledger ainda = nada a medir (o ciclo nunca rodou), não é problema."""
    import sqlite3
    from compliance_agent.autoaprimoramento import monitor
    try:
        s = monitor.saude(pasta or DATA / "autoaprimoramento", db or DATA / "compliance.db")
    except sqlite3.Error as e:                     # `sentir` transforma em `sensor:autoaprimoramento` (cego ≠ ok)
        raise RuntimeError(f"ledger ilegível: {type(e).__name__}: {e}") from e
    if s is None:
        return []
    out = []
    if s["kill"] is not None:
        out.append(_p("autoaprimoramento", "kill", "kill switch do autoaprimoramento ligado", s["kill"],
                      acao_humana="ler o motivo; resolvido, apagar data/autoaprimoramento/KILL"))
    perdidos, novos, ultimo = s["fonte_perdida"], s["fora_do_ledger"], s["ultimo"]
    if perdidos:
        out.append(_p("autoaprimoramento", "fonte_perdida",
                      f"{len(perdidos)} laudo(s) conferido(s) na fonte primária regravado(s) por juízo mais fraco",
                      ", ".join(perdidos[:6]),
                      acao_humana="o laudo da fonte está no ledger (data/autoaprimoramento/auto.db, laudo_versao "
                                  "nivel_prova=2): reaplicar com tools.lex_execucao.aplicar_conferencia depois de "
                                  "conferir que a captura não mudou"))
    if novos:
        out.append(_p("autoaprimoramento", "ledger_parado",
                      f"{novos} conferência(s) na fonte primária fora do ledger (último registro {ultimo})",
                      acao_humana="rodar o ciclo REAL (o ensaio grava numa cópia e não cura este alerta): "
                                  "`JFN_AUTOAPRIMORAMENTO=1 python -m compliance_agent.autoaprimoramento ciclo` "
                                  "(sem LLM, ~30 s) e ler data/autoaprimoramento/relatorio.md"))
    return out


def sensor_propagacao(estado: dict | None = None) -> list[dict]:
    """Grafo de propagação (24/11/2026): UM item por derivado sujo além do SLO (`propagacao.slo_s`) e um se o
    despachante parou. Lê `propagacao.estado()` direto — o grafo da certeza só via o atraso quando o PRÓPRIO
    derivado `certeza` rodava, e ele estava 27 h atrasado. Base ausente (`ok: False`) = nada a medir aqui."""
    if estado is None:
        sys.path.insert(0, str(_REPO))
        from compliance_agent import propagacao
        estado = propagacao.estado()
    if not estado.get("ok"):
        return []
    out = []
    if estado.get("estado") == "PARADO":
        out.append(_p("propagacao", "parado", "despachante de propagação parado (último ciclo há mais de 20 min)",
                      acao_humana="ver `crontab -l | grep propagacao` e data/propagacao_cron.log"))
    for a in estado.get("atrasados") or []:
        out.append(_p("propagacao", f"atrasado:{a['id']}", f"derivado {a['id']} atrasado: sujo há {a['sujo_ha_h']} h "
                      f"(SLO {a['slo_h']} h)", f"{a['nome']} · peso {a['peso']} · adiado: {a.get('adiado') or '—'}",
                      acao_humana="Sistema › Propagação: o motivo do adiamento diz quem segura (semáforo, carga, "
                                  "dependência, recuo)"))
    return out


def sensor_deploy(arq: Path | None = None) -> list[dict]:
    """Deploy pós-commit (tools/deploy_pos_commit.sh, 24/11/2026): o último restart do jfn.service deixou o painel
    sem 200? O script não reverte nem tenta de novo — avisa aqui. Arquivo ausente = nenhum deploy ainda."""
    arq = arq or DATA / "deploy_estado.json"
    if not arq.exists():
        return []
    d = json.loads(arq.read_text(encoding="utf-8"))
    if d.get("ok"):
        return []
    return [_p("deploy", "falhou", f"deploy do commit {d.get('commit')} falhou: {d.get('motivo')}",
               f"base {d.get('base')} · data/deploy_pos_commit.log",
               acao_humana="journalctl --user -u jfn -n 80; corrigir e commitar (o gancho reinicia de novo) "
                           "ou reverter o commit")]


def sensor_certeza(pasta: Path | None = None, agora: float | None = None) -> list[dict]:
    """Certeza (docs/ARQUITETURA-DE-CERTEZA.md): número divergente entre registro de fatos, vault, documentos e
    cérebro; violação de contrato de dados; nível de prova que regrediu; escrita recusada pelo portão; defeito grave
    do grafo de propagação. Lê a fotografia do último ciclo (data/certeza/estado.json) — não recalcula nada.
    Pasta inexistente = o ciclo nunca rodou nesta máquina (nada a medir); fotografia velha ou ilegível É problema."""
    pasta = pasta or DATA / "certeza"
    if not pasta.exists():
        return []
    agora = agora or time.time()
    est = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))      # ausente/ilegível → `sensor:certeza`
    out = []
    if agora - est["gerado_em"] > 26 * 3600:
        out.append(_p("certeza", "parada", f"painel de certeza sem ciclo há {(agora - est['gerado_em']) / 3600:.0f} h",
                      acao_humana="ver o derivado `certeza` em Sistema › Propagação e data/propagacao_certeza.log"))
    por_tipo: dict[str, list] = {}
    for d in est.get("divergencias", []):
        por_tipo.setdefault(d["tipo"], []).append(d)
    for tipo, ds in sorted(por_tipo.items()):
        d0 = ds[0]
        out.append(_p("certeza", f"divergencia:{tipo}", f"{len(ds)} número(s) divergente(s) do registro de fatos ({tipo.replace('_', ' ')})",
                      "; ".join(f"{d['superficie']}: {d['local']} diz {d['encontrado']}, vigente {d['esperado']}" for d in ds[:3]),
                      acao_humana=f"corrigir o texto e citar o fato pelo id (`python -m compliance_agent.certeza fato {d0['fato_id']}`)"))
    for v in (est.get("contratos") or {}).get("violacoes", []):
        out.append(_p("certeza", f"contrato:{v['contrato']}:{v['regra'].split(' ')[0]}:{v['detalhe'][:40]}",
                      f"contrato de dados violado em {v['contrato']}: {v['detalhe']} ({v.get('n')} linha(s))",
                      "; ".join(map(str, v.get("exemplos", [])[:3])),
                      acao_humana="valor sem faixa plausível/proveniência: achar quem gravou (data/certeza/relatorio.md §3)"))
    reg = sum(f.get("regressoes_abertas", 0) for f in ((est.get("contratos") or {}).get("fotografia") or {}).values())
    if reg:
        out.append(_p("certeza", "regressao_de_prova", f"{reg} linha(s) de achado regrediram de nível de prova",
                      acao_humana="o conteúdo anterior está em data/certeza/certeza.db (tabela regressao): reaplicar depois de conferir"))
    r = est.get("resumo", {})
    if r.get("recusas_24h"):
        out.append(_p("certeza", "recusas", f"{r['recusas_24h']} escrita(s) de fato recusada(s) pelo portão em 24 h",
                      acao_humana="ler data/certeza/certeza.db (tabela recusa): produtor que tentou regredir prova ou gravar sem proveniência"))
    if r.get("risco_alto_verificado_sem_prova_primaria"):
        out.append(_p("certeza", "verificado_sem_prova", f"{r['risco_alto_verificado_sem_prova_primaria']} laudo(s) de risco alto "
                      "saem VERIFICADO sem prova primária", acao_humana="conferir compliance_agent/correlacao_sei.estado_do_laudo"))
    erros = ((est.get("ciclo") or {}).get("extracao") or {}).get("erros") or []
    if erros:
        out.append(_p("certeza", "extracao", f"{len(erros)} bloco(s) de fato sem extração (fonte ausente ou ilegível)",
                      "; ".join(f"{e['no']}: {e['erro']}" for e in erros[:3]), acao_humana="ver o derivado que publica o fato"))
    from compliance_agent.certeza.grafo import GRAVES
    for k in GRAVES:
        itens = ((est.get("grafo") or {}).get("achados") or {}).get(k) or []
        if itens:
            out.append(_p("certeza", f"grafo:{k}", f"grafo de propagação: {k.replace('_', ' ')} ({len(itens)})",
                          "; ".join(map(str, itens[:3])), acao_humana="config/propagacao.yaml — ver data/certeza/relatorio.md §4"))
    return out


# USO DAS MÁQUINAS (dono 19/11/2026: "vm1, vm2 e it campo sendo usados ao maximo"). Média de 15 min por núcleo; o
# it-campo pelo próprio estado (data/itcampo_estado.json, gravado pelo supervisor de lá). Ociosa = capacidade
# parada (mover trabalho para lá); sobrecarga = trabalho demais (tirar dali). Sem medida = INDISPONÍVEL, nunca "ok".
OCIOSA_POR_NUCLEO, SOBRECARGA_POR_NUCLEO = 0.5, 2.5


def _carga_vm2() -> tuple[float, int] | None:
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "vm2-ts",
                            "cat /proc/loadavg; nproc"], capture_output=True, text=True, timeout=25)
        ln = r.stdout.split()
        return float(ln[2]), int(ln[5])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _estado_itcampo(agora: float | None = None) -> dict | None:
    try:
        d = json.loads((_REPO / "data" / "itcampo_estado.json").read_text(encoding="utf-8"))
        idade = (agora or time.time()) - datetime.fromisoformat(d["t"]).timestamp()
        return None if idade > 3600 else d
    except (OSError, ValueError, KeyError):
        return None


# it-campo: "ociosa" só é problema quando HÁ trabalho que ela não está fazendo (dono, 20/11/2026: "tem que fazer disso
# um fluxo"). O laço fecha em três casos, decididos pela fila de OCR dos dois lados — a do trabalhador
# (`ocr_gpu.restantes`) e a que a VM-1 publica (`data/sei_ocr_gpu_fila.txt`, linhas e idade):
#   GPU parada · trabalhador sem fila · fila da VM-1 velha/ausente → REMÉDIO: regerar a fila (alimentar)
#   GPU parada · trabalhador sem fila · fila da VM-1 nova e vazia  → nada a fazer: não é problema, não vira item
#   GPU parada · há fila (no trabalhador, ou nova na VM-1 e ele não puxou) → trabalhador quebrado: ESCALA ao dono
FILA_OCR = _REPO / "data" / "sei_ocr_gpu_fila.txt"
FILA_OCR_VELHA_S = 3 * 3600
_ALIMENTAR_OCR = "PYTHONPATH=. .venv/bin/python -m tools.sei_ocr_gpu_fila >> data/sei_ocr_gpu_fila.log 2>&1"


def _fila_ocr(agora: float | None = None, arq: Path = FILA_OCR) -> tuple[int, float] | None:
    """(linhas, idade em s) da fila de OCR que a VM-1 publica; None = não existe."""
    try:
        linhas = sum(1 for ln in arq.read_text(encoding="utf-8").splitlines() if ln.strip())
        return linhas, (agora or time.time()) - arq.stat().st_mtime
    except OSError:
        return None


def _avaliar_itcampo(itc: dict, fila_ocr: tuple[int, float] | None | bool) -> list[dict]:
    """`fila_ocr=False` = fila não informada (comportamento antigo: ociosa vira item sem remédio)."""
    out = []
    maq = itc.get("maquina") or {}
    gpu, cpu = (maq.get("gpu") or {}).get("util_pct"), itc.get("cpu_pct")
    restantes = (maq.get("ocr_gpu") or {}).get("restantes")
    sabe = fila_ocr is not False and restantes is not None
    velha = fila_ocr is None or (fila_ocr is not False and fila_ocr[1] > FILA_OCR_VELHA_S)
    publicada = 0 if not fila_ocr else fila_ocr[0]
    ha_trabalho = None if not sabe else bool(restantes) or (publicada > 0 and not velha)
    if gpu is not None and gpu < 50:
        if not sabe:
            out.append(_p("maquinas", "itcampo:gpu_ociosa", f"it-campo: GPU em {gpu}% (OCR parado?)",
                          acao_humana="conferir a tarefa JFN-OCR-GPU e a fila de escaneados"))
        elif restantes:
            out.append(_p("maquinas", "itcampo:gpu_parada_com_fila", f"it-campo: GPU em {gpu}% com {restantes} "
                          "documento(s) na fila do trabalhador — trabalhador de OCR parado",
                          acao_humana="trabalhador quebrado (não é falta de fila): ver ~/jfn-gpu/ocr no it-campo "
                                      "(log do ocr_gpu_worker, vLLM no ar, memória do WSL)"))
        elif velha:
            idade = "ausente" if fila_ocr is None else f"de {fila_ocr[1] / 3600:.1f} h atrás"
            out.append(_p("maquinas", "itcampo:gpu_ociosa", f"it-campo: GPU em {gpu}% e fila de OCR vazia no "
                          f"trabalhador; a fila publicada pela VM-1 é {idade}",
                          remediar=_ALIMENTAR_OCR))
        elif publicada:
            out.append(_p("maquinas", "itcampo:gpu_fila_nao_puxada", f"it-campo: GPU em {gpu}% — a VM-1 publicou "
                          f"{publicada} documento(s) há {fila_ocr[1] / 60:.0f} min e o trabalhador segue com fila vazia",
                          acao_humana="o trabalhador não está puxando data/sei_ocr_gpu_fila.txt (evento "
                                      "fila_da_vm1 no log dele): conferir ssh it-campo→VM-1 e o código puxado (md5)"))
    if cpu is not None and cpu < 40 and (itc.get("win_disp_gb") or 0) > (itc.get("piso_gb") or 3) + 4 \
            and ha_trabalho is not False:
        out.append(_p("maquinas", "itcampo:cpu_ociosa", f"it-campo: CPU em {cpu}% com "
                      f"{itc.get('win_disp_gb')} GB livres", acao_humana="subir o alvo do pool nativo / mais detectores"))
    return out


def avaliar_maquinas(vm1: tuple[float, int] | None, vm2: tuple[float, int] | None, itc: dict | None,
                     fila_ocr: tuple[int, float] | None | bool = False) -> list[dict]:
    out = []
    for nome, med in (("vm1", vm1), ("vm2", vm2)):
        if med is None:
            out.append(_p("maquinas", f"{nome}:sem_medida", f"{nome.upper()}: uso não medido (INDISPONÍVEL)"))
            continue
        por = med[0] / max(med[1], 1)
        if por < OCIOSA_POR_NUCLEO:
            out.append(_p("maquinas", f"{nome}:ociosa", f"{nome.upper()} ociosa: carga 15 min {med[0]:.1f} em "
                          f"{med[1]} núcleos", acao_humana="mover fila pesada para lá (sweeps SEI, padrões, perícia)"))
        elif por > SOBRECARGA_POR_NUCLEO:
            out.append(_p("maquinas", f"{nome}:sobrecarga", f"{nome.upper()} sobrecarregada: carga 15 min "
                          f"{med[0]:.1f} em {med[1]} núcleos", acao_humana="tirar trabalho dali (it-campo tem 24 núcleos)"))
    if itc is None:
        out.append(_p("maquinas", "itcampo:sem_medida", "it-campo: estado ausente ou com mais de 1 h (INDISPONÍVEL)"))
    else:
        out += _avaliar_itcampo(itc, fila_ocr)
    return out


# it-campo OCIOSO POR MAIS DE 2 H (dono 21/11/2026 23h55: "mantenha it campo sempre sendo usado ao máximo"). O vigia
# (tools/itcampo_vigia.py, cron */15) grava uma leitura por passada e já dispara lote quando pode; se mesmo assim TODAS
# as leituras de 2 h acusam CPU sobrando, o remédio automático não alcança (memória, fila vazia) → item na fila, SEM
# remédio (só a fila; o dono não quer o Yoda falando sem pedido, 22/11/2026).
VIGIA_HIST = _REPO / "data" / "itcampo_vigia.jsonl"
ITCAMPO_OCIOSO_S, ITCAMPO_OCIOSO_PCT = 2 * 3600, 50.0


def avaliar_itcampo_ocioso(hist: list[dict], agora: float) -> list[dict]:
    def ts(m):
        return datetime.strptime(m["t"], "%Y-%m-%d %H:%M:%S").timestamp()

    def cpu(m):
        return m.get("win_cpu") if m.get("win_cpu") is not None else m.get("wsl_cpu")

    lidas = [m for m in hist if m.get("ok") and cpu(m) is not None and agora - ts(m) <= ITCAMPO_OCIOSO_S + 900]
    # precisa de 2 h COBERTAS (a mais velha da janela com ≥ 2 h) e de leitura recente (vigia vivo)
    if len(lidas) < 6 or agora - ts(lidas[0]) < ITCAMPO_OCIOSO_S or agora - ts(lidas[-1]) > 1800:
        return []
    if any(cpu(m) >= ITCAMPO_OCIOSO_PCT for m in lidas):
        return []
    mem = sum(1 for m in lidas if "memória" in (m.get("decisao") or ""))
    disparos = sum(1 for m in lidas if m.get("disparou"))
    media = sum(cpu(m) for m in lidas) / len(lidas)
    return [_p("maquinas", "itcampo:ocioso_2h", f"it-campo ocioso há > 2 h: CPU média {media:.0f}% em {len(lidas)} "
               f"leituras ({disparos} lote(s) disparado(s) pelo vigia)",
               f"decisões: {mem} por memória do WSL; última: {lidas[-1].get('decisao')}",
               acao_humana=("a memória do WSL é o teto — ver .wslconfig (ação do dono, reinício do WSL)" if mem * 2 >=
                            len(lidas) else "sem trabalho para a CPU: ver a fila do OCR e o tools/itcampo_vigia.py"))]


def sensor_maquinas() -> list[dict]:
    la = Path("/proc/loadavg").read_text().split()
    hist = []
    if VIGIA_HIST.exists():
        hist = [json.loads(ln) for ln in VIGIA_HIST.read_text(encoding="utf-8").splitlines()[-40:] if ln.strip()]
    return avaliar_maquinas((float(la[2]), os.cpu_count() or 1), _carga_vm2(), _estado_itcampo(), _fila_ocr()) \
        + avaliar_itcampo_ocioso(hist, time.time())


# PRECISÃO POR DETECTOR (19/11/2026, dono: "melhore todos os detectores… de forma sistemática e constante").
# A triagem já julgou milhares de alertas, mas ninguém lia os vereditos por detector: o D3 tinha 57% de falso
# positivo. Janela de 30 dias, para o conserto aparecer como CURA quando os vereditos novos melhorarem.
# O corte de SUSPENSÃO da triagem (FP ≥ 50%) e a amostra mínima moram em compliance_agent/triagem_alertas.py (um
# lugar só); aqui fica só o corte do AVISO (30%), que pede conserto antes de o detector chegar a ser suspenso.
FP_MAX = 0.30


def avaliar_precisao(linhas: list[tuple[str, int, int]]) -> list[dict]:
    from compliance_agent.triagem_alertas import FP_MIN_N, FP_SUSPENDE, suspenso
    out = []
    for tipo, n, fp in linhas:
        if n >= FP_MIN_N and fp / n >= FP_MAX:
            fora = suspenso(n, fp)
            out.append(_p("detector", f"fp:{tipo}", f"detector {tipo}: {100 * fp / n:.0f}% de provável falso "
                          f"positivo em {n} vereditos (30 dias)"
                          + (f" — SUSPENSO da triagem (≥ {FP_SUSPENDE:.0%}); alertas seguem gravados" if fora else ""),
                          acao_humana="abrir 5 falsos positivos (justificativa na alertas_triagem), achar a regra "
                                      "que dispara errado e corrigir no detector — não no prompt"))
    return out


def sensor_detectores(db: Path | None = None) -> list[dict]:
    import sqlite3

    from compliance_agent.triagem_alertas import precisao_por_detector
    con = sqlite3.connect(f"file:{db or _REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=60)
    try:
        linhas = precisao_por_detector(con)
    finally:
        con.close()
    return avaliar_precisao(linhas)


# INTEGRAÇÃO DE AGENTES (20/11/2026). Duas sobras da integração por patch, as duas com dano medido no mesmo dia:
# worktree esquecido (45 = 14 GB → disco a 100% → o binário do Claude Code sumiu e o juiz caiu) e remoção parada no
# índice (14 arquivos "apagados" que seguiram no repositório). O remédio do primeiro é seguro e automático: só sai
# worktree limpo, parado há 12 h, sem processo dentro e INTEGRADO (ponta ancestral do HEAD ou conteúdo já aplicado);
# a branch fica. Decisão 6 do dono (20/11/2026): integrado sai sempre, sem esperar o disco apertar — guardar worktree
# integrado não protege nada. O segundo é do dono (commitar ou devolver).
WORKTREES_MAX = 10
_LIMPAR_WORKTREES = ("PYTHONPATH=. .venv/bin/python -m tools.integracao_conferir worktrees --aplicar --horas 12 "
                     ">> data/integracao_conferir.log 2>&1")


def avaliar_integracao(lista: list[dict], em_stage: list[str], disco_pct: float) -> list[dict]:
    out = []
    saem = [w for w in lista if w["pode_sair"]]
    if saem:
        out.append(_p("integracao", "worktrees", f"{len(lista)} worktree(s) de agente no disco ({disco_pct:.0f}% "
                      f"cheio); {len(saem)} limpo(s), parado(s) e já integrado(s) podem sair",
                      "; ".join(Path(w["caminho"]).name for w in saem[:6]), remediar=_LIMPAR_WORKTREES))
    elif len(lista) >= WORKTREES_MAX:
        out.append(_p("integracao", "worktrees_presos", f"{len(lista)} worktree(s) de agente e nenhum pode sair "
                      "sozinho (sujo, recente, em uso ou com trabalho fora do HEAD)",
                      "; ".join(f"{Path(w['caminho']).name} (sujo {w['sujo']}, parado {w['parado_h']} h, "
                                f"{'integrado' if w.get('integrado') else 'não integrado'})" for w in lista[:6]),
                      acao_humana="integrar ou descartar o que está fora de commit e remover: "
                                  "`python -m tools.integracao_conferir worktrees`"))
    if em_stage:
        out.append(_p("integracao", "remocao_em_stage", f"{len(em_stage)} remoção(ões) parada(s) no índice do git "
                      "(apagado no patch, nunca commitado)", "; ".join(em_stage[:6]),
                      acao_humana="commitar a remoção pela lista do diff (`git commit -- <caminhos>`) ou devolver "
                                  "(`git restore --staged`); conferir com `python -m tools.integracao_conferir stage`"))
    return out


def sensor_integracao() -> list[dict]:
    import shutil
    from tools import integracao_conferir as I
    du = shutil.disk_usage("/")
    return avaliar_integracao(I.worktrees(horas=12), I.remocoes_em_stage(), 100 * du.used / du.total)


# MODELOS GRÁTIS E FRACOS (dono 22/11/2026: "faça a automelhoria atuar também nos modelos grátis e mais fracos que o
# Opus"). Divergência do Opus por modelo × tarefa, disponibilidade (404, cota, janela) e candidatos do catálogo vivo;
# o remédio seguro (rebaixar/tirar na cadeia, `llm/cascata_ajuste`) e o banco de casos negativos moram em
# `tools/automelhoria_modelos.py`. Banco travado/ilegível vira `sensor:modelos` (cego ≠ ok), nunca derruba a rodada.
def sensor_modelos() -> list[dict]:
    import sqlite3
    from tools import automelhoria_modelos
    try:
        return automelhoria_modelos.sensor()
    except sqlite3.Error as e:
        raise RuntimeError(f"banco: {e}") from e


# ─── PLATAFORMA (dono, 23/11/2026: "essas ideias do gemini e chatgpt eram pra automelhoria sempre ir fazendo e
# acusando"). Cada achado da avaliação dos planos externos (docs/PLANO-PLATAFORMA-EVIDENCIAS.md) vira vigília:
# o problema fica aberto até a fase que o resolve entregar, e REINCIDE se voltar.
PLAT_COBERTURA_MIN = 0.95       # fração dos caracteres do acervo que a perícia integral alcança
PLAT_DISCO_MAX = 85.0
PLAT_RECAPTURA_MAX = 0.10       # fração do TEMPO de captura gasta recapturando árvore igual
PLAT_CACHE_MIN = 0.30           # cache lido ÷ (lido + escrito) do Opus pela assinatura
RODADAS_ITCAMPO = DATA / "itcampo_rodadas.jsonl"


def avaliar_cobertura_leitura(total: int, alcancavel: int, procs: int, procs_cortados: int) -> list[dict]:
    if total <= 0 or alcancavel / total >= PLAT_COBERTURA_MIN:
        return []
    frac = f"{100 * alcancavel / total:.1f}".replace(".", ",")
    return [_p("plataforma", "cobertura_leitura", f"a perícia integral alcança só {frac}% do texto do acervo",
               f"{procs_cortados} de {procs} processos com texto passam do teto (240k no total, 12k por peça); "
               "o corte por peça não é declarado no laudo",
               acao_humana="Fase 4 do docs/PLANO-PLATAFORMA-EVIDENCIAS.md: leitura integral em fatias com "
                           "citação verificada e cobertura gravada por laudo")]


def avaliar_disco(maquina: str, pct: float) -> list[dict]:
    if pct < PLAT_DISCO_MAX:
        return []
    return [_p("plataforma", f"disco_{maquina}", f"disco da {maquina} em {pct:.0f}%",
               "acima de 85% o frio para de receber e a VM-1 enche atrás (23/11: VM-2 96% travou o frio)",
               acao_humana="mover re-obtível para o HD externo do it-campo pela porta única (Fase 0a do plano)")]


def avaliar_vazao_fila(nome: str, entrada_7d: int, saida_7d: int, pendentes: int) -> list[dict]:
    if pendentes < 100 or entrada_7d <= 1.2 * saida_7d:
        return []
    return [_p("plataforma", f"vazao_{nome}", f"fila {nome} cresce mais do que esvazia",
               f"7 dias: entraram {entrada_7d}, saíram {saida_7d}; {pendentes} pendentes — nunca zera",
               acao_humana="Fase 5 do plano: a fila entra por risco + amostra estratificada, não por falta de cota")]


def fracao_recaptura_igual(rodadas: list[dict]) -> tuple[float, int]:
    """Fração do tempo de captura gasta em recaptura com a MESMA árvore da captura anterior do processo."""
    ultima: dict[str, int] = {}
    total = igual = 0.0
    n = 0
    for r in sorted(rodadas, key=lambda r: r.get("ts", "")):
        for proc, d in (r.get("procs") or {}).items():
            if d.get("status") != "ok":
                continue
            seg = float(d.get("segundos") or 0)
            total += seg
            arv = d.get("arvore")
            if arv is not None and ultima.get(proc) == arv:
                igual += seg
                n += 1
            if arv is not None:
                ultima[proc] = arv
    return (igual / total if total else 0.0), n


def avaliar_recaptura(frac: float, n: int) -> list[dict]:
    if frac < PLAT_RECAPTURA_MAX:
        return []
    return [_p("plataforma", "recaptura_igual",
               f"{100 * frac:.0f}% do tempo de captura é recaptura sem documento novo",
               f"{n} recapturas com a mesma árvore da captura anterior (7 dias, it-campo)",
               acao_humana="Fases 0e/2 do plano: guarda de convergência (árvore+motivo) e captura por delta")]


def avaliar_cache_opus(cache_escrito: int, cache_lido: int, chamadas: int) -> list[dict]:
    if chamadas < 10 or cache_escrito + cache_lido == 0:
        return []
    frac = cache_lido / (cache_lido + cache_escrito)
    if frac >= PLAT_CACHE_MIN:
        return []
    return [_p("plataforma", "cache_opus", f"Opus reaproveita só {100 * frac:.0f}% do prompt em cache",
               f"{chamadas} chamadas em 7 dias: {cache_escrito} tokens escritos no cache, {cache_lido} lidos — "
               "a parte variável vem antes da fixa",
               acao_humana="Fase 4 do plano: instruções e schema fixos ANTES da entrada em todos os prompts")]


def _cobertura_acervo() -> tuple[int, int, int, int]:
    from compliance_agent.pericia_integral import TETO_DOC, TETO_TEXTO
    total = alc = procs = cortados = 0
    for m in (DATA / "sei_arquivo").glob("*/manifest.json"):
        try:
            cs = [int(d.get("chars") or 0) for d in json.loads(m.read_text()).get("docs", []) if d.get("texto")]
        except (OSError, ValueError, AttributeError):
            continue
        if not cs:
            continue
        t, a = sum(cs), min(sum(min(c, TETO_DOC) for c in cs), TETO_TEXTO)
        total, alc, procs, cortados = total + t, alc + a, procs + 1, cortados + (a < t)
    return total, alc, procs, cortados


def _disco_vm2() -> float | None:
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "vm2-ts",
                            "df --output=pcent / | tail -1"], capture_output=True, text=True, timeout=25)
        return float(r.stdout.strip().rstrip("%"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _vazao_opus(agora: float | None = None) -> tuple[int, int, int]:
    import sqlite3
    desde = datetime.fromtimestamp((agora or time.time()) - 7 * 86400).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(f"file:{DATA / 'conferencia_opus.db'}?mode=ro", uri=True)
    try:
        ent = con.execute("SELECT COUNT(*) FROM fila WHERE criado_em >= ?", (desde,)).fetchone()[0]
        sai = con.execute("SELECT COUNT(*) FROM fila WHERE conferido_em >= ?", (desde,)).fetchone()[0]
        pend = con.execute("SELECT COUNT(*) FROM fila WHERE status = 'pendente'").fetchone()[0]
    finally:
        con.close()
    return ent, sai, pend


def _rodadas_7d(agora: float | None = None) -> list[dict]:
    desde = datetime.fromtimestamp((agora or time.time()) - 7 * 86400).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for ln in RODADAS_ITCAMPO.read_text(errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue                      # linha corrompida (3 medidas em 23/11) não cega o sensor
        if r.get("ts", "") >= desde:
            out.append(r)
    return out


def _cache_opus(agora: float | None = None) -> tuple[int, int, int]:
    desde = datetime.fromtimestamp((agora or time.time()) - 7 * 86400).strftime("%Y-%m-%d %H:%M:%S")
    cw = cr = n = 0
    for ln in (DATA / "claude_motor.log").read_text(errors="replace").splitlines():
        if "tarefa=conferencia_opus ok" not in ln or ln[1:20] < desde:
            continue
        m = re.search(r"cw=(\d+) cr=(\d+)", ln)
        if m:
            cw, cr, n = cw + int(m[1]), cr + int(m[2]), n + 1
    return cw, cr, n


def sensor_plataforma() -> list[dict]:
    out = avaliar_cobertura_leitura(*_cobertura_acervo())
    pct = _disco_vm2()
    if pct is None:                       # INDISPONÍVEL ≠ 0: VM-2 fora do ar não vira "disco ok"
        raise RuntimeError("vm2-ts não respondeu ao df")
    out += avaliar_disco("vm2", pct)
    out += avaliar_vazao_fila("conferencia_opus", *_vazao_opus())
    out += avaliar_recaptura(*fracao_recaptura_igual(_rodadas_7d()))
    out += avaliar_cache_opus(*_cache_opus())
    return out


# ─────────────────────────── E18 (O8.4): a automelhoria consome os SLOs do estágio observar ───────────────────────────
_FORA_DO_SLO = ("DEGRADADO", "ATRASADO", "BLOQUEADO")
_REMEDIO_DECLARADO = re.compile(r"^remediar:([a-z_]+)\b")


def problemas_e18(estado: dict, remedios: frozenset[str] | set[str] | None = None) -> list[dict]:
    """Estado do E18 (`sensores.estado_slos`) → problemas da fila única. Puro.

    Cada SLO DEGRADADO/ATRASADO/BLOQUEADO (por nó) vira um item com o `remediar:` declarado no slos.yaml. CRITÉRIO
    FORTE: só vira comando automático o remédio que começa por `remediar:<nome>` com <nome> em fluxo/remedios.REMEDIOS
    (salvaguarda própria, resfriamento, efeito relido pelo próprio sensor) e sem marca ⚖️/🔒; o resto é ação humana.
    SLO sem medida NÃO é saudável (INDISPONÍVEL ≠ 0): vira UM item agregado `e18:sem-medida` com a lista."""
    if remedios is None:
        from compliance_agent.fluxo.remedios import REMEDIOS
        remedios = set(REMEDIOS)
    out = []
    for it in estado.get("itens", []):
        if it["estado"] not in _FORA_DO_SLO:
            continue
        chave = f"{it['slo']}@{it['no']}" if it.get("escopo") == "maquina" and it.get("no") else it["slo"]
        marca = it.get("decisao") or ""
        m = _REMEDIO_DECLARADO.match(it.get("remediar") or "")
        cmd = (f"PYTHONPATH=. .venv/bin/python -m compliance_agent.fluxo.remedios {m[1]}"
               if m and m[1] in remedios and not marca else "")
        humano = "" if cmd else it.get("remediar") or ""
        out.append(_p("e18", chave, f"SLO {it['slo']} {it['estado']}" + (f" em {it['no']}" if it.get("no") else ""),
                      f"{it.get('motivo') or ''} · severidade {it.get('severidade')} · dono {it.get('dono')}",
                      remediar=cmd, acao_humana=humano, ao_dono=marca))
    sem = estado.get("nao_medidos") or []
    if sem:
        out.append(_p("e18", "sem-medida", f"{len(sem)} SLO(s) do E18 sem medida na janela",
                      ", ".join(sem[:25]) + (" …" if len(sem) > 25 else ""),
                      acao_humana="visão além do SLO não está ok: conferir se as rotinas observar_* do fluxo rodam "
                                  "(na parada de obras é esperado e declarado — religação na O9.0)"))
    return out


def sensor_e18() -> list[dict]:
    sys.path.insert(0, str(_REPO))
    from compliance_agent.fluxo import sensores as S
    slos = S.carregar_slos()
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(f"psycopg ausente: {exc}") from exc
    try:
        con = S.conectar_leitura()
        try:
            linhas = S.ler_ultimos(con, slos)
        finally:
            con.close()
    except psycopg.Error as exc:                 # PG da VM-2 fora: o sensor está cego, não "tudo ok"
        raise RuntimeError(f"fluxo.metricas ilegível: {type(exc).__name__}: {str(exc)[:120]}") from exc
    return problemas_e18(S.estado_slos(linhas, slos))


# ─────────────────────────── avisos calados (O8.4): o que o silêncio de 17/11 engolia ───────────────────────────
SILENCIADOS = DATA / "telegram_silenciado.jsonl"
FALHAS_SYSTEMD = DATA / "falhas_systemd.jsonl"
JANELA_AVISOS_S = 7 * 86400


def _ler_jsonl(arq: Path) -> list[dict]:
    if not arq.exists():
        return []
    out = []
    for ln in arq.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            logger.warning("linha ilegível em %s: %s", arq.name, ln[:80])
    return out


def classe_do_aviso(linha: dict, classes: dict) -> str | None:
    for cid, c in classes.items():
        if c["origem"] == linha.get("origem") and re.search(c["padrao"], linha.get("inicio") or ""):
            return cid
    return None


def avaliar_avisos(linhas: list[dict], classes: dict, agora: float) -> list[dict]:
    """Avisos calados (data/telegram_silenciado.jsonl) × config/avisos_calados.yaml. Puro.
    · classe `fechado` com linha DEPOIS de `fechado_em` ⇒ o fechamento na origem não pegou (efeito, não ação);
    · classe `registrado` com linha nos últimos 7 dias ⇒ item com a ação humana declarada;
    · linha sem classe (7 dias) ⇒ `aviso:sem-classe` — aviso calado sem dono não some."""
    def ts(t: str) -> float:
        return datetime.strptime(t[:16], "%Y-%m-%d %H:%M").timestamp()

    por: dict[str, list[dict]] = {}
    for ln in linhas:
        por.setdefault(classe_do_aviso(ln, classes) or "", []).append(ln)
    out = []
    for cid, lns in por.items():
        c = classes.get(cid)
        if c and c["estado"] == "fechado":
            depois = [x for x in lns if ts(x["t"]) > ts(c["fechado_em"])]
            if depois:
                out.append(_p("aviso", cid, f"aviso '{cid}' fechado na origem VOLTOU a ser calado ({len(depois)}×)",
                              f"último {depois[-1]['t']} · {depois[-1].get('inicio', '')[:120]}",
                              acao_humana=f"o produtor {c.get('produtor')} voltou a montar o aviso: o fechamento não "
                                          "pegou (config/avisos_calados.yaml)"))
            continue
        recentes = [x for x in lns if agora - ts(x["t"]) <= JANELA_AVISOS_S]
        if not recentes:
            continue
        if c:
            out.append(_p("aviso", cid, f"aviso calado sem destino: {cid} ({len(recentes)}× em 7 dias)",
                          f"{c['causa'][:150]} · último {recentes[-1]['t']}", acao_humana=c.get("acao_humana", "")))
        else:
            origens = sorted({x.get("origem") or "?" for x in recentes})
            out.append(_p("aviso", "sem-classe", f"{len(recentes)} aviso(s) calado(s) sem classe em 7 dias",
                          f"origens: {', '.join(origens)} · último: {recentes[-1].get('inicio', '')[:120]}",
                          acao_humana="classificar em config/avisos_calados.yaml: fechar na origem ou registrar"))
    return out


def avaliar_quedas_systemd(linhas: list[dict], agora: float, minimo: int = 2) -> list[dict]:
    """Quedas registradas pelo OnFailure (tools/notificar_falha.sh): a unidade que caiu ≥ `minimo` vezes em 7 dias
    vira item — inclusive a que JÁ VOLTOU sozinha (o sensor systemd só vê a que ficou failed). Puro."""
    por: dict[str, list[dict]] = {}
    for ln in linhas:
        if agora - datetime.strptime(ln["t"][:19], "%Y-%m-%d %H:%M:%S").timestamp() <= JANELA_AVISOS_S:
            por.setdefault(ln.get("unidade") or "?", []).append(ln)
    return [_p("systemd-queda", u, f"{u} caiu {len(lns)}× em 7 dias",
               f"último {lns[-1]['t']} · estado {lns[-1].get('estado')} · reinícios {lns[-1].get('nrestarts')} · "
               f"{(lns[-1].get('motivo') or '')[:150]}",
               acao_humana=f"reinício repetido tem causa: journalctl --user -u {u} -n 50")
            for u, lns in sorted(por.items()) if len(lns) >= minimo]


def sensor_avisos() -> list[dict]:
    import yaml
    classes = yaml.safe_load((_REPO / "config" / "avisos_calados.yaml").read_text(encoding="utf-8"))["classes"]
    agora = time.time()
    return avaliar_avisos(_ler_jsonl(SILENCIADOS), classes, agora) + avaliar_quedas_systemd(_ler_jsonl(FALHAS_SYSTEMD),
                                                                                            agora)


# nome → (sensor, o que ele vigia — a linha "Vigio:" do /melhorias). Sensor novo entra aqui e aparece lá.
_SENSORES = {"slo": (sensor_slo, "rotinas (SLO)"), "ci": (sensor_ci, "CI"),
             "catracas": (sensor_catracas, "catracas de código"), "systemd": (sensor_systemd, "serviços"),
             "voz": (sensor_voz, "voz do Yoda"), "ronda": (sensor_ronda, "API/LLM"), "siafe": (sensor_siafe, "SIAFE"),
             "yoda": (sensor_yoda, "minhas conversas"), "rem": (sensor_rem, "sono REM do Hermes"),
             "dados": (sensor_dados_siafe, "dados do SIAFE"), "vm": (sensor_vm, "VM (disco/memória)"),
             "polimonitor": (sensor_polimonitor, "Polimonitor (pm2)"), "painel": (sensor_painel, "painel/API"),
             "filas": (sensor_filas, "filas de feedback"), "pareceres": (sensor_pareceres, "oscilação dos pareceres"),
             "qualidade": (sensor_qualidade, "regras de qualidade"),
             "autoaprimoramento": (sensor_autoaprimoramento, "autoaprimoramento da perícia"),
             "certeza": (sensor_certeza, "certeza dos números"),
             "propagacao": (sensor_propagacao, "propagação (derivados além do SLO)"),
             "deploy": (sensor_deploy, "deploy pós-commit do painel"), "maquinas": (sensor_maquinas, "uso das máquinas"),
             "detectores": (sensor_detectores, "precisão dos detectores"),
             "integracao": (sensor_integracao, "integração de agentes (worktrees e remoções)"),
             "modelos": (sensor_modelos, "modelos grátis e fracos (divergência do Opus, disponibilidade)"),
             "plataforma": (sensor_plataforma, "plano de reescrita (cobertura de leitura, disco VM-2, fila do Opus, "
                                               "recaptura, cache)"),
             "e18": (sensor_e18, "SLOs do E18 (fluxo.metricas)"),
             "avisos": (sensor_avisos, "avisos calados e quedas de serviço")}
SENSORES = {nome: fn for nome, (fn, _) in _SENSORES.items()}
_AREAS = tuple(rotulo for _, rotulo in _SENSORES.values())


def sentir(sensores: dict = SENSORES) -> tuple[list[dict], dict]:
    problemas, medidos = [], {}
    for nome, fn in sensores.items():
        try:
            achados = fn()
            problemas += achados
            medidos[nome] = len(achados)
        # sensor quebrado vira PROBLEMA, nunca "ok" (INDISPONÍVEL ≠ 0). Específico, não `Exception`: são
        # estas as falhas reais — arquivo/JSON ausente, gh/pytest/systemctl falhando ou estourando tempo.
        except (OSError, ValueError, KeyError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
            logger.warning("sensor %s não mediu: %s", nome, exc)
            problemas.append(_p("sensor", nome, f"sensor {nome} não conseguiu medir", f"{type(exc).__name__}: {exc}",
                                acao_humana="o sensor está cego: ver data/automelhoria_geral.log"))
            medidos[nome] = None
    return problemas, medidos


# ─────────────────────────── conciliação: aberto → curado → REINCIDIU ───────────────────────────

def dispensados_slo() -> set[str]:
    """Assinaturas que o DONO mandou não vigiar (`dispensado:` em config/pipelines.yaml)."""
    import yaml
    cfg = yaml.safe_load((_REPO / "config" / "pipelines.yaml").read_text())["pipelines"]
    return {f"slo:{c['nome']}" for c in cfg if c.get("dispensado")}


# Dispensas do dono fora das rotinas do SLO (sensor de serviço, de dados etc.). Cada uma com a ordem e a data.
_DISPENSADOS_DONO = {
    "systemd:jfn-tfe-ob.service": "dono, 30/10/2026: 'esquece automelhoria do TFE' (SEFAZ recusa IP de datacenter; OB vem do SIAFE)",
}


def dispensados_dono() -> set[str]:
    return dispensados_slo() | set(_DISPENSADOS_DONO)


def conciliar(problemas: list[dict], fila_path: Path = FILA, agora: float | None = None,
              dispensados: set[str] = frozenset()) -> dict:
    """`dispensados`: itens que saem da fila por decisão do dono — nem curados (seria falso) nem abertos."""
    agora = agora or time.time()
    quando = datetime.fromtimestamp(agora).strftime("%Y-%m-%d %H:%M")
    try:
        fila = json.loads(fila_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fila = {}
    vistos = {p["assinatura"] for p in problemas}
    novos, reinc, curados = [], [], []
    for p in problemas:
        it = fila.get(p["assinatura"])
        if p["assinatura"] in dispensados and it is not None:
            # dispensado que volta não REINCIDE (nem avisa): a decisão do dono vale antes da conciliação
            it.update(status="dispensado", dispensado_em=it.get("dispensado_em") or quando, ultimo=quando)
            continue
        if it is None:
            fila[p["assinatura"]] = {**p, "status": "aberto", "primeiro": quando, "ultimo": quando, "rodadas": 1}
            novos.append(p["assinatura"])
            continue
        if it["status"] == "curado":
            it.update(status="REINCIDIU", reincidiu_em=quando, acoes=[], escalado=False)
            reinc.append(p["assinatura"])
        it.update(titulo=p["titulo"], detalhe=p["detalhe"], remediar=p.get("remediar", ""),
                  acao_humana=p.get("acao_humana", ""), ao_dono=p.get("ao_dono", ""), ultimo=quando,
                  rodadas=it.get("rodadas", 0) + 1)
    for sig in dispensados:
        if sig in fila and fila[sig]["status"] != "dispensado":
            fila[sig].update(status="dispensado", dispensado_em=quando)
    for sig, it in fila.items():
        if sig not in vistos and it["status"] in ("aberto", "REINCIDIU"):
            # o EFEITO verificado: se houve remédio automático, a cura é creditada a ele
            it.update(status="curado", curado_em=quando,
                      curado_por="remédio automático" if it.get("acoes") else "conserto externo")
            it["historico_acoes"] = it.get("historico_acoes", []) + it.get("acoes", [])
            it["acoes"] = []
            curados.append(sig)
    fila_path.parent.mkdir(parents=True, exist_ok=True)
    fila_path.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"fila": fila, "novos": novos, "reincidiu": reinc, "curados": curados}


MAX_TENTATIVAS, INTERVALO_S, CARGA_MAX = 2, 20 * 3600, 4.0


def remediar(fila: dict, agora: float | None = None, executar=None) -> dict:
    """O loop AGE: para cada problema aberto que tem remédio seguro declarado, executa (destacado, sem
    bloquear), no máximo 2 vezes com 20 h de intervalo. A rodada seguinte mede o efeito — se o sinal some,
    `conciliar` marca curado pelo remédio; se 2 tentativas não curaram, ESCALA ao dono (conserto automático
    que não pega não pode virar ruído silencioso). Carga alta adia, não força (a VM tem 2 vCPU)."""
    import os
    agora = agora or time.time()
    executar = executar or _executar_destacado
    feitos, escalados, adiados = [], [], []
    for sig, it in fila.items():
        if it["status"] in ("curado", "dispensado") or not it.get("remediar"):
            continue
        acoes = it.setdefault("acoes", [])
        if len(acoes) >= MAX_TENTATIVAS:
            if not it.get("escalado"):
                it["escalado"] = True
                escalados.append(sig)
            continue
        if acoes and agora - acoes[-1]["ts"] < INTERVALO_S:
            continue
        if os.getloadavg()[0] >= CARGA_MAX:
            adiados.append(sig)
            continue
        log = DATA / f"automelhoria_remedio_{sig.replace(':', '_').replace('/', '_')[:60]}.log"
        executar(it["remediar"], log)
        acoes.append({"ts": agora, "quando": datetime.fromtimestamp(agora).strftime("%Y-%m-%d %H:%M"),
                      "cmd": it["remediar"], "log": str(log.relative_to(_REPO))})
        feitos.append(sig)
    return {"feitos": feitos, "escalados": escalados, "adiados": adiados}


def _executar_destacado(cmd: str, log: Path) -> None:
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now():%F %T}] remédio automático: {cmd}\n")
        f.flush()
        # `nice` FORA do shell: `nice -n 10 PYTHONPATH=. …` falha ("No such file") — medido no 1º teste ao vivo
        # env da sessão: no cron, `systemctl --user restart` sem barramento falhava sem curar nada
        subprocess.Popen(["nice", "-n", "10", "bash", "-c", cmd], cwd=_REPO, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True, env=_env_sessao())


# AVISO SÓ DO ESCALADO (decisão 7 do dono, 20/11/2026). Os avisos de sistema estão silenciados desde 17/11
# (notifications/silencio) e "escalar ao dono" não chegava a ninguém. Reabre-se o canal SÓ para o item ESCALADO
# (2 remédios automáticos sem cura), marcado como tal, UMA vez por item (`escalado_avisado` fica gravado na fila e
# não volta). Tudo o mais segue silenciado. Entrega = `result.message_id` na resposta do Telegram; sem ele, o item
# não é marcado e tenta de novo na rodada seguinte (o silêncio devolve ok=True SEM enviar).
def _texto_escalado(it: dict) -> str:
    return (f"🆘 ESCALADO — automelhoria\n[{it['area']}] {it['titulo']}\n"
            f"Remédio automático tentado {len(it.get('acoes') or [])}× sem cura"
            + (f": {it['remediar'][:200]}" if it.get("remediar") else "") + "\n"
            + (f"👤 {it['acao_humana'][:200]}\n" if it.get("acao_humana") else "")
            + "Precisa de você. Detalhe: /melhorias")


def avisar_escalados(fila: dict, enviar=None, agora: float | None = None) -> list[str]:
    """Avisa (uma vez) cada item escalado e ainda aberto; devolve as assinaturas entregues."""
    if enviar is None:
        from compliance_agent.siafe_coord import enviar_ao_dono as enviar
    quando = datetime.fromtimestamp(agora or time.time()).strftime("%Y-%m-%d %H:%M")
    entregues = []
    for sig, it in fila.items():
        if not it.get("escalado") or it.get("escalado_avisado") or it["status"] in ("curado", "dispensado"):
            continue
        r = enviar(_texto_escalado(it))
        mid = ((r or {}).get("result") or {}).get("message_id") if isinstance(r, dict) else None
        if not mid:
            logger.warning("escalado %s NÃO entregue (sem message_id): %s", sig, str(r)[:200])
            continue
        it.update(escalado_avisado=quando, escalado_msg_id=mid)
        entregues.append(sig)
    return entregues


def resumo(fila: dict, max_itens: int = 15) -> str:
    abertos = sorted(((s, it) for s, it in fila.items() if it["status"] not in ("curado", "dispensado")),
                     key=lambda x: (x[1]["status"] != "REINCIDIU", x[1]["area"], x[1]["primeiro"]))
    curados = sorted(((s, it) for s, it in fila.items() if it["status"] == "curado"),
                     key=lambda x: x[1].get("curado_em", ""), reverse=True)
    L = [f"🔁 Automelhoria — {len(abertos)} aberto(s) · {len(curados)} curado(s) e vigiado(s)",
         "Vigio: " + " · ".join(_AREAS)]
    for _, it in abertos[:max_itens]:
        marca = "🔴 REINCIDIU" if it["status"] == "REINCIDIU" else "🟡"
        L.append(f"{marca} [{it['area']}] {it['titulo']} — desde {it['primeiro'][:10]}"
                 + (f" · {it['detalhe'][:80]}" if it.get("detalhe") else ""))
        if it.get("acoes"):
            L.append(f"    🤖 remédio automático tentado {len(it['acoes'])}× (último {it['acoes'][-1]['quando']})"
                     + (" — NÃO PEGOU, precisa de você" if it.get("escalado") else ""))
        if it.get("acao_humana"):
            L.append(f"    {'👤 ' + it['ao_dono'] + ' precisa do seu ✅' if it.get('ao_dono') else '👤'} "
                     f"{it['acao_humana'][:140]}")
    if len(abertos) > max_itens:
        L.append(f"… e mais {len(abertos) - max_itens}")
    disp = [it["titulo"] for it in fila.values() if it["status"] == "dispensado"]
    if disp:
        L.append("🔕 Dispensados pelo dono: " + "; ".join(d[:50] for d in disp))
    if curados:
        L.append("✅ Curados recentes: " + "; ".join(
            f"{it['titulo'][:50]} ({it.get('curado_em', '')[:10]}, {it.get('curado_por', 'conserto externo')})" for _, it in curados[:5]))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resumo", action="store_true")
    ap.add_argument("--sem-aviso", action="store_true")
    # O9.0 (25/11/2026): no fluxo, os remédios antigos (shell destacado: despachante `propagacao ciclo`, siafe_runner,
    # sei_integra_fila…) furavam a liberação estágio por estágio e o ritmo — rodaram E9/E10 com só E17/E18 liberados.
    # Com --sem-remediar a rodada mede, concilia e reporta; quem refaz trabalho atrasado é o planejador.
    # 26/11/2026 (frente B): o `/melhorias agora` do Yoda chamava sem a bandeira e lançava os mesmos remédios. Remediar
    # virou OPT-IN (`--remediar`); `--sem-remediar` segue aceito (é o argv do job no config/fluxo.yaml) e é o padrão.
    ap.add_argument("--sem-remediar", action="store_true")
    ap.add_argument("--remediar", action="store_true")
    a = ap.parse_args()
    if a.resumo:
        try:
            print(resumo(json.loads(FILA.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            print("🔁 Automelhoria — a fila ainda não foi medida (roda às 07:40; /melhorias agora mede já).")
        return 0
    problemas, medidos = sentir()
    r = conciliar(problemas, dispensados=dispensados_dono())
    rem = (remediar(r["fila"]) if a.remediar and not a.sem_remediar
           else {"feitos": [], "escalados": [], "adiados": []})
    avisados = [] if a.sem_aviso else avisar_escalados(r["fila"])
    FILA.write_text(json.dumps(r["fila"], ensure_ascii=False, indent=1), encoding="utf-8")
    txt = resumo(r["fila"], max_itens=60)
    md = (f"# Automelhoria geral — {datetime.now():%Y-%m-%d %H:%M}\n\n"
          f"Sensores (problemas achados; `None` = não mediu): `{json.dumps(medidos, ensure_ascii=False)}`\n\n"
          f"Novos: {len(r['novos'])} · reincidências: {len(r['reincidiu'])} · curados nesta rodada: "
          f"{len(r['curados'])} · remédios lançados: {rem['feitos']} · escalados: {rem['escalados']} · "
          f"escalados avisados ao dono: {avisados} · adiados por carga: {rem['adiados']}\n\n```\n{txt}\n```\n")
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    (RELATORIOS / f"{datetime.now():%Y-%m-%d}.md").write_text(md, encoding="utf-8")
    print(md)
    # O resumo de novidades no Telegram FECHOU NA ORIGEM (O8.4; config/avisos_calados.yaml `automelhoria-novidades`):
    # 44 deles morreram no silêncio de 17/11 sem ninguém ler. A novidade vive na fila, no /melhorias e no relatório do
    # vault; ao Telegram só vai o ESCALADO (avisar_escalados, decisão 7 do dono).
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(main())
