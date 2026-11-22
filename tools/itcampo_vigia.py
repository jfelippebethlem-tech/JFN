"""Vigia do it-campo — mede a ociosidade e, com CPU sobrando e memória boa, dispara o próximo lote determinístico.

POR QUE (dono, 21/11/2026 23h55: "mantenha it campo sempre sendo usado ao máximo seu potencial computacional").
Medido 21/11 23h: 24 núcleos com 50–80% ociosos e a GPU em 93%; o OCR em CPU (`tools/itcampo_ocr_cpu.sh`, cron :15/:45)
trabalhava ~3 min de cada 30 (8 PDFs por processo e acabou) e cedia em metade das rodadas por memória do WSL < 6 GB.
O gargalo é MEMÓRIA, não CPU: o lote só sai quando as duas coisas deixam.

Uma passada (cron */15 na VM-1, `nice`, `timeout`, trava própria — nada de laço):
  1. mede pelo ssh: CPU do Windows inteiro (estado do pool nativo, `C:\\JFN-Nativo\\estado.json`), CPU do WSL
     (delta de /proc/stat em 10 s), memória disponível do WSL, GPU; grava uma linha em `data/itcampo_vigia.jsonl`;
  2. ocioso = CPU do Windows < CPU_OCIOSA_PCT nas DUAS últimas leituras (a de agora e a de ~15 min atrás);
  3. ocioso e memória do WSL ≥ MEM_LOTE_GB → dispara uma rodada extra do OCR em CPU com K processos que cabem na
     memória medida (cada um ~GB_POR_PROC de pico, acima do freio de 3 GB do trabalhador da GPU) e mais PDFs por
     rodada. A trava do `itcampo_ocr_cpu.sh` impede duas rodadas juntas (a do cron e a do vigia);
  4. mantém o receptor do Claude (`deploy/itcampo/claude/claude_remoto.py`) igual ao do git (md5 nas duas pontas).
Sessões do SEI NÃO são tocadas: o teto medido é do IP (5 íntegras + 1 varredura, memória acelerador-cpu-ociosa).

O sensor da automelhoria (`tools/automelhoria_geral.sensor_itcampo_vigia`) lê o mesmo histórico e abre item quando
o it-campo passa > 2 h ocioso (sem Telegram: só a fila). Pausar: `data/.pause_itcampo_vigia` (mede, não dispara).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
J = Path(os.environ.get("JFN_DIR", "/home/ubuntu/JFN"))          # dados e locks sempre da árvore de produção
HIST = J / "data" / "itcampo_vigia.jsonl"
PAUSA = J / "data" / ".pause_itcampo_vigia"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "it-campo"]
CPU_OCIOSA_PCT = 50.0      # CPU do Windows abaixo disto = mais da metade dos 24 núcleos parada
LEITURA_MAX_S = 25 * 60    # a leitura anterior só vale se for de até 25 min atrás (cron */15)
FREIO_GPU_GB = 3.0         # o trabalhador da GPU espera abaixo disto (deploy/itcampo/ocr_gpu/ocr_gpu_worker.py)
GB_POR_PROC = 1.5          # pico medido do RapidOCR por processo (18–19/11: 1,1–1,5 GB)
MEM_LOTE_GB = FREIO_GPU_GB + GB_POR_PROC
MAX_PROC, THREADS, ORCAMENTO_S, PDFS_POR_RODADA = 4, 5, 1500, 16
REC_LOCAL = REPO / "deploy" / "itcampo" / "claude" / "claude_remoto.py"
REC_REMOTO = "C:/JFN-Nativo/claude_remoto.py"

_SONDA = r"""
a=$(head -n 1 /proc/stat); sleep 10; b=$(head -n 1 /proc/stat)
echo "$a" "$b" | awk '{t1=0;for(i=2;i<=11;i++)t1+=$i; t2=0;for(i=13;i<=22;i++)t2+=$i; i1=$5+$6; i2=$16+$17;
  printf "wsl_cpu=%.0f\n", (t2>t1)?100*((t2-t1)-(i2-i1))/(t2-t1):0}'
awk '/MemAvailable/{printf "wsl_disp_gb=%.2f\n",$2/1048576}/SwapTotal/{st=$2}/SwapFree/{printf "wsl_swap_gb=%.2f\n",(st-$2)/1048576}' /proc/meminfo
echo "gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')"
echo "estado=$(tr -d '\n' < /mnt/c/JFN-Nativo/estado.json 2>/dev/null)"
"""


def medir() -> dict:
    """Uma leitura do it-campo; falha de ssh = {"ok": False} (INDISPONÍVEL, nunca "ocioso")."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        r = subprocess.run([*SSH, "wsl -d Ubuntu -- bash -s"], input=_SONDA, capture_output=True, text=True,
                           timeout=90)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"t": agora, "ok": False, "erro": type(e).__name__}
    kv = dict(ln.split("=", 1) for ln in r.stdout.splitlines() if "=" in ln)
    try:
        est = json.loads(kv.get("estado") or "{}")
    except ValueError:
        est = {}
    try:
        return {"t": agora, "ok": True, "win_cpu": est.get("cpu_pct"), "win_disp_gb": est.get("win_disp_gb"),
                "wsl_cpu": float(kv["wsl_cpu"]), "wsl_disp_gb": float(kv["wsl_disp_gb"]),
                "wsl_swap_gb": float(kv.get("wsl_swap_gb") or 0), "gpu": int(kv["gpu"]) if kv.get("gpu") else None,
                "sei_sessoes": (est.get("maquina") or {}).get("sessoes_sei_capturando")}
    except (KeyError, ValueError):
        return {"t": agora, "ok": False, "erro": "sonda sem resposta legível", "rc": r.returncode}


def ler_hist(n: int = 50) -> list[dict]:
    try:
        return [json.loads(ln) for ln in HIST.read_text(encoding="utf-8").splitlines()[-n:] if ln.strip()]
    except (OSError, ValueError):
        return []


def _ts(t: str) -> float:
    return datetime.strptime(t, "%Y-%m-%d %H:%M:%S").timestamp()


def ociosa(m: dict) -> bool:
    """CPU do Windows (a máquina inteira); sem ela, a do WSL."""
    cpu = m.get("win_cpu") if m.get("win_cpu") is not None else m.get("wsl_cpu")
    return bool(m.get("ok")) and cpu is not None and cpu < CPU_OCIOSA_PCT


def decidir(atual: dict, anterior: dict | None) -> dict:
    """Dispara só com DUAS leituras ociosas seguidas (a de agora e a de até 25 min atrás) e memória para 1+ processo."""
    if not ociosa(atual):
        return {"disparar": False, "motivo": "sem medida" if not atual.get("ok") else "CPU ocupada"}
    if not anterior or not ociosa(anterior) or _ts(atual["t"]) - _ts(anterior["t"]) > LEITURA_MAX_S:
        return {"disparar": False, "motivo": "1ª leitura ociosa (espera a 2ª)"}
    disp = atual.get("wsl_disp_gb") or 0
    if disp < MEM_LOTE_GB:
        return {"disparar": False, "motivo": f"memória do WSL {disp:.1f} GB < {MEM_LOTE_GB:.1f}"}
    k = max(1, min(MAX_PROC, int((disp - FREIO_GPU_GB) // GB_POR_PROC)))
    return {"disparar": True, "k": k, "motivo": f"ociosa 2× e {disp:.1f} GB livres → {k} processo(s) de OCR"}


def disparar(k: int) -> int:
    """Rodada extra do OCR em CPU (mesma porta do cron). Cada processo começa PDF novo só com o próprio pico livre
    acima do freio da GPU (MEM_LOTE_GB) — a memória que os outros já usam está descontada na medida."""
    env = dict(os.environ, ITCAMPO_OCR_ARGS=f"{k} {THREADS} {ORCAMENTO_S} {MEM_LOTE_GB} {PDFS_POR_RODADA}")
    with open(J / "data" / "itcampo_ocr_cpu.log", "a", encoding="utf-8") as log:
        log.write(f"[{datetime.now():%F %T}] vigia: rodada extra K={k}\n")
        log.flush()
        return subprocess.run(["nice", "-n", "10", "bash", str(J / "tools" / "itcampo_ocr_cpu.sh")], env=env,
                              cwd=J, stdout=log, stderr=subprocess.STDOUT, timeout=ORCAMENTO_S + 600).returncode


def sincronizar_receptor() -> str:
    """O receptor do Claude no Windows igual ao do git (md5 nas duas pontas)."""
    local = hashlib.md5(REC_LOCAL.read_bytes()).hexdigest()
    try:
        r = subprocess.run([*SSH, f"(Get-FileHash -Algorithm MD5 '{REC_REMOTO}').Hash"], capture_output=True,
                           text=True, timeout=60)
        if r.stdout.strip().lower() == local:
            return "igual"
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(REC_LOCAL), f"it-campo:{REC_REMOTO}"], timeout=60,
                       check=True)
        r = subprocess.run([*SSH, f"(Get-FileHash -Algorithm MD5 '{REC_REMOTO}').Hash"], capture_output=True,
                           text=True, timeout=60)
        return "atualizado" if r.stdout.strip().lower() == local else "md5 diverge"
    except (OSError, subprocess.SubprocessError) as e:
        return f"falhou ({type(e).__name__})"


def main() -> int:
    hist = ler_hist(5)
    atual = medir()
    d = decidir(atual, hist[-1] if hist else None)
    if d["disparar"] and PAUSA.exists():
        d = {"disparar": False, "motivo": "pausado (data/.pause_itcampo_vigia)"}
    atual["decisao"] = d["motivo"]
    atual["disparou"] = d["disparar"]
    atual["receptor_claude"] = sincronizar_receptor() if atual.get("ok") else None
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(atual, ensure_ascii=False) + "\n")
    print(json.dumps(atual, ensure_ascii=False), flush=True)
    if d["disparar"]:
        rc = disparar(d["k"])
        print(f"rodada extra rc={rc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
