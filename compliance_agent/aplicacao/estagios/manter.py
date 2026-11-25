# -*- coding: utf-8 -*-
"""E17 `manter:<rotina>` — backup com a volta conferida, checkpoint do WAL, VACUUM condicional e zelador (plano
mestre v2 §3.2 E17; O8.2/O8.5). Absorve `manutencao`, `backup_*` e `zelador` como rotinas de UM estágio.

Rotinas (`ROTINAS`):
  backup_compliance     `tools/backup_compliance.sh` — snapshot a quente, cifra com age (a volta conferida por sha256
                        em `tools/cifrar_backup.sh`) e porta única; a linha "✓ off-box:" só sai depois disso;
  backup_evidencias_pg  `tools/backup_evidencias_pg.sh` — pg_dump da VM-2, age, porta única;
  wal_checkpoint        `manutencao.checkpoint_wal` (TRUNCATE, com a 2ª via do reinício do log);
  vacuum                `manutencao.vacuum` — SÓ se as páginas livres passam do mínimo (o resto é "pulado");
  zelador               `tools/zelador/zelador.py --perfil <nó> --aplicar`.

Modo SIMULAR (padrão; o único do ensaio O8.5 e da parada de obras): lista o que faria e confere as pré-condições
(script presente, `age` no PATH, destinatários age, chave para provar a volta, banco legível, páginas livres do
VACUUM, tamanho do WAL) — LÊ, nunca executa backup, checkpoint, VACUUM nem zelador. Modo real só com
`payload.simular = false` E `JFN_MANTER_REAL=1` no ambiente (religação é decisão do dono, O9.0); sem isso,
ErroPermanente.

Efeito conferido em OUTRO processo: (simular) o plano recalculado tem as mesmas pré-condições com o mesmo resultado
e nenhum backup novo apareceu em `data/backups` depois do início; (real) o comando terminou com 0 e o log tem a marca
da rotina (a de `backup_compliance` é a que o sensor `backup.compliance_idade_h` lê), ou o WAL ficou no teto / o
VACUUM pulou ou não cresceu o banco. Sem evento: a rotina é terminal (entrada = relógio).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.fluxo.fila import Resultado

TIPO = "manter"
RAIZ = Path(__file__).resolve().parents[3]
ENV_REAL = "JFN_MANTER_REAL"
TIMEOUT_S = 10800
ROTINAS: dict[str, dict] = {
    "backup_compliance": {"argv": ["bash", "tools/backup_compliance.sh"], "marca": r"\[backup\] ✓ off-box: ",
                          "precisa": ("script", "age", "destinatarios", "chave_volta", "banco")},
    "backup_evidencias_pg": {"argv": ["bash", "tools/backup_evidencias_pg.sh"], "marca": r"armazenamento rc=0\b",
                             "precisa": ("script", "age", "destinatarios", "chave_volta")},
    "wal_checkpoint": {"funcao": "checkpoint_wal", "precisa": ("banco", "wal")},
    "vacuum": {"funcao": "vacuum", "precisa": ("banco", "paginas_livres")},
    "zelador": {"argv": [sys.executable, "tools/zelador/zelador.py", "--perfil", "{perfil}", "--aplicar"],
                "marca": None, "precisa": ("script",)},
}


def rotina_de(payload: dict, ctx: Contexto | None = None) -> str:
    r = payload.get("rotina") or (ctx.tipo.split(":", 2)[1] if ctx and ":" in ctx.tipo else "")
    if r not in ROTINAS:
        raise ErroPermanente(f"E17: rotina inválida {r!r} (válidas: {', '.join(sorted(ROTINAS))})")
    return r


def _db(payload: dict) -> Path:
    return Path(payload.get("db") or os.environ.get("JFN_DB") or RAIZ / "data" / "compliance.db")


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)


def comando(rotina: str, payload: dict) -> list[str]:
    d = ROTINAS[rotina]
    if "argv" in d:
        return [a.format(perfil=payload.get("perfil") or os.environ.get("JFN_NO") or "vm1") for a in d["argv"]]
    return ["python", "-c", f"compliance_agent.manutencao.{d['funcao']}({str(_db(payload))!r})"]


def precondicao(nome: str, rotina: str, payload: dict) -> dict:
    """{nome, ok, detalhe} — só LÊ (nunca o conteúdo dos destinatários nem da chave, só se existem)."""
    from compliance_agent import manutencao as M
    db = _db(payload)
    if nome == "script":
        alvo = RAIZ / comando(rotina, payload)[1]
        return {"nome": nome, "ok": alvo.is_file(), "detalhe": str(alvo.relative_to(RAIZ))}
    if nome == "age":
        return {"nome": nome, "ok": shutil.which("age") is not None, "detalhe": "binário age no PATH"}
    if nome == "destinatarios":
        rec = Path(os.environ.get("BACKUP_AGE_RECIPIENTS") or Path.home() / ".config/jfn/backup_age_recipients.txt")
        try:
            n = sum(1 for linha in rec.read_text(encoding="utf-8").splitlines() if linha.startswith("ssh-"))
        except OSError:
            n = 0
        return {"nome": nome, "ok": n >= 1, "detalhe": f"{n} destinatário(s) age"}
    if nome == "chave_volta":
        ident = Path(os.environ.get("BACKUP_AGE_IDENTITY") or Path.home() / ".ssh/id_ed25519")
        return {"nome": nome, "ok": ident.is_file(), "detalhe": "chave desta máquina para provar a volta"}
    if nome == "banco":
        try:
            con = _ro(db)
            try:
                con.execute("PRAGMA schema_version").fetchone()
            finally:
                con.close()
            return {"nome": nome, "ok": True, "detalhe": f"{db.name} legível ({db.stat().st_size} bytes)"}
        except (sqlite3.Error, OSError) as e:
            return {"nome": nome, "ok": False, "detalhe": f"{db.name} ilegível ({type(e).__name__})"}
    if nome == "wal":
        n = M._sz(str(db) + "-wal")
        faz = n > M._WAL_TETO
        return {"nome": nome, "ok": True, "faria": faz,
                "detalhe": f"WAL {n} bytes; checkpoint {'necessário' if faz else 'dispensável'}"}
    if nome == "paginas_livres":
        try:
            con = _ro(db)
            try:
                pag = con.execute("PRAGMA page_count").fetchone()[0] or 1
                livre = round(100 * con.execute("PRAGMA freelist_count").fetchone()[0] / pag, 2)
            finally:
                con.close()
        except sqlite3.Error as e:
            return {"nome": nome, "ok": False, "detalhe": f"páginas livres ilegíveis ({type(e).__name__})"}
        faria = livre >= M._VACUUM_MIN_LIVRE_PCT
        return {"nome": nome, "ok": True, "faria": faria,
                "detalhe": f"{livre}% livres (mínimo {M._VACUUM_MIN_LIVRE_PCT}%): {'faria' if faria else 'pularia'}"}
    raise ValueError(f"pré-condição desconhecida: {nome}")


def plano(rotina: str, payload: dict) -> dict:
    pre = [precondicao(n, rotina, payload) for n in ROTINAS[rotina]["precisa"]]
    return {"rotina": rotina, "comando": comando(rotina, payload), "precondicoes": pre,
            "pronto": all(p["ok"] for p in pre)}


def _backups_depois(t0: float) -> list[str]:
    d = RAIZ / "data" / "backups"
    return sorted(p.name for p in d.glob("*") if p.is_file() and p.stat().st_mtime >= t0) if d.is_dir() else []


def _real(rotina: str, payload: dict, ctx: Contexto) -> dict:
    from compliance_agent import manutencao as M
    d = ROTINAS[rotina]
    if "funcao" in d:
        return {"retorno": getattr(M, d["funcao"])(str(_db(payload)))}
    log = RAIZ / "data" / "logs" / f"manter_{rotina}_{ctx.ficha}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as f:
        rc = subprocess.run(comando(rotina, payload), cwd=RAIZ, stdout=f, stderr=subprocess.STDOUT,
                            timeout=TIMEOUT_S).returncode
    return {"rc": rc, "log": str(log)}


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    rotina = rotina_de(payload, ctx)
    simular = payload.get("simular", True) is not False
    t0 = time.time()
    p = plano(rotina, payload)
    if simular:
        return Resultado(efeito={**p, "simulado": True, "executado": False, "t0": t0})
    if os.environ.get(ENV_REAL) != "1":
        raise ErroPermanente(f"E17 {rotina}: execução real só com {ENV_REAL}=1 (parada de obras; religação na O9.0)")
    if not p["pronto"]:
        raise ErroPermanente(f"E17 {rotina}: pré-condição falhou — "
                             + "; ".join(x["detalhe"] for x in p["precondicoes"] if not x["ok"]))
    return Resultado(efeito={**p, "simulado": False, "executado": True, "t0": t0, **_real(rotina, payload, ctx)})


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    from compliance_agent import manutencao as M
    ef = resultado.efeito or {}
    rotina = rotina_de(payload, ctx)
    if ef.get("rotina") != rotina:
        return False
    if ef.get("simulado"):
        ok = lambda pre: [(x["nome"], x["ok"], x.get("faria")) for x in pre]          # noqa: E731
        return (not ef.get("executado") and ok(plano(rotina, payload)["precondicoes"]) == ok(ef["precondicoes"])
                and not _backups_depois(float(ef.get("t0") or 0)))
    if rotina == "wal_checkpoint":
        return M._sz(str(_db(payload)) + "-wal") <= M._WAL_TETO
    if rotina == "vacuum":
        r = ef.get("retorno") or {}
        return bool(r.get("pulado")) or int(r.get("db_depois") or 0) <= int(r.get("db_antes") or 0)
    if ef.get("rc") != 0:
        return False
    marca = ROTINAS[rotina].get("marca")
    try:
        texto = Path(ef["log"]).read_text(encoding="utf-8", errors="replace")
    except (OSError, KeyError):
        return False
    return marca is None or re.search(marca, texto) is not None


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["disco"], prioridade=60,
                  volta={"nos": ["vm2", "vm1"]})
