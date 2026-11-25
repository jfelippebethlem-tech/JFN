# -*- coding: utf-8 -*-
"""Remédios declarados do E18 (`remediar:` em config/slos.yaml) — o que os vigias antigos faziam sozinhos, agora como
rotina explícita, com salvaguarda e sem laço de restart (plano mestre v2 §3.2 E18, O8.1; O8.4 consome).

  · `painel_shm`     — absorve tools/guardiao_db_malformed.sh (parte reativa): sonda as 4 rotas que leem o
    compliance.db; "database disk image is malformed" com o ARQUIVO ÍNTEGRO (quick_check=ok) é o WAL-index (-shm)
    morto dentro do processo ⇒ reinicia o jfn.service UMA vez. SALVAGUARDA do script: quick_check ≠ ok (ou não medido)
    ⇒ NUNCA reinicia (o problema é de dado: perícia, tools/reconstruir_db). Resfriamento: reiniciou há menos de
    `RESFRIAMENTO_S` ⇒ não reinicia de novo, escala (nunca laço de restart).
  · `painel_travado` — absorve ~/bin/painel_vigia.sh: /painel sem resposta em 25 s DUAS checagens seguidas ⇒ reinicia
    UMA vez (mesmo resfriamento). A queda do processo segue coberta pelo Restart=always do systemd.
A sonda proativa de integridade do guardião é o SENSOR `db.integridade` (fluxo/sensores.py), não um remédio.

Cada remédio recebe o MUNDO injetável (sondas, quick_check, restart, relógio) — o teste prova a salvaguarda sem
servidor nem banco. A linha final `remedio <nome>: <acao> — <motivo>` é o efeito que a rotina confere no log.

    python -m compliance_agent.fluxo.remedios painel_shm
    python -m compliance_agent.fluxo.remedios painel_travado
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from compliance_agent.fluxo import sensores as S

RAIZ = S.RAIZ
RESFRIAMENTO_S = 1800
MARCA_REINICIO = "data/.remedio_jfn_reiniciado"           # quando o último restart por remédio aconteceu
MARCA_FALHA_PAINEL = "data/.painel_vigia_falha"           # a mesma do painel_vigia.sh (1ª falha, confirma na próxima)
MALFORMED = "disk image is malformed"


@dataclass
class Mundo:
    sondar: Callable[[str], tuple[int | None, str]]       # caminho → (http, corpo); http None = sem resposta
    quick_check: Callable[[], tuple[str | None, str]]     # (saída | None, motivo de não ter medido)
    reiniciar: Callable[[], tuple[bool, str]]             # (executou, erro)
    esperar_painel: Callable[[], bool]                    # o painel voltou a responder?
    agora: Callable[[], float] = time.time


def _resfriando(marca: Path, agora: float, resfriamento_s: int) -> float | None:
    """Segundos desde o último restart por remédio, se ainda dentro do resfriamento; senão None."""
    if not marca.exists():
        return None
    ha = agora - marca.stat().st_mtime
    return ha if ha < resfriamento_s else None


def _reiniciar_uma_vez(m: Mundo, marca: Path, resfriamento_s: int) -> tuple[str, str] | None:
    """Reinicia respeitando o resfriamento. Devolve (acao, motivo) quando NÃO reiniciou ou o restart falhou."""
    ha = _resfriando(marca, m.agora(), resfriamento_s)
    if ha is not None:
        return "escalar", (f"já reiniciou por remédio há {ha / 60:.0f} min (< {resfriamento_s / 60:.0f}): não insisto "
                           "— laço de restart não cura; escalar ao dono")
    ok, erro = m.reiniciar()
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(str(m.agora()), encoding="utf-8")
    os.utime(marca, (m.agora(), m.agora()))
    if not ok:
        return "falhou", f"systemctl NÃO executou o restart: {erro or 'sem mensagem'} — remédio impotente, não é o banco"
    return None


def painel_shm(m: Mundo, raiz: Path = RAIZ, resfriamento_s: int = RESFRIAMENTO_S) -> dict:
    doente = None
    for r in S.ROTAS_MALFORMED:
        _cod, corpo = m.sondar(f"/api/{r}")
        if MALFORMED in (corpo or ""):
            doente = r
            break
    if doente is None:
        return {"acao": "nada", "motivo": "nenhuma das 4 rotas devolveu 'malformed'"}
    saida, erro = m.quick_check()
    if saida is None:
        return {"acao": "nao_reinicia", "rota": doente,
                "motivo": f"malformed em /{doente} e a integridade NÃO foi medida ({erro}): sem prova de arquivo "
                          "íntegro não reinicio"}
    if saida != "ok":
        return {"acao": "nao_reinicia", "rota": doente,
                "motivo": f"ARQUIVO CORROMPIDO de verdade (quick_check={saida[:120]}): NÃO reinicio — perícia de dado "
                          "(python -m tools.reconstruir_db)"}
    falha = _reiniciar_uma_vez(m, raiz / MARCA_REINICIO, resfriamento_s)
    if falha:
        return {"acao": falha[0], "rota": doente, "motivo": falha[1]}
    m.esperar_painel()
    _cod, corpo = m.sondar(f"/api/{doente}")
    if MALFORMED in (corpo or ""):
        return {"acao": "escalar", "rota": doente, "motivo": "AINDA malformed após o restart — escalar (não insisto)"}
    return {"acao": "curado", "rota": doente, "motivo": f"-shm morto em /{doente} com arquivo íntegro; restart curou"}


def painel_travado(m: Mundo, raiz: Path = RAIZ, resfriamento_s: int = RESFRIAMENTO_S) -> dict:
    cod, _ = m.sondar("/painel")
    falha = raiz / MARCA_FALHA_PAINEL
    if cod in S.VIVO_HTTP:
        falha.unlink(missing_ok=True)
        return {"acao": "nada", "motivo": f"painel respondeu (http={cod})"}
    if not falha.exists():
        falha.parent.mkdir(parents=True, exist_ok=True)
        falha.write_text(str(m.agora()), encoding="utf-8")
        return {"acao": "confirmar", "motivo": f"painel sem resposta (http={cod}) — confirmo na próxima"}
    falha.unlink(missing_ok=True)
    r = _reiniciar_uma_vez(m, raiz / MARCA_REINICIO, resfriamento_s)
    if r:
        return {"acao": r[0], "motivo": r[1]}
    volta = m.esperar_painel()
    return {"acao": "curado" if volta else "escalar",
            "motivo": "painel sem resposta 2× seguidas; restart " + ("curou" if volta else "não trouxe o painel de volta")}


# ── o mundo real ──────────────────────────────────────────────────────────────────────────────────────────────────
def _env_systemd() -> dict:
    run = f"/run/user/{os.getuid()}"
    return {**os.environ, "XDG_RUNTIME_DIR": run, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={run}/bus"}


def mundo_real(raiz: Path = RAIZ) -> Mundo:
    def sondar(caminho: str) -> tuple[int | None, str]:
        cod, _ms, corpo = S._http(f"{S.PAINEL_URL}{caminho}", 25.0)
        return cod, corpo.decode("utf-8", "replace")

    def quick_check() -> tuple[str | None, str]:
        db = Path(os.environ.get("JFN_DATA_DIR") or (raiz / "data")) / "compliance.db"
        if not db.exists():
            return None, "compliance.db ausente"
        saida, _seg, erro = S.quick_check_ro(db, raiz / S.TRAVA_QUICK_CHECK)
        return saida, erro

    def reiniciar() -> tuple[bool, str]:
        r = subprocess.run(["systemctl", "--user", "restart", "jfn.service"], capture_output=True, text=True,
                           timeout=120, env=_env_systemd())
        return r.returncode == 0, (r.stderr or "").strip()[-200:]

    def esperar_painel() -> bool:
        for _ in range(30):
            if sondar("/api/compliance/painel")[0] in S.VIVO_HTTP:
                return True
            time.sleep(2)
        return False

    return Mundo(sondar=sondar, quick_check=quick_check, reiniciar=reiniciar, esperar_painel=esperar_painel)


REMEDIOS = {"painel_shm": painel_shm, "painel_travado": painel_travado}
SEM_ERRO = ("nada", "confirmar", "curado")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.fluxo.remedios")
    ap.add_argument("remedio", choices=sorted(REMEDIOS))
    a = ap.parse_args(argv)
    r = REMEDIOS[a.remedio](mundo_real())
    print(f"remedio {a.remedio}: {r['acao']} — {r['motivo']}")
    return 0 if r["acao"] in SEM_ERRO else 1


if __name__ == "__main__":
    sys.exit(main())
