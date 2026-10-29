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
"""
from __future__ import annotations

import argparse
import json
import logging
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
            "tests/test_catraca_nao_pode_ser_tolerada.py", "tests/test_capacidade_pronta_tem_superficie.py"]
# unidades do desktop gráfico da VM que falham sem efeito sobre o JFN — não são problema da casa
_SYSTEMD_RUIDO = {"xfce4-notifyd.service"}

logger = logging.getLogger(__name__)


def _p(area: str, chave: str, titulo: str, detalhe: str = "", remediar: str = "", acao_humana: str = "") -> dict:
    """`remediar` = comando SEGURO que o loop executa sozinho; `acao_humana` = o que só gente resolve."""
    return {"assinatura": f"{area}:{chave}", "area": area, "titulo": titulo, "detalhe": detalhe[:300],
            "remediar": remediar, "acao_humana": acao_humana}


# Diagnóstico medido (sonda de 24/10/2026), para a ação humana não ser genérica.
_ACAO_LOGIN = {"1": "SIAFE 1 (www5, 2016-2023): NullPointerException intermitente no RootMenuParser ao montar o menu. "
                    "Medido em 29/10/2026: depois dele, o re-login no MESMO contexto reabria a sessão quebrada "
                    "(login.jsp → errorDisplay), enquanto um contexto limpo recebia o formulário — desde então o "
                    "re-login limpa os cookies do www5. Se persistir com sessão nova: ler os `erros` por tentativa "
                    "no log do par antes de qualquer outra hipótese"}
_ACAO_CONFLITO = {"326100_2025": "recoleta limpa de 24/10 devolveu 0 em TODAS as fatias (UG+Número 2025OB*) para um "
                                  "par com 1.310 OBs na base, coletadas pelo mesmo caminho em 15/08; o login é o mesmo "
                                  "do dreno que funciona — depurar o filtro com print da tela"}
_DIARIO_SIAFE = "PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_runner diario >> data/siafe_runner_cron.log 2>&1"


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
    r = subprocess.run(["gh", "run", "list", "-b", br, "-L", "8", "--json", "conclusion,status,headSha,name"],
                       cwd=_REPO, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"gh run list: {(r.stderr or r.stdout).strip()[:120]}")
    runs = [x for x in json.loads(r.stdout or "[]") if x.get("status") == "completed"
            and x.get("conclusion") not in ("skipped", "cancelled")]
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


def sensor_systemd() -> list[dict]:
    r = subprocess.run(["systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend"],
                       capture_output=True, text=True, timeout=30)
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
_CAUSA_EXTERNA = {"recusou o IP": "a SEFAZ recusa o IP da VM (AS31898 Oracle, catálogo de abuso) no TFE e recomenda "
                                  "outra origem ou chamado na OuvERJ — decidir: reinstalar o WARP (registra dispositivo "
                                  "na Cloudflare) ou abrir o chamado. Não é crítico: OB = SIAFE; o TFE é espelho"}


def _ultimo_erro(unidade: str) -> str:
    """A CAUSA no próprio item ("TFE recusou o IP…"), não só "em falha" — quem lê o /melhorias decide sem abrir o journal."""
    try:
        j = subprocess.run(["journalctl", "--user", "-u", unidade, "-n", "40", "--no-pager", "-o", "cat"],
                           capture_output=True, text=True, timeout=20).stdout.splitlines()
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
        out.append(_p("siafe", "diario", "coleta diária do SIAFE falhou",
                      f"{ult.get('erro')} — {ult.get('detail', '')}", remediar=_DIARIO_SIAFE))
    for sis in ("1", "2"):
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
    from tools.siafe_recoletar_dias import suspeitos
    sus = suspeitos()
    if not sus:
        return []
    return [_p("dados", "siafe_dias_no_plato", f"{len(sus)} dia(s) do SIAFE parados no platô do teto",
               ", ".join(f"{d}={n}" for d, n in sus[:6]),
               remediar="PYTHONPATH=. .venv/bin/python tools/siafe_recoletar_dias.py --auto --max 3 "
                        ">> data/siafe_recoletar_dias.log 2>&1")]


def sensor_vm() -> list[dict]:
    """A VM (2 vCPU, 11,6 GB) é o teto de tudo: disco cheio derruba SQLite/WAL; memória baixa derruba browser."""
    import shutil
    out = []
    du = shutil.disk_usage("/")
    pct = 100 * du.used / du.total
    if pct >= 90:
        out.append(_p("vm", "disco", f"disco em {pct:.0f}% ({du.free / 2**30:.0f} GB livres)",
                      acao_humana="maiores: ~/JFN/data/sei_cache (26 GB), ~/.npm (14 GB, cache regenerável), "
                                  "~/.ollama (9,7 GB), ~/.cache (9 GB — NÃO apagar ms-playwright nem uv). "
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
    for proc in json.loads(r.stdout or "[]"):
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
        except (urllib.error.URLError, TimeoutError):
            # tempo esgotado é CACHE FRIO, não rota quebrada: medido 24/10 logo após reiniciar o jfn.service,
            # /fontes/frescor levou 46 s frio (carga 6,4) e 0,006 s em seguida. O remédio é o pré-aquecimento.
            cod = 200
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


SENSORES = {"slo": sensor_slo, "ci": sensor_ci, "catracas": sensor_catracas, "systemd": sensor_systemd,
            "ronda": sensor_ronda, "siafe": sensor_siafe, "yoda": sensor_yoda, "rem": sensor_rem,
            "dados": sensor_dados_siafe, "vm": sensor_vm, "polimonitor": sensor_polimonitor,
            "painel": sensor_painel, "filas": sensor_filas}


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
        if it is None:
            fila[p["assinatura"]] = {**p, "status": "aberto", "primeiro": quando, "ultimo": quando, "rodadas": 1}
            novos.append(p["assinatura"])
            continue
        if it["status"] == "curado":
            it.update(status="REINCIDIU", reincidiu_em=quando, acoes=[], escalado=False)
            reinc.append(p["assinatura"])
        it.update(titulo=p["titulo"], detalhe=p["detalhe"], remediar=p.get("remediar", ""),
                  acao_humana=p.get("acao_humana", ""), ultimo=quando, rodadas=it.get("rodadas", 0) + 1)
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


_AREAS = ("rotinas (SLO)", "CI", "catracas de código", "serviços", "API/LLM", "SIAFE", "dados do SIAFE",
          "VM (disco/memória)", "sono REM do Hermes", "minhas conversas", "Polimonitor (pm2)",
          "painel/API", "filas de feedback")
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
        subprocess.Popen(["nice", "-n", "10", "bash", "-c", cmd], cwd=_REPO, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)


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
            L.append(f"    👤 {it['acao_humana'][:140]}")
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
    a = ap.parse_args()
    if a.resumo:
        try:
            print(resumo(json.loads(FILA.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            print("🔁 Automelhoria — a fila ainda não foi medida (roda às 07:40; /melhorias agora mede já).")
        return 0
    problemas, medidos = sentir()
    r = conciliar(problemas, dispensados=dispensados_slo())
    rem = remediar(r["fila"])
    FILA.write_text(json.dumps(r["fila"], ensure_ascii=False, indent=1), encoding="utf-8")
    txt = resumo(r["fila"], max_itens=60)
    md = (f"# Automelhoria geral — {datetime.now():%Y-%m-%d %H:%M}\n\n"
          f"Sensores (problemas achados; `None` = não mediu): `{json.dumps(medidos, ensure_ascii=False)}`\n\n"
          f"Novos: {len(r['novos'])} · reincidências: {len(r['reincidiu'])} · curados nesta rodada: "
          f"{len(r['curados'])} · remédios lançados: {rem['feitos']} · escalados: {rem['escalados']} · "
          f"adiados por carga: {rem['adiados']}\n\n```\n{txt}\n```\n")
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    (RELATORIOS / f"{datetime.now():%Y-%m-%d}.md").write_text(md, encoding="utf-8")
    print(md)
    if (r["novos"] or r["reincidiu"] or rem["escalados"]) and not a.sem_aviso:
        from compliance_agent.siafe_coord import notificar
        L = [f"🔁 Automelhoria: {len(r['novos'])} problema(s) novo(s), {len(r['reincidiu'])} reincidência(s)"
             + (f", {len(r['curados'])} curado(s)" if r["curados"] else "") + "."]
        for s in rem["escalados"]:
            L.append(f"🆘 conserto automático NÃO pegou em 2 tentativas: {r['fila'][s]['titulo']}")
        for s in (r["reincidiu"] + r["novos"])[:8]:
            it = r["fila"][s]
            L.append(f"{'🔴 ' if s in r['reincidiu'] else '• '}[{it['area']}] {it['titulo']}"
                     + (" — 🤖 já tentando consertar" if s in rem["feitos"] else ""))
        L.append("Detalhe: /melhorias")
        notificar("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(main())
