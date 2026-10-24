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


def _p(area: str, chave: str, titulo: str, detalhe: str = "") -> dict:
    return {"assinatura": f"{area}:{chave}", "area": area, "titulo": titulo, "detalhe": detalhe[:300]}


# ─────────────────────────── sensores (cada um devolve a lista de problemas AGORA) ───────────────────────────

def sensor_slo() -> list[dict]:
    sys.path.insert(0, str(_REPO))
    from tools.pipelines_slo import checar
    return [_p("slo", it["nome"], f"rotina {it['nome']} {it['status']}",
               f"idade {it['idade_h']} h · SLO {it['slo_h']} h")
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
        return [_p("ci", br, f"CI vermelho em {br}", f"commit {runs[0]['headSha'][:8]} · {runs[0]['name'][:60]}")]
    return []


def sensor_catracas() -> list[dict]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *CATRACAS],
                       cwd=_REPO, capture_output=True, text=True, timeout=600)
    falhas = [ln.split(" ", 1)[1].split(" - ")[0] for ln in r.stdout.splitlines() if ln.startswith("FAILED ")]
    if r.returncode not in (0, 1):
        raise RuntimeError(f"pytest rc={r.returncode}: {r.stdout[-160:]}")
    return [_p("catraca", f, f"catraca vermelha: {f.split('::')[-1]}", f) for f in falhas]


def sensor_systemd() -> list[dict]:
    r = subprocess.run(["systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend"],
                       capture_output=True, text=True, timeout=30)
    unid = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
    return [_p("systemd", u, f"serviço {u} em falha") for u in unid if u not in _SYSTEMD_RUIDO]


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


def sensor_siafe() -> list[dict]:
    out = []
    ult = json.loads((DATA / "sei_cache" / "siafe_runner_ultimo.json").read_text(encoding="utf-8"))
    if not ult.get("ok"):
        out.append(_p("siafe", "diario", "coleta diária do SIAFE falhou",
                      f"{ult.get('erro')} — {ult.get('detail', '')}"))
    for sis in ("1", "2"):
        av = DATA / f".siafe_dreno_aviso_login_{sis}"
        if av.exists() and time.time() - av.stat().st_mtime < 86400:
            out.append(_p("siafe", f"login_sistema_{sis}", f"login do SIAFE {sis} quebrado (disjuntor do dreno)"))
    q = DATA / "siafe_dreno_quarentena.json"
    if q.exists():
        for par, e in json.loads(q.read_text(encoding="utf-8")).items():
            if e.get("n", 0) >= 99:
                out.append(_p("siafe", f"conflito_{par}", f"dreno: conflito checkpoint × medidor em {par}",
                              e.get("motivo", "")))
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
                          f"{it['n']}× · último {it['ultimo']}"))
    return out


SENSORES = {"slo": sensor_slo, "ci": sensor_ci, "catracas": sensor_catracas, "systemd": sensor_systemd,
            "ronda": sensor_ronda, "siafe": sensor_siafe, "yoda": sensor_yoda}


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
            problemas.append(_p("sensor", nome, f"sensor {nome} não conseguiu medir", f"{type(exc).__name__}: {exc}"))
            medidos[nome] = None
    return problemas, medidos


# ─────────────────────────── conciliação: aberto → curado → REINCIDIU ───────────────────────────

def conciliar(problemas: list[dict], fila_path: Path = FILA, agora: float | None = None) -> dict:
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
            it.update(status="REINCIDIU", reincidiu_em=quando)
            reinc.append(p["assinatura"])
        it.update(titulo=p["titulo"], detalhe=p["detalhe"], ultimo=quando, rodadas=it.get("rodadas", 0) + 1)
    for sig, it in fila.items():
        if sig not in vistos and it["status"] in ("aberto", "REINCIDIU"):
            it.update(status="curado", curado_em=quando)
            curados.append(sig)
    fila_path.parent.mkdir(parents=True, exist_ok=True)
    fila_path.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"fila": fila, "novos": novos, "reincidiu": reinc, "curados": curados}


def resumo(fila: dict, max_itens: int = 15) -> str:
    abertos = sorted(((s, it) for s, it in fila.items() if it["status"] != "curado"),
                     key=lambda x: (x[1]["status"] != "REINCIDIU", x[1]["area"], x[1]["primeiro"]))
    curados = sorted(((s, it) for s, it in fila.items() if it["status"] == "curado"),
                     key=lambda x: x[1].get("curado_em", ""), reverse=True)
    L = [f"🔁 Automelhoria — {len(abertos)} aberto(s) · {len(curados)} curado(s) e vigiado(s)"]
    for _, it in abertos[:max_itens]:
        marca = "🔴 REINCIDIU" if it["status"] == "REINCIDIU" else "🟡"
        L.append(f"{marca} [{it['area']}] {it['titulo']} — desde {it['primeiro'][:10]}"
                 + (f" · {it['detalhe'][:80]}" if it.get("detalhe") else ""))
    if len(abertos) > max_itens:
        L.append(f"… e mais {len(abertos) - max_itens}")
    if curados:
        L.append("✅ Curados recentes: " + "; ".join(f"{it['titulo'][:50]} ({it.get('curado_em', '')[:10]})"
                                                  for _, it in curados[:5]))
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
    r = conciliar(problemas)
    txt = resumo(r["fila"], max_itens=60)
    md = (f"# Automelhoria geral — {datetime.now():%Y-%m-%d %H:%M}\n\n"
          f"Sensores (problemas achados; `None` = não mediu): `{json.dumps(medidos, ensure_ascii=False)}`\n\n"
          f"Novos: {len(r['novos'])} · reincidências: {len(r['reincidiu'])} · curados nesta rodada: "
          f"{len(r['curados'])}\n\n```\n{txt}\n```\n")
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    (RELATORIOS / f"{datetime.now():%Y-%m-%d}.md").write_text(md, encoding="utf-8")
    print(md)
    if (r["novos"] or r["reincidiu"]) and not a.sem_aviso:
        from compliance_agent.siafe_coord import notificar
        L = [f"🔁 Automelhoria: {len(r['novos'])} problema(s) novo(s), {len(r['reincidiu'])} reincidência(s)"
             + (f", {len(r['curados'])} curado(s)" if r["curados"] else "") + "."]
        for s in (r["reincidiu"] + r["novos"])[:8]:
            it = r["fila"][s]
            L.append(f"{'🔴 ' if s in r['reincidiu'] else '• '}[{it['area']}] {it['titulo']}")
        L.append("Detalhe: /melhorias")
        notificar("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(main())
