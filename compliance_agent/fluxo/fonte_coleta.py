"""Fonte ÚNICA de leitura da coleta bruta (compliance.db) para os estágios que rodam fora da VM-1 (26/11/2026).

Antes: 5 estágios (E6, E9, E10, E11, E16) tinham cada um o caminho fixo `~/snapshot-20261124/compliance.db` — que só
existe na VM-1, enquanto eles rodam na VM-2/it-campo: toda conferência do E6 registrava «fonte SIAFE ausente». E o
snapshot é o universo CONGELADO da parada de obras: depois da religação o E1 coleta no compliance.db vivo, e quem lê
o snapshot lê dado velho.

Regra:
  · o caminho vem DAQUI (o ENV específico de cada estágio continua valendo, para ensaio/teste);
  · ordem: JFN_FONTE_COLETA → cópia RENOVADA (`~/jfn-fonte-coleta/compliance.db`, distribuída pela VM-1 com md5)
    → snapshot da parada (só enquanto não houver renovada);
  · o nó que tem a fonte anuncia a CAPACIDADE `fonte_coleta`; o estágio que precisa a declara em `recursos` — nó sem
    o arquivo não reserva o job (em vez de rodar e concluir «indisponível»).
CLI: `python -m compliance_agent.fluxo.fonte_coleta distribuir` (VM-1) — cópia consistente pela API de backup do
SQLite, md5, rsync aos nós, md5 remoto e troca atômica.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

CAPACIDADE = "fonte_coleta"
CAPACIDADES = frozenset({CAPACIDADE})       # recurso de PRESENÇA (não é vaga disputada): fora da regra de prioridade
VAGAS = 99
ENV = "JFN_FONTE_COLETA"
PARADA = Path.home() / "snapshot-20261124" / "compliance.db"
RENOVADA = Path.home() / "jfn-fonte-coleta" / "compliance.db"
VIVO = Path.home() / "JFN" / "data" / "compliance.db"
NOS_DESTINO = {"vm2": "vm2-ts", "itcampo": "it-campo"}


def candidatos() -> list[Path]:
    env = os.environ.get(ENV)
    return ([Path(env)] if env else []) + [RENOVADA, PARADA]


def caminho() -> Path:
    """A primeira fonte que existe; se nenhuma, a preferida (o erro do leitor nomeia o que falta)."""
    cs = candidatos()
    return next((p for p in cs if p.is_file()), cs[0])


def disponivel() -> bool:
    return caminho().is_file()


def capacidades() -> dict[str, int]:
    """O que este nó anuncia na reserva: `fonte_coleta` só se o arquivo está aqui."""
    return {CAPACIDADE: VAGAS} if disponivel() else {}


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def distribuir(origem: Path = VIVO, nos: dict[str, str] | None = None) -> dict:
    """VM-1: cópia consistente do compliance.db vivo (API de backup, sem travar o coletor) → md5 → cada nó recebe em
    .tmp, confere o md5 lá e troca atomicamente. Nó que falha fica com a cópia anterior (registrado, não calado)."""
    RENOVADA.parent.mkdir(parents=True, exist_ok=True)
    tmp = RENOVADA.with_suffix(".db.tmp")
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True, timeout=120)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst, pages=4096)
    finally:
        dst.close()
        src.close()
    md5 = _md5(tmp)
    os.replace(tmp, RENOVADA)
    out = {"md5": md5, "bytes": RENOVADA.stat().st_size, "nos": {}}
    for no, host in (NOS_DESTINO if nos is None else nos).items():
        alvo = "jfn-fonte-coleta/compliance.db"
        try:
            subprocess.run(["ssh", host, "mkdir -p ~/jfn-fonte-coleta"], check=True, timeout=60)
            subprocess.run(["nice", "-n", "15", "ionice", "-c3", "rsync", "-a", "--partial", "--inplace",
                            "--timeout=300", str(RENOVADA), f"{host}:{alvo}.tmp"], check=True, timeout=7200)
            r = subprocess.run(["ssh", host, f"md5sum ~/{alvo}.tmp | cut -c1-32"], capture_output=True, text=True,
                               check=True, timeout=1800).stdout.strip()
            if r != md5:
                out["nos"][no] = f"md5 divergente ({r[:12]} ≠ {md5[:12]}): cópia anterior mantida"
                continue
            subprocess.run(["ssh", host, f"mv -f ~/{alvo}.tmp ~/{alvo}"], check=True, timeout=60)
            out["nos"][no] = "ok"
        except (subprocess.SubprocessError, OSError) as exc:
            out["nos"][no] = f"falhou: {type(exc).__name__}: {str(exc)[:160]}"
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["distribuir"]:
        r = distribuir()
        print(f"fonte_coleta: {json.dumps(r, ensure_ascii=False)}")
        return 0 if all(v == "ok" for v in r["nos"].values()) else 1
    print(json.dumps({"caminho": str(caminho()), "disponivel": disponivel(),
                      "candidatos": [str(p) for p in candidatos()]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
