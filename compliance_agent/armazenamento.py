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
        → DUAS cópias em provedores DIFERENTES: Drive + B2.
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

# ── destinos (a mesma CHAVE `<maquina>/<caminho relativo>` em todos) ─────────────────────────────────────
DESTINOS = {
    "gdrive": "gdrive:frio",                 # pasta JFN (root_folder_id no rclone.conf) → frio/
    "b2": "b2:jfn-backup-jorge/frio",
    "r2": "r2:jorgefelippe/frio",            # legado/serviço (fachadas, anexos); não é destino padrão do frio
}
INDICE_REMOTO = {"gdrive": "gdrive:indice", "b2": "b2:jfn-backup-jorge/indice"}

# Natureza → destinos obrigatórios (todos conferidos por hash NO MESMO ciclo antes de apagar o local).
# `JFN_DESTINO_REOBTIVEL` troca o destino do re-obtível SEM mudar a regra de 1 cópia (21/11: o cliente OAuth
# padrão do rclone é compartilhado e o Drive responde `rateLimitExceeded`; até o dono criar o cliente próprio, a
# VM-2 em 98% usou o R2 — saída grátis, US$ 0,015/GB). Quando voltar ao Drive, o zelador reconfere, não acha a
# cópia no Drive e reenvia: a migração R2 → Drive é automática.
_REOBTIVEL = os.environ.get("JFN_DESTINO_REOBTIVEL", "gdrive")
if _REOBTIVEL not in DESTINOS:
    raise ValueError(f"JFN_DESTINO_REOBTIVEL inválido: {_REOBTIVEL}")
POLITICA = {
    "reobtivel": (_REOBTIVEL,),
    "insubstituivel": ("gdrive", "b2"),
}
CLASSES = {
    # re-obtível da fonte pública
    "sei_pdf": "reobtivel", "sei_foto": "reobtivel", "sei_cache": "reobtivel", "sei_arvore": "reobtivel",
    "quarentena": "reobtivel", "substituido": "reobtivel", "tse": "reobtivel", "pncp": "reobtivel",
    "receita": "reobtivel", "coleta_cache": "reobtivel",
    # insubstituível
    "backup_db": "insubstituivel", "trabalho": "insubstituivel", "sessao_claude": "insubstituivel",
    "indice": "insubstituivel", "relatorio": "insubstituivel", "midia": "insubstituivel",
}
PREFERENCIA_DOWNLOAD = ("r2", "gdrive", "b2")   # R2 e Drive: saída sem custo; B2 tem teto diário (Caps)

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


@dataclass
class Rclone:
    binario: str = field(default_factory=lambda: os.environ.get("JFN_RCLONE") or shutil.which("rclone")
                         or str(HOME / ".local" / "bin" / "rclone"))
    timeout: int = 7200
    # --tpslimit: o cliente OAuth padrão do rclone é compartilhado no mundo todo e o Drive responde
    # `rateLimitExceeded` (medido 21/11: um tar de 103 MB parado 7 min em backoff). 4 req/s evita a espiral.
    extra: list = field(default_factory=lambda: ["--retries", "3", "--low-level-retries", "20", "--tpslimit", "4",
                                                 "--drive-chunk-size", "32M", "--contimeout", "60s",
                                                 "--timeout", "300s"])

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([self.binario, *args, *self.extra], capture_output=True, text=True,
                                  timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(e.cmd, 124, "", "timeout")
        except OSError as e:
            return subprocess.CompletedProcess([self.binario], 127, "", str(e))

    def enviar(self, local: Path, remoto: str) -> tuple[bool, str]:
        r = self._run(["copyto", "--checksum", str(local), remoto])
        return r.returncode == 0, (r.stderr or "")[-500:]

    def baixar(self, remoto: str, local: Path) -> tuple[bool, str]:
        r = self._run(["copyto", remoto, str(local)])
        return r.returncode == 0, (r.stderr or "")[-500:]

    def stat(self, remoto: str) -> dict | None:
        """Objeto remoto (Size, Hashes) ou None se não existe/erro. Não confia no rc do envio."""
        r = self._run(["lsjson", "--stat", "--hash", remoto], timeout=600)
        if r.returncode != 0:
            return None
        try:
            d = json.loads(r.stdout or "null")
        except ValueError:
            return None
        return d if isinstance(d, dict) and not d.get("IsDir") else None

    def hash_baixando(self, remoto: str, tipo: str = "md5") -> str | None:
        r = self._run(["hashsum", tipo, "--download", remoto], timeout=7200)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout.split()[0].lower()

    def apagar(self, remoto: str) -> tuple[bool, str]:
        r = self._run(["deletefile", remoto], timeout=600)
        return r.returncode == 0, (r.stderr or "")[-500:]

    def listar(self, base: str) -> list[dict] | None:
        r = self._run(["lsjson", "-R", "--files-only", "--hash", base], timeout=7200)
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout or "[]")
        except ValueError:
            return None

    def acessivel(self, base: str) -> bool:
        r = self._run(["lsf", "--max-depth", "1", base], timeout=300)
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
    h = rc.hash_baixando(u, "md5")
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


def enviar_unidade(con: sqlite3.Connection, rc: Rclone, u: Unidade, ciclo: str,
                   destinos: tuple[str, ...] | None = None) -> dict[str, str]:
    """Sobe a unidade a cada destino da política e confere cada cópia NESTE ciclo. Devolve {destino: status}."""
    destinos = destinos or POLITICA[u.natureza]
    registrar_unidade(con, u, ciclo)
    res = {}
    for d in destinos:
        journal(con, "enviar", u.chave, d, ciclo)
        ok, err = rc.enviar(u.arquivo, url(d, u.chave))
        status, htipo, det = conferir_copia(rc, d, u.chave, u.bytes, u.md5, u.sha1)
        if not ok and status == "ok":
            det = f"rclone rc≠0 mas cópia conferida: {err[-200:]}"
        elif not ok:
            det = f"rclone falhou: {err[-300:]} | {det}"
        con.execute("INSERT OR REPLACE INTO copias VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (u.chave, d, url(d, u.chave), status, htipo, u.md5 if htipo.startswith("md5") else u.sha1,
                     u.bytes, agora(), agora(), ciclo if status == "ok" else None, det))
        con.commit()
        res[d] = status
    return res


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
        if set(POLITICA.get(r["natureza"], ("?",))) <= oks:
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
    res = {}
    for d in POLITICA[u.natureza]:
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
    """A trava central: TODOS os destinos da política conferidos por hash NESTE ciclo (não em ciclo anterior)."""
    r = con.execute("SELECT natureza FROM unidades WHERE chave=?", (chave,)).fetchone()
    if not r or r["natureza"] not in POLITICA:
        return False
    exigidos = set(POLITICA[r["natureza"]])
    return exigidos <= copias_conferidas_no_ciclo(con, chave, ciclo)


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
                    ok, _ = rc.baixar(cps[d]["url"], baixado)
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


def inventariar_nuvens(con: sqlite3.Connection, rc: Rclone, bases: dict[str, str] | None = None) -> dict:
    """Foto do que existe em cada remoto (rclone lsjson -R) e marca cópias do índice que sumiram/divergem."""
    bases = bases or {"r2": "r2:jorgefelippe", "b2": "b2:jfn-backup-jorge", "gdrive": "gdrive:"}
    out = {}
    for nome, base in bases.items():
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
    prefixo = {"gdrive": "frio/", "b2": "frio/", "r2": "frio/"}
    sumidas = []
    for c in con.execute("SELECT c.chave, c.destino, c.bytes FROM copias c WHERE c.status='ok'").fetchall():
        if out.get(c["destino"]) in (None, "erro"):
            continue
        r = con.execute("SELECT bytes FROM remotos WHERE remoto=? AND caminho=?",
                        (c["destino"], prefixo[c["destino"]] + c["chave"])).fetchone()
        if r is None or int(r["bytes"] or -1) != int(c["bytes"] or -2):
            sumidas.append((c["chave"], c["destino"]))
            con.execute("UPDATE copias SET status=?, detalhe=? WHERE chave=? AND destino=?",
                        ("sumida" if r is None else "divergente", "inventário " + agora(), c["chave"], c["destino"]))
    con.commit()
    out["copias_sumidas_ou_divergentes"] = sumidas
    return out


def testar_recuperacao(con: sqlite3.Connection, rc: Rclone, amostra: int = 3, maximo_mb: int = 300) -> list[dict]:
    """Traz de volta uma amostra de cópias e confere o hash. Qualquer falha é falha do ciclo."""
    rows = con.execute("SELECT c.chave, c.destino, c.url, u.md5, u.bytes FROM copias c JOIN unidades u "
                       "USING(chave) WHERE c.status='ok' AND u.bytes <= ?", (maximo_mb << 20,)).fetchall()
    por_destino: dict[str, list] = {}
    for r in rows:
        por_destino.setdefault(r["destino"], []).append(r)
    res = []
    for d, lst in por_destino.items():
        for r in random.sample(lst, min(amostra, len(lst))):
            with tempfile.TemporaryDirectory(dir=_tmp_base()) as td:
                p = Path(td) / "t"
                ok, err = rc.baixar(r["url"], p)
                h = hashes(p)[0] if ok and p.exists() else None
                res.append({"chave": r["chave"], "destino": d, "ok": h == r["md5"],
                            "detalhe": "" if h == r["md5"] else (err or f"hash {h} ≠ {r['md5']}")[-300:]})
    return res


def exportar_indice(con: sqlite3.Connection, rc: Rclone, maq: str | None = None) -> dict[str, str]:
    """Cópia do índice nas DUAS nuvens (o índice é insubstituível e não pode morar só numa máquina)."""
    maq = maq or maquina()
    with tempfile.TemporaryDirectory(dir=_tmp_base()) as td:
        snap = Path(td) / f"{maq}.db"
        dst = sqlite3.connect(str(snap))
        con.backup(dst)
        dst.close()
        md5, sha1 = hashes(snap)
        out = {}
        for d, base in INDICE_REMOTO.items():
            u = f"{base}/{maq}.db"
            ok, err = rc.enviar(snap, u)
            st = rc.stat(u)
            hs = {k.lower(): (v or "").lower() for k, v in ((st or {}).get("Hashes") or {}).items()}
            bom = bool(st) and int(st.get("Size", -1)) == snap.stat().st_size and \
                (hs.get("md5") == md5 or hs.get("sha1") == sha1)
            out[d] = "ok" if bom else f"falhou {err[-200:]}"
    return out


def sincronizar_indices(rc: Rclone | None = None) -> dict[str, str]:
    """Baixa os índices das outras máquinas (de qualquer nuvem que responda) para ~/.zelador/indices/."""
    rc = rc or Rclone()
    out = {}
    d = dir_indices_outros()
    d.mkdir(parents=True, exist_ok=True)
    for maq in ("vm1", "vm2", "itcampo"):
        if maq == maquina():
            continue
        for base in INDICE_REMOTO.values():
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
    return "trabalho"                    # na dúvida, insubstituível (duas cópias)


def consolidar_legado(con: sqlite3.Connection, rc: Rclone, aplicar: bool = False,
                      ignorar: set[str] | None = None) -> list[dict]:
    """`frio/` do R2 e do B2 eram cópias iguais (offload-nuvem.sh). Política nova: re-obtível → só Drive;
    insubstituível → Drive + B2. Para cada objeto: garante a cópia que FICA (conferida por hash) e só então apaga
    a que sai. `ignorar`: caminhos que não vão ao Drive nem ficam (duplicata provada à parte)."""
    r2 = {i["Path"]: i for i in (rc.listar(DESTINOS["r2"]) or [])}
    b2 = {i["Path"]: i for i in (rc.listar(DESTINOS["b2"]) or [])}
    if not r2:
        raise ErroArmazenamento("listagem do R2 vazia ou falhou — nada a consolidar")
    out = []
    for path, o in sorted(r2.items()):
        if ignorar and path in ignorar:
            continue
        classe = classe_por_caminho(path)
        nat = CLASSES[classe]
        tam = int(o.get("Size", -1))
        md5 = ((o.get("Hashes") or {}).get("md5") or "").lower() or rc.hash_baixando(url("r2", path), "md5")
        sha1 = rc.hash_baixando(url("r2", path), "sha1") if nat == "insubstituivel" else ""
        if not md5:
            out.append({"path": path, "status": "sem md5 no R2"}); continue
        reg = {"path": path, "classe": classe, "natureza": nat, "bytes": tam}
        st, _, det = conferir_copia(rc, "gdrive", path, tam, md5, sha1 or "-")
        if st != "ok" and aplicar:
            ok, err = rc._run(["copyto", url("r2", path), url("gdrive", path)]).returncode == 0, ""
            st, _, det = conferir_copia(rc, "gdrive", path, tam, md5, sha1 or "-")
        reg["gdrive"] = st
        b = b2.get(path)
        bsha = ((b or {}).get("Hashes") or {}).get("sha1", "").lower() if b else ""
        reg["b2"] = "ausente" if not b else ("ok" if (int(b.get("Size", -2)) == tam and (not sha1 or bsha == sha1))
                                             else "divergente")
        con.execute("INSERT OR REPLACE INTO unidades(chave, maquina, origem, tipo, classe, natureza, processo, cnpj, "
                    "bytes, md5, sha1, n_membros, criado_em, ciclo, assinatura) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (path, path.split("/", 1)[0], "/home/ubuntu/" + path.split("/", 1)[1], "arquivo", classe, nat,
                     processo_de(path), cnpj_de(path), tam, md5, sha1, 1, agora(), "consolidacao-legado", ""))
        con.execute("INSERT OR REPLACE INTO membros VALUES(?,?,?,?,?,?,?,?,?)",
                    (path.split("/", 1)[0], "/home/ubuntu/" + path.split("/", 1)[1], path, "", tam, md5,
                     processo_de(path), cnpj_de(path), "antes de 21/11 (offload-nuvem.sh)"))
        for d, s_ in (("gdrive", reg["gdrive"]), ("b2", reg["b2"]), ("r2", "ok")):
            con.execute("INSERT OR REPLACE INTO copias VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (path, d, url(d, path), s_, "md5" if d != "b2" else "sha1", md5 if d != "b2" else sha1,
                         tam, None, agora(), "consolidacao-legado" if s_ == "ok" else None, ""))
        con.commit()
        sai = []
        if nat == "reobtivel" and reg["gdrive"] == "ok":
            sai = ["r2"] + (["b2"] if b else [])
        elif nat == "insubstituivel" and reg["gdrive"] == "ok" and reg["b2"] == "ok":
            sai = ["r2"]
        reg["sai"] = sai
        if aplicar:
            for d in sai:
                journal(con, "apagar_nuvem", url(d, path), f"fica: {'gdrive' if nat == 'reobtivel' else 'gdrive+b2'}",
                        "consolidacao-legado")
                ok, err = rc.apagar(url(d, path))
                if ok:
                    con.execute("DELETE FROM copias WHERE chave=? AND destino=?", (path, d))
                    con.commit()
                else:
                    reg.setdefault("erros", []).append(f"{d}: {err[-200:]}")
        out.append(reg)
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
    if a.cmd == "consolidar-legado":
        r = consolidar_legado(con, Rclone(), aplicar=a.aplicar, ignorar=set(a.ignorar))
        for x in r:
            print(json.dumps(x, ensure_ascii=False))
        return 0
    if a.cmd == "inventariar":
        r = inventariar_nuvens(con, Rclone())
        print(json.dumps({k: (v if k != "copias_sumidas_ou_divergentes" else len(v)) for k, v in r.items()},
                         ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
