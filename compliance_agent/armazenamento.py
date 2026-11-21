"""Porta ÚNICA do armazenamento do JFN: guardar na nuvem, achar e trazer de volta.

Pedido do dono (21/11/2026): "use as coisas do drive, b2 e r2 […] ensinar todos a usarem os armazenamentos em
cloud" · "tem que indexar tudo e organizar pra todos saberem" · "duas cópias na nuvem? assim gasta o dobro".
Arquitetura e política completas: `docs/ARMAZENAMENTO.md`. Resumo:

  * QUENTE  — VM-1/VM-2: só o que o JFN lê/escreve hoje.
  * FRIO    — nuvem, acessível às duas VMs pelo rclone (o it-campo é só cache/processamento: nada que as VMs
              precisem pode ficar só nele).
  * Política por natureza do arquivo (POLITICA abaixo):
      - REOBTIVEL (PDF/foto/árvore do SEI, TSE, PNCP, Receita, caches de coleta, quarentenas de captura)
        → UMA cópia, no Drive (cota da conta do dono já paga: 400 GiB), conferida por hash antes de apagar.
      - INSUBSTITUIVEL (backups de banco, trabalho próprio, sessões, o próprio índice)
        → DUAS cópias em provedores DIFERENTES: Drive + a 1ª de `segunda_copia` que couber no GRÁTIS.
  * NUVENS SÓ NO GRÁTIS — remotos, capacidade e limites em `config/armazenamento_nuvens.json` (fonte única);
    `Orcamento` (pré-voo) recusa a chamada que estouraria um limite grátis e a recusa é escalada.
  * ÍNDICE ÚNICO — `data/armazenamento_indice.db` (SQLite): uma linha por unidade guardada (arquivo ou pacote
    .tar de uma pasta), uma por membro (o caminho ORIGINAL de cada arquivo), uma por cópia (onde está, hash,
    quando foi conferida). Cada máquina tem o seu índice; todos sobem para a nuvem em `indice/<maquina>.db`
    e `onde`/`obter` consultam todos.

Uso (todos — sessões, ferramentas, Yoda):

    python -m compliance_agent.armazenamento onde <caminho | processo 070002/021988/2025 | cnpj>
    python -m compliance_agent.armazenamento obter <caminho original> [--restaurar]
    python -m compliance_agent.armazenamento guardar <arquivo> --classe <classe> [--apagar-local]
    python -m compliance_agent.armazenamento resumo
    python -m compliance_agent.armazenamento conferir --amostra 20
    python -m compliance_agent.armazenamento sincronizar      # baixa os índices das outras máquinas

    from compliance_agent.armazenamento import obter, guardar
    p = obter("/home/ubuntu/JFN/data/sei_cache/integra_X/001.pdf")   # local, ou baixa do frio e confere

Só biblioteca padrão + o binário `rclone` (roda igual na VM-1, VM-2 e no WSL do it-campo).
Credenciais: só no rclone.conf de cada máquina — este módulo nunca as lê nem imprime.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent

# ── nuvens: caminhos, capacidade e limites grátis num lugar SÓ (`config/armazenamento_nuvens.json`) ──────────
# Dono, 21/11/2026: B2 e R2 SÓ no grátis (teto de gasto ZERO); Drive é o principal; remoto novo entra só por
# config. Nada aqui repete número de limite: tudo vem do JSON (com a URL oficial de cada limite).
def caminho_config_nuvens() -> Path:
    return Path(os.environ.get("JFN_NUVENS_CONFIG") or REPO / "config" / "armazenamento_nuvens.json")


NUVENS: dict = {}
DESTINOS: dict[str, str] = {}
INDICE_REMOTO: dict[str, str] = {}
PREFERENCIA_DOWNLOAD: tuple[str, ...] = ()
POLITICA: dict[str, tuple[tuple[str, ...], ...]] = {}


def configurar(caminho: Path | str | None = None) -> dict:
    """(Re)carrega a config das nuvens e deriva DESTINOS/INDICE_REMOTO/PREFERENCIA_DOWNLOAD/POLITICA.

    POLITICA: natureza → tupla de VAGAS; cada vaga é uma tupla de remotos aceitáveis (basta UM conferido).
      re-obtível     → ((principal,),)                       1 cópia
      insubstituível → ((principal,), (b2, r2, mega, ...))   principal + a 2ª cópia que couber
    `JFN_DESTINO_REOBTIVEL` troca o destino do re-obtível sem mudar a regra de 1 cópia (21/11: o cliente OAuth
    padrão do rclone é compartilhado e o Drive responde `rateLimitExceeded`)."""
    global NUVENS, DESTINOS, INDICE_REMOTO, PREFERENCIA_DOWNLOAD, POLITICA
    cfg = json.loads(Path(caminho or caminho_config_nuvens()).read_text(encoding="utf-8"))
    rem = cfg["remotos"]
    principal = cfg["principal"]
    segunda = tuple(n for n in cfg.get("segunda_copia", []) if n in rem and n != principal)
    if principal not in rem or not segunda:
        raise ValueError("config das nuvens: principal ausente ou segunda_copia vazia")
    reob = os.environ.get("JFN_DESTINO_REOBTIVEL", principal)
    if reob not in rem:
        raise ValueError(f"JFN_DESTINO_REOBTIVEL inválido: {reob}")
    NUVENS = cfg
    DESTINOS = {n: c["frio"] for n, c in rem.items()}
    INDICE_REMOTO = {n: c["indice"] for n, c in rem.items() if c.get("indice") and (n == principal or n in segunda)}
    PREFERENCIA_DOWNLOAD = tuple(sorted(rem, key=lambda n: rem[n].get("preferencia_download", 99)))
    POLITICA = {"reobtivel": ((reob,),), "insubstituivel": ((principal,), segunda)}
    return cfg


configurar()


def destinos_da_politica(natureza: str) -> set[str]:
    return {d for vaga in POLITICA[natureza] for d in vaga}


def vagas_satisfeitas(natureza: str, conferidos: set[str]) -> bool:
    """Toda vaga da política tem ao menos um remoto conferido."""
    return natureza in POLITICA and all(set(vaga) & conferidos for vaga in POLITICA[natureza])


CLASSES = {
    # re-obtível da fonte pública
    "sei_pdf": "reobtivel", "sei_foto": "reobtivel", "sei_cache": "reobtivel", "sei_arvore": "reobtivel",
    "quarentena": "reobtivel", "substituido": "reobtivel", "tse": "reobtivel", "pncp": "reobtivel",
    "receita": "reobtivel", "coleta_cache": "reobtivel",
    # insubstituível
    "backup_db": "insubstituivel", "trabalho": "insubstituivel", "sessao_claude": "insubstituivel",
    "indice": "insubstituivel", "relatorio": "insubstituivel", "midia": "insubstituivel",
}

_RX_PROC = re.compile(r"(?<!\d)(\d{6})[_/](\d{6})[_/](\d{4})(?!\d)")
_RX_CNPJ = re.compile(r"(?<!\d)(\d{14})(?!\d)")


def maquina() -> str:
    m = os.environ.get("JFN_MAQUINA")
    if m:
        return m
    h = socket.gethostname().lower()
    if "core" in h or h.endswith("-1") or h == "jfn-agent-1":
        return "vm1"
    if "agent-2" in h or h.endswith("-2"):
        return "vm2"
    if Path("/mnt/c/Windows").exists():
        return "itcampo"
    return h


def caminho_indice() -> Path:
    env = os.environ.get("JFN_ARMAZENAMENTO_DB")
    if env:
        return Path(env)
    if (REPO / "data").is_dir():
        return REPO / "data" / "armazenamento_indice.db"
    return HOME / ".zelador" / "armazenamento_indice.db"


def dir_indices_outros() -> Path:
    return HOME / ".zelador" / "indices"


def processo_de(texto: str) -> str | None:
    m = _RX_PROC.search(texto)
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None


def cnpj_de(texto: str) -> str | None:
    m = _RX_CNPJ.search(texto)
    return m.group(1) if m else None


def agora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def hashes(p: Path) -> tuple[str, str]:
    """(md5, sha1) numa única leitura — o Drive e o R2 conferem md5, o B2 confere sha1."""
    m, s = hashlib.md5(), hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(4 << 20), b""):
            m.update(b)
            s.update(b)
    return m.hexdigest(), s.hexdigest()


# ── índice ─────────────────────────────────────────────────────────────────────────────────────────────
ESQUEMA = """
CREATE TABLE IF NOT EXISTS unidades(
  chave TEXT PRIMARY KEY, maquina TEXT, origem TEXT, tipo TEXT, classe TEXT, natureza TEXT,
  processo TEXT, cnpj TEXT, bytes INTEGER, md5 TEXT, sha1 TEXT, n_membros INTEGER,
  criado_em TEXT, ciclo TEXT, assinatura TEXT);
CREATE TABLE IF NOT EXISTS membros(
  maquina TEXT, caminho TEXT, chave TEXT, nome TEXT, bytes INTEGER, md5 TEXT, processo TEXT, cnpj TEXT,
  local_apagado_em TEXT, PRIMARY KEY(maquina, caminho, chave));
CREATE INDEX IF NOT EXISTS ix_membros_caminho ON membros(caminho);
CREATE INDEX IF NOT EXISTS ix_membros_processo ON membros(processo);
CREATE INDEX IF NOT EXISTS ix_membros_md5 ON membros(md5, bytes);
CREATE TABLE IF NOT EXISTS copias(
  chave TEXT, destino TEXT, url TEXT, status TEXT, hash_tipo TEXT, hash TEXT, bytes INTEGER,
  enviado_em TEXT, conferido_em TEXT, ciclo_conferido TEXT, detalhe TEXT, PRIMARY KEY(chave, destino));
CREATE TABLE IF NOT EXISTS externos(
  origem TEXT, caminho_original TEXT, onde TEXT, hash_tipo TEXT, hash TEXT, bytes INTEGER, em TEXT,
  status TEXT, PRIMARY KEY(origem, caminho_original, onde));
CREATE INDEX IF NOT EXISTS ix_externos_caminho ON externos(caminho_original);
CREATE TABLE IF NOT EXISTS remotos(
  remoto TEXT, caminho TEXT, bytes INTEGER, md5 TEXT, sha1 TEXT, visto_em TEXT, PRIMARY KEY(remoto, caminho));
CREATE TABLE IF NOT EXISTS journal(
  id INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT, maquina TEXT, ciclo TEXT, acao TEXT, alvo TEXT,
  detalhe TEXT);
CREATE TABLE IF NOT EXISTS ciclos(
  id TEXT PRIMARY KEY, maquina TEXT, perfil TEXT, modo TEXT, inicio TEXT, fim TEXT, status TEXT,
  resumo TEXT);
"""


def conectar(db: Path | None = None) -> sqlite3.Connection:
    db = Path(db or caminho_indice())
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(ESQUEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(unidades)")}
    if "assinatura" not in cols:                       # índices criados antes de 21/11 15h
        con.execute("ALTER TABLE unidades ADD COLUMN assinatura TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS ix_unidades_assinatura ON unidades(assinatura)")
    return con


def journal(con: sqlite3.Connection, acao: str, alvo: str, detalhe: str = "", ciclo: str = "") -> None:
    """Toda ação vira linha ANTES de acontecer (commit imediato)."""
    con.execute("INSERT INTO journal(quando, maquina, ciclo, acao, alvo, detalhe) VALUES(?,?,?,?,?,?)",
                (agora(), maquina(), ciclo, acao, alvo, detalhe[:2000]))
    con.commit()


# ── rclone (injetável nos testes) ───────────────────────────────────────────────────────────────────────
class ErroArmazenamento(RuntimeError):
    pass


# ── pré-voo por nuvem: uso real + consumo do dia/mês, ANTES de cada chamada (dono 21/11: só no grátis) ──────
def caminho_consumo() -> Path:
    return Path(os.environ.get("JFN_CONSUMO_NUVENS") or HOME / ".zelador" / "consumo_nuvens.json")


def nome_remoto(remoto: str) -> str | None:
    """'b2:jfn-backup-jorge/frio/x' → 'b2' (só remotos da config; caminho local → None)."""
    n = str(remoto).split(":", 1)[0] if ":" in str(remoto) else ""
    return n if n in NUVENS.get("remotos", {}) else None


_MIB = 1 << 20


def custo_operacao(tipo: str, op: str, nbytes: int = 0, n_objetos: int = 0) -> dict[str, float]:
    """Estimativa CONSERVADORA do que UMA chamada do rclone gasta de cada contador do provedor.

    B2 (backblaze.com/cloud-storage/transaction-pricing): upload = Classe A (grátis); HEAD/download/get_file_info
    = Classe B; authorize_account/list_buckets/list_file_names = Classe C. Toda invocação do rclone autoriza e
    lista o bucket (2 × C). R2 (developers.cloudflare.com/r2/pricing): Put/List/Copy/multipart = Classe A;
    Get/Head = Classe B; Delete grátis; saída grátis. MEGA: só a transferência de download conta."""
    c: dict[str, float] = {}
    baixa = op in ("baixar", "hash_baixando")
    if tipo == "b2":
        c["classe_c"] = 2
        if op in ("enviar", "stat", "apagar"):
            c["classe_b"] = 1
        elif baixa:
            c["classe_b"], c["download_bytes"] = 2, nbytes
        elif op in ("listar", "medir", "acessivel"):
            c["classe_c"] += 1 + n_objetos // 1000
    elif tipo == "s3":
        if op == "enviar":
            partes = 1 if nbytes <= 200 * _MIB else -(-nbytes // (5 * _MIB)) + 2
            c["classe_a"], c["classe_b"] = 1 + partes, 1
        elif op in ("stat", "apagar"):
            c["classe_b"] = 1
        elif baixa:
            c["classe_b"], c["download_bytes"] = 2, nbytes
        elif op in ("listar", "medir", "acessivel"):
            c["classe_a"] = 1 + n_objetos // 1000
    elif baixa:
        c["download_bytes"] = nbytes
    return c


def _periodos(quando: dt.datetime | None = None) -> dict[str, str]:
    u = quando or dt.datetime.now(dt.timezone.utc)
    return {"dia": u.strftime("%Y-%m-%d"), "mes": u.strftime("%Y-%m")}


class Orcamento:
    """Contador LOCAL por remoto e período (dia/mês UTC) de bytes baixados e transações estimadas, mais o uso
    real do armazenamento medido no remoto (`rclone about`, ou `rclone size` da raiz). `recusa()` diz se a
    chamada estouraria um limite grátis da config × a partilha desta máquina; `cabe()` se o upload passa do
    alvo (limite − margem − reserva). Sem medida = não sobe (fechado por padrão). Recusa nunca é silenciosa:
    vai para `recusas` (o zelador registra e escala)."""

    def __init__(self, caminho: Path | None = None, maq: str | None = None):
        self.caminho = Path(caminho or caminho_consumo())
        self.maq = maq or maquina()
        self.uso: dict[str, dict | None] = {}
        self.recusas: list[str] = []

    def partilha(self) -> float:
        return float(NUVENS.get("partilha_por_maquina", {}).get(self.maq, NUVENS.get("partilha_desconhecida", 0.1)))

    def _mutar(self, fn=None) -> dict:
        import fcntl
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(self.caminho, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                est = json.loads(f.read() or "{}")
            except ValueError:
                est = {}
            if fn is not None:
                fn(est)
                f.seek(0)
                f.truncate()
                f.write(json.dumps(est, ensure_ascii=False, indent=1))
            return est

    def consumo(self, nome: str) -> dict:
        r = self._mutar().get(nome, {})
        per = _periodos()
        out = {p: (r.get(p) if (r.get(p) or {}).get("chave") == k else {"chave": k}) for p, k in per.items()}
        out["esgotado_ate"], out["esgotado_motivo"] = r.get("esgotado_ate"), r.get("esgotado_motivo")
        return out

    def limites(self, nome: str) -> dict[str, float]:
        cfg = NUVENS["remotos"][nome]
        lim = {k: float(v) for k, v in (cfg.get("limites") or {}).items()}
        if cfg.get("amostra_download_mb_dia"):
            lim["amostra_bytes_dia"] = float(cfg["amostra_download_mb_dia"]) * 1e6
        return lim

    def recusa(self, nome: str, custo: dict) -> str | None:
        if nome not in NUVENS.get("remotos", {}):
            return None
        est = self.consumo(nome)
        if est.get("esgotado_ate") and dt.datetime.now(dt.timezone.utc).isoformat() < est["esgotado_ate"]:
            return (f"{nome}: o provedor recusou por limite ({(est.get('esgotado_motivo') or '').strip()[-120:]}) "
                    f"— esgotado até {est['esgotado_ate'][:16]} UTC")
        part = self.partilha()
        for chave, lim in self.limites(nome).items():
            contador, per = chave.rsplit("_", 1)
            pedido = float(custo.get(contador, 0) or 0)
            gasto = float(est.get(per, {}).get(contador, 0) or 0)
            if pedido and gasto + pedido > lim * part:
                return (f"{nome}: {contador}/{per} {gasto:,.0f} + {pedido:,.0f} > {lim * part:,.0f} "
                        f"(grátis {lim:,.0f} × partilha {self.maq} {part:.0%})").replace(",", ".")
        return None

    def registrar(self, nome: str, custo: dict) -> None:
        if nome not in NUVENS.get("remotos", {}) or not custo:
            return
        per = _periodos()

        def fn(est):
            r = est.setdefault(nome, {})
            for p, k in per.items():
                if (r.get(p) or {}).get("chave") != k:
                    r[p] = {"chave": k}
                for c, v in custo.items():
                    r[p][c] = r[p].get(c, 0) + v
        self._mutar(fn)

    def esgotar(self, nome: str, motivo: str) -> None:
        """O provedor disse 'cap exceeded': nada mais nele até o próximo 00:00 UTC (quando os contadores zeram)."""
        amanha = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                                                  microsecond=0)

        def fn(est):
            est.setdefault(nome, {}).update(esgotado_ate=amanha.isoformat(), esgotado_motivo=motivo[-300:])
        self._mutar(fn)

    def alvo_e_usado(self, nome: str, rc: "Rclone") -> tuple[float, float] | None:
        """(alvo útil em bytes = limite − margem − reserva, usado agora). None = sem medida."""
        if nome not in self.uso:
            self.uso[nome] = rc.medir_uso(nome)
        u = self.uso[nome]
        cfg = NUVENS["remotos"][nome]
        if u is None:
            return None
        total = float(cfg["armazenamento_gb"]) * 1e9 if cfg.get("armazenamento_gb") else u.get("total")
        if total is None:
            return None
        folga = (float(cfg.get("margem_gb", 0)) + float(cfg.get("reserva_gb", 0))) * 1e9
        return total - folga, float(u["usado"])

    def cabe(self, nome: str, nbytes: int, rc: "Rclone", substitui: int = 0) -> str | None:
        if nome not in NUVENS.get("remotos", {}):
            return None
        au = self.alvo_e_usado(nome, rc)
        if au is None:
            return f"{nome}: uso real não medido — sem medida não sobe (fechado por padrão)"
        alvo, usado = au
        if usado - substitui + nbytes > alvo:
            return (f"{nome}: armazenado {usado / 1e9:.2f} GB + {nbytes / 1e9:.3f} GB > alvo {alvo / 1e9:.2f} GB "
                    f"(limite − margem − reserva)")
        return None

    def somar_uso(self, nome: str, nbytes: int) -> None:
        if self.uso.get(nome):
            self.uso[nome]["usado"] = float(self.uso[nome]["usado"]) + nbytes


_RX_CAP = re.compile(r"cap[_ ]exceeded|transaction_cap|download_cap|storage_cap|\b403\b", re.I)


def _binario_rclone() -> str:
    """O oficial em ~/.local/bin primeiro (o do Ubuntu, 1.60.1-DEV, não tem mega/filen/protondrive/internxt e o
    cron não tem ~/.local/bin no PATH)."""
    loc = HOME / ".local" / "bin" / "rclone"
    return os.environ.get("JFN_RCLONE") or (str(loc) if loc.exists() else (shutil.which("rclone") or str(loc)))


@dataclass
class Rclone:
    binario: str = field(default_factory=_binario_rclone)
    timeout: int = 7200
    # --tpslimit: o cliente OAuth padrão do rclone é compartilhado no mundo todo e o Drive responde
    # `rateLimitExceeded` (medido 21/11: um tar de 103 MB parado 7 min em backoff). 4 req/s evita a espiral.
    extra: list = field(default_factory=lambda: ["--retries", "3", "--low-level-retries", "20", "--tpslimit", "4",
                                                 "--drive-chunk-size", "32M", "--contimeout", "60s",
                                                 "--timeout", "300s"])
    orcamento: Orcamento | None = field(default_factory=lambda: Orcamento())

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([self.binario, *args, *self.extra], capture_output=True, text=True,
                                  timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(e.cmd, 124, "", "timeout")
        except OSError as e:
            return subprocess.CompletedProcess([self.binario], 127, "", str(e))

    # pré-voo de cada chamada ------------------------------------------------------------------------------
    def _custo(self, nome: str, op: str, nbytes: int, n_objetos: int, amostra: bool) -> dict:
        c = custo_operacao(NUVENS["remotos"][nome].get("tipo", ""), op, nbytes, n_objetos)
        if amostra:
            c["amostra_bytes"] = nbytes
        return c

    def _gate(self, op: str, remoto: str, nbytes: int = 0, amostra: bool = False,
              substitui: int = 0) -> tuple[str | None, str | None]:
        """(nome do remoto, motivo da recusa | None). A recusa vai para `orcamento.recusas` (escalada)."""
        nome = nome_remoto(remoto)
        if nome is None or self.orcamento is None:
            return None, None
        motivo = self.orcamento.recusa(nome, self._custo(nome, op, nbytes, 0, amostra))
        if motivo is None and op == "enviar":
            motivo = self.orcamento.cabe(nome, nbytes, self, substitui)
        if motivo:
            self.orcamento.recusas.append(f"{op} {remoto}: {motivo}")
            return nome, "RECUSADO pelo pré-voo (limite grátis): " + motivo
        return nome, None

    def _registrar(self, nome: str | None, op: str, r: subprocess.CompletedProcess, nbytes: int = 0,
                   n_objetos: int = 0, amostra: bool = False) -> None:
        """A chamada aconteceu (deu certo ou não): o gasto conta. 'cap exceeded'/403 do provedor = esgotado hoje."""
        if nome is None or self.orcamento is None:
            return
        self.orcamento.registrar(nome, self._custo(nome, op, nbytes, n_objetos, amostra))
        if r.returncode != 0 and NUVENS["remotos"][nome].get("limites") and _RX_CAP.search(r.stderr or ""):
            self.orcamento.esgotar(nome, (r.stderr or "")[-300:])

    def pode_enviar(self, nome: str, nbytes: int, substitui: int = 0) -> str | None:
        """Consulta pura (não registra recusa): None = o upload cabe nos limites grátis de `nome`."""
        if self.orcamento is None or nome not in NUVENS.get("remotos", {}):
            return None
        return self.orcamento.recusa(nome, self._custo(nome, "enviar", nbytes, 0, False)) or \
            self.orcamento.cabe(nome, nbytes, self, substitui)

    # chamadas ---------------------------------------------------------------------------------------------
    def versao(self) -> str | None:
        r = self._run(["version"], timeout=60)
        return (r.stdout or "").splitlines()[0].strip() if r.returncode == 0 and r.stdout else None

    def medir_uso(self, nome: str) -> dict | None:
        """Uso REAL do remoto: `rclone about` (quando o provedor responde) ou `rclone size` da raiz."""
        cfg = NUVENS["remotos"].get(nome)
        if not cfg:
            return None
        raiz = cfg["raiz"]
        nome_, motivo = self._gate("medir", raiz)
        if motivo:
            return None
        if cfg.get("medir") == "about":
            r = self._run(["about", "--json", raiz], timeout=300)
            self._registrar(nome_, "medir", r)
            try:
                d = json.loads(r.stdout) if r.returncode == 0 else None
            except ValueError:
                d = None
            if not d or d.get("total") is None:
                return None
            usado = d["total"] - d["free"] if d.get("free") is not None else d.get("used", 0)
            return {"usado": float(usado), "total": float(d["total"]), "como": "about"}
        r = self._run(["size", "--json", raiz], timeout=1800)
        try:
            d = json.loads(r.stdout) if r.returncode == 0 else None
        except ValueError:
            d = None
        self._registrar(nome_, "medir", r, n_objetos=int((d or {}).get("count", 0)))
        if not d:
            return None
        return {"usado": float(d.get("bytes", 0)), "objetos": int(d.get("count", 0)), "como": "size"}

    def enviar(self, local: Path, remoto: str, substitui: int = 0) -> tuple[bool, str]:
        n = Path(local).stat().st_size
        nome, motivo = self._gate("enviar", remoto, n, substitui=substitui)
        if motivo:
            return False, motivo
        r = self._run(["copyto", "--checksum", str(local), remoto])
        self._registrar(nome, "enviar", r, n)
        if r.returncode == 0 and nome and self.orcamento:
            self.orcamento.somar_uso(nome, n - substitui)
        return r.returncode == 0, (r.stderr or "")[-500:]

    def baixar(self, remoto: str, local: Path, nbytes: int = 0, amostra: bool = False) -> tuple[bool, str]:
        nome, motivo = self._gate("baixar", remoto, nbytes, amostra=amostra)
        if motivo:
            return False, motivo
        r = self._run(["copyto", remoto, str(local)])
        real = Path(local).stat().st_size if Path(local).exists() else 0
        self._registrar(nome, "baixar", r, max(real, nbytes), amostra=amostra)
        return r.returncode == 0, (r.stderr or "")[-500:]

    def copiar(self, origem: str, destino: str, nbytes: int) -> tuple[bool, str]:
        """Remoto → remoto (passa por esta máquina): orça a leitura na origem e a escrita no destino."""
        no, mo = self._gate("baixar", origem, nbytes)
        nd, md = (None, None) if mo else self._gate("enviar", destino, nbytes)
        if mo or md:
            return False, mo or md
        r = self._run(["copyto", "--checksum", origem, destino])
        self._registrar(no, "baixar", r, nbytes)
        self._registrar(nd, "enviar", r, nbytes)
        if r.returncode == 0 and nd and self.orcamento:
            self.orcamento.somar_uso(nd, nbytes)
        return r.returncode == 0, (r.stderr or "")[-500:]

    def stat(self, remoto: str) -> dict | None:
        """Objeto remoto (Size, Hashes) ou None se não existe/erro/recusado. Não confia no rc do envio."""
        nome, motivo = self._gate("stat", remoto)
        if motivo:
            return None
        r = self._run(["lsjson", "--stat", "--hash", remoto], timeout=600)
        self._registrar(nome, "stat", r)
        if r.returncode != 0:
            return None
        try:
            d = json.loads(r.stdout or "null")
        except ValueError:
            return None
        return d if isinstance(d, dict) and not d.get("IsDir") else None

    def hash_baixando(self, remoto: str, tipo: str = "md5", nbytes: int = 0) -> str | None:
        nome, motivo = self._gate("hash_baixando", remoto, nbytes)
        if motivo:
            return None
        r = self._run(["hashsum", tipo, "--download", remoto], timeout=7200)
        self._registrar(nome, "hash_baixando", r, nbytes)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout.split()[0].lower()

    def apagar(self, remoto: str) -> tuple[bool, str]:
        nome, motivo = self._gate("apagar", remoto)
        if motivo:
            return False, motivo
        r = self._run(["deletefile", remoto], timeout=600)
        self._registrar(nome, "apagar", r)
        return r.returncode == 0, (r.stderr or "")[-500:]

    def listar(self, base: str) -> list[dict] | None:
        nome, motivo = self._gate("listar", base)
        if motivo:
            return None
        r = self._run(["lsjson", "-R", "--files-only", "--hash", base], timeout=7200)
        try:
            itens = json.loads(r.stdout or "[]") if r.returncode == 0 else None
        except ValueError:
            itens = None
        self._registrar(nome, "listar", r, n_objetos=len(itens or []))
        return itens

    def acessivel(self, base: str) -> bool:
        nome, motivo = self._gate("acessivel", base)
        if motivo:
            return False
        r = self._run(["lsf", "--max-depth", "1", base], timeout=300)
        self._registrar(nome, "acessivel", r)
        return r.returncode == 0 or "directory not found" in (r.stderr or "")


def url(destino: str, chave: str) -> str:
    return f"{DESTINOS[destino]}/{chave}"


def conferir_copia(rc: Rclone, destino: str, chave: str, bytes_: int, md5: str, sha1: str,
                   permitir_download: bool = True) -> tuple[str, str, str]:
    """('ok'|'sumida'|'divergente'|'sem_hash', hash_tipo, detalhe). Só 'ok' conta como cópia.

    Exige: o objeto EXISTE na listagem, o tamanho bate e um hash forte bate. Um `rclone` que devolve 0 sem
    o arquivo estar lá cai em 'sumida' — o rc do envio nunca é prova.
    """
    u = url(destino, chave)
    st = rc.stat(u)
    if st is None:
        return "sumida", "", f"não listado em {u}"
    if int(st.get("Size", -1)) != int(bytes_):
        return "divergente", "", f"tamanho {st.get('Size')} ≠ {bytes_}"
    hs = {k.lower(): (v or "").lower() for k, v in (st.get("Hashes") or {}).items()}
    if hs.get("md5"):
        return ("ok", "md5", "") if hs["md5"] == md5 else ("divergente", "md5", f"md5 {hs['md5']} ≠ {md5}")
    if hs.get("sha1"):
        return ("ok", "sha1", "") if hs["sha1"] == sha1 else ("divergente", "sha1", f"sha1 {hs['sha1']} ≠ {sha1}")
    if not permitir_download:
        return "sem_hash", "", "remoto sem hash"
    h = rc.hash_baixando(u, "md5", nbytes=int(bytes_))
    if h is None:
        return "sem_hash", "", "hash por download falhou"
    return ("ok", "md5-download", "") if h == md5 else ("divergente", "md5-download", f"{h} ≠ {md5}")


# ── unidades: arquivo único ou pacote de pasta ──────────────────────────────────────────────────────────
@dataclass
class Membro:
    caminho: Path          # onde está agora
    original: Path         # caminho lógico original (o que o JFN procura)
    nome: str              # nome dentro do pacote ('' para arquivo único)
    bytes: int
    md5: str
    mtime: float


@dataclass
class Unidade:
    chave: str
    origem: str
    tipo: str              # 'arquivo' | 'pacote'
    classe: str
    arquivo: Path          # o que sobe (o próprio arquivo, ou o .tar temporário)
    membros: list[Membro]
    bytes: int = 0
    md5: str = ""
    sha1: str = ""
    assinatura: str = ""   # nome+tamanho+mtime de cada membro: pasta igual não sobe de novo

    @property
    def natureza(self) -> str:
        return CLASSES[self.classe]


def chave_de(original: Path, maq: str) -> str:
    try:
        rel = original.resolve(strict=False).relative_to(HOME)
    except ValueError:
        rel = Path(str(original).lstrip("/"))
    return f"{maq}/{rel.as_posix()}"


def unidade_arquivo(p: Path, classe: str, original: Path | None = None, maq: str | None = None) -> Unidade:
    maq = maq or maquina()
    original = original or p
    st = p.stat()
    md5, sha1 = hashes(p)
    m = Membro(p, original, "", st.st_size, md5, st.st_mtime)
    return Unidade(chave_de(original, maq), str(original), "arquivo", classe, p, [m], st.st_size, md5, sha1)


def unidade_pacote(pasta: Path, arquivos: list[Path], classe: str, tmpdir: Path, ciclo: str,
                   original_de=None, maq: str | None = None) -> Unidade:
    """Empacota (tar sem compressão: PDF/JPG já são comprimidos) para não subir 100 mil objetos pequenos."""
    maq = maq or maquina()
    original_de = original_de or (lambda p: p)
    orig_pasta = original_de(pasta)
    base_chave = chave_de(orig_pasta, maq)
    tmpdir.mkdir(parents=True, exist_ok=True)
    tar_path = tmpdir / (re.sub(r"[^A-Za-z0-9_.-]", "_", base_chave)[-170:] + f"__{ciclo}.tar")
    membros = []
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as tf:
        for f in sorted(arquivos):
            st = f.stat()
            md5, _ = hashes(f)
            nome = f.relative_to(pasta).as_posix()
            tf.add(str(f), arcname=nome, recursive=False)
            membros.append(Membro(f, original_de(f), nome, st.st_size, md5, st.st_mtime))
    md5, sha1 = hashes(tar_path)
    # chave estável pelo CONTEÚDO: reenviar uma pasta que não mudou sobrescreve o mesmo objeto (sem duplicar)
    chave = f"{base_chave}__{md5[:12]}.tar"
    return Unidade(chave, str(orig_pasta), "pacote", classe, tar_path, membros, tar_path.stat().st_size, md5, sha1)


def registrar_unidade(con: sqlite3.Connection, u: Unidade, ciclo: str) -> None:
    maq = u.chave.split("/", 1)[0]
    con.execute("INSERT OR REPLACE INTO unidades(chave, maquina, origem, tipo, classe, natureza, processo, cnpj, "
                "bytes, md5, sha1, n_membros, criado_em, ciclo, assinatura) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (u.chave, maq, u.origem, u.tipo, u.classe, u.natureza, processo_de(u.origem),
                 cnpj_de(u.origem), u.bytes, u.md5, u.sha1, len(u.membros), agora(), ciclo, u.assinatura))
    con.executemany("INSERT OR REPLACE INTO membros VALUES(?,?,?,?,?,?,?,?,NULL)",
                    [(maq, str(m.original), u.chave, m.nome, m.bytes, m.md5, processo_de(str(m.original)),
                      cnpj_de(str(m.original))) for m in u.membros])
    con.commit()


def _enviar_a(con: sqlite3.Connection, rc: Rclone, u: Unidade, d: str, ciclo: str, substitui: int = 0) -> str:
    journal(con, "enviar", u.chave, d, ciclo)
    ok, err = rc.enviar(u.arquivo, url(d, u.chave), substitui=substitui) if substitui else \
        rc.enviar(u.arquivo, url(d, u.chave))
    if not ok and err.startswith("RECUSADO"):
        journal(con, "recusado", u.chave, f"{d}: {err}", ciclo)
        return "recusado"
    status, htipo, det = conferir_copia(rc, d, u.chave, u.bytes, u.md5, u.sha1)
    if not ok and status == "ok":
        det = f"rclone rc≠0 mas cópia conferida: {err[-200:]}"
    elif not ok:
        det = f"rclone falhou: {err[-300:]} | {det}"
    con.execute("INSERT OR REPLACE INTO copias VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (u.chave, d, url(d, u.chave), status, htipo, u.md5 if htipo.startswith("md5") else u.sha1,
                 u.bytes, agora(), agora(), ciclo if status == "ok" else None, det))
    con.commit()
    return status


def enviar_unidade(con: sqlite3.Connection, rc: Rclone, u: Unidade, ciclo: str,
                   destinos: tuple[str, ...] | None = None) -> dict[str, str]:
    """Sobe a unidade e confere cada cópia NESTE ciclo. Devolve {destino: status}.

    Sem `destinos`: segue as VAGAS da política — vaga de um remoto só sobe nele; vaga com alternativas
    (a 2ª cópia do insubstituível) tenta, na ordem da config, o primeiro remoto que o pré-voo aceita (limite
    grátis de armazenamento e de operações); se ele falhar, o próximo. Nenhum coube → '<a|b|c>': 'recusado'."""
    registrar_unidade(con, u, ciclo)
    res: dict[str, str] = {}
    if destinos:
        for d in destinos:
            res[d] = _enviar_a(con, rc, u, d, ciclo)
        return res
    for vaga in POLITICA[u.natureza]:
        if len(vaga) == 1:
            res[vaga[0]] = _enviar_a(con, rc, u, vaga[0], ciclo)
            continue
        for d in vaga:
            if rc.pode_enviar(d, u.bytes) is not None:
                continue
            res[d] = _enviar_a(con, rc, u, d, ciclo)
            if res[d] == "ok":
                break
        else:
            if not any(res.get(d) == "ok" for d in vaga):
                motivos = "; ".join(f"{d}: {rc.pode_enviar(d, u.bytes)}" for d in vaga if d not in res)
                journal(con, "recusado", u.chave, f"nenhum remoto da vaga {vaga} coube: {motivos}", ciclo)
                if rc.orcamento is not None:
                    rc.orcamento.recusas.append(f"enviar {u.chave}: nenhum de {'|'.join(vaga)} coube — {motivos}")
                res["|".join(vaga)] = "recusado"
    return res


def copias_ok(res: dict[str, str]) -> set[str]:
    return {d for d, s in res.items() if s == "ok"}


def assinatura_de(arquivos: list[Path], base: Path) -> str:
    h = hashlib.sha1(f"{base}\n".encode())     # o caminho da pasta entra: pastas gêmeas não se confundem
    for f in sorted(arquivos):
        st = f.stat()
        h.update(f"{f.relative_to(base).as_posix()}\t{st.st_size}\t{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def ja_na_nuvem(con: sqlite3.Connection, assinatura: str) -> bool:
    """Mesma pasta (mesma assinatura) já guardada com TODAS as cópias da política 'ok'."""
    for r in con.execute("SELECT chave, natureza FROM unidades WHERE assinatura=?", (assinatura,)).fetchall():
        oks = {c["destino"] for c in con.execute("SELECT destino FROM copias WHERE chave=? AND status='ok'",
                                                 (r["chave"],))}
        if vagas_satisfeitas(r["natureza"], oks):
            return True
    return False


def unidade_do_indice(con: sqlite3.Connection, assinatura: str, arquivos: list[Path], base: Path,
                      original_de=None) -> Unidade | None:
    """Pasta/arquivo que JÁ subiu (mesma assinatura): remonta a Unidade pelo índice, sem empacotar nem subir de
    novo — o ciclo só reconfere as cópias (o que vale para apagar é a conferência DESTE ciclo)."""
    original_de = original_de or (lambda p: p)
    r = con.execute("SELECT * FROM unidades WHERE assinatura=? ORDER BY criado_em DESC LIMIT 1",
                    (assinatura,)).fetchone()
    if r is None:
        return None
    por_nome = {m["nome"]: m for m in con.execute("SELECT * FROM membros WHERE chave=?", (r["chave"],))}
    membros = []
    for f in arquivos:
        nome = "" if r["tipo"] == "arquivo" else f.relative_to(base).as_posix()
        m = por_nome.get(nome)
        if m is None:
            return None
        st = f.stat()
        membros.append(Membro(f, original_de(f), nome, int(m["bytes"]), m["md5"], st.st_mtime))
    if len(membros) != len(por_nome):
        return None
    return Unidade(r["chave"], r["origem"], r["tipo"], r["classe"], Path(""), membros, int(r["bytes"]),
                   r["md5"], r["sha1"], assinatura)


def reconferir_unidade(con: sqlite3.Connection, rc: Rclone, u: Unidade, ciclo: str) -> dict[str, str]:
    """Reconfere, NESTE ciclo, as cópias que o índice diz existir (vaga de um remoto só: sempre). Vaga com
    alternativas satisfeita na primeira 'ok' — não gasta operação das outras. Quem decide é `vagas_satisfeitas`."""
    res = {}
    tem = {c["destino"] for c in con.execute("SELECT destino FROM copias WHERE chave=?", (u.chave,))}
    alvos = []
    for vaga in POLITICA[u.natureza]:
        alvos += list(vaga) if len(vaga) == 1 else [d for d in vaga if d in tem]
    for d in alvos:
        if any(res.get(o) == "ok" for v in POLITICA[u.natureza] if d in v and len(v) > 1 for o in v):
            continue
        status, htipo, det = conferir_copia(rc, d, u.chave, u.bytes, u.md5, u.sha1)
        con.execute("INSERT OR REPLACE INTO copias VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (u.chave, d, url(d, u.chave), status, htipo, u.md5 if htipo.startswith("md5") else u.sha1,
                     u.bytes, None, agora(), ciclo if status == "ok" else None, "reconferida: " + det))
        con.commit()
        res[d] = status
    return res


def copias_conferidas_no_ciclo(con: sqlite3.Connection, chave: str, ciclo: str) -> set[str]:
    rows = con.execute("SELECT destino FROM copias WHERE chave=? AND status='ok' AND ciclo_conferido=?",
                       (chave, ciclo)).fetchall()
    return {r["destino"] for r in rows}


def liberado_para_apagar(con: sqlite3.Connection, chave: str, ciclo: str) -> bool:
    """A trava central: TODA vaga da política com uma cópia conferida por hash NESTE ciclo (não em ciclo
    anterior)."""
    r = con.execute("SELECT natureza FROM unidades WHERE chave=?", (chave,)).fetchone()
    if not r or r["natureza"] not in POLITICA:
        return False
    return vagas_satisfeitas(r["natureza"], copias_conferidas_no_ciclo(con, chave, ciclo))


def guardar(arquivo: str | Path, classe: str, apagar_local: bool = False, rc: Rclone | None = None,
            con: sqlite3.Connection | None = None) -> dict:
    """Porta para qualquer ferramenta: sobe um arquivo pela política da classe, confere, indexa.

    `apagar_local=True` só apaga se TODAS as cópias exigidas foram conferidas agora; o journal grava antes.
    """
    if classe not in CLASSES:
        raise ValueError(f"classe desconhecida: {classe} (válidas: {', '.join(sorted(CLASSES))})")
    p = Path(arquivo)
    if not p.is_file() or p.is_symlink():
        raise ErroArmazenamento(f"não é arquivo regular: {p}")
    rc = rc or Rclone()
    con = con or conectar()
    ciclo = "guardar-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    u = unidade_arquivo(p, classe)
    res = enviar_unidade(con, rc, u, ciclo)
    apagado = False
    if apagar_local and liberado_para_apagar(con, u.chave, ciclo):
        if hashes(p)[0] == u.md5:
            journal(con, "apagar_local", str(p), f"cópias {sorted(res)}", ciclo)
            p.unlink()
            con.execute("UPDATE membros SET local_apagado_em=? WHERE chave=?", (agora(), u.chave))
            con.commit()
            apagado = True
    return {"chave": u.chave, "copias": res, "apagado": apagado}


# ── achar e trazer de volta ─────────────────────────────────────────────────────────────────────────────
def bancos() -> list[Path]:
    """O índice local e os das outras máquinas já sincronizados."""
    out = [caminho_indice()]
    d = dir_indices_outros()
    if d.is_dir():
        out += sorted(p for p in d.glob("*.db") if p.resolve() != out[0].resolve())
    return [p for p in out if p.exists()]


def onde(consulta: str) -> list[dict]:
    """Por caminho (exato ou trecho), processo (070002/021988/2025 ou 070002_021988_2025) ou CNPJ."""
    proc = processo_de(consulta)
    cnpj = cnpj_de(consulta) if not proc else None
    out = []
    for db in bancos():
        con = conectar(db)
        if proc:
            rows = con.execute("SELECT * FROM membros WHERE processo=? LIMIT 5000", (proc,)).fetchall()
        elif cnpj:
            rows = con.execute("SELECT * FROM membros WHERE cnpj=? LIMIT 5000", (cnpj,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM membros WHERE caminho=?", (consulta,)).fetchall() or \
                con.execute("SELECT * FROM membros WHERE caminho LIKE ? LIMIT 2000", (f"%{consulta}%",)).fetchall()
        for m in rows:
            cps = con.execute("SELECT destino, url, status, conferido_em FROM copias WHERE chave=?",
                              (m["chave"],)).fetchall()
            out.append({**dict(m), "indice": db.name, "copias": [dict(c) for c in cps]})
        ext = con.execute("SELECT * FROM externos WHERE caminho_original LIKE ? LIMIT 500",
                          (f"%{consulta}%",)).fetchall() if not (proc or cnpj) else []
        out += [{**dict(e), "indice": db.name, "externo": True} for e in ext]
        con.close()
    return out


def cache_frio() -> Path:
    return Path(os.environ.get("JFN_CACHE_FRIO", str(HOME / ".cache" / "jfn-frio")))


def obter(caminho: str | Path, restaurar: bool = False, rc: Rclone | None = None) -> Path:
    """Devolve um caminho legível para `caminho`: o próprio, se existe; senão baixa do frio, confere o hash e
    entrega no cache (`~/.cache/jfn-frio/…`, regenerável) — ou no lugar original com `restaurar=True`."""
    p = Path(caminho)
    if p.exists():
        return p
    rc = rc or Rclone()
    alvo = p if restaurar else cache_frio() / str(p).lstrip("/")
    if alvo.exists():
        return alvo
    for db in bancos():
        con = conectar(db)
        ms = con.execute("SELECT m.*, u.tipo, u.bytes AS ubytes, u.md5 AS umd5, u.sha1 AS usha1 FROM membros m "
                         "JOIN unidades u USING(chave) WHERE m.caminho=? ORDER BY u.criado_em DESC",
                         (str(p),)).fetchall()
        for m in ms:
            cps = {c["destino"]: c for c in con.execute(
                "SELECT * FROM copias WHERE chave=? AND status='ok'", (m["chave"],)).fetchall()}
            for d in [d for d in PREFERENCIA_DOWNLOAD if d in cps]:
                with tempfile.TemporaryDirectory(dir=_tmp_base()) as td:
                    baixado = Path(td) / "u"
                    ok, _ = rc.baixar(cps[d]["url"], baixado, nbytes=int(m["ubytes"] or 0))
                    if not ok or not baixado.exists() or hashes(baixado)[0] != m["umd5"]:
                        continue
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    if m["tipo"] == "pacote":
                        with tarfile.open(baixado) as tf:
                            src = tf.extractfile(m["nome"])
                            if src is None:
                                continue
                            tmp_out = Path(td) / "membro"
                            with open(tmp_out, "wb") as f:
                                shutil.copyfileobj(src, f)
                    else:
                        tmp_out = baixado
                    if hashes(tmp_out)[0] != m["md5"]:
                        continue
                    shutil.move(str(tmp_out), alvo)
                    con.close()
                    return alvo
        con.close()
    raise FileNotFoundError(f"{p}: não está no disco nem no índice do armazenamento (rode `onde`)")


def _tmp_base() -> str:
    d = HOME / ".zelador" / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


# ── importar o que já existia (manifestos de mudanças anteriores) ─────────────────────────────────────
def importar_manifestos(con: sqlite3.Connection, zelador: Path = HOME / ".zelador") -> dict:
    n = {"nuvem": 0, "itcampo": 0, "frio_vm2": 0}
    mn = zelador / "manifesto-nuvem.tsv"            # data, original, bytes, sha256, r2, b2
    if mn.exists():
        for ln in mn.read_text(encoding="utf-8").splitlines():
            c = ln.split("\t")
            if len(c) < 6 or c[0] == "data":
                continue
            for onde_ in (c[4], c[5]):
                con.execute("INSERT OR REPLACE INTO externos VALUES(?,?,?,?,?,?,?,?)",
                            ("manifesto-nuvem", c[1], onde_, "sha256", c[3], int(c[2] or 0), c[0], "importado"))
                n["nuvem"] += 1
    mi = zelador / "manifesto-itcampo.tsv"          # original, destino, md5, bytes, data
    if mi.exists():
        for ln in mi.read_text(encoding="utf-8").splitlines():
            c = ln.split("\t")
            if len(c) < 5:
                continue
            con.execute("INSERT OR REPLACE INTO externos VALUES(?,?,?,?,?,?,?,?)",
                        ("manifesto-itcampo", c[0], "itcampo:" + c[1], "md5", c[2], int(c[3] or 0), c[4],
                         "so_no_itcampo"))
            n["itcampo"] += 1
    jf = REPO / "data" / "sei_arquivo_frio.jsonl"   # pasta → vm2/itcampo (lane horária da VM-1)
    if jf.exists():
        for ln in jf.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if "pasta" in d and "destino" in d:
                con.execute("INSERT OR REPLACE INTO externos VALUES(?,?,?,?,?,?,?,?)",
                            ("sei_arquivo_frio", d["pasta"], d["destino"], "", "", 0, d.get("em", ""),
                             "rc=" + str(d.get("rc"))))
                n["frio_vm2"] += 1
    con.commit()
    return n


def _prefixo_frio(nome: str) -> str:
    """'b2:jfn-backup-jorge/frio' com raiz 'b2:jfn-backup-jorge' → 'frio/' (o caminho do frio dentro da raiz)."""
    c = NUVENS["remotos"][nome]
    raiz, frio = c["raiz"].rstrip("/"), c["frio"].rstrip("/")
    rel = frio[len(raiz):].lstrip("/") if frio.startswith(raiz) else frio.split(":", 1)[1]
    return (rel + "/") if rel else ""


def inventariar_nuvens(con: sqlite3.Connection, rc: Rclone, bases: dict[str, str] | None = None) -> dict:
    """Foto do que existe em cada remoto (rclone lsjson -R) e marca cópias do índice que sumiram/divergem."""
    bases = bases or {n: c["raiz"] for n, c in NUVENS["remotos"].items()}
    out = {}
    for nome, base in bases.items():
        if rc.orcamento is not None and nome in NUVENS["remotos"]:
            motivo = rc.orcamento.recusa(nome, custo_operacao(NUVENS["remotos"][nome].get("tipo", ""), "listar"))
            if motivo:                      # limite grátis do dia: não lista, não é "erro" — é recusa escalada
                rc.orcamento.recusas.append(f"listar {base}: {motivo}")
                out[nome] = "recusado: " + motivo
                continue
        itens = rc.listar(base)
        if itens is None:
            out[nome] = "erro"
            continue
        con.execute("DELETE FROM remotos WHERE remoto=?", (nome,))
        con.executemany("INSERT OR REPLACE INTO remotos VALUES(?,?,?,?,?,?)",
                        [(nome, i["Path"], i.get("Size"), (i.get("Hashes") or {}).get("md5"),
                          (i.get("Hashes") or {}).get("sha1"), agora()) for i in itens])
        out[nome] = len(itens)
    con.commit()
    # divergências: cópia 'ok' no índice que não aparece no inventário do remoto
    sumidas = []
    for c in con.execute("SELECT c.chave, c.destino, c.bytes FROM copias c WHERE c.status='ok'").fetchall():
        if not isinstance(out.get(c["destino"]), int) or c["destino"] not in NUVENS["remotos"]:
            continue
        r = con.execute("SELECT bytes FROM remotos WHERE remoto=? AND caminho=?",
                        (c["destino"], _prefixo_frio(c["destino"]) + c["chave"])).fetchone()
        if r is None or int(r["bytes"] or -1) != int(c["bytes"] or -2):
            sumidas.append((c["chave"], c["destino"]))
            con.execute("UPDATE copias SET status=?, detalhe=? WHERE chave=? AND destino=?",
                        ("sumida" if r is None else "divergente", "inventário " + agora(), c["chave"], c["destino"]))
    con.commit()
    out["copias_sumidas_ou_divergentes"] = sumidas
    return out


def testar_recuperacao(con: sqlite3.Connection, rc: Rclone, amostra: int = 3, maximo_mb: int = 300) -> list[dict]:
    """A cópia que não volta não é cópia — mas sem queimar o grátis (dono 21/11):

    1. Por destino, `amostra` cópias conferidas pela LISTAGEM (tamanho + md5/sha1 que o provedor devolve, sem
       baixar nada; no B2 cada uma custa 1 Classe B).
    2. Por destino, UM download de verdade (a menor cópia da amostra, ≤ `maximo_mb`), só se o pré-voo deixar
       (B2: teto de amostra `amostra_download_mb_dia` da config, ex. 50 MB/dia). Remoto sem hash na listagem
       (MEGA) só se confere por download — o mesmo teto vale.
    Recusa do pré-voo não é falha (o hash da listagem já provou a cópia); hash errado é."""
    rows = con.execute("SELECT c.chave, c.destino, c.url, u.md5, u.sha1, u.bytes FROM copias c JOIN unidades u "
                       "USING(chave) WHERE c.status='ok' AND u.bytes <= ?", (maximo_mb << 20,)).fetchall()
    por_destino: dict[str, list] = {}
    for r in rows:
        if r["destino"] in DESTINOS:
            por_destino.setdefault(r["destino"], []).append(r)
    res = []
    for d, lst in por_destino.items():
        escolhidos = random.sample(lst, min(amostra, len(lst)))
        sem_hash = []
        for r in escolhidos:
            st, _, det = conferir_copia(rc, d, r["chave"], r["bytes"], r["md5"], r["sha1"], permitir_download=False)
            if st == "sem_hash":
                sem_hash.append(r)
                continue
            res.append({"chave": r["chave"], "destino": d, "ok": st == "ok", "modo": "listagem",
                        "detalhe": det if st != "ok" else ""})
        for r in sorted(sem_hash or escolhidos, key=lambda x: int(x["bytes"] or 0))[:1]:
            with tempfile.TemporaryDirectory(dir=_tmp_base()) as td:
                p = Path(td) / "t"
                ok, err = rc.baixar(r["url"], p, nbytes=int(r["bytes"] or 0), amostra=True)
                if not ok and err.startswith("RECUSADO"):
                    res.append({"chave": r["chave"], "destino": d, "ok": r not in sem_hash, "modo": "download recusado",
                                "detalhe": err[:300]})
                    continue
                h = hashes(p)[0] if ok and p.exists() else None
                res.append({"chave": r["chave"], "destino": d, "ok": h == r["md5"], "modo": "download",
                            "detalhe": "" if h == r["md5"] else (err or f"hash {h} ≠ {r['md5']}")[-300:]})
    return res


def exportar_indice(con: sqlite3.Connection, rc: Rclone, maq: str | None = None) -> dict[str, str]:
    """Cópia do índice em DOIS provedores: o principal + o 1º remoto de `segunda_copia` que o pré-voo aceitar
    (o índice é insubstituível e não pode morar só numa máquina). Ver `indice_exportado`."""
    maq = maq or maquina()
    principal = NUVENS["principal"]
    with tempfile.TemporaryDirectory(dir=_tmp_base()) as td:
        snap = Path(td) / f"{maq}.db"
        dst = sqlite3.connect(str(snap))
        con.backup(dst)
        dst.close()
        md5, sha1 = hashes(snap)
        out = {}
        for vaga in POLITICA["insubstituivel"]:
            for d in vaga:
                if d not in INDICE_REMOTO:
                    continue
                u = f"{INDICE_REMOTO[d]}/{maq}.db"
                ok, err = rc.enviar(snap, u)
                if not ok and err.startswith("RECUSADO"):
                    out[d] = err[:300]
                    continue
                st = rc.stat(u)
                hs = {k.lower(): (v or "").lower() for k, v in ((st or {}).get("Hashes") or {}).items()}
                bom = bool(st) and int(st.get("Size", -1)) == snap.stat().st_size and \
                    (hs.get("md5") == md5 or hs.get("sha1") == sha1 or
                     (not hs.get("md5") and not hs.get("sha1") and rc.hash_baixando(u, "md5", snap.stat().st_size) == md5))
                out[d] = "ok" if bom else f"falhou {err[-200:]}"
                if bom:
                    break
        out.setdefault(principal, "não tentado")
    return out


def indice_exportado(out: dict[str, str]) -> bool:
    """Principal 'ok' e pelo menos um remoto de `segunda_copia` 'ok'."""
    return vagas_satisfeitas("insubstituivel", {d for d, s in out.items() if s == "ok"})


def sincronizar_indices(rc: Rclone | None = None) -> dict[str, str]:
    """Baixa os índices das outras máquinas (do remoto que responder, na ordem de preferência de download)."""
    rc = rc or Rclone()
    out = {}
    d = dir_indices_outros()
    d.mkdir(parents=True, exist_ok=True)
    bases = [INDICE_REMOTO[n] for n in PREFERENCIA_DOWNLOAD if n in INDICE_REMOTO]
    for maq in ("vm1", "vm2", "itcampo"):
        if maq == maquina():
            continue
        for base in bases:
            ok, _ = rc.baixar(f"{base}/{maq}.db", d / f"{maq}.db")
            if ok:
                out[maq] = base
                break
        else:
            out[maq] = "não encontrado"
    return out


def resumo(con: sqlite3.Connection | None = None) -> dict:
    out: dict = {"indices": [str(b) for b in bancos()], "por_maquina_classe": [], "copias": [], "externos": []}
    for db in bancos():
        c = conectar(db)
        out["por_maquina_classe"] += [dict(r) for r in c.execute(
            "SELECT maquina, classe, natureza, COUNT(*) unidades, SUM(n_membros) arquivos, "
            "ROUND(SUM(bytes)/1e9,2) gb FROM unidades GROUP BY 1,2,3 ORDER BY gb DESC")]
        out["copias"] += [dict(r) for r in c.execute(
            "SELECT destino, status, COUNT(*) n, ROUND(SUM(bytes)/1e9,2) gb FROM copias GROUP BY 1,2")]
        out["externos"] += [dict(r) for r in c.execute(
            "SELECT origem, status, COUNT(*) n, ROUND(SUM(bytes)/1e9,2) gb FROM externos GROUP BY 1,2")]
        out.setdefault("remotos", []).extend(dict(r) for r in c.execute(
            "SELECT remoto, COUNT(*) objetos, ROUND(SUM(bytes)/1e9,2) gb FROM remotos GROUP BY 1"))
        c.close()
    return out


def conferir(con: sqlite3.Connection, rc: Rclone, amostra: int = 20) -> list[dict]:
    rows = con.execute("SELECT c.chave, c.destino, u.bytes, u.md5, u.sha1 FROM copias c JOIN unidades u "
                       "USING(chave) WHERE c.status='ok'").fetchall()
    res = []
    for r in random.sample(rows, min(amostra, len(rows))):
        st, ht, det = conferir_copia(rc, r["destino"], r["chave"], r["bytes"], r["md5"], r["sha1"],
                                     permitir_download=False)
        if st not in ("ok", "sem_hash"):
            con.execute("UPDATE copias SET status=?, detalhe=? WHERE chave=? AND destino=?",
                        (st, det, r["chave"], r["destino"]))
        else:
            con.execute("UPDATE copias SET conferido_em=? WHERE chave=? AND destino=?",
                        (agora(), r["chave"], r["destino"]))
        res.append({"chave": r["chave"], "destino": r["destino"], "status": st, "detalhe": det})
    con.commit()
    return res


# ── consolidação do frio legado (R2 × B2 iguais, 21/11) ────────────────────────────────────────────────
def classe_por_caminho(caminho: str) -> str:
    c, nome = caminho.lower(), caminho.rsplit("/", 1)[-1].lower()
    if "compliance" in nome and (".db" in nome or nome.endswith(".zst")):
        return "backup_db"
    if "/sei_cache/" in c or "/sei_pdfs/" in c:
        return "sei_cache"
    if "/tse_cache/" in c:
        return "tse"
    if any(k in c for k in ("/contasrio/", "/ajovem_folhas/", "/tfe_cache/", "/pcrj_opendata/", "/cge_paineis/")):
        return "coleta_cache"
    if "/vm2_quarentena/" in c:
        return "quarentena"
    if "/vm2_substituidos/" in c or "/sei_arquivo_substituido/" in c or "/_substituido" in c:
        return "substituido"
    return "trabalho"                    # na dúvida, insubstituível (duas cópias)


def consolidar_legado(con: sqlite3.Connection, rc: Rclone, aplicar: bool = False,
                      ignorar: set[str] | None = None, maq: str | None = None) -> list[dict]:
    """`frio/` do R2 e do B2 eram cópias iguais (offload-nuvem.sh) e o R2 recebeu o re-obtível da VM-2 em 21/11:
    os dois passaram dos 10 GB grátis. Política: re-obtível → só o principal (Drive); insubstituível → principal
    + o que couber no grátis (fica onde está). Para cada objeto do R2 desta máquina (`<maq>/…`, o índice dela é
    quem sabe dos pacotes): garante a cópia no Drive conferida por hash e SÓ ENTÃO apaga o re-obtível do R2 e
    do B2. `ignorar`: caminhos que não vão ao Drive nem ficam (duplicata provada à parte)."""
    maq = maq or maquina()
    principal = NUVENS["principal"]
    r2 = {i["Path"]: i for i in (rc.listar(DESTINOS["r2"]) or [])}
    b2 = {i["Path"]: i for i in (rc.listar(DESTINOS["b2"]) or [])}
    if not r2:
        raise ErroArmazenamento("listagem do R2 vazia ou falhou — nada a consolidar")
    out = []
    for path, o in sorted(r2.items()):
        if (ignorar and path in ignorar) or not path.startswith(f"{maq}/"):
            continue
        ja = con.execute("SELECT classe, natureza FROM unidades WHERE chave=?", (path,)).fetchone()
        classe = ja["classe"] if ja else classe_por_caminho(path)
        nat = CLASSES[classe]
        tam = int(o.get("Size", -1))
        md5 = ((o.get("Hashes") or {}).get("md5") or "").lower() or rc.hash_baixando(url("r2", path), "md5", tam)
        sha1 = rc.hash_baixando(url("r2", path), "sha1", tam) if nat == "insubstituivel" else ""
        if not md5:
            out.append({"path": path, "status": "sem md5 no R2"})
            continue
        reg = {"path": path, "classe": classe, "natureza": nat, "bytes": tam}
        st, _, det = conferir_copia(rc, principal, path, tam, md5, sha1 or "-")
        if st != "ok" and aplicar:
            ok, err = rc.copiar(url("r2", path), url(principal, path), tam)
            st, _, det = conferir_copia(rc, principal, path, tam, md5, sha1 or "-")
            if st != "ok":
                det = f"{det} | {err[-200:]}"
        reg[principal] = st
        if st != "ok":
            reg["detalhe"] = det[:300]
        b = b2.get(path)
        bsha = ((b or {}).get("Hashes") or {}).get("sha1", "").lower() if b else ""
        reg["b2"] = "ausente" if not b else ("ok" if (int(b.get("Size", -2)) == tam and (not sha1 or bsha == sha1))
                                             else "divergente")
        if not ja:                          # o que o índice não conhecia entra como arquivo (nunca rebaixa pacote)
            con.execute("INSERT OR IGNORE INTO unidades(chave, maquina, origem, tipo, classe, natureza, processo, "
                        "cnpj, bytes, md5, sha1, n_membros, criado_em, ciclo, assinatura) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (path, maq, "/home/ubuntu/" + path.split("/", 1)[1], "arquivo", classe, nat,
                         processo_de(path), cnpj_de(path), tam, md5, sha1, 1, agora(), "consolidacao-legado", ""))
            con.execute("INSERT OR IGNORE INTO membros VALUES(?,?,?,?,?,?,?,?,?)",
                        (maq, "/home/ubuntu/" + path.split("/", 1)[1], path, "", tam, md5,
                         processo_de(path), cnpj_de(path), "antes de 21/11 (offload-nuvem.sh)"))
        for d, s_ in ((principal, reg[principal]), ("b2", reg["b2"]), ("r2", "ok")):
            if s_ == "ausente":
                continue
            con.execute("INSERT OR REPLACE INTO copias VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (path, d, url(d, path), s_, "sha1" if d == "b2" else "md5", sha1 if d == "b2" else md5,
                         tam, None, agora(), "consolidacao-legado" if s_ == "ok" else None, ""))
        con.commit()
        sai = (["r2"] + (["b2"] if b else [])) if nat == "reobtivel" and reg[principal] == "ok" else []
        reg["sai"] = sai
        if aplicar:
            for d in sai:
                journal(con, "apagar_nuvem", url(d, path), f"fica: {principal} (md5 conferido)", "consolidacao-legado")
                ok, err = rc.apagar(url(d, path))
                if ok:
                    con.execute("DELETE FROM copias WHERE chave=? AND destino=?", (path, d))
                    con.commit()
                    if rc.orcamento is not None:
                        rc.orcamento.somar_uso(d, -tam)
                else:
                    reg.setdefault("erros", []).append(f"{d}: {err[-200:]}")
        out.append(reg)
    return out


# ── o grátis que sobra: encher os remotos de `segunda_copia` até o alvo, por prioridade (dono 21/11) ──────────
def estado_nuvens(rc: Rclone) -> dict:
    """Uso real + alvo + consumo do dia/mês de cada remoto da config (o pré-voo, visível)."""
    out = {}
    for nome, cfg in NUVENS["remotos"].items():
        au = rc.orcamento.alvo_e_usado(nome, rc) if rc.orcamento else None
        u = (rc.orcamento.uso.get(nome) or {}) if rc.orcamento else {}
        cons = rc.orcamento.consumo(nome) if rc.orcamento else {}
        out[nome] = {"usado_gb": round(au[1] / 1e9, 2) if au else None,
                     "alvo_gb": round(au[0] / 1e9, 2) if au else None,
                     "total_gb": round((cfg.get("armazenamento_gb") or 0) or (u.get("total") or 0) / 1e9, 2),
                     "medido_por": u.get("como"),
                     "hoje": {k: v for k, v in (cons.get("dia") or {}).items() if k != "chave"},
                     "mes": {k: v for k, v in (cons.get("mes") or {}).items() if k != "chave"},
                     "esgotado_ate": cons.get("esgotado_ate")}
    return out


def snapshot_sqlite_gz(origem: Path, destino_gz: Path) -> Path:
    """Cópia CONSISTENTE de um banco vivo (API de backup do SQLite, em lotes com pausa: não trava escritores),
    `quick_check` e gzip -1 (nice/ionice). Nunca toca o original."""
    cru = destino_gz.with_suffix("")
    cru.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(str(origem), timeout=120)
    b = sqlite3.connect(str(cru))
    with b:
        s.backup(b, pages=4000, sleep=0.02)
    b.close()
    s.close()
    chk = sqlite3.connect(str(cru)).execute("PRAGMA quick_check(1)").fetchone()[0]
    if chk != "ok":
        cru.unlink(missing_ok=True)
        raise ErroArmazenamento(f"quick_check do snapshot de {origem}: {chk}")
    pre = [x for x in (["nice", "-n", "19"], ["ionice", "-c3"]) if shutil.which(x[0])]
    subprocess.run([*sum(pre, []), "gzip", "-1", "-f", str(cru)], check=True)
    return destino_gz


def encher(con: sqlite3.Connection, rc: Rclone, aplicar: bool = False, itens: list | None = None,
           remotos: list | None = None) -> list[dict]:
    """Ocupa o grátis que sobra nos remotos de `enchimento.remotos` (B2, R2) com os itens da config, NA ORDEM
    (insubstituível primeiro), até o alvo de cada um (limite − margem − reserva, medido no remoto). Cada item
    também fica no principal. Chave estável por item (`<maq>/<caminho>.gz`): o snapshot novo substitui o velho
    (espaço limitado não acumula). Item que não cabe num remoto é pulado nele (um menor depois ainda pode
    caber) — isso não é recusa; recusa de operação (dia/mês) é, e vai para `orcamento.recusas`.
    Sem `aplicar`: só o plano, pelo tamanho CRU do arquivo (teto: o .gz é menor)."""
    cfg = NUVENS.get("enchimento", {})
    itens = itens if itens is not None else cfg.get("itens", [])
    remotos = [r for r in (remotos or cfg.get("remotos", [])) if r in NUVENS["remotos"]]
    principal = NUVENS["principal"]
    maq = maquina()
    ciclo = "encher-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = []
    todos = remotos
    for it in itens:
        remotos = [r for r in it.get("remotos", todos) if r in todos]     # item pode excluir um remoto
        src = Path(it["caminho"]).expanduser()
        src = src if src.is_absolute() else HOME / src
        reg = {"item": it["nome"], "origem": str(src)}
        out.append(reg)
        if not src.is_file():
            reg["status"] = "ausente"
            continue
        sqlite_ = it.get("tipo") == "sqlite"
        original = Path(str(src) + ".gz") if sqlite_ else src
        chave = chave_de(original, maq)
        antigos = {d: int((rc.stat(url(d, chave)) or {}).get("Size", 0) or 0) for d in [principal, *remotos]}
        estimado = src.stat().st_size
        cabem = [d for d in remotos if rc.pode_enviar(d, estimado, substitui=antigos[d]) is None]
        # o .gz de um banco SQLite raramente fica abaixo de 1/4 do cru: abaixo disso nem vale gerar o snapshot
        talvez = cabem + [d for d in remotos if d not in cabem and sqlite_
                          and rc.pode_enviar(d, estimado // 4, antigos[d]) is None]
        reg.update(chave=chave, estimado_gb=round(estimado / 1e9, 3), destinos_plano=[principal, *cabem],
                   talvez_comprimido=[d for d in talvez if d not in cabem])
        if not talvez:
            reg["status"] = "não cabe em nenhum remoto grátis"
            continue
        if not aplicar:
            reg["status"] = "plano"
            continue
        with tempfile.TemporaryDirectory(dir=_tmp_base()) as td:
            arq = snapshot_sqlite_gz(src, Path(td) / (src.name + ".gz")) if sqlite_ else src
            n = arq.stat().st_size
            u = unidade_arquivo(arq, it.get("classe", "backup_db"), original=original, maq=maq)
            u.chave = chave
            destinos = [principal] + [d for d in remotos if rc.pode_enviar(d, n, substitui=antigos[d]) is None]
            registrar_unidade(con, u, ciclo)
            res = {}
            for d in destinos:
                res[d] = _enviar_a(con, rc, u, d, ciclo, substitui=antigos[d] if d != principal else 0)
            reg.update(bytes_gb=round(n / 1e9, 3), copias=res,
                       status="ok" if res.get(principal) == "ok" and len(copias_ok(res)) >= 2 else "incompleto")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.armazenamento", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("onde"); p.add_argument("consulta")
    p = sub.add_parser("obter"); p.add_argument("caminho"); p.add_argument("--restaurar", action="store_true")
    p = sub.add_parser("guardar"); p.add_argument("arquivo"); p.add_argument("--classe", required=True)
    p.add_argument("--apagar-local", action="store_true")
    sub.add_parser("resumo")
    p = sub.add_parser("conferir"); p.add_argument("--amostra", type=int, default=20)
    sub.add_parser("sincronizar")
    sub.add_parser("importar")
    sub.add_parser("inventariar")
    p = sub.add_parser("consolidar-legado"); p.add_argument("--aplicar", action="store_true")
    p.add_argument("--ignorar", nargs="*", default=[])
    sub.add_parser("nuvens")
    p = sub.add_parser("encher"); p.add_argument("--aplicar", action="store_true")
    p.add_argument("--item", nargs="*", default=None, help="só estes itens da config (nome)")
    a = ap.parse_args(argv)
    if a.cmd == "onde":
        rs = onde(a.consulta)
        for r in rs[:200]:
            print(json.dumps(r, ensure_ascii=False, default=str))
        print(f"# {len(rs)} registro(s)", file=sys.stderr)
        return 0 if rs else 1
    if a.cmd == "obter":
        print(obter(a.caminho, restaurar=a.restaurar))
        return 0
    if a.cmd == "guardar":
        print(json.dumps(guardar(a.arquivo, a.classe, apagar_local=a.apagar_local), ensure_ascii=False))
        return 0
    if a.cmd == "resumo":
        print(json.dumps(resumo(), ensure_ascii=False, indent=1, default=str))
        return 0
    con = conectar()
    if a.cmd == "conferir":
        r = conferir(con, Rclone(), a.amostra)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if all(x["status"] in ("ok", "sem_hash") for x in r) else 2
    if a.cmd == "sincronizar":
        print(json.dumps(sincronizar_indices(), ensure_ascii=False))
        return 0
    if a.cmd == "importar":
        print(json.dumps(importar_manifestos(con), ensure_ascii=False))
        return 0
    if a.cmd == "nuvens":
        print(json.dumps(estado_nuvens(Rclone()), ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("consolidar-legado", "encher"):
        rc = Rclone()
        if a.cmd == "encher":
            its = [i for i in NUVENS.get("enchimento", {}).get("itens", []) if not a.item or i["nome"] in a.item]
            r = encher(con, rc, aplicar=a.aplicar, itens=its)
        else:
            r = consolidar_legado(con, rc, aplicar=a.aplicar, ignorar=set(a.ignorar))
        for x in r:
            print(json.dumps(x, ensure_ascii=False))
        for m in (rc.orcamento.recusas if rc.orcamento else []):
            print("RECUSADO", m, file=sys.stderr)
        return 0 if not (rc.orcamento and rc.orcamento.recusas) else 3
    if a.cmd == "inventariar":
        r = inventariar_nuvens(con, Rclone())
        print(json.dumps({k: (v if k != "copias_sumidas_ou_divergentes" else len(v)) for k, v in r.items()},
                         ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
