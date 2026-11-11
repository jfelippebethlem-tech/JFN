# -*- coding: utf-8 -*-
"""Coletor do AO VIVO: transforma o estado REAL da máquina em {motores, eventos}.

Quatro fontes, todas de leitura:
  1. `systemctl --user show`  — ActiveState/SubState/desde/código de saída dos serviços e a próxima
                                execução dos timers (duas chamadas por leitura, para todas as units);
  2. `/proc/locks`            — arquivo de trava preso = job rodando AGORA (cron sem unit). Lê o
                                kernel; não tenta pegar a trava (pegar, mesmo por um instante, faria
                                o job real desistir com "já rodando");
  3. logs conhecidos          — só linhas que casam a LISTA BRANCA de `motores.yaml` viram evento;
  4. `MAX(rowid)` de tabelas  — salto entre leituras = linhas novas (bancos abertos em `mode=ro`);
  5. `efeito` (opcional)      — onde o trabalho do motor APARECE (coluna de data, mtime de arquivo ou
                                valor de log). Medido em 11/11/2026: o painel via 2 dos 5 vermelhos,
                                porque `sei-varredura` e `bombeiros` rodavam com exit 0 sem produzir.

Um coletor por processo, com trava e intervalo mínimo: dez abas abertas não multiplicam o trabalho.
INDISPONÍVEL ≠ ocioso: se o systemd não responde, o motor sai como `indisponivel`, nunca "parado".
"""
from __future__ import annotations

import logging
import http.client
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

import yaml

from compliance_agent.aovivo.saneamento import sanear

_AQUI = Path(__file__).resolve().parent
_REPO = _AQUI.parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR") or (_REPO / "data"))
INTERVALO = 3.0            # s entre leituras de systemd/log
INTERVALO_CONTADOR = 20.0  # s entre leituras de MAX(rowid)
INTERVALO_EFEITO = 300.0   # s entre medições do efeito (efeito se mede em horas, não em segundos)
_RE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ANEL = 240                 # eventos guardados (replay por Last-Event-ID)
_PROPS = "Id,ActiveState,SubState,Type,Result,ExecMainStatus,ExecMainStartTimestamp,ActiveEnterTimestamp,InactiveEnterTimestamp,StateChangeTimestamp,LoadState"
_RE_TS_LOG = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})( UTC)?\]")
_RE_TS_TIMER = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{2})(\d{2})?")


def catalogo() -> list[dict]:
    return yaml.safe_load((_AQUI / "motores.yaml").read_text(encoding="utf-8"))["motores"]


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def _unix(v: str | None) -> float | None:
    """'@1794214860' (systemctl --timestamp=unix) → 1794214860.0; vazio/0 → None."""
    if v and v.startswith("@"):
        try:
            x = float(v[1:])
            return x if x > 0 else None
        except ValueError:
            return None
    return None


def _ts_timer(v: str | None) -> float | None:
    """'Mon 2026-11-16 06:00:00 -03' → epoch (os campos *USec* do timer ignoram --timestamp=unix)."""
    m = _RE_TS_TIMER.search(v or "")
    if not m:
        return None
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{m.group(3)}:{m.group(4) or '00'}").timestamp()
    except ValueError:
        return None


def _ts_texto(v) -> float | None:
    """'2026-11-11T14:44:12' / '2026-11-11 14:44:12' (hora local se sem fuso) → epoch; resto → None."""
    try:
        dt = datetime.fromisoformat(str(v).strip().replace(" ", "T", 1)[:32])
    except (TypeError, ValueError):
        return None
    return (dt if dt.tzinfo else dt.astimezone()).timestamp()


def medir_efeito(cfg: dict) -> float | None:
    """Epoch do ÚLTIMO efeito do motor, ou None se não dá para medir (INDISPONÍVEL ≠ parado).

      {db, tabela, coluna}  MAX(coluna) de data (banco em `mode=ro`) — use coluna indexada ou tabela pequena
      {arquivo}             mtime do arquivo
      {log, regex}          hora da última linha em que o 1º grupo MUDOU de valor (cauda de 512 KB) —
                            para motor que repete o mesmo placar a cada lote (bombeiros: "LACUNA: 9459");
                            `sentido: desce|sobe` conta só a mudança na direção do progresso (a lacuna
                            dos bombeiros SUBIU 9.458→9.459 em 09/11 — processo novo, não trabalho feito)
    """
    try:
        if cfg.get("arquivo"):
            a = Path(cfg["arquivo"])
            return (a if a.is_absolute() else _REPO / a).stat().st_mtime
        if cfg.get("log"):
            lg = Path(cfg["log"]) if os.path.isabs(cfg["log"]) else _REPO / cfg["log"]
            rg = re.compile(cfg["regex"])
            with open(lg, "rb") as f:
                tam = f.seek(0, 2)
                f.seek(max(0, tam - 512_000))
                bloco = f.read().decode("utf-8", "replace")
            ult_val, mudou_em, primeira = None, None, None
            for ln in bloco.splitlines():
                mm, mt = rg.search(ln), _RE_TS_LOG.match(ln)
                if not mm or not mt:
                    continue
                ts = _ts_texto(f"{mt.group(1)}T{mt.group(2)}")
                primeira = primeira or ts
                if ult_val is not None and mm.group(1) != ult_val:
                    sentido = cfg.get("sentido")
                    try:
                        a, b = float(ult_val), float(mm.group(1))
                    except ValueError:
                        a = b = None
                    if not sentido or a is None or (b < a if sentido == "desce" else b > a):
                        mudou_em = ts
                ult_val = mm.group(1)
            # sem mudança na cauda: o efeito é no máximo tão recente quanto a 1ª linha lida
            return mudou_em or primeira
        if cfg.get("db"):
            if not (_RE_IDENT.match(cfg.get("tabela", "")) and _RE_IDENT.match(cfg.get("coluna", ""))):
                return None
            arq = DATA / cfg["db"]
            if not arq.exists():
                return None
            c = sqlite3.connect(f"file:{arq}?mode=ro", uri=True, timeout=2)
            try:
                v = c.execute(f"SELECT MAX({cfg['coluna']}) FROM {cfg['tabela']}").fetchone()[0]
            finally:
                c.close()
            return _ts_texto(v) if v else None
    except (OSError, sqlite3.Error, re.error, KeyError, TypeError):
        return None
    return None


def efeito_parado(ultimo: float | None, horas: float, agora: float) -> bool | None:
    """True = o efeito não avança há mais de `horas`; None = não medido."""
    if ultimo is None:
        return None
    return agora - ultimo > horas * 3600


def ler_systemd(units: list[str]) -> dict[str, dict] | None:
    """{unit: props} para serviços e timers. None = systemd não respondeu (INDISPONÍVEL)."""
    if not units:
        return {}
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    out: dict[str, dict] = {}
    try:
        for sufixo, props in ((".service", _PROPS), (".timer", "Id,ActiveState,NextElapseUSecRealtime,LastTriggerUSec,LoadState")):
            r = subprocess.run(["systemctl", "--user", "show", "--timestamp=unix", "-p", props, *[u + sufixo for u in units]],
                               capture_output=True, text=True, timeout=8, env=env)
            if r.returncode != 0 and not r.stdout.strip():
                return None
            for bloco in r.stdout.split("\n\n"):
                d = dict(ln.split("=", 1) for ln in bloco.splitlines() if "=" in ln)
                if d.get("Id"):
                    out[d["Id"]] = d
    except (OSError, subprocess.SubprocessError):
        return None
    return out


def travas_presas() -> set[tuple[int, int]] | None:
    """{(dispositivo, inode)} de toda trava presa agora, lido de /proc/locks. None = não deu para ler."""
    try:
        presas = set()
        for ln in Path("/proc/locks").read_text().splitlines():
            p = ln.split()
            if len(p) >= 6 and p[5].count(":") == 2:
                ma, mi, ino = p[5].split(":")
                presas.add((os.makedev(int(ma, 16), int(mi, 16)), int(ino)))
        return presas
    except (OSError, ValueError):
        return None


def trava_presa(caminho: Path, presas: set | None) -> bool | None:
    if presas is None:
        return None
    try:
        st = caminho.stat()
    except OSError:
        return False
    return (st.st_dev, st.st_ino) in presas


def estado_do_motor(svc: dict | None, timer: dict | None, presa: bool | None, agora: float) -> dict:
    """Estado de UM motor a partir do que o systemd/kernel disseram. Função pura (testada)."""
    out = {"estado": "ocioso", "desde": None, "proxima": None, "saida": None}
    if svc is not None and svc.get("LoadState") != "not-found":
        act = svc.get("ActiveState")
        try:
            out["saida"] = int(svc.get("ExecMainStatus") or 0)
        except ValueError:
            out["saida"] = None
        if act == "failed":
            out["estado"] = "falhou"
            out["desde"] = _unix(svc.get("InactiveEnterTimestamp")) or _unix(svc.get("StateChangeTimestamp"))
        elif act in ("active", "activating", "reloading", "deactivating"):
            out["estado"] = "rodando"
            out["desde"] = _unix(svc.get("ActiveEnterTimestamp")) or _unix(svc.get("ExecMainStartTimestamp")) or _unix(svc.get("StateChangeTimestamp"))
        else:
            out["desde"] = _unix(svc.get("InactiveEnterTimestamp"))
    if presa and out["estado"] != "rodando":
        out["estado"] = "rodando"
        out["desde"] = None                      # a trava não diz desde quando
    if timer is not None and timer.get("LoadState") != "not-found":
        prox = _ts_timer(timer.get("NextElapseUSecRealtime"))
        if prox and prox > agora:
            out["proxima"] = prox
        # timer monotônico (OnUnitActiveSec) não tem hora de parede: segue "agendado", sem inventar a hora
        if out["estado"] == "ocioso" and (out["proxima"] or timer.get("ActiveState") == "active"):
            out["estado"] = "agendado"
    return out


class Coletor:
    def __init__(self):
        self.cat = catalogo()
        self._trava = threading.Lock()
        self._ult = 0.0
        self._ult_cont = 0.0
        self._ult_efeito = 0.0
        self._efeito: dict[str, float | None] = {}
        self._sem_efeito_ant: dict[str, bool] = {}
        self._seq = 0
        self.eventos: deque = deque(maxlen=ANEL)
        self._estado_ant: dict[str, str] = {}
        self._pos_log: dict[str, int] = {}
        self._cont: dict[str, int] = {}
        self._prog: dict[str, float | None] = {}
        self.motores: list[dict] = []
        self.fontes = {"systemd": None, "travas": None}
        self._regex = {m["id"]: [(re.compile(e["regex"]), e) for e in m.get("eventos", [])] for m in self.cat}

    # ── eventos ──
    def _emitir(self, motor: str, tipo: str, texto: str, t: float | None = None) -> None:
        self._seq += 1
        ts = t or time.time()
        self.eventos.append({"id": int(ts * 1000) * 100 + self._seq % 100, "t": _iso(ts), "_ts": ts, "motor": motor, "tipo": tipo,
                             "texto": sanear(texto)})

    def _ler_log(self, m: dict, semear: bool) -> None:
        caminho = _REPO / m["log"] if not os.path.isabs(m["log"]) else Path(m["log"])
        try:
            tam = caminho.stat().st_size
        except OSError:
            return
        pos = self._pos_log.get(m["id"])
        semeando = pos is None
        if semeando:                                      # 1ª leitura: semeia com a cauda (eventos REAIS, com a hora do log)
            pos = max(0, tam - 24_000) if semear else tam
        if tam < pos:
            pos = 0                                       # log rotacionado
        if tam == pos:
            self._pos_log[m["id"]] = pos
            return
        with open(caminho, "rb") as f:
            f.seek(pos)
            bloco = f.read(min(tam - pos, 96_000))
        self._pos_log[m["id"]] = pos + len(bloco)
        corte = time.time() - 3600
        for ln in bloco.decode("utf-8", "replace").splitlines():
            for rg, e in self._regex[m["id"]]:
                mm = rg.search(ln)
                if not mm:
                    continue
                ts = None
                mt = _RE_TS_LOG.match(ln)
                if mt:
                    try:
                        dt = datetime.fromisoformat(f"{mt.group(1)}T{mt.group(2)}")
                        ts = (dt.replace(tzinfo=timezone.utc) if mt.group(3) else dt.astimezone()).timestamp()
                    except ValueError:
                        ts = None
                if ts is None and semeando:
                    break                                  # cauda sem data não entra: não dá para dizer QUANDO foi
                if ts is not None and ts < corte:
                    break                                  # mais velho que 1 h: fora da janela do ao vivo
                txt = e["texto"]
                for i, g in enumerate(mm.groups(), 1):
                    txt = txt.replace("{%d}" % i, g or "")
                if e.get("progresso"):
                    try:
                        a, b = (float(mm.group(i)) for i in e["progresso"])
                        self._prog[m["id"]] = max(0.0, min(1.0, a / b)) if b else None
                    except (ValueError, IndexError) as exc:   # linha de progresso torta: segue sem barra
                        logger.debug("ao vivo: progresso ilegível em %s: %s", m["id"], exc)
                else:
                    self._prog.pop(m["id"], None)          # evento sem fração encerra a barra (ex.: "fim do slot")
                self._emitir(m["id"], e.get("tipo", "progresso"), txt, ts)
                break

    def _ler_contadores(self) -> None:
        por_db: dict[str, list] = {}
        for m in self.cat:
            if m.get("contador"):
                por_db.setdefault(m["contador"]["db"], []).append(m)
        for db, ms in por_db.items():
            try:
                c = sqlite3.connect(f"file:{DATA / db}?mode=ro", uri=True, timeout=2)
            except sqlite3.Error:
                continue
            try:
                for m in ms:
                    k = m["contador"]
                    try:
                        v = c.execute(f"SELECT MAX(rowid) FROM {k['tabela']}").fetchone()[0] or 0
                    except sqlite3.Error:
                        continue
                    ant = self._cont.get(m["id"])
                    self._cont[m["id"]] = v
                    if ant is not None and v > ant:
                        n = v - ant
                        self._emitir(m["id"], k.get("tipo", "dado"), f"+{n} {k['rotulo']}" if k.get("tipo") != "achado"
                                     else f"{n} {'novo alerta' if n == 1 else 'novos alertas'} de compliance")
            finally:
                c.close()

    def _ler_territorio(self) -> None:
        """Contrato recém-atribuído pelo motor território vira evento COM território (`cod_ibge`/`ap`) —
        é o que faz o mapa pulsar no lugar certo. 1ª leitura só marca o ponto de partida."""
        try:
            c = sqlite3.connect(f"file:{DATA / 'territorio.db'}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            return
        try:
            for tabela, col, rot in (("territorio_contrato_estado", "cod_ibge", "contrato do Estado atribuído a"),
                                     ("territorio_contrato_pcrj", "ap", "contrato da Prefeitura atribuído à AP")):
                try:
                    topo = c.execute(f"SELECT MAX(atualizado_em) FROM {tabela}").fetchone()[0]
                    ant = self._cont.get("terr:" + tabela)
                    self._cont["terr:" + tabela] = topo
                    if not ant or not topo or topo <= ant:
                        continue
                    linhas = c.execute(f"SELECT {col}, municipios_json FROM {tabela} WHERE atualizado_em>? AND {col} IS NOT NULL LIMIT 12"
                                       if col == "cod_ibge" else
                                       f"SELECT {col}, NULL FROM {tabela} WHERE atualizado_em>? AND {col} IS NOT NULL LIMIT 12", (ant,)).fetchall()
                except sqlite3.Error:
                    continue
                for alvo, js in linhas:
                    nome = str(alvo)
                    if col == "cod_ibge":
                        try:
                            nome = __import__("json").loads(js or "[]")[0]["nome"]
                        except (ValueError, IndexError, KeyError) as exc:   # sem nome: fica o código IBGE
                            logger.debug("ao vivo: nome do município ilegível (%s): %s", alvo, exc)
                    self._emitir("territorio", "dado", f"{rot} {nome}")
                    self.eventos[-1]["cod_ibge" if col == "cod_ibge" else "ap"] = alvo
        finally:
            c.close()

    def _sonda(self, m: dict) -> str:
        url = os.environ.get(m["sonda_env"], "")
        if not url:
            return "indisponivel"
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return "rodando" if 200 <= r.status < 300 else "falhou"
        except (OSError, ValueError, http.client.HTTPException):   # URLError/HTTPError/timeout são OSError; URL torta é ValueError
            return "indisponivel"

    # ── uma leitura ──
    def tick(self, forcar: bool = False) -> None:
        agora = time.time()
        if not forcar and agora - self._ult < INTERVALO:
            return
        with self._trava:
            if not forcar and time.time() - self._ult < INTERVALO:
                return
            primeira = not self.motores
            units = [m["unidade"] for m in self.cat if m.get("unidade")]
            sd = ler_systemd(units)
            presas = travas_presas()
            self.fontes = {"systemd": sd is not None, "travas": presas is not None}
            for m in self.cat:
                if m.get("log"):
                    self._ler_log(m, semear=primeira)
            if agora - self._ult_cont >= INTERVALO_CONTADOR:
                self._ult_cont = agora
                self._ler_contadores()
                self._ler_territorio()
            if agora - self._ult_efeito >= INTERVALO_EFEITO:
                self._ult_efeito = agora
                for m in self.cat:
                    if m.get("efeito"):
                        self._efeito[m["id"]] = medir_efeito(m["efeito"])
            limite = agora - 3600
            novos = []
            for m in self.cat:
                d = {"id": m["id"], "nome": m["nome"], "classe": m.get("classe", "motor"), "descricao": m.get("descricao"),
                     "unidade": m.get("unidade"), "estado": "indisponivel", "desde": None, "proxima": None, "saida": None,
                     "progresso": None, "ultimo_evento": None, "efeito": None}
                if m.get("sonda_env"):
                    d["estado"] = self._sonda(m)
                elif m.get("unidade") and sd is None:
                    d["estado"] = "indisponivel"
                else:
                    svc = sd.get(m["unidade"] + ".service") if m.get("unidade") and sd else None
                    tmr = sd.get(m["unidade"] + ".timer") if m.get("unidade") and sd else None
                    presa = trava_presa(_REPO / m["trava"] if not os.path.isabs(m["trava"]) else Path(m["trava"]), presas) if m.get("trava") else None
                    e = estado_do_motor(svc, tmr, presa, agora)
                    if not m.get("unidade") and not m.get("trava"):
                        # só contador: "rodando" se gravou linha nos últimos 5 min (fato medido), senão ocioso
                        recente = any(x["motor"] == m["id"] and x["_ts"] >= agora - 300 and x["tipo"] in ("dado", "achado") for x in self.eventos)
                        e["estado"] = "rodando" if recente else "ocioso"
                    d.update(estado=e["estado"], desde=_iso(e["desde"]), proxima=_iso(e["proxima"]), saida=e["saida"])
                ant = self._estado_ant.get(m["id"])
                if ant is not None and ant != d["estado"]:
                    if d["estado"] == "rodando":
                        self._emitir(m["id"], "estado", f"{m['nome']}: começou")
                    elif d["estado"] == "falhou":
                        self._emitir(m["id"], "falha", f"{m['nome']}: falhou" + (f" (código {d['saida']})" if d["saida"] else ""))
                    elif ant == "rodando":
                        self._emitir(m["id"], "estado", f"{m['nome']}: terminou" + (f" (código {d['saida']})" if d["saida"] else ""))
                elif ant is None and d["estado"] == "falhou" and d["desde"]:
                    ts = datetime.fromisoformat(d["desde"]).timestamp()   # falha antiga: entra com a hora REAL da falha
                    if ts >= limite:
                        self._emitir(m["id"], "falha", f"{m['nome']}: falhou" + (f" (código {d['saida']})" if d["saida"] else ""), ts)
                self._estado_ant[m["id"]] = d["estado"]
                if m.get("efeito"):
                    h = float(m["efeito"].get("horas") or 24)
                    ult = self._efeito.get(m["id"])
                    # motor que falhou ou está indisponível já aparece como tal; o 🟡 é para o "saudável" que não produz
                    parado = efeito_parado(ult, h, agora) if d["estado"] in ("rodando", "agendado", "ocioso") else None
                    d["efeito"] = {"ultimo": _iso(ult), "horas": h, "parado": parado}
                    if parado and not self._sem_efeito_ant.get(m["id"]):
                        self._emitir(m["id"], "estado", f"{m['nome']}: rodando sem efeito há {(agora - ult) / 3600:.0f} h")
                    self._sem_efeito_ant[m["id"]] = bool(parado)
                if d["estado"] == "rodando":
                    d["progresso"] = self._prog.get(m["id"])
                else:
                    self._prog.pop(m["id"], None)
                novos.append(d)
            evs = sorted(self.eventos, key=lambda x: x["_ts"])
            for d in novos:
                meus = [x for x in evs if x["motor"] == d["id"]]
                if meus:
                    d["ultimo_evento"] = {"t": meus[-1]["t"], "texto": meus[-1]["texto"]}
                at = [0] * 60
                for x in meus:
                    k = int((agora - x["_ts"]) // 60)
                    if 0 <= k < 60:
                        at[59 - k] += 1
                d["atividade"] = at
            self.motores = novos
            self._ult = time.time()

    def eventos_publicos(self, depois_de: int = 0, limite: int = 60) -> list[dict]:
        evs = sorted(self.eventos, key=lambda x: (x["_ts"], x["id"]))
        evs = [x for x in evs if x["id"] > depois_de][-limite:]
        return [{k: v for k, v in x.items() if not k.startswith("_")} for x in evs]

    def snapshot(self) -> dict:
        self.tick()
        agora = time.time()
        return {"atualizado_em": _iso(agora), "fontes": self.fontes, "motores": self.motores,
                "eventos": self.eventos_publicos(), "eventos_min": round(sum(1 for x in self.eventos if x["_ts"] >= agora - 300) / 5, 2),
                "resumo": {e: sum(1 for m in self.motores if m["estado"] == e and m["classe"] == "motor")
                           for e in ("rodando", "agendado", "ocioso", "falhou", "indisponivel")}
                | {"sem_efeito": sum(1 for m in self.motores if (m.get("efeito") or {}).get("parado") and m["classe"] == "motor")}}


_coletor: Coletor | None = None
_trava_c = threading.Lock()


def coletor() -> Coletor:
    global _coletor
    with _trava_c:
        if _coletor is None:
            _coletor = Coletor()
        return _coletor
