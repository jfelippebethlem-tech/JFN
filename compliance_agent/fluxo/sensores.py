# -*- coding: utf-8 -*-
"""Sensores do estágio E18 `observar` (plano mestre v2 §3.2 E18, §3.3 `fluxo.metricas`, §3.10 inv. 2 e 5; O8.1).

Os 14 vigias antigos (ronda, painel_vigia, guardião, keepalive, handoff_watcher, vm_guard, pipelines_slo, sentinela,
automelhoria_geral…) viram SENSORES: medem e gravam em `fluxo.metricas(no, nome, valor, quando, rotulos)`; não
reiniciam serviço, não matam processo, não mandam Telegram. O que eles faziam sozinhos virou `remediar` declarado em
config/slos.yaml (a O8.4 consome). Mapa vigia → sensor: ~/vault/refatoracao/vigias-para-sensores.md.

Três camadas:
  · funções PURAS (texto do /proc, do log ou do JSON → número): o teste fixa o cenário sem depender da máquina;
  · grupos de coleta (`GRUPOS`): cada um lê UMA fonte e devolve `Leitura`s; falha de leitura vira INDISPONIVEL do
    grupo inteiro, nunca 0 e nunca derruba a coleta dos outros;
  · `coletar`: roda os grupos que valem para o nó (os `nos` do SLO em config/slos.yaml), avalia cada leitura contra o
    SLO e grava tudo numa transação, com a etiqueta `coleta` — o efeito do estágio é conferido recontando por ela.

INDISPONÍVEL ≠ 0: sensor que não mediu grava `valor = NaN` (a coluna é NOT NULL) e `rotulos.estado = INDISPONIVEL`
com o motivo. Medida velha (além de `janela_s`) também é INDISPONIVEL na leitura (`estado_slos`).

Sensores caros (quick_check, frescor, cobertura da perícia, rotas do painel) são ESPAÇADOS pela própria série: se o nó
já gravou o grupo há menos de `intervalo_s`, a coleta pula (sem carimbo em arquivo — a prova é a linha no PG).

CLI de diagnóstico (a rotina `observar_*` do config/fluxo.yaml roda o ESTÁGIO, aplicacao/estagios/observar.py):
    python -m compliance_agent.fluxo.sensores coletar --no vm1 [--grupo psi ...] [--forcar]
    python -m compliance_agent.fluxo.sensores estado                       # só leitura: estado por SLO, JSON
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from compliance_agent.dominio.estados import SaudeOperacional

RAIZ = Path(__file__).resolve().parents[2]
CAMINHO_SLOS = RAIZ / "config" / "slos.yaml"
ORDEM = tuple(s.value for s in (SaudeOperacional.SAUDAVEL, SaudeOperacional.DEGRADADO, SaudeOperacional.ATRASADO,
                                SaudeOperacional.BLOQUEADO, SaudeOperacional.INDISPONIVEL))
SAUDAVEL, DEGRADADO, ATRASADO, BLOQUEADO, INDISPONIVEL = ORDEM
NOS_FLUXO = ("vm1", "vm2", "itcampo")
NO_SEM_HEARTBEAT_S = 300
PAINEL_URL = "http://127.0.0.1:8000"
ROTAS_MALFORMED = ("comparador/economia", "intel/sancionadas?limite=1", "pericias?limite=1", "ugs")   # as do guardião
VIVO_HTTP = (200, 301, 302, 303, 307, 401, 403)          # o processo respondeu (falha-fechado devolve 401/303)
# erros que um sensor pode levantar ao LER o mundo: viram INDISPONIVEL do grupo (nunca 0, nunca derrubam a coleta)
ERROS_LEITURA: tuple[type[BaseException], ...] = (OSError, ValueError, KeyError, TypeError, AttributeError,
                                                  IndexError, ZeroDivisionError, LookupError, sqlite3.Error,
                                                  subprocess.SubprocessError, ImportError, RuntimeError)


def _erros() -> tuple[type[BaseException], ...]:
    try:
        import psycopg
        return ERROS_LEITURA + (psycopg.Error,)
    except ImportError:
        return ERROS_LEITURA


def pior(*estados: str) -> str:
    return max(estados, key=ORDEM.index, default=SAUDAVEL)


# ── contrato dos SLOs (config/slos.yaml) ──────────────────────────────────────────────────────────────────────────
class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AplicaSe(_Base):
    sensor: str
    maior_que: float


class AtenuaSe(_Base):
    """Teto do estado quando OUTRO sensor prova que o sintoma não está doendo (pedido do dono na O8.1, feito na
    O8.4): swap cheio com PSI de memória ~0 é página fria estacionada — DEGRADADO, não BLOQUEADO. Condição não
    medida ou velha ⇒ NÃO atenua (falha fechada: sem prova de alívio fica o estado do limite)."""
    sensor: str
    menor_que: float
    ate: Literal["DEGRADADO", "ATRASADO"]


class Slo(_Base):
    sensor: str = Field(min_length=3)
    descricao: str = Field(min_length=5)
    unidade: str
    sentido: Literal["max", "min"]
    saudavel: float
    degradado: float | None = None
    pior: Literal["DEGRADADO", "ATRASADO", "BLOQUEADO"]
    janela_s: int = Field(gt=0)
    escopo: Literal["maquina", "global"] = "maquina"
    nos: list[str] = Field(min_length=1)
    aplica_se: AplicaSe | None = None
    atenua_se: AtenuaSe | None = None
    dono: str
    severidade: Literal["baixa", "media", "alta", "critica"]
    fonte: str = Field(min_length=3)
    runbook: str = Field(min_length=3)
    remediar: str = Field(min_length=5)
    # ⚖️ = regra jurídica/contábil · 🔒 = irreversível ou voltado para fora (plano v2, legenda): o remédio só com ✅ do
    # dono — a automelhoria escala, nunca executa (O8.4).
    decisao: Literal["⚖️", "🔒"] | None = None
    origem: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _limites(self):
        fora = sorted(set(self.nos) - set(NOS_FLUXO))
        if fora:
            raise ValueError(f"nó desconhecido: {fora}")
        if self.degradado is not None:
            ok = self.degradado >= self.saudavel if self.sentido == "max" else self.degradado <= self.saudavel
            if not ok:
                raise ValueError(f"{self.sensor}: limite degradado {self.degradado} do lado errado de {self.saudavel}")
        return self


class Slos(_Base):
    versao: int = Field(ge=1)
    slos: dict[str, Slo]

    @model_validator(mode="after")
    def _unicos(self):
        vistos: dict[str, str] = {}
        for sid, s in self.slos.items():
            if s.sensor in vistos:
                raise ValueError(f"sensor {s.sensor} julgado por dois SLOs ({vistos[s.sensor]}, {sid})")
            vistos[s.sensor] = sid
        for sid, s in self.slos.items():
            if s.aplica_se and s.aplica_se.sensor not in vistos:
                raise ValueError(f"{sid}: aplica_se cita sensor sem SLO ({s.aplica_se.sensor})")
            if s.atenua_se and s.atenua_se.sensor not in vistos:
                raise ValueError(f"{sid}: atenua_se cita sensor sem SLO ({s.atenua_se.sensor})")
        return self

    def por_sensor(self) -> dict[str, tuple[str, Slo]]:
        return {s.sensor: (sid, s) for sid, s in self.slos.items()}


def carregar_slos(caminho: Path | str | None = None) -> Slos:
    return Slos.model_validate(yaml.safe_load(Path(caminho or CAMINHO_SLOS).read_text(encoding="utf-8")) or {})


# ── leitura e avaliação (puras) ───────────────────────────────────────────────────────────────────────────────────
@dataclass
class Leitura:
    """Uma medida. `valor=None` = NÃO MEDIU (grava NaN + INDISPONIVEL, com `motivo`). `forcado` = estado que o
    próprio sensor afirma além do número (quick_check falhou, restauração falhou, painel sem resposta)."""
    nome: str
    valor: float | None
    motivo: str = ""
    forcado: str | None = None
    rotulos: dict = field(default_factory=dict)


def nao_mediu(nome: str, motivo: str, **rotulos) -> Leitura:
    return Leitura(nome, None, motivo=motivo, rotulos=rotulos)


def _num(v) -> float | None:
    """NaN/None/ilegível → None (não mediu)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def avaliar(slo: Slo, valor, forcado: str | None = None) -> tuple[str, str]:
    """(estado, motivo) de UM valor contra o SLO. Sem valor = INDISPONIVEL; `forcado` só piora."""
    v = _num(valor)
    if v is None:
        return INDISPONIVEL, "não medido"
    dentro = (lambda lim: v <= lim) if slo.sentido == "max" else (lambda lim: v >= lim)
    sinal = "≤" if slo.sentido == "max" else "≥"
    if dentro(slo.saudavel):
        estado, motivo = SAUDAVEL, f"{v:g} {slo.unidade} {sinal} {slo.saudavel:g}"
    elif slo.degradado is not None and dentro(slo.degradado):
        estado, motivo = DEGRADADO, f"{v:g} {slo.unidade} fora de {sinal} {slo.saudavel:g} (limite {slo.degradado:g})"
    else:
        lim = slo.degradado if slo.degradado is not None else slo.saudavel
        estado, motivo = slo.pior, f"{v:g} {slo.unidade} além do limite {sinal} {lim:g}"
    if forcado and forcado in ORDEM and ORDEM.index(forcado) > ORDEM.index(estado):
        return forcado, f"{motivo}; o sensor afirma {forcado}"
    return estado, motivo


def psi(texto: str, linha: str = "some", janela: str = "avg60") -> float | None:
    """'some avg10=1.68 avg60=0.90 …' → 0.90. Texto vazio (kernel sem PSI) ou linha ausente → None (não 0 — o
    governador cai em 0 por desenho; o sensor diz que não mediu)."""
    for ln in (texto or "").splitlines():
        partes = ln.split()
        if partes and partes[0] == linha:
            for p in partes[1:]:
                k, _, v = p.partition("=")
                if k == janela:
                    return float(v)
    return None


def meminfo(texto: str) -> dict[str, float]:
    out = {}
    for ln in (texto or "").splitlines():
        nome, _, resto = ln.partition(":")
        if resto.split():
            out[nome.strip()] = float(resto.split()[0])            # kB
    return out


def swap_pct(m: Mapping[str, float]) -> float | None:
    if "SwapTotal" not in m or "SwapFree" not in m:
        return None
    return 0.0 if m["SwapTotal"] <= 0 else round(100.0 * (m["SwapTotal"] - m["SwapFree"]) / m["SwapTotal"], 2)


def mem_disponivel_gb(m: Mapping[str, float]) -> float | None:
    return None if "MemAvailable" not in m else round(m["MemAvailable"] / 1024 / 1024, 3)


def tendencia_pp_dia(pontos: Iterable[tuple[float, float]], minimo_s: float = 3600.0) -> float | None:
    """Inclinação (mínimos quadrados) de (epoch, % usado) em pontos percentuais por dia. Menos de 2 pontos ou
    janela < `minimo_s` → None: não há série para dizer tendência."""
    p = [(float(t), float(u)) for t, u in pontos if _num(u) is not None]
    if len(p) < 2 or max(t for t, _ in p) - min(t for t, _ in p) < minimo_s:
        return None
    mt = sum(t for t, _ in p) / len(p)
    mu = sum(u for _, u in p) / len(p)
    den = sum((t - mt) ** 2 for t, _ in p)
    return round(86400.0 * sum((t - mt) * (u - mu) for t, u in p) / den, 4) if den else None


_RX_DUMP_OK = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) dump ok")
_RX_ARMAZ = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) armazenamento rc=(\d+)")
_RX_OFFBOX = re.compile(r"✓ off-box: .*?compliance-(\d{8})-(\d{6})\.db\.gz(?:\.age)?")   # .age desde 25/11/2026


def ultimo_dump_guardado(texto: str) -> datetime | None:
    """Último 'dump ok' do backup do PG seguido de 'armazenamento rc=0' (dump sem cópia guardada não é backup)."""
    dump = guardado = None
    for ln in (texto or "").splitlines():
        if m := _RX_DUMP_OK.match(ln):
            dump = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        elif (m := _RX_ARMAZ.match(ln)) and dump is not None:
            if m.group(2) == "0":
                guardado = dump
            dump = None
    return guardado


def ultimo_backup_compliance(texto: str) -> datetime | None:
    datas = [datetime.strptime(a + b, "%Y%m%d%H%M%S") for a, b in _RX_OFFBOX.findall(texto or "")]
    return max(datas) if datas else None


def idade_h(quando: datetime | None, agora: datetime) -> float | None:
    return None if quando is None else round((agora - quando).total_seconds() / 3600.0, 2)


def razao_opus(entradas: int, saidas: int) -> tuple[float, str]:
    """Conferidos ÷ entrados em 7 dias. Sem entrada, 'saída ≥ entrada' vale trivialmente (1,0, declarado) — o
    acúmulo antigo aparece no `opus.pendentes`, não aqui."""
    if entradas <= 0:
        return 1.0, "sem entrada na janela: saída ≥ entrada trivial"
    return round(saidas / entradas, 4), f"{saidas} conferidos ÷ {entradas} entrados (7 dias)"


def estado_slos(linhas: Iterable[Mapping], slos: Slos, agora: float | None = None) -> dict:
    """Estado por SLO a partir da ÚLTIMA linha de cada (nó, sensor) — o que o painel mostra. Puro.

    `linhas`: {no, nome, valor, quando(epoch), rotulos}. SLO de escopo `maquina` vira um item por nó declarado; `global`
    usa a linha mais nova de qualquer nó. Sem linha ou linha além de `janela_s` = INDISPONIVEL.
    Estado global honesto: o pior entre os MEDIDOS; nenhum medido = INDISPONIVEL; algum não medido e o pior medido
    SAUDAVEL = DEGRADADO (não dá para dizer 'saudável' sem ter olhado tudo)."""
    agora = time.time() if agora is None else agora
    ult: dict[tuple[str | None, str], Mapping] = {}
    for ln in linhas:
        k = (ln.get("no"), ln["nome"])
        if k not in ult or float(ln["quando"]) > float(ult[k]["quando"]):
            ult[k] = ln
    por_nome: dict[str, Mapping] = {}
    for (_no, nome), ln in ult.items():
        if nome not in por_nome or float(ln["quando"]) > float(por_nome[nome]["quando"]):
            por_nome[nome] = ln

    def _linha(slo: Slo, no: str | None) -> Mapping | None:
        return por_nome.get(slo.sensor) if no is None else ult.get((no, slo.sensor))

    def julgar(sid: str, slo: Slo, no: str | None) -> dict:
        ln = _linha(slo, no)
        base = {"slo": sid, "sensor": slo.sensor, "no": no if no is not None else (ln or {}).get("no"),
                "escopo": slo.escopo, "unidade": slo.unidade, "descricao": slo.descricao, "dono": slo.dono,
                "severidade": slo.severidade, "limite": {"sentido": slo.sentido, "saudavel": slo.saudavel,
                                                         "degradado": slo.degradado, "pior": slo.pior},
                "remediar": slo.remediar, "decisao": slo.decisao, "valor": None, "medido_em": None}
        if ln is None:
            return {**base, "estado": INDISPONIVEL, "motivo": "nunca medido neste nó" if no else "nunca medido"}
        rot = ln.get("rotulos") or {}
        idade = agora - float(ln["quando"])
        base.update(valor=_num(ln.get("valor")), medido_em=_iso(float(ln["quando"])), idade_s=round(idade))
        if idade > slo.janela_s:
            return {**base, "estado": INDISPONIVEL,
                    "motivo": f"medida velha: {idade / 60:.0f} min > janela de {slo.janela_s / 60:.0f} min"}
        if base["valor"] is None:
            return {**base, "estado": INDISPONIVEL, "motivo": rot.get("motivo") or "não medido"}
        if slo.aplica_se:
            cond = _linha(slos.slos[slos.por_sensor()[slo.aplica_se.sensor][0]], no)
            cv = _num((cond or {}).get("valor"))
            if cv is None:
                return {**base, "estado": INDISPONIVEL, "motivo": f"condição {slo.aplica_se.sensor} não medida"}
            if cv <= slo.aplica_se.maior_que:
                return {**base, "estado": SAUDAVEL,
                        "motivo": f"não se aplica: {slo.aplica_se.sensor} = {cv:g} (≤ {slo.aplica_se.maior_que:g})"}
        estado, motivo = avaliar(slo, base["valor"], rot.get("forcado"))
        if slo.atenua_se and not rot.get("forcado") and ORDEM.index(estado) > ORDEM.index(slo.atenua_se.ate):
            cond_slo = slos.slos[slos.por_sensor()[slo.atenua_se.sensor][0]]
            estado, motivo = _atenuar(slo, estado, motivo, _linha(cond_slo, no), cond_slo.janela_s, agora)
        if rot.get("motivo"):
            motivo = f"{motivo} — {rot['motivo']}"
        return {**base, "estado": estado, "motivo": motivo}

    itens = []
    for sid, slo in slos.slos.items():
        if slo.escopo == "global":
            itens.append(julgar(sid, slo, None))
        else:
            itens += [julgar(sid, slo, no) for no in slo.nos]
    medidos = [i["estado"] for i in itens if i["estado"] != INDISPONIVEL]
    nao_medidos = [f"{i['slo']}@{i['no']}" if i["escopo"] == "maquina" else i["slo"]
                   for i in itens if i["estado"] == INDISPONIVEL]
    if not medidos:
        geral, motivo = INDISPONIVEL, "nenhum SLO medido dentro da janela"
    else:
        geral = pior(*medidos)
        motivo = f"pior estado medido: {geral}"
        if nao_medidos and geral == SAUDAVEL:
            geral, motivo = DEGRADADO, "tudo o que foi medido está saudável, mas há SLO sem medida"
    contagem = {e: sum(i["estado"] == e for i in itens) for e in ORDEM}
    return {"estado": geral, "motivo": motivo, "total": len(itens), "contagem": contagem,
            "nao_medidos": nao_medidos, "itens": itens}


def _atenuar(slo: Slo, estado: str, motivo: str, cond: Mapping | None, janela_cond: int,
             agora: float) -> tuple[str, str]:
    """Aplica `atenua_se`: só com a condição MEDIDA, dentro da janela dela e abaixo do limiar. Puro."""
    a = slo.atenua_se
    cv = _num((cond or {}).get("valor"))
    if cv is None or agora - float(cond["quando"]) > janela_cond:
        return estado, f"{motivo}; sem atenuação: {a.sensor} não medido na janela"
    if cv >= a.menor_que:
        return estado, f"{motivo}; {a.sensor} = {cv:g} (≥ {a.menor_que:g}): a pressão é real"
    return a.ate, f"{motivo}; atenuado para {a.ate}: {a.sensor} = {cv:g} < {a.menor_que:g} (sintoma sem pressão)"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


# ── grupos de coleta (tocam o mundo; só leitura) ──────────────────────────────────────────────────────────────────
@dataclass
class Ctx:
    no: str
    con: object | None                    # conexão psycopg no esquema do fluxo (None = sem PG)
    agora: datetime
    raiz: Path = RAIZ
    proc: str = "/proc"

    @property
    def agora_local(self) -> datetime:
        """Hora local sem fuso: é como os logs e as colunas de coleta do compliance.db gravam (Brasília)."""
        return self.agora.astimezone().replace(tzinfo=None)

    @property
    def data(self) -> Path:
        return Path(os.environ.get("JFN_DATA_DIR") or (self.raiz / "data"))


def _ler(caminho: Path | str) -> str:
    with open(caminho, encoding="utf-8", errors="replace") as f:
        return f.read()


def _sqlite_ro(caminho: Path, timeout: float = 30.0) -> sqlite3.Connection:
    if not caminho.exists():
        raise FileNotFoundError(f"{caminho.name} ausente")
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=timeout)


def g_psi(ctx: Ctx) -> list[Leitura]:
    out = []
    for recurso, chave in (("cpu", "cpu"), ("memory", "mem"), ("io", "io")):
        try:
            texto = _ler(Path(ctx.proc) / "pressure" / recurso)
        except OSError as e:
            texto, erro = "", f"{type(e).__name__}: {e}"
        else:
            erro = "linha ausente no PSI"
        linhas = ("some",) if recurso == "cpu" else ("some", "full")
        for ln in linhas:
            v = psi(texto, ln)
            nome = f"psi.{chave}_{ln}"
            out.append(Leitura(nome, v, rotulos={"janela": "avg60"}) if v is not None else nao_mediu(nome, erro))
    return out


def g_memoria(ctx: Ctx) -> list[Leitura]:
    m = meminfo(_ler(Path(ctx.proc) / "meminfo"))
    s, d = swap_pct(m), mem_disponivel_gb(m)
    return [Leitura("swap.uso_pct", s, rotulos={"swap_total_gb": round(m.get("SwapTotal", 0) / 1048576, 2)})
            if s is not None else nao_mediu("swap.uso_pct", "SwapTotal/SwapFree ausentes no meminfo"),
            Leitura("mem.disponivel_gb", d) if d is not None else nao_mediu("mem.disponivel_gb", "sem MemAvailable")]


def g_disco(ctx: Ctx) -> list[Leitura]:
    u = shutil.disk_usage("/")
    livre = round(100.0 * u.free / u.total, 3)
    out = [Leitura("disco.livre_pct", livre, rotulos={"livre_gb": round(u.free / 2**30, 1),
                                                       "total_gb": round(u.total / 2**30, 1)})]
    if ctx.con is None:
        return out + [nao_mediu("disco.tendencia_pp_dia", "sem PG: a série do disco mora em fluxo.metricas",
                                recalcular_com_pg=True)]
    return out + [tendencia_disco(ctx.con, ctx.no, livre, ctx.agora.timestamp())]


def tendencia_disco(con, no: str, livre_pct: float, agora_epoch: float) -> Leitura:
    """Tendência do uso do disco do nó (pp/dia) pela série de `disco.livre_pct` das últimas 72 h em fluxo.metricas
    mais o ponto de agora. Série curta (< 1 h ou 1 ponto) = INDISPONIVEL, nunca 0."""
    serie = con.execute(
        "SELECT extract(epoch FROM quando), valor FROM metricas WHERE no = %s AND nome = 'disco.livre_pct' "
        "AND quando > now() - interval '72 hours' AND valor = valor ORDER BY quando", (no,)).fetchall()
    pontos = [(float(t), 100.0 - float(v)) for t, v in serie] + [(agora_epoch, 100.0 - livre_pct)]
    t = tendencia_pp_dia(pontos)
    return (Leitura("disco.tendencia_pp_dia", t, rotulos={"pontos": len(pontos)}) if t is not None else
            nao_mediu("disco.tendencia_pp_dia", f"série curta ({len(pontos)} ponto(s), < 1 h): sem tendência ainda",
                      pontos=len(pontos)))


def g_navegador(ctx: Ctx) -> list[Leitura]:
    if not shutil.which("pgrep"):
        return [nao_mediu("navegador.orfaos", "pgrep ausente")]
    from tools.vm_guard import _meus_chromium_pids
    return [Leitura("navegador.orfaos", float(len(_meus_chromium_pids(somente_orfaos=True))))]


def _http(url: str, timeout: float) -> tuple[int | None, float, bytes]:
    """(código, ms, corpo). Redirecionamento NÃO é seguido (303 do login = processo vivo)."""
    class _SemRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    abrir = urllib.request.build_opener(_SemRedir).open
    t0 = time.monotonic()
    try:
        with abrir(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
            corpo, cod = r.read(65536), r.status
    except urllib.error.HTTPError as e:
        corpo, cod = e.read(65536) if e.fp else b"", e.code
    except (urllib.error.URLError, OSError):
        return None, round((time.monotonic() - t0) * 1000.0, 1), b""
    return cod, round((time.monotonic() - t0) * 1000.0, 1), corpo


def painel_estado(vivo: bool, falhas_antes: int) -> tuple[int, str | None]:
    """Regra do painel_vigia (2 checagens seguidas): (falhas seguidas, estado forçado). Puro. 1ª falha = DEGRADADO
    ('confirmo na próxima'); 2ª em diante = BLOQUEADO (processo vivo porém travado)."""
    if vivo:
        return 0, None
    n = falhas_antes + 1
    return n, (BLOQUEADO if n >= 2 else DEGRADADO)


def _falhas_painel_antes(ctx: Ctx) -> int:
    if ctx.con is None:
        return 0
    r = ctx.con.execute("SELECT rotulos->>'falhas_seguidas' FROM metricas WHERE no = %s AND nome = "
                        "'painel.latencia_ms' ORDER BY quando DESC LIMIT 1", (ctx.no,)).fetchone()
    return int(r[0]) if r and r[0] and str(r[0]).isdigit() else 0


def g_painel(ctx: Ctx) -> list[Leitura]:
    """Absorve ~/bin/painel_vigia.sh como SENSOR: /painel em 25 s; sem resposta 2× seguidas = BLOQUEADO. O restart
    é o remédio `painel_travado` (compliance_agent/fluxo/remedios.py), nunca o sensor."""
    cod, ms, _ = _http(f"{PAINEL_URL}/painel", 25.0)
    vivo = cod in VIVO_HTTP
    n, forcado = painel_estado(vivo, 0 if vivo else _falhas_painel_antes(ctx))
    if vivo:
        return [Leitura("painel.latencia_ms", ms, rotulos={"http": cod, "falhas_seguidas": 0})]
    return [Leitura("painel.latencia_ms", ms, forcado=forcado, rotulos={"http": cod, "falhas_seguidas": n},
                    motivo=f"painel sem resposta válida (http={cod}), {n}ª checagem seguida"
                           + (" — confirmo na próxima" if n < 2 else ""))]


def g_painel_malformed(ctx: Ctx) -> list[Leitura]:
    doentes, cegas = [], []
    for r in ROTAS_MALFORMED:
        cod, _ms, corpo = _http(f"{PAINEL_URL}/api/{r}", 20.0)
        if cod is None:
            cegas.append(r)
        elif b"disk image is malformed" in corpo:
            doentes.append(r)
    if len(cegas) == len(ROTAS_MALFORMED):
        return [nao_mediu("painel.rotas_malformed", "nenhuma rota respondeu", cegas=cegas)]
    return [Leitura("painel.rotas_malformed", float(len(doentes)), rotulos={"doentes": doentes, "cegas": cegas})]


def g_fila(ctx: Ctx) -> list[Leitura]:
    c = ctx.con
    if c is None:
        raise RuntimeError("sem PG: fluxo.jobs inacessível")
    r = c.execute(
        "SELECT count(*) FILTER (WHERE estado = 'fila' AND disponivel_em <= now()), "
        "coalesce(extract(epoch FROM now() - min(disponivel_em) FILTER (WHERE estado = 'fila' "
        "AND disponivel_em <= now())), 0), count(*) FILTER (WHERE estado = 'quarentena'), "
        "count(*) FILTER (WHERE estado = 'reservado' AND prazo < now()), "
        "count(*) FILTER (WHERE estado = 'feito' AND concluido_em > now() - interval '1 hour') FROM jobs").fetchone()
    eleg, idade, quar, orf, feitos = (float(x or 0) for x in r)
    por = c.execute("SELECT tipo, estado, count(*), extract(epoch FROM now() - min(criado_em)) FROM jobs "
                    "WHERE estado IN ('fila', 'reservado') GROUP BY tipo, estado ORDER BY 4 DESC LIMIT 50").fetchall()
    vazia = {"fila_vazia": True} if eleg == 0 else {}
    out = [Leitura("fila.idade_max_s", round(idade, 1), rotulos=vazia), Leitura("fila.elegiveis", eleg),
           Leitura("fila.quarentena", quar), Leitura("fila.orfaos", orf), Leitura("fila.conclusoes_h", feitos)]
    out += [Leitura("fila.idade_s.por_tipo", round(float(i or 0), 1),
                    rotulos={"detalhe_de": "fila.idade_max_s", "tipo": t, "estado_job": e, "jobs": n})
            for t, e, n, i in por]
    out += _percentis_espera(c)
    vivos = {x[0] for x in c.execute("SELECT no FROM nos WHERE heartbeat_em > now() - make_interval(secs => %s)",
                                     (NO_SEM_HEARTBEAT_S,))}
    fora = [n for n in NOS_FLUXO if n not in vivos]
    out.append(Leitura("fluxo.nos_sem_heartbeat", float(len(fora)), rotulos={"fora": fora, "vivos": sorted(vivos)}))
    return out


_SQL_PERCENTIS = ("SELECT {grupo} count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY e), "
                  "percentile_cont(0.95) WITHIN GROUP (ORDER BY e) FROM (SELECT tipo, extract(epoch FROM now() - "
                  "disponivel_em) AS e FROM jobs WHERE estado = 'fila' AND disponivel_em <= now()) x {por}")


def _percentis_espera(c) -> list[Leitura]:
    """Espera dos jobs ELEGÍVEIS (now − disponivel_em): p50/p95 global (o p95 tem SLO) e por tipo (detalhe). Fila
    vazia = espera 0 MEDIDA (ninguém esperando), com `fila_vazia` — não é ausência de medida."""
    n, p50, p95 = c.execute(_SQL_PERCENTIS.format(grupo="", por="")).fetchone()
    vazia = {"fila_vazia": True} if not n else {}
    out = [Leitura("fila.espera_p95_s", round(float(p95 or 0), 1), rotulos={"jobs": int(n or 0), **vazia}),
           Leitura("fila.espera_p50_s", round(float(p50 or 0), 1),
                   rotulos={"detalhe_de": "fila.espera_p95_s", "jobs": int(n or 0), **vazia})]
    for tipo, k, q50, q95 in c.execute(_SQL_PERCENTIS.format(grupo="tipo,", por="GROUP BY tipo ORDER BY 4 DESC "
                                                                                  "LIMIT 50")):
        rot = {"detalhe_de": "fila.espera_p95_s", "tipo": tipo, "jobs": k}
        out += [Leitura("fila.espera_p50_s.por_tipo", round(float(q50), 1), rotulos=rot),
                Leitura("fila.espera_p95_s.por_tipo", round(float(q95), 1), rotulos=rot)]
    return out


def g_wal_pg(ctx: Ctx) -> list[Leitura]:
    c = ctx.con
    if c is None:
        raise RuntimeError("sem PG")
    modo = c.execute("SELECT setting FROM pg_settings WHERE name = 'archive_mode'").fetchone()
    if not modo or modo[0] == "off":
        return [nao_mediu("wal.pg_arquivo_atraso_s", "archive_mode=off: arquivamento contínuo de WAL não ligado "
                          "(WAL-G é a O8.2); o backup do PG hoje é o pg_dump diário (backup.evidencias_pg_idade_h)")]
    arq, falhas, atraso, falhou_depois = c.execute(
        "SELECT archived_count, failed_count, extract(epoch FROM now() - last_archived_time), "
        "coalesce(last_failed_time > last_archived_time, false) FROM pg_stat_archiver").fetchone()
    rot = {"arquivados": arq, "falhas": falhas}
    if atraso is None:
        return [nao_mediu("wal.pg_arquivo_atraso_s", "archive_mode ligado e nenhum segmento arquivado ainda", **rot)]
    return [Leitura("wal.pg_arquivo_atraso_s", round(float(atraso), 1), rotulos=rot,
                    forcado=DEGRADADO if falhou_depois else None,
                    motivo="a última tentativa de arquivar FALHOU" if falhou_depois else "")]


def g_frescor(ctx: Ctx) -> list[Leitura]:
    from compliance_agent.ingestao import contrato as ct
    from compliance_agent.ingestao import sensores as si
    c = ct.carregar()
    con = _sqlite_ro(ctx.data / "compliance.db", timeout=60)
    out, atrasadas, cegas, declaradas = [], [], [], []
    agora = ctx.agora_local
    try:
        for fid, f in c.fontes.items():
            if f.natureza != "externa" or f.banco != "compliance":
                continue
            if not si._tem(con, f.tabela):
                cegas.append(fid)
                out.append(nao_mediu("frescor.atraso_h", f"tabela {f.tabela} ausente", detalhe_de="frescor.fontes_atrasadas",
                                     fonte=fid))
                continue
            ultima = con.execute(si.sql_frescor(f)).fetchone()[0]
            a = si.atualidade(ultima, agora, f.slo_frescor_h, estado_fonte=f.estado, motivo_estado=f.motivo_estado,
                              formato=f.formato_frescor)
            rot = {"detalhe_de": "frescor.fontes_atrasadas", "fonte": fid, "estado_fonte": f.estado,
                   "slo_h": f.slo_frescor_h, "sensor": a["estado"]}
            out.append(Leitura("frescor.atraso_h", a["valor"], motivo=a["detalhe"], rotulos=rot))
            if a["estado"] == si.ALERTA and f.estado in ("ATIVA", "PARCIAL"):
                atrasadas.append(fid)
            elif a["estado"] == si.INDISPONIVEL and f.estado in ("ATIVA", "PARCIAL"):
                cegas.append(fid)
            elif f.estado not in ("ATIVA", "PARCIAL"):
                declaradas.append(fid)
    finally:
        con.close()
    out.insert(0, Leitura("frescor.fontes_atrasadas", float(len(atrasadas)),
                          motivo=("atrasadas: " + ", ".join(atrasadas)) if atrasadas else "",
                          rotulos={"atrasadas": atrasadas, "sem_medida": cegas, "paradas_declaradas": declaradas}))
    return out


def g_frescor_visoes(ctx: Ctx) -> list[Leitura]:
    """Frescor das visões materializadas do E15 (O7.1; dono: estagios/materializar.py)."""
    from compliance_agent.aplicacao.estagios.materializar import g_visoes
    return g_visoes(ctx)


def custo_mes(gateway_usd: float | None, gateway_n: int, legado_usd: float, livro: Mapping | None,
              mes: str) -> tuple[float | None, dict, str]:
    """Gasto pago do mês (US$) somando as fontes sem contar duas vezes. Puro.
    · gateway (llm_trace.origem='gateway', pago=1) — quando JÁ gravou neste mês, ele é a fonte da API do Claude (o
      backend api do gateway leva o custo do livro-caixa para o `custo_usd`);
    · senão, o livro-caixa da API (data/claude_api_gasto.json), que é CUMULATIVO: só conta se começou neste mês
      (`desde`); começou antes ⇒ não dá para separar o mês ⇒ INDISPONIVEL (subestimar seria pior que não medir);
    · mais as chamadas pagas do trace antigo (`usd` > 0, ex.: openrouter_pago), que o gateway não cobre."""
    partes = {"legado_trace_usd": round(legado_usd, 4)}
    if gateway_usd is not None and gateway_n > 0:
        partes["gateway_usd"] = round(gateway_usd, 4)
        return round(gateway_usd + legado_usd, 4), partes, "gateway + trace antigo"
    if not livro:
        return None, partes, "sem gateway no mês e sem livro-caixa da API: gasto da API do Claude não medido"
    desde = str(livro.get("desde") or "")
    if desde[:7].replace("-", "") != mes.replace("-", ""):
        return None, partes, f"livro-caixa da API é cumulativo desde {desde[:10] or '?'}: o mês {mes} não se separa"
    partes["claude_api_usd"] = round(float(livro.get("total_usd") or 0.0), 4)
    return round(partes["claude_api_usd"] + legado_usd, 4), partes, \
        f"livro-caixa da API (desde {desde[:10]}) + trace antigo; gateway ainda sem chamada paga gravada no mês"


def g_llm(ctx: Ctx) -> list[Leitura]:
    con = _sqlite_ro(ctx.data / "llm_trace.db", timeout=10)
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(llm_trace)")}
        gw, gn = None, 0
        if {"origem", "pago", "custo_usd", "ts"} <= cols:
            # mesma soma de adaptadores/llm/gateway.gasto_mes_usd, em conexão SÓ LEITURA (a do gateway migra o schema)
            gw, gn = con.execute("SELECT COALESCE(SUM(custo_usd), 0), COUNT(*) FROM llm_trace WHERE origem='gateway' "
                                 "AND pago=1 AND strftime('%Y-%m', ts)=?", (mes,)).fetchone()
        legado = 0.0
        if "usd" in cols:
            filtro = " AND COALESCE(origem, '') != 'gateway'" if "origem" in cols else ""
            legado = float(con.execute(f"SELECT COALESCE(SUM(usd), 0) FROM llm_trace WHERE usd > 0 "
                                       f"AND strftime('%Y-%m', ts)=?{filtro}", (mes,)).fetchone()[0])
    finally:
        con.close()
    q = ctx.data / "claude_api_gasto.json"
    livro = json.loads(_ler(q)) if q.exists() else None
    valor, partes, como = custo_mes(None if gw is None else float(gw), int(gn or 0), legado, livro, mes)
    pol = yaml.safe_load((ctx.raiz / "config" / "llm_politica.yaml").read_text(encoding="utf-8")) or {}
    rot = {"mes": mes, "teto_usd": (pol.get("orcamento_mensal") or {}).get("teto_usd"), "como": como, **partes}
    if valor is None:
        return [nao_mediu("llm.custo_mes_usd", como, **rot)]
    return [Leitura("llm.custo_mes_usd", valor, rotulos=rot)]


def g_pericia(ctx: Ctx) -> list[Leitura]:
    from tools.automelhoria_geral import _cobertura_acervo
    total, alc, procs, cortados = _cobertura_acervo()
    if total <= 0:
        return [nao_mediu("pericia.cobertura_chars", "nenhum manifesto com texto em data/sei_arquivo")]
    return [Leitura("pericia.cobertura_chars", round(alc / total, 4),
                    rotulos={"acervo_chars": total, "alcancavel_chars": alc, "processos": procs,
                             "processos_cortados": cortados})]


def g_opus(ctx: Ctx) -> list[Leitura]:
    con = _sqlite_ro(ctx.data / "conferencia_opus.db", timeout=10)
    desde = datetime.fromtimestamp(ctx.agora.timestamp() - 7 * 86400).strftime("%Y-%m-%d %H:%M:%S")
    norm = lambda c: f"REPLACE({c}, 'T', ' ')"  # noqa: E731 — datas ISO com 'T' (timestamp-iso-com-T)
    try:
        ent = con.execute(f"SELECT COUNT(*) FROM fila WHERE {norm('criado_em')} >= ?", (desde,)).fetchone()[0]
        sai = con.execute(f"SELECT COUNT(*) FROM fila WHERE {norm('conferido_em')} >= ?", (desde,)).fetchone()[0]
        pend = con.execute("SELECT COUNT(*) FROM fila WHERE status = 'pendente'").fetchone()[0]
    finally:
        con.close()
    r, motivo = razao_opus(int(ent), int(sai))
    return [Leitura("opus.saida_por_entrada_7d", r, motivo=motivo, rotulos={"entradas_7d": ent, "saidas_7d": sai}),
            Leitura("opus.pendentes", float(pend))]


def texto_dos_logs(data: Path, arq: str, rotina: str) -> str | None:
    """O log do cron (antes da religação) + o log da rotina no motor (data/logs/fluxo/<rotina>.log, desde a O9.0):
    26/11/2026 o sensor lia só o do cron, parado, e acusava 31 h com o backup do dia feito. Nenhum dos dois = None."""
    partes = [_ler(p) for p in (data / arq, data / "logs" / "fluxo" / f"{rotina}.log") if p.exists()]
    return "\n".join(partes) if partes else None


def g_backup(ctx: Ctx) -> list[Leitura]:
    agora = ctx.agora_local
    out = []
    for nome, arq, rotina, fn in (
            ("backup.compliance_idade_h", "backup_compliance_cron.log", "backup_compliance", ultimo_backup_compliance),
            ("backup.evidencias_pg_idade_h", "backup_evidencias_pg.log", "backup_evidencias_pg", ultimo_dump_guardado)):
        txt = texto_dos_logs(ctx.data, arq, rotina)
        if txt is None:
            out.append(nao_mediu(nome, f"{arq} e logs/fluxo/{rotina}.log ausentes: nenhum backup registrado"))
            continue
        h = idade_h(fn(txt), agora)
        out.append(Leitura(nome, h, rotulos={"log": arq}) if h is not None else
                   nao_mediu(nome, f"{arq} sem backup concluído reconhecível"))
    rm = _restauracao_metricas(ctx.con, ctx.agora.timestamp()) if ctx.con is not None else None
    out.append(rm or _restauracao(ctx.data / "plataforma" / "restauracao_pg.json", agora))
    db = ctx.data / "compliance.db"
    if not db.exists():
        out.append(nao_mediu("sqlite.wal_mb", "compliance.db ausente neste nó"))
    else:
        wal = db.with_name(db.name + "-wal")
        out.append(Leitura("sqlite.wal_mb", round(wal.stat().st_size / 2**20, 2) if wal.exists() else 0.0,
                           rotulos={} if wal.exists() else {"sem_wal": True}))
    return out


def restauracao_de_linhas(ok: float | None, quando_epoch: float | None, rotulos: Mapping | None, no: str | None,
                          agora_epoch: float) -> Leitura | None:
    """A última execução de `tools/restauracao_semanal.py gravar` (E17, O8.2): o par `backup.restauracao_ok` (1/0) e
    `backup.restauracao_quando` (epoch do fim) da MESMA execução, em fluxo.metricas. Puro. Sem par = None (o chamador
    cai no JSON antigo do restaurar_teste.sh)."""
    q = _num(quando_epoch)
    if q is None:
        return None
    rot = dict(rotulos or {})
    if _num(ok) is None:
        return nao_mediu("restauracao.pg_idade_h", "backup.restauracao_quando sem o backup.restauracao_ok da mesma "
                         "execução: resultado não se sabe", execucao=rot.get("execucao"))
    base = {"resultado": "ok" if _num(ok) == 1.0 else "falhou", "execucao": rot.get("execucao"), "no_restauracao": no,
            "fonte_sensor": "fluxo.metricas backup.restauracao_*"}
    h = round((agora_epoch - q) / 3600.0, 2)
    if _num(ok) == 1.0:
        return Leitura("restauracao.pg_idade_h", h, rotulos=base)
    return Leitura("restauracao.pg_idade_h", h, forcado=BLOQUEADO, rotulos=base,
                   motivo=f"a última restauração FALHOU: {', '.join(rot.get('falhas') or []) or 'ver rotulos'}"[:240])


def _restauracao_metricas(con, agora_epoch: float) -> Leitura | None:
    r = con.execute(
        "SELECT q.no, q.valor, q.rotulos, (SELECT o.valor FROM metricas o WHERE o.nome = 'backup.restauracao_ok' AND "
        "o.rotulos->>'execucao' = q.rotulos->>'execucao' ORDER BY o.quando DESC LIMIT 1) FROM metricas q "
        "WHERE q.nome = 'backup.restauracao_quando' AND q.valor = q.valor ORDER BY q.quando DESC LIMIT 1").fetchone()
    if r is None:
        return None
    no, quando, rot, ok = r
    return restauracao_de_linhas(ok, quando, rot, no, agora_epoch)


def _restauracao(p: Path, agora: datetime) -> Leitura:
    nome = "restauracao.pg_idade_h"
    if not p.exists():
        return nao_mediu(nome, "nenhuma restauração registrada: nem backup.restauracao_* em fluxo.metricas "
                         "(tools/restauracao_semanal.py, O8.2) nem data/plataforma/restauracao_pg.json")
    d = json.loads(_ler(p))
    em = datetime.strptime(str(d.get("em")), "%Y-%m-%d %H:%M:%S")
    h = idade_h(em, agora)
    if d.get("estado") == "ok":
        return Leitura(nome, h, rotulos={"resultado": "ok"})
    return Leitura(nome, h, forcado=BLOQUEADO, rotulos={"resultado": d.get("estado")},
                   motivo=f"o último teste de restauração FALHOU: {str(d.get('detalhe'))[:200]}")


_QUICK_CHECK = ("import sqlite3, sys\n"
                "c = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True, timeout=120)\n"
                "print(c.execute('PRAGMA quick_check(1)').fetchone()[0])\n")


TRAVA_QUICK_CHECK = "data/locks/db_integridade.lock"   # a MESMA do remédio painel_shm: nunca 2 quick_check juntos
MARCA_INCIDENTE_DB = "data/.observar_db_corrompido.alertado"


def quick_check_ro(db: Path, trava: Path, timeout_s: int = 900) -> tuple[str | None, float, str]:
    """PRAGMA quick_check(1) do banco em modo SÓ LEITURA, num processo-filho com ionice -c3/nice 19, sob trava
    própria não bloqueante. (saída | None, segundos, motivo de não ter medido). Trava ocupada ⇒ None (não mediu)."""
    import fcntl
    trava.parent.mkdir(parents=True, exist_ok=True)
    with trava.open("a") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None, 0.0, "outra quick_check em curso (trava ocupada)"
        prio = ((["ionice", "-c3"] if shutil.which("ionice") else []) +
                (["nice", "-n19"] if shutil.which("nice") else []))
        t0 = time.monotonic()
        r = subprocess.run(prio + [sys.executable, "-c", _QUICK_CHECK, str(db)], capture_output=True, text=True,
                           timeout=timeout_s)
        seg = round(time.monotonic() - t0, 1)
    if r.returncode != 0:
        return None, seg, f"quick_check não rodou (rc={r.returncode}): {(r.stderr or '').strip()[-200:]}"
    return (r.stdout or "").strip(), seg, ""


def incidente(marca: Path, ok: bool) -> str:
    """Regra de marca do guardião: o incidente abre UMA vez (marca criada no primeiro resultado ruim) e fecha quando
    volta ao normal (marca removida, para o próximo incidente voltar a avisar). 'novo' | 'aberto' | 'encerrado' | ''."""
    if ok:
        if marca.exists():
            marca.unlink()
            return "encerrado"
        return ""
    if marca.exists():
        return "aberto"
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    return "novo"


def g_integridade(ctx: Ctx) -> list[Leitura]:
    """`db.integridade` (absorve a sonda proativa do tools/guardiao_db_malformed.sh): 1 = quick_check ok; resultado
    não-ok = BLOQUEADO, e o ALERTA é por incidente (rotulo `incidente`: 'novo' só na primeira medida ruim). Nada
    reinicia aqui — o remédio painel_shm (compliance_agent/fluxo/remedios.py) é que decide, e só com o arquivo ok."""
    nome = "db.integridade"
    db = ctx.data / "compliance.db"
    if not db.exists():
        return [nao_mediu(nome, "compliance.db ausente neste nó")]
    saida, seg, erro = quick_check_ro(db, ctx.raiz / TRAVA_QUICK_CHECK)
    if saida is None:
        return [nao_mediu(nome, erro, segundos=seg)]
    inc = incidente(ctx.raiz / MARCA_INCIDENTE_DB, saida == "ok")
    rot = {"segundos": seg, **({"incidente": inc} if inc else {})}
    if saida == "ok":
        return [Leitura(nome, 1.0, rotulos=rot)]
    return [Leitura(nome, 0.0, forcado=BLOQUEADO, rotulos=rot,
                    motivo=f"quick_check={saida[:200]} — corrupção REAL: não reiniciar, perícia de dado")]


def g_rotinas(ctx: Ctx) -> list[Leitura]:
    from tools import pipelines_slo, sentinela_integridade
    itens = pipelines_slo.checar()
    ruins = [i["nome"] for i in itens if i["status"] in ("stale", "ausente")]
    out = [Leitura("pipelines.atrasadas", float(len(ruins)), rotulos={"etapas": len(itens), "atrasadas": ruins[:40]},
                   motivo=("atrasadas: " + ", ".join(ruins[:10])) if ruins else "")]
    inv = sentinela_integridade.checar()
    violadas = [i["invariante"] for i in inv if i.get("estado") == "violado"]
    cegas = [i["invariante"] for i in inv if i.get("estado") in ("erro", "indisponivel")]
    if inv and len(cegas) == len(inv):
        out.append(nao_mediu("integridade.violacoes", "nenhuma invariante da sentinela mediu", cegas=cegas))
    else:
        out.append(Leitura("integridade.violacoes", float(len(violadas)),
                           rotulos={"violadas": violadas, "sem_medida": cegas, "invariantes": len(inv)}))
    return out


def g_qualidade(ctx: Ctx) -> list[Leitura]:
    p = ctx.data / "qualidade_estado.json"
    if not p.exists():
        return [nao_mediu("qualidade.bloqueantes", "sem fotografia (qualidade_estado.json) — sensores nunca rodaram")]
    d = json.loads(_ler(p))
    b = _num(d.get("bloqueantes"))
    if b is None:
        return [nao_mediu("qualidade.bloqueantes", "fotografia sem o campo 'bloqueantes'")]
    return [Leitura("qualidade.bloqueantes", b, rotulos={"medido_em": d.get("em"), "total": d.get("total")})]


def g_assistentes(ctx: Ctx) -> list[Leitura]:
    out = []
    p = ctx.data / "claude_assinatura_uso.json"
    if p.exists():
        from compliance_agent.llm.ritmo_assinatura import classificar
        c = classificar(json.loads(_ler(p)), agora=ctx.agora.timestamp())
        if c.get("medido") and c.get("semana_pct") is not None and c.get("linha_pct") is not None:
            out.append(Leitura("assinatura.ritmo_pp", round(float(c["semana_pct"]) - float(c["linha_pct"]), 2),
                               motivo=c.get("motivo") or "", rotulos={"nivel": c.get("nivel"),
                                                                       "semana_pct": c["semana_pct"],
                                                                       "linha_pct": c["linha_pct"]}))
        else:
            out.append(nao_mediu("assinatura.ritmo_pp", c.get("motivo") or "medição da assinatura inválida"))
    else:
        out.append(nao_mediu("assinatura.ritmo_pp", "claude_assinatura_uso.json ausente"))
    inbox = Path.home() / "shared-brain" / "_handoff" / "from-vm2"
    cursor = inbox.parent / ".core_seen.json"
    if inbox.is_dir():
        vistos = set(json.loads(_ler(cursor))) if cursor.exists() else set()
        novos = sorted(f.name for f in inbox.glob("*.md") if f.name not in vistos)
        out.append(Leitura("handoff.nao_lidos", float(len(novos)), rotulos={"arquivos": novos[:20]}))
    else:
        out.append(nao_mediu("handoff.nao_lidos", "inbox de passagem ausente neste nó"))
    for nome, arq, status in (("yoda.falhas_abertas", "yoda_melhorias_fila.json", ("aberto", "REINCIDIU")),
                              ("automelhoria.reincidiu", "automelhoria_fila.json", ("REINCIDIU",))):
        q = ctx.data / arq
        if not q.exists():
            out.append(nao_mediu(nome, f"{arq} ausente"))
            continue
        d = json.loads(_ler(q))
        itens = [k for k, v in d.items() if isinstance(v, dict) and v.get("status") in status]
        out.append(Leitura(nome, float(len(itens)), rotulos={"itens": itens[:20], "fila": len(d)}))
    return out


# ── domínio da esteira no PG (captura, cobertura, prova) e custo/FP (O8.1) ─────────────────────────────────────────
ENV_ESQUEMA_CAPTURA = "JFN_CAPTURA_ESQUEMA"       # o mesmo do E2/E3 (aplicacao/estagios/arvore.py), padrão `public`
ENV_ESQUEMA_FATOS = "JFN_FATOS_ESQUEMA"           # o mesmo do E8 (aplicacao/estagios/fatos.py), padrão `public`
FONTE_E3 = "sei:e3"                               # aquisicao.fonte do E3 capturar


def _esq(env: str) -> str:
    from compliance_agent.fluxo.schema import validar_esquema
    return validar_esquema(os.environ.get(env) or "public")


def _tem_tabela(con, esquema: str, tabela: str) -> bool:
    return con.execute("SELECT to_regclass(%s)", (f'"{esquema}"."{tabela}"',)).fetchone()[0] is not None


def _tem_coluna(con, esquema: str, tabela: str, coluna: str) -> bool:
    return con.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND "
                       "column_name = %s", (esquema, tabela, coluna)).fetchone() is not None


def pct(parte: float, todo: float) -> float | None:
    """parte ÷ todo × 100 com 2 casas; todo ≤ 0 = None (não há o que medir — nunca 0 % nem 100 %)."""
    return None if not todo or todo <= 0 else round(100.0 * float(parte) / float(todo), 2)


def captura_util(capturados: int, novas: int, aquisicoes: int, sem_novidade: int) -> tuple[float | None, float | None]:
    """(útil %, duplicidade %) das aquisições do E3 na janela. Puro. Útil = versões NOVAS ÷ documentos baixados;
    duplicidade = aquisições que não trouxeram nenhuma versão nova (recaptura sem novidade) ÷ aquisições."""
    return pct(novas, capturados), pct(sem_novidade, aquisicoes)


def g_captura(ctx: Ctx) -> list[Leitura]:
    """Captura útil, duplicidade e cobertura do acervo — do PG (ADR-001), esquema do E2/E3. Global: mede onde o PG
    mora. Só as aquisições do E3 (`aquisicao.fonte='sei:e3'`) dizem quantos documentos foram BAIXADOS; o legado
    (`sei_arquivo`) só diz o que entrou, então útil/duplicidade sem E3 na janela = INDISPONIVEL."""
    c = ctx.con
    if c is None:
        raise RuntimeError("sem PG: captura e cobertura moram no PG")
    e = _esq(ENV_ESQUEMA_CAPTURA)
    out: list[Leitura] = []
    if _tem_tabela(c, e, "aquisicao") and _tem_tabela(c, e, "versoes"):
        aq, capt, sem_nov, novas = c.execute(
            f'SELECT count(*), coalesce(sum((a.detalhe->>\'capturados\')::int), 0), count(*) FILTER (WHERE NOT EXISTS '
            f'(SELECT 1 FROM "{e}".versoes v WHERE v.aquisicao_id = a.id)), (SELECT count(*) FROM "{e}".versoes v '
            f'JOIN "{e}".aquisicao b ON b.id = v.aquisicao_id WHERE b.fonte = %s AND b.concluida_em > now() - '
            f'interval \'24 hours\') FROM "{e}".aquisicao a WHERE a.fonte = %s AND a.concluida_em > now() - '
            f'interval \'24 hours\'', (FONTE_E3, FONTE_E3)).fetchone()
        util, dup = captura_util(int(capt), int(novas), int(aq), int(sem_nov))
        rot = {"aquisicoes_24h": aq, "baixados_24h": capt, "versoes_novas_24h": novas, "sem_novidade_24h": sem_nov,
               "esquema": e}
        sem = "nenhuma captura do E3 nas últimas 24 h: não há o que julgar (útil/duplicidade sem tentativa)"
        out.append(Leitura("captura.util_pct", util, rotulos=rot) if util is not None else
                   nao_mediu("captura.util_pct", sem, **rot))
        out.append(Leitura("captura.duplicidade_pct", dup, rotulos=rot) if dup is not None else
                   nao_mediu("captura.duplicidade_pct", sem, **rot))
        corte = (ctx.agora_local - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")   # vista_em: texto, hora local
        n, = c.execute(f'SELECT count(*) FROM "{e}".versoes WHERE vista_em >= %s', (corte,)).fetchone()
        out.append(Leitura("captura.versoes_novas_24h", float(n),
                           rotulos={"detalhe_de": "captura.util_pct", "todas_as_origens": True}))
    else:
        out += [nao_mediu(n, f"tabelas aquisicao/versoes ausentes no esquema {e}") for n in
                ("captura.util_pct", "captura.duplicidade_pct")]
    if _tem_tabela(c, e, "documentos") and _tem_tabela(c, e, "versoes"):
        restr = "WHERE NOT coalesce(d.restrito, false)" if _tem_coluna(c, e, "documentos", "restrito") else ""
        tot, com = c.execute(f'SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM "{e}".versoes v WHERE '
                             f'v.processo = d.processo AND v.doc_id = d.doc_id)) FROM "{e}".documentos d {restr}'
                             ).fetchone()
        p = pct(com, tot)
        rot = {"documentos": tot, "com_versao": com, "sem_versao": tot - com, "exclui_restritos": bool(restr),
               "esquema": e}
        out.append(Leitura("cobertura.docs_com_versao_pct", p, rotulos=rot) if p is not None else
                   nao_mediu("cobertura.docs_com_versao_pct", f"nenhum documento em {e}.documentos", **rot))
        if _tem_tabela(c, e, "arvores"):
            procs, = c.execute(f'SELECT count(DISTINCT processo) FROM "{e}".arvores').fetchone()
            out.append(Leitura("cobertura.processos_com_arvore", float(procs),
                               rotulos={"detalhe_de": "cobertura.docs_com_versao_pct"}))
    else:
        out.append(nao_mediu("cobertura.docs_com_versao_pct", f"tabelas documentos/versoes ausentes no esquema {e}"))
    if _tem_tabela(c, e, "arvore_leitura"):
        pend = c.execute(
            f'WITH vig AS (SELECT DISTINCT ON (processo) processo, docs FROM "{e}".arvore_leitura ORDER BY processo, '
            f'id DESC) SELECT count(DISTINCT vig.processo), count(*) FROM vig, jsonb_array_elements(vig.docs) d WHERE '
            f'NOT coalesce((d->>\'restrito\')::boolean, false) AND NOT EXISTS (SELECT 1 FROM "{e}".versoes v WHERE '
            f'v.processo = vig.processo AND v.doc_id = d->>\'doc_id\')').fetchone()
        out.append(Leitura("cobertura.e3_pendentes_docs", float(pend[1]),
                           rotulos={"detalhe_de": "cobertura.docs_com_versao_pct", "processos": pend[0]}))
    else:
        out.append(nao_mediu("cobertura.e3_pendentes_docs", f"{e}.arvore_leitura ausente: o E2 ainda não gravou "
                             "leitura de árvore neste esquema (captura_001)", detalhe_de="cobertura.docs_com_versao_pct"))
    return out


def g_prova(ctx: Ctx) -> list[Leitura]:
    """Prova numérica: fatos com citação literal CONFERIDA (estado VERIFICADO do E8) ÷ todos os fatos gravados."""
    c = ctx.con
    if c is None:
        raise RuntimeError("sem PG: os fatos do E8 moram no PG")
    e = _esq(ENV_ESQUEMA_FATOS)
    if not _tem_tabela(c, e, "fatos"):
        return [nao_mediu("prova.fatos_verificados_pct", f"{e}.fatos ausente")]
    por = {str(k): int(n) for k, n in c.execute(f'SELECT estado, count(*) FROM "{e}".fatos GROUP BY 1')}
    tot = sum(por.values())
    p = pct(por.get("VERIFICADO", 0), tot)
    rot = {"total": tot, "por_estado": por, "esquema": e}
    return [Leitura("prova.fatos_verificados_pct", p, rotulos=rot) if p is not None else
            nao_mediu("prova.fatos_verificados_pct", "nenhum fato gravado pelo E8", **rot)]


def custo_por_processo(gasto_usd: float | None, chamadas: int, processos: int) -> tuple[float | None, str]:
    """US$ pagos no mês pelo gateway ÷ processos lidos no mês. Puro. Sem chamada do gateway no mês ⇒ None (o trace
    não viu nada: 0 seria mentira); sem processo lido ⇒ None."""
    if gasto_usd is None or chamadas <= 0:
        return None, "gateway sem chamada registrada no mês: custo não atribuível"
    if processos <= 0:
        return None, f"{chamadas} chamada(s) do gateway no mês e nenhum processo lido: custo sem denominador"
    return round(gasto_usd / processos, 4), f"US$ {gasto_usd:.4f} pagos ÷ {processos} processo(s) lido(s) no mês"


def g_custo_processo(ctx: Ctx) -> list[Leitura]:
    """Custo por processo: o trace do gateway (data/llm_trace.db, origem='gateway') ainda não leva o processo, então
    o sensor dá a MÉDIA do mês (pago ÷ processos lidos pelo E8 no mês, tabela `leituras` do PG) e declara isso."""
    if ctx.con is None:
        raise RuntimeError("sem PG: processos lidos (leituras) moram no PG")
    t = _sqlite_ro(ctx.data / "llm_trace.db", timeout=10)
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        cols = {r[1] for r in t.execute("PRAGMA table_info(llm_trace)")}
        if not {"origem", "pago", "custo_usd", "ts"} <= cols:
            return [nao_mediu("llm.custo_por_processo_usd", "llm_trace sem as colunas do gateway (O6.1)")]
        n, pago = t.execute("SELECT count(*), coalesce(sum(CASE WHEN pago = 1 THEN custo_usd END), 0) FROM llm_trace "
                            "WHERE origem = 'gateway' AND strftime('%Y-%m', ts) = ?", (mes,)).fetchone()
    finally:
        t.close()
    e = _esq(ENV_ESQUEMA_FATOS)
    procs = 0
    if _tem_tabela(ctx.con, e, "leituras"):
        procs, = ctx.con.execute(f'SELECT count(DISTINCT processo) FROM "{e}".leituras WHERE substr(em, 1, 7) = %s',
                                 (mes,)).fetchone()
    v, como = custo_por_processo(float(pago), int(n), int(procs))
    rot = {"mes": mes, "chamadas_gateway": n, "pago_usd": round(float(pago), 4), "processos_lidos": procs,
           "como": como, "atribuicao": "média do mês (trace do gateway sem processo — pendência O8.4)"}
    return [Leitura("llm.custo_por_processo_usd", v, rotulos=rot) if v is not None else
            nao_mediu("llm.custo_por_processo_usd", como, **rot)]


def fp_de_detector(e: Mapping, hoje=None) -> tuple[float | None, str]:
    """(taxa de FP em %, motivo) de UMA entrada do registro (config/qualidade_detectores.yaml). Puro. Só conta medida
    VÁLIDA (COR-04: completa e com ≤ 180 dias) e com decididos (n > 0); o resto é 'não medido', nunca 0 %."""
    from compliance_agent.qualidade import detectores as D
    fp = e.get("fp_medida")
    if not isinstance(fp, dict):
        return None, "sem fp_medida no registro"
    if not D._calibrado(dict(e), hoje):
        return None, "fp_medida incompleta ou vencida (> 180 dias)"
    n, k = fp.get("n"), fp.get("falsos")
    if not isinstance(n, int) or not isinstance(k, int) or n <= 0:
        return None, f"fp_medida sem decididos (n={n})"
    return round(100.0 * k / n, 2), f"{k} falso(s) em {n} decidido(s) ({fp.get('data')})"


def g_detectores(ctx: Ctx) -> list[Leitura]:
    """fp_medida por detector ATIVO do registro: uma linha por detector (detalhe) + a fração com medida válida e o
    número de detectores medidos acima do teto de FP do Tier 1 (os dois com SLO)."""
    from compliance_agent.qualidade import detectores as D
    reg = D.carregar()
    ativos = {k: v for k, v in reg.items() if (v.get("estado") or "ativo") == "ativo"}
    out, medidos, acima = [], [], []
    for did, e in sorted(ativos.items()):
        taxa, motivo = fp_de_detector(e)
        rot = {"detalhe_de": "detectores.fp_medida_pct", "detector": did, "tier": e.get("tier"),
               "manchete": bool(e.get("manchete"))}
        if taxa is None:
            out.append(nao_mediu("detector.fp_taxa_pct", motivo, **rot))
            continue
        medidos.append(did)
        if taxa > 100.0 * D.TIER1_PONTO_MAX:
            acima.append(did)
        out.append(Leitura("detector.fp_taxa_pct", taxa, motivo=motivo, rotulos=rot))
    p = pct(len(medidos), len(ativos))
    out.insert(0, Leitura("detectores.fp_medida_pct", p, rotulos={"ativos": len(ativos), "medidos": medidos})
               if p is not None else nao_mediu("detectores.fp_medida_pct", "nenhum detector ativo no registro"))
    rot = {"teto_pct": 100.0 * D.TIER1_PONTO_MAX, "acima": acima, "medidos": len(medidos)}
    out.insert(1, Leitura("detectores.fp_acima_teto", float(len(acima)), rotulos=rot) if medidos else
               nao_mediu("detectores.fp_acima_teto", "nenhum detector ativo com fp_medida válida", **rot))
    return out


ALIAS_ITCAMPO = "it-campo"      # alias do ~/.ssh/config da VM-1 (a topologia fica fora do repo — ADR-011)


def g_alcance(ctx: Ctx) -> list[Leitura]:
    """O it-campo responde pela rede? (Modern Standby: tela apagada derruba a rede.) Um `ssh … exit` com teto curto,
    medido da VM-1 — independe do heartbeat do jfn-fluxo, que só existe depois da O9.0. 1 = respondeu; 0 = não (MEDIDO:
    a máquina sumiu da rede); ssh ausente = INDISPONIVEL."""
    if not shutil.which("ssh"):
        return [nao_mediu("itcampo.alcancavel", "ssh ausente neste nó")]
    t0 = time.monotonic()
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ALIAS_ITCAMPO, "exit"],
                           capture_output=True, text=True, timeout=20)
        rc, erro = r.returncode, (r.stderr or "").strip()[-160:]
    except subprocess.TimeoutExpired:
        rc, erro = None, "ssh passou de 20 s"
    ms = round((time.monotonic() - t0) * 1000.0, 1)
    if rc == 0:
        return [Leitura("itcampo.alcancavel", 1.0, rotulos={"ms": ms})]
    return [Leitura("itcampo.alcancavel", 0.0, rotulos={"ms": ms, "rc": rc},
                    motivo=f"it-campo não respondeu ao ssh (rc={rc}): {erro}")]


@dataclass(frozen=True)
class Grupo:
    fn: Callable[[Ctx], list[Leitura]]
    nomes: tuple[str, ...]                 # sensores que o grupo promete (os que faltarem viram INDISPONIVEL)
    intervalo_s: int = 0                   # espaçamento (0 = toda coleta)


JANELA_LEITURA_S = 86400


def g_leitura(ctx: Ctx) -> list[Leitura]:
    """Leitura única (O8.5, plano §19): % de leituras de documento que REPETEM uma (estágio, tipo, sha, versão) já lida
    por outro job nas últimas 24 h (modo `rodar`; a conferência de efeito fica fora). Registro em `leitura_registro` no
    esquema do fluxo (`fluxo/leituras`, ligado por JFN_LEITURAS_REGISTRAR=1). Sem a tabela ou sem leitura na janela =
    INDISPONIVEL (não há o que julgar — nunca 0 %)."""
    from compliance_agent.fluxo import leituras as LR
    if ctx.con is None:
        raise RuntimeError("sem PG: o registro de leituras mora no esquema do fluxo")
    linhas = LR.ler_linhas(ctx.con, desde_s=JANELA_LEITURA_S)
    if linhas is None:
        return [nao_mediu("leitura.repetida_pct", f"{LR.TABELA} ausente: o registro de leituras não está ligado "
                          f"({LR.ENV_LIGADO}=1 no filho do fluxo)")]
    r = LR.resumir(linhas)
    rot = {k: r[k] for k in ("leituras", "distintas", "repetidas", "downloads", "llm", "releituras_no_job",
                             "conferencia")}
    rot["repetidas_amostra"] = r["repetidas_lista"][:10]
    if r["repetida_pct"] is None:
        return [nao_mediu("leitura.repetida_pct", "nenhuma leitura de documento nas últimas 24 h", **rot)]
    return [Leitura("leitura.repetida_pct", r["repetida_pct"], rotulos=rot)]


GRUPOS: dict[str, Grupo] = {
    "psi": Grupo(g_psi, ("psi.cpu_some", "psi.mem_some", "psi.mem_full", "psi.io_some", "psi.io_full")),
    "memoria": Grupo(g_memoria, ("swap.uso_pct", "mem.disponivel_gb")),
    "disco": Grupo(g_disco, ("disco.livre_pct", "disco.tendencia_pp_dia")),
    "navegador": Grupo(g_navegador, ("navegador.orfaos",)),
    "painel": Grupo(g_painel, ("painel.latencia_ms",)),
    "painel_malformed": Grupo(g_painel_malformed, ("painel.rotas_malformed",), intervalo_s=1800),
    "fila": Grupo(g_fila, ("fila.idade_max_s", "fila.elegiveis", "fila.quarentena", "fila.orfaos",
                           "fila.conclusoes_h", "fluxo.nos_sem_heartbeat", "fila.espera_p95_s")),
    "wal_pg": Grupo(g_wal_pg, ("wal.pg_arquivo_atraso_s",)),
    "frescor": Grupo(g_frescor, ("frescor.fontes_atrasadas",), intervalo_s=3600),
    "frescor_visoes": Grupo(g_frescor_visoes, ("visoes.atrasadas",)),
    "llm": Grupo(g_llm, ("llm.custo_mes_usd",)),
    "pericia": Grupo(g_pericia, ("pericia.cobertura_chars",), intervalo_s=21600),
    "opus": Grupo(g_opus, ("opus.saida_por_entrada_7d", "opus.pendentes")),
    "backup": Grupo(g_backup, ("backup.compliance_idade_h", "backup.evidencias_pg_idade_h", "restauracao.pg_idade_h",
                               "sqlite.wal_mb")),
    "integridade": Grupo(g_integridade, ("db.integridade",), intervalo_s=3600),
    "rotinas": Grupo(g_rotinas, ("pipelines.atrasadas", "integridade.violacoes"), intervalo_s=3600),
    "qualidade": Grupo(g_qualidade, ("qualidade.bloqueantes",)),
    "assistentes": Grupo(g_assistentes, ("assinatura.ritmo_pp", "handoff.nao_lidos", "yoda.falhas_abertas",
                                         "automelhoria.reincidiu")),
    "captura": Grupo(g_captura, ("captura.util_pct", "captura.duplicidade_pct", "cobertura.docs_com_versao_pct"),
                     intervalo_s=3600),
    "prova": Grupo(g_prova, ("prova.fatos_verificados_pct",), intervalo_s=3600),
    "custo_processo": Grupo(g_custo_processo, ("llm.custo_por_processo_usd",), intervalo_s=3600),
    "alcance": Grupo(g_alcance, ("itcampo.alcancavel",)),
    "detectores": Grupo(g_detectores, ("detectores.fp_medida_pct", "detectores.fp_acima_teto"), intervalo_s=3600),
    "leitura": Grupo(g_leitura, ("leitura.repetida_pct",)),
}


def grupos_do_no(no: str, slos: Slos) -> list[str]:
    """Grupos que valem para o nó: algum SLO de um sensor do grupo lista o nó em `nos` (o yaml decide onde mede)."""
    ps = slos.por_sensor()
    return [g for g, gr in GRUPOS.items() if any(no in ps[n][1].nos for n in gr.nomes if n in ps)]


def _medir_grupo(nome: str, gr: Grupo, ctx: Ctx) -> list[Leitura]:
    try:
        leituras = list(gr.fn(ctx))
    except _erros() as e:                                    # leitura falhou: o grupo inteiro é INDISPONIVEL
        return [nao_mediu(n, f"{type(e).__name__}: {str(e)[:240]}", grupo=nome) for n in gr.nomes]
    vistos = {x.nome for x in leituras}
    return leituras + [nao_mediu(n, "o sensor não devolveu esta medida", grupo=nome) for n in gr.nomes
                       if n not in vistos]


def _gravado_ha(con, no: str, nomes: Iterable[str]) -> float | None:
    r = con.execute("SELECT extract(epoch FROM now() - max(quando)) FROM metricas WHERE no = %s AND nome = ANY(%s)",
                    (no, list(nomes))).fetchone()
    return None if r is None or r[0] is None else float(r[0])


def linha_de(leitura: Leitura, no: str, coleta: str, slos_por_sensor: Mapping[str, tuple[str, Slo]]) -> tuple:
    """(no, nome, valor, rotulos_json). NaN quando não mediu (a coluna é NOT NULL; NaN ≠ 0 e o leitor o trata)."""
    rot = {"coleta": coleta, **leitura.rotulos}
    if leitura.motivo:
        rot["motivo"] = leitura.motivo
    if leitura.forcado:
        rot["forcado"] = leitura.forcado
    if leitura.nome in slos_por_sensor:
        sid, slo = slos_por_sensor[leitura.nome]
        rot["slo"], rot["unidade"] = sid, slo.unidade
        rot["estado"] = avaliar(slo, leitura.valor, leitura.forcado)[0]
    elif leitura.valor is None:
        rot["estado"] = INDISPONIVEL
    v = leitura.valor if _num(leitura.valor) is not None else float("nan")
    return no, leitura.nome, float(v), json.dumps(rot, ensure_ascii=False, default=str)


def coletar(con, no: str, slos: Slos | None = None, *, grupos: Iterable[str] | None = None, forcar: bool = False,
            agora: datetime | None = None, coleta: str | None = None) -> dict:
    """Mede os grupos do nó e grava em `metricas` numa transação. Devolve {coleta, gravadas, conferidas, grupos,
    pulados}. `conferidas` = recontagem no PG pela etiqueta `coleta` (o efeito do estágio)."""
    slos = slos or carregar_slos()
    coleta = coleta or uuid.uuid4().hex
    m = medir(con, no, slos, grupos=grupos, forcar=forcar, agora=agora, coleta=coleta)
    return gravar_medidas(con, m, slos)


def medir(con, no: str, slos: Slos, *, grupos: Iterable[str] | None = None, forcar: bool = False,
          agora: datetime | None = None, coleta: str | None = None) -> dict:
    """Só MEDE (não grava): {coleta, no, linhas, grupos, pulados}. Com `con=None` mede o que não depende do PG — é
    como o nó sem psycopg (it-campo antes da O9.0) mede; outro nó grava com `gravar_medidas`."""
    ps = slos.por_sensor()
    coleta = coleta or uuid.uuid4().hex
    ctx = Ctx(no=no, con=con, agora=agora or datetime.now(timezone.utc))
    alvo = list(grupos) if grupos else grupos_do_no(no, slos)
    linhas, pulados, por_grupo = [], {}, {}
    for g in alvo:
        gr = GRUPOS[g]
        if gr.intervalo_s and not forcar and con is not None:
            ha = _gravado_ha(con, no, gr.nomes)
            if ha is not None and ha < gr.intervalo_s:
                pulados[g] = f"medido há {ha / 60:.0f} min (< {gr.intervalo_s / 60:.0f} min)"
                continue
        ls = _medir_grupo(g, gr, ctx)
        por_grupo[g] = len(ls)
        linhas += [linha_de(x, no, coleta, ps) for x in ls]
    return {"coleta": coleta, "no": no, "linhas": linhas, "grupos": por_grupo, "pulados": pulados,
            "agora": ctx.agora.timestamp()}


def _completar_sem_pg(con, linhas: list[tuple], slos: Slos, agora_epoch: float) -> list[tuple]:
    """Linhas medidas sem PG que o PG completa ao gravar: a tendência do disco (a série mora em fluxo.metricas)."""
    ps = slos.por_sensor()
    livre = {no: v for no, nome, v, _r in linhas if nome == "disco.livre_pct" and _num(v) is not None}
    out = []
    for no, nome, v, rj in linhas:
        rot = json.loads(rj)
        if nome == "disco.tendencia_pp_dia" and rot.get("recalcular_com_pg") and no in livre:
            t = tendencia_disco(con, no, float(livre[no]), agora_epoch)
            t.rotulos["medido_sem_pg"] = True
            no, nome, v, rj = linha_de(t, no, rot["coleta"], ps)
        out.append((no, nome, v, rj))
    return out


def gravar_medidas(con, m: Mapping, slos: Slos) -> dict:
    """Grava as linhas de `medir` numa transação e reconta pela etiqueta `coleta` (o efeito)."""
    linhas = _completar_sem_pg(con, [tuple(x) for x in m["linhas"]], slos, float(m.get("agora") or time.time()))
    with con.transaction():
        with con.cursor() as cur:
            cur.executemany("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (%s, %s, %s, %s::jsonb)", linhas)
    conferidas = contar_coleta(con, m["coleta"])
    return {"coleta": m["coleta"], "no": m["no"], "gravadas": len(linhas), "conferidas": conferidas,
            "grupos": m["grupos"], "pulados": m["pulados"]}


def contar_coleta(con, coleta: str) -> int:
    return int(con.execute("SELECT count(*) FROM metricas WHERE rotulos->>'coleta' = %s", (coleta,)).fetchone()[0])


def conectar_leitura(dsn: str | None = None, esquema: str | None = None, timeout_s: int = 5):
    """Sessão do painel: o servidor recusa escrita (READ ONLY), conexão e consulta com teto curto (rota não pendura
    o painel se a VM-2 sumir) e search_path só no esquema do fluxo."""
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    from compliance_agent.fluxo.fila import esquema_vigente
    from compliance_agent.fluxo.schema import validar_esquema
    dsn = dsn or dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    con = psycopg.connect(dsn, autocommit=True, connect_timeout=timeout_s)
    con.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    con.execute(f"SET statement_timeout = {int(timeout_s * 1000)}")
    con.execute(f'SET search_path TO "{validar_esquema(esquema or esquema_vigente())}"')
    return con


SQL_ULTIMOS = ("SELECT DISTINCT ON (no, nome) no, nome, valor, extract(epoch FROM quando), rotulos FROM metricas "
               "WHERE nome = ANY(%s) AND quando > now() - make_interval(secs => %s) ORDER BY no, nome, quando DESC")


def ler_ultimos(con, slos: Slos) -> list[dict]:
    """Última linha de cada (nó, sensor com SLO), dentro da maior janela (o resto seria INDISPONIVEL de todo modo)."""
    nomes = list(slos.por_sensor())
    janela = max(s.janela_s for s in slos.slos.values())
    return [{"no": no, "nome": nome, "valor": valor, "quando": float(q), "rotulos": rot or {}}
            for no, nome, valor, q, rot in con.execute(SQL_ULTIMOS, (nomes, float(janela)))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.fluxo.sensores")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coletar")
    c.add_argument("--no", required=True, choices=NOS_FLUXO)
    c.add_argument("--grupo", action="append", choices=sorted(GRUPOS), default=None)
    c.add_argument("--forcar", action="store_true", help="ignora o espaçamento dos sensores caros")
    sub.add_parser("estado")
    a = ap.parse_args(argv)
    from compliance_agent.fluxo import fila
    slos = carregar_slos()
    con = fila.conectar()
    try:
        if a.cmd == "estado":
            print(json.dumps(estado_slos(ler_ultimos(con, slos), slos), ensure_ascii=False, indent=1, default=str))
            return 0
        try:
            os.nice(10)
        except OSError:
            pass
        r = coletar(con, a.no, slos, grupos=a.grupo, forcar=a.forcar)
    finally:
        con.close()
    print(json.dumps(r, ensure_ascii=False, default=str))
    if r["conferidas"] != r["gravadas"] or not r["gravadas"]:
        print(f"observar: efeito NÃO conferido ({r['conferidas']} de {r['gravadas']} linha(s))", file=sys.stderr)
        return 1
    # a linha que a rotina legado:observar_* confere no log (efeito.log_contem) — só sai depois da recontagem
    print(f"observar: {r['conferidas']} linha(s) conferida(s) em fluxo.metricas (coleta {r['coleta']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
