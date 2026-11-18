# -*- coding: utf-8 -*-
"""grafo — auditoria do GRAFO ÚNICO de dependências (config/propagacao.yaml) e frescor por nó.

O mapa do despachante já liga fontes → derivados. Esta auditoria acrescenta o que faltava para ele ser o grafo de
TUDO, sem criar outro arquivo nem tocar no despachante:

  · `externos:`  o que é recalculado FORA do despachante (perícia de execução, triagem, fichas do sweep — usam LLM
                 e têm cron próprio). Declaram `depende` (fontes), `publica` (a fonte que eles alimentam) e `atraso`
                 (função só-leitura que conta o que está velho). É o que fecha a cadeia SEI → laudo → derivados.
  · `fatos:`     o que cada nó publica no registro de fatos.
  · `frescor_max_s` por derivado (padrão: o maior entre 6 h e 3× o intervalo mínimo).

Achados da auditoria (cada um é uma LISTA — "quais", não só "quantos"):
  ciclo/erro de mapa · fonte sem sonda e sem emissor · fonte que ninguém consome · sonda cega ou com erro ·
  derivado sem efeito verificável · derivado sem consumidor · derivado que nunca rodou · derivado falhando ·
  derivado atrasado · arquivo servido pelo painel fora do grafo · detector que grava achado fora do grafo ·
  externo sem agendamento · externo com atraso acima do teto · externo cuja fila não diminui em 24 h.
"""
from __future__ import annotations

import importlib
import re
import sqlite3
import subprocess
import time
from pathlib import Path

import yaml

from . import config

_TIPOS_SONDA = ("sql", "arquivo", "pasta", "log", "git")


def carregar() -> dict:
    from compliance_agent import propagacao
    return propagacao.carregar()


def _modulos(cmd) -> set[str]:
    """Caminhos de arquivo .py que um argv (ou linha de cron) executa: `-m a.b` → a/b.py; `tools/x.py` → idem."""
    txt = " ".join(map(str, cmd)) if isinstance(cmd, (list, tuple)) else str(cmd)
    out = {m.replace(".", "/") + ".py" for m in re.findall(r"-m\s+([\w.]+)", txt)}
    out |= set(re.findall(r"([\w./-]+\.py)\b", txt))
    return {o.lstrip("./") for o in out}


def crontab() -> str | None:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _emissores(raiz: Path, fontes: list[str]) -> dict[str, list[str]]:
    """Fonte manual → arquivos do código que a emitem (`emitir(…, "<fonte>"` ou `propagacao emitir <fonte>`)."""
    out: dict[str, list[str]] = {f: [] for f in fontes}
    if not fontes:
        return out
    rx = re.compile(r"emitir\W.{0,80}?[\"'\s](" + "|".join(map(re.escape, fontes)) + r")[\"'\s]", re.S)
    for pasta in ("compliance_agent", "tools", "rotas"):
        for arq in (raiz / pasta).rglob("*.py"):
            if "/certeza/" in str(arq):
                continue
            try:
                txt = arq.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "emitir" in txt:
                for m in rx.finditer(txt):
                    out[m.group(1)].append(str(arq.relative_to(raiz)))
    return {k: sorted(set(v)) for k, v in out.items()}


def frescor_max(d: dict) -> float:
    return float(d.get("frescor_max_s") or max(6 * 3600, 3 * d.get("intervalo_min_s", 0)))


def auditar(cfg: dict | None = None, estado_prop: dict | None = None, raiz: Path | None = None,
            cron: str | None = "", ro: sqlite3.Connection | None = None, agora: float | None = None) -> dict:
    """Auditoria do grafo. `estado_prop` = `propagacao.estado()` (None/INDISPONÍVEL → as medidas que dependem dele
    saem INDISPONÍVEIS, nunca zero). `cron` = texto do crontab ("" = ler agora; None = indisponível)."""
    from compliance_agent import propagacao
    cfg, raiz, agora = cfg or carregar(), raiz or config.REPO, agora or time.time()
    fontes, ders, exts = cfg["fontes"], cfg["derivados"], cfg.get("externos") or {}
    if cron == "":
        cron = crontab()
    ach: dict[str, list] = {}
    ach["erro_de_mapa"] = propagacao.validar(cfg)
    for eid, e in exts.items():
        for dep in e.get("depende", []):
            if dep not in fontes and dep not in ders:
                ach["erro_de_mapa"].append(f"externo {eid}: depende de '{dep}', que não existe")
        if e.get("publica") and e["publica"] not in fontes:
            ach["erro_de_mapa"].append(f"externo {eid}: publica '{e['publica']}', que não é fonte")

    manuais = [f for f, d in fontes.items() if not any(t in (d.get("sonda") or {}) for t in _TIPOS_SONDA)]
    emis = _emissores(raiz, manuais)
    ach["fonte_sem_sonda_nem_emissor"] = [f for f in manuais if not emis[f] and not fontes[f].get("manual")]
    consumida = {dep for d in list(ders.values()) + list(exts.values()) for dep in d.get("depende", [])}
    ach["fonte_sem_consumidor"] = sorted(f for f in fontes if f not in consumida)
    publicada = {e.get("publica") for e in exts.values()}
    ach["derivado_sem_efeito_verificavel"] = sorted(
        i for i, d in ders.items() if d.get("tipo", "comando") == "comando" and not (d.get("efeito") or {}).get("arquivo"))
    ach["derivado_sem_consumidor"] = sorted(
        i for i, d in ders.items() if not d.get("onde") and i not in consumida and not d.get("fatos") and not d.get("cerebro"))

    # estado medido pelo despachante
    ok_prop = bool(estado_prop and estado_prop.get("ok"))
    nos = []
    if ok_prop:
        ach["despachante_parado"] = ["último ciclo há mais de 20 min"] if estado_prop.get("estado") == "PARADO" else []
        sond = {f["id"]: f for f in estado_prop["fontes"]}
        ach["sonda_com_erro"] = sorted(f"{i}: {s['erro']}" for i, s in sond.items() if s.get("erro"))
        ach["sonda_nunca_viu_mudanca"] = sorted(i for i, s in sond.items() if not s["manual"] and not s.get("mudou_em"))
        lin = {d["id"]: d for d in estado_prop["derivados"]}
        nunca, falha, atras = [], [], []
        for i, d in ders.items():
            ln = lin.get(i) or {}
            efeito = (d.get("efeito") or {}).get("arquivo")
            mt = None
            if efeito:
                try:
                    mt = (raiz / efeito).stat().st_mtime
                except OSError:
                    mt = None
            ultimo = max(x for x in (ln.get("ultimo_fim"), mt, 0) if x is not None) or None
            if not ultimo and d.get("tipo") != "cache":
                nunca.append(i)
            if ln.get("ultimo_estado") == "falhou":
                falha.append(f"{i}: {ln.get('falhas')} falha(s) — {str(ln.get('ultimo_erro'))[:160]}")
            sujo_ha = (agora - ln["sujo_desde"]) if ln.get("sujo_desde") else None
            est = "nunca rodou" if (not ultimo and d.get("tipo") != "cache") else \
                "falhou" if ln.get("ultimo_estado") == "falhou" else \
                "atrasado" if sujo_ha is not None and sujo_ha > frescor_max(d) else \
                "sujo" if ln.get("sujo") else "fresco"
            if est == "atrasado":
                atras.append(f"{i}: sujo há {sujo_ha / 3600:.1f} h (teto {frescor_max(d) / 3600:.0f} h)")
            nos.append({"id": i, "tipo": "derivado", "estado": est, "ultimo": ultimo, "sujo_ha_s": sujo_ha,
                        "frescor_max_s": frescor_max(d), "depende": d.get("depende", [])})
        for i, s in sond.items():
            nos.append({"id": i, "tipo": "fonte", "manual": s["manual"], "publicada_por_externo": i in publicada,
                        "estado": "erro" if s.get("erro") else "manual" if s["manual"] else "observada",
                        "ultimo": s.get("mudou_em"), "alimenta": s.get("alimenta", [])})
        ach["derivado_nunca_rodou"], ach["derivado_falhando"], ach["derivado_atrasado"] = sorted(nunca), falha, atras
    indisponiveis = [] if ok_prop else ["estado do despachante (propagacao.db)"]

    # o que o painel serve e o que os detectores gravam × o grafo
    no_grafo_arq = {(d.get("efeito") or {}).get("arquivo") for d in ders.values()} | \
                   {b.get("arquivo") for d in ders.values() for b in (d.get("fatos") or [])}
    no_grafo_mod = set().union(*[_modulos(d.get("comando", [])) for d in ders.values()] or [set()]) | \
        set().union(*[_modulos(e.get("cron", "")) for e in exts.values()] or [set()])
    try:
        inv = yaml.safe_load((raiz / "config" / "qualidade_inventario.yaml").read_text(encoding="utf-8")) or {}
        fora = []
        for arq, meta in (inv.get("dados_painel") or {}).items():
            if arq not in no_grafo_arq and str(meta.get("gerador")) not in no_grafo_mod:
                try:
                    idade = f"{(agora - (raiz / arq).stat().st_mtime) / 3600:.0f} h"
                except OSError:
                    idade = "arquivo ausente"
                fora.append(f"{arq} (gerador {meta.get('gerador')}; rota {meta.get('rota')}; idade {idade})")
        ach["arquivo_do_painel_fora_do_grafo"] = sorted(fora)
    except (OSError, yaml.YAMLError) as e:
        indisponiveis.append(f"inventário: {type(e).__name__}")
    try:
        det = (yaml.safe_load((raiz / "config" / "qualidade_detectores.yaml").read_text(encoding="utf-8")) or {}).get("detectores", {})
        grava = {k: d for k, d in det.items()
                 if d.get("grava") and not re.match(r"\s*(n[aã]o grava|sob demanda)", str(d["grava"]), re.I)}
        fora_det: dict[str, list[str]] = {}
        for k, d in grava.items():
            alvo = str(d["grava"]).split(" (")[0].strip()
            if str(d.get("modulo")) not in no_grafo_mod and alvo not in no_grafo_arq:
                fora_det.setdefault(alvo, []).append(k)
        ach["achado_gravado_fora_do_grafo"] = sorted(f"{alvo}: {len(ks)} detector(es) — {', '.join(sorted(ks)[:4])}"
                                                     + ("…" if len(ks) > 4 else "") for alvo, ks in fora_det.items())
    except (OSError, yaml.YAMLError) as e:
        indisponiveis.append(f"registro de detectores: {type(e).__name__}")

    # externos: agendamento e atraso
    sem_cron, atrasos, medidas = [], [], {}
    for eid, e in exts.items():
        if cron is None:
            indisponiveis.append(f"crontab (externo {eid})")
        elif e.get("cron") and not any(e["cron"] in ln and not ln.lstrip().startswith("#") for ln in cron.splitlines()):
            sem_cron.append(f"{eid}: '{e['cron']}' não está agendado")
        at = e.get("atraso")
        if at and ro is not None:
            try:
                mod, _, nome = at["funcao"].partition(":")
                n = len(getattr(importlib.import_module(mod), nome)(ro))
                medidas[eid] = n
                if at.get("teto") is not None and n > at["teto"]:
                    atrasos.append(f"{eid}: {n} item(ns) com a fonte mais nova que o derivado (teto {at.get('teto', 0)}) — {at.get('o_que', '')}")
            except (ImportError, AttributeError, sqlite3.Error, OSError, ValueError, TypeError) as ex:
                indisponiveis.append(f"atraso de {eid}: {type(ex).__name__}: {ex}")
        nos.append({"id": eid, "tipo": "externo", "estado": "sem agendamento" if any(x.startswith(eid + ":") for x in sem_cron)
                    else "atrasado" if any(x.startswith(eid + ":") for x in atrasos) else "agendado",
                    "depende": e.get("depende", []), "publica": e.get("publica"), "atraso": medidas.get(eid)})
    ach["externo_sem_agendamento"], ach["externo_atrasado"] = sem_cron, atrasos

    graves = ("erro_de_mapa", "fonte_sem_sonda_nem_emissor", "sonda_com_erro", "derivado_nunca_rodou", "derivado_falhando",
              "derivado_atrasado", "externo_sem_agendamento", "externo_atrasado", "externo_sem_drenar", "despachante_parado")
    return {"achados": ach, "nos": nos, "indisponiveis": indisponiveis, "emissores_de_fonte_manual": emis, "atraso_dos_externos": medidas,
            "resumo": {"fontes": len(fontes), "derivados": len(ders), "externos": len(exts),
                       "fatos_declarados": sum(len(d.get("fatos") or []) for s in ("fontes", "derivados", "externos")
                                               for d in (cfg.get(s) or {}).values()),
                       "achados": {k: len(v) for k, v in ach.items()},
                       "graves": sum(len(ach.get(k, [])) for k in graves)}}
