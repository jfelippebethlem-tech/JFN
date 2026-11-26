"""siafe_agenda — dispara, pelo despachante (config/propagacao.yaml), as coletas LONGAS do SIAFE em segundo plano.

POR QUE EXISTE (19/11/2026). A releitura de status e a varredura de NE/NL levam 1–2 h de navegador; o ciclo da
propagação é um só (flock global) e esperaria a coleta inteira — todo derivado da casa ficaria parado junto. Aqui o
despachante só DISPARA: o coletor sobe numa sessão própria, herda a trava da tarefa (o despachante não o dispara
de novo enquanto ele vive) e tem teto duro (`timeout`). O efeito que o despachante confere é o arquivo de estado.

GUARDAS (sessão única do SIAFE, cron 05:00, MFA):
  • só entre 06:40 e 22:40 — a madrugada é do diário (05:00), da NE 2023 (23:20) e da NE/NL 2025 (03:10);
    o orçamento nunca passa das 23:15;
  • só se o diário de HOJE já logou (o perfil persistente tem a dispensa do MFA): sem isso o login pediria o código
    ao dono fora do fluxo do diário — a retentativa diurna (09:55/13:55/17:55) é quem avisa antes e pede;
  • SIAFE ocupado (lock do runner ou browser_lock(siafe) vivos) → não dispara; a próxima volta tenta.

Uso (o despachante chama): python -m compliance_agent.siafe_agenda status|documentos
      (o job do fluxo chama com `--esperar`: a coleta roda no grupo do job, sem destacar)
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
JANELA_LIVRE = ("06:40", "22:40")
FIM_DO_DIA = "23:15"
TAREFAS = {
    "status": {"minutos": 80,
               "argv": ["-m", "compliance_agent.siafe_status_ob", "--exercicios", "2026,2025,2024",
                        "--max-dias", "14"]},
    "documentos": {"minutos": 100,
                   "argv": ["tools/siafe_documento_sweep.py", "--exercicios", "2026,2025,2024", "--max-ugs", "12",
                            "--tipos", "NE,NL,OBR,CT", "--ate", "23:15"]},   # OBR/CT: dono 19/11/2026, todas as UGs
}


def _estado(nome: str) -> Path:
    return _REPO / "data" / f"siafe_agenda_{nome}.json"


def minutos_livres(agora: datetime, pedido: int) -> int:
    """Orçamento: o pedido, cortado em `FIM_DO_DIA`. Zero fora da janela livre."""
    hm = agora.strftime("%H:%M")
    if not (JANELA_LIVRE[0] <= hm < JANELA_LIVRE[1]):
        return 0
    h, m = (int(x) for x in FIM_DO_DIA.split(":"))
    fim = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    return max(0, min(pedido, int((fim - agora).total_seconds() // 60)))


def _diario_logou_hoje(agora: datetime) -> bool:
    from compliance_agent import siafe_runner as R
    ok = R.ultimo_ok_iso()
    if not ok:
        return False
    try:
        return datetime.fromisoformat(ok).astimezone().date() == agora.date()
    except ValueError:
        return False


def _siafe_ocupado() -> str | None:
    from compliance_agent import siafe_runner as R
    from compliance_agent.recursos import _arquivo_lock, _lock_obsoleto
    st = R.lock_status()
    if st.get("locked"):
        return f"lock do runner: {st.get('quem')}"
    arq = _arquivo_lock("siafe")
    if arq.exists() and not _lock_obsoleto(1800.0, arq):
        return "browser_lock(siafe) vivo"
    return None


def decidir(nome: str, agora: datetime, _logou=_diario_logou_hoje, _ocupado=_siafe_ocupado) -> tuple[int, str | None]:
    """(minutos, motivo_de_não_disparar). Função pura sobre o relógio e as duas sondas."""
    minutos = minutos_livres(agora, TAREFAS[nome]["minutos"])
    if minutos < 15:
        return 0, f"fora da janela livre {JANELA_LIVRE[0]}–{JANELA_LIVRE[1]} (ou menos de 15 min até {FIM_DO_DIA})"
    if not _logou(agora):
        return 0, "o diário de hoje ainda não logou no SIAFE (MFA/sessão): não peço código fora do fluxo do diário"
    oc = _ocupado()
    if oc:
        return 0, f"SIAFE ocupado ({oc})"
    return minutos, None


def disparar(nome: str, agora: datetime | None = None, _popen=subprocess.Popen, esperar: bool = False) -> dict:
    agora = agora or datetime.now()
    minutos, motivo = decidir(nome, agora)
    res: dict = {"tarefa": nome, "em": agora.isoformat(timespec="seconds")}
    if motivo:
        res["pulado"] = motivo
    else:
        argv = [sys.executable, *TAREFAS[nome]["argv"], "--minutos", str(minutos)]
        teto = minutos * 60 + 1800            # o coletor para ENTRE dias/fatias; o teto só pega o travado
        log = (_REPO / "data" / f"siafe_agenda_{nome}.log").open("ab")
        cmd = ["timeout", "-k", "120", str(teto), "nice", "-n", "10", *argv]
        if esperar:
            # O9.0 (26/11/2026, frente B): pelo motor (`--esperar`) a coleta roda NO grupo do job — o teto do job, o
            # governador e a parada a alcançam, e o slot `siafe_sessao` fica preso até ela acabar. Destacada, o job
            # saía em segundos ("feito") e 80–130 min de navegador SIAFE seguiam fora da reserva e do teto.
            p = _popen(cmd, cwd=_REPO, stdout=log, stderr=subprocess.STDOUT)
            res.update({"disparado": True, "pid": p.pid, "minutos": minutos, "esperou": True, "rc": p.wait()})
        else:
            # close_fds=False: o filho herda a trava da tarefa que o despachante passou (pass_fds) e a segura até o fim
            p = _popen(cmd, cwd=_REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=False)
            res.update({"disparado": True, "pid": p.pid, "minutos": minutos,
                        "ate": (agora + timedelta(minutes=minutos)).isoformat(timespec="minutes")})
    _estado(nome).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main() -> None:
    args = sys.argv[1:]
    nome = args[0] if args else ""
    if nome not in TAREFAS or any(a != "--esperar" for a in args[1:]):
        raise SystemExit(f"uso: python -m compliance_agent.siafe_agenda {'|'.join(TAREFAS)} [--esperar]")
    from compliance_agent import host_siafe
    host_siafe.exigir_autorizacao()
    res = disparar(nome, esperar="--esperar" in args[1:])
    print(json.dumps(res, ensure_ascii=False))
    if res.get("rc"):
        raise SystemExit(res["rc"])            # coleta que falhou no job do fluxo = job que falhou


if __name__ == "__main__":
    main()
