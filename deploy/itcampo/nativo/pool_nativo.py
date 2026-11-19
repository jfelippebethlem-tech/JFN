"""Pool de trabalho NATIVO do Windows no it-campo — CPU que o WSL não usa, sem tirar memória do Surya nem do dono.

POR QUE (dono, 19/11/2026: "de um jeito de usar além do WSL pra aproveitar tudo da máquina sem quebrar ela").
Medido às 09:35: GPU 0% em 5 amostras, WSL com 18/19 GB usados, CPU com carga 2,8 em 24 núcleos e o OCR em CPU da
reserva (RapidOCR, `tools/sei_ocr_reserva.py`) cedendo em TODA rodada no WSL ("memória livre 3,2 GB < 6,0"). A
memória do WSL é disputada pelo vLLM do Surya, pelo trabalhador da GPU e pelos navegadores do SEI; a CPU sobra.
Aqui o OCR roda no Python do WINDOWS: memória que volta ao sistema assim que o processo termina, prioridade IDLE
(o dono sempre passa na frente) e fora do OOM do WSL. O transporte (ssh/rsync com as chaves vm1-ts/vm2-ts) segue
pelo WSL — só rede (`sei_ocr_reserva._unix`).

DESENHO:
  · trabalhador = uma rodada `sei_ocr_reserva.py rodar --paralelo` com nó próprio `itcampo-win-K` (reserva na VM-1
    sob trava, sempre do FIM da fila da GPU, nunca duplica o Surya; o que sobra de uma rodada morta volta como
    `sobra` na próxima rodada do mesmo nó → retomável).
  · quantos: min(MAX_TRAB, CPU livre ÷ THREADS, memória disponível do Windows acima do PISO ÷ GB_POR_TRAB); sobe um
    por ciclo (gradual), nunca abaixo do PISO de memória disponível do Windows (o uso humano).
  · freio duro: disponível < PISO − 1 GB → encerra o trabalhador mais novo (a reserva dele volta na próxima rodada).
  · pausa: arquivo PAUSA, ou usuário ATIVO (entrada há < OCIOSO_S) com a CPU dos OUTROS acima de CPU_PAUSA →
    suspende os trabalhadores (CPU devolvida na hora) e retoma quando passar.
  · fila vazia/cedeu: a vaga espera ESPERA_VAZIA_S antes de perguntar de novo à VM-1 (não martela a VM-1).
  · código: `sei_ocr_reserva.py` vem da VM-1 com md5 conferido nas duas pontas antes de cada lançamento.
  · estado: `estado.json` (lido pela VM-1 → painel Sistema) e `pool.log` (JSON por linha).
Pausar: criar C:\\JFN-Nativo\\PAUSA. Desligar: schtasks /change /tn JFN-Nativo /disable (e apagar a PAUSA depois).
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

BASE = Path(os.environ.get("JFN_NATIVO_DIR", r"C:\JFN-Nativo"))
PY = BASE / "venv" / "Scripts" / "python.exe"
CODIGO = BASE / "tools" / "sei_ocr_reserva.py"
PAUSA = BASE / "PAUSA"
ESTADO = BASE / "estado.json"
LOG = BASE / "pool.log"
PISO_GB = float(os.environ.get("JFN_NATIVO_PISO_GB", "6"))          # disponível do Windows reservado ao dono
GB_POR_TRAB = float(os.environ.get("JFN_NATIVO_GB_POR_TRAB", "1.5"))  # pico medido do RapidOCR num PDF de 19 pág: 1,1 GB
# Medido 19/11 no Windows (PDF de 12 págs, texto IDÊNTICO ao do WSL por md5): 2 threads 13,8 s/pág · 4 → 8,0 · 8 → 5,2.
# A memória (≈1,5 GB por trabalhador) limita antes da CPU: menos trabalhadores com mais threads rendem mais por GB.
THREADS = int(os.environ.get("JFN_NATIVO_THREADS", "6"))
MAX_TRAB = int(os.environ.get("JFN_NATIVO_MAX", "3"))                # 3 × 6 = 18 de 24 núcleos (o WSL fica com o resto)
CPU_PAUSA = float(os.environ.get("JFN_NATIVO_CPU_PAUSA", "60"))      # % da CPU usada pelos OUTROS com o dono ativo
OCIOSO_S = 120
CICLO_S = 30
ESPERA_VAZIA_S = 900
ORCAMENTO_S, N_POR_RODADA = 1500, 8
WSL = ["wsl.exe", "-d", "Ubuntu", "-e"]
IDLE = 0x00000040            # IDLE_PRIORITY_CLASS
SEM_JANELA = 0x08000000      # CREATE_NO_WINDOW: a janela do pool mostra tudo; cada rodada não abre um console


def log(**kw) -> None:
    linha = json.dumps({"t": time.strftime("%F %T"), **kw}, ensure_ascii=False)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    print(linha, flush=True)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def ocioso_s() -> float:
    """Segundos desde a última tecla/mouse do dono (sessão interativa — por isso a tarefa roda com /it)."""
    li = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000


def alvo(disp_gb: float, cpu_outros: float, ncpu: int, vivos: int) -> int:
    """Quantos trabalhadores cabem: CPU livre dos outros ÷ THREADS e memória acima do PISO ÷ GB_POR_TRAB."""
    cabe_cpu = int((100 - cpu_outros) / 100 * ncpu // THREADS)
    cabe_mem = vivos + int((disp_gb - PISO_GB) // GB_POR_TRAB)
    return max(0, min(MAX_TRAB, cabe_cpu, cabe_mem))


def deve_pausar(pausa_arquivo: bool, ocioso: float, cpu_outros: float) -> str:
    if pausa_arquivo:
        return "arquivo PAUSA"
    if ocioso < OCIOSO_S and cpu_outros > CPU_PAUSA:
        return f"dono ativo e CPU dos outros {cpu_outros:.0f}% > {CPU_PAUSA:.0f}%"
    return ""


def atualizar_codigo() -> bool:
    """Puxa `tools/sei_ocr_reserva.py` da VM-1 e só o adota com md5 igual nas duas pontas."""
    import hashlib
    novo = CODIGO.with_suffix(".py.novo")
    CODIGO.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(WSL + ["rsync", "-a", "vm1-ts:JFN/tools/sei_ocr_reserva.py",
                              "/mnt/c/" + str(novo)[3:].replace("\\", "/")],
                       capture_output=True, text=True, encoding="utf-8", timeout=180)
    rr = subprocess.run(WSL + ["ssh", "-o", "BatchMode=yes", "vm1-ts", "md5sum < JFN/tools/sei_ocr_reserva.py"],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0 or rr.returncode != 0 or not novo.exists():
        log(ev="codigo_nao_atualizado", rc=r.returncode, erro=(r.stderr or rr.stderr)[-200:])
        return CODIGO.exists()
    local, remoto = hashlib.md5(novo.read_bytes()).hexdigest(), rr.stdout.split()[0]
    if local != remoto:
        log(ev="codigo_md5_diverge", local=local, remoto=remoto)
        novo.unlink(missing_ok=True)
        return CODIGO.exists()
    novo.replace(CODIGO)
    return True


def lancar(k: int) -> subprocess.Popen:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "JFN_FRIO_REMOTO": "vm2-ts:arquivo_frio/sei_cache/", "JFN_VM1_SSH": "vm1-ts",
           "JFN_OCR_RESERVA_DIR": str(BASE / "reserva"), "JFN_OCR_MEM_MIN_GB": str(PISO_GB),
           "JFN_OCR_LOAD_POR_NUCLEO": "0.85", "JFN_OCR_THREADS": str(THREADS), "OMP_NUM_THREADS": str(THREADS)}
    saida = (BASE / f"trab_{k}.log").open("a", encoding="utf-8")
    return subprocess.Popen([str(PY), str(CODIGO), "rodar", "--paralelo", "--orcamento", str(ORCAMENTO_S),
                             "--n", str(N_POR_RODADA), "--no", f"itcampo-win-{k}"],
                            cwd=str(BASE), env=env, stdout=saida, stderr=subprocess.STDOUT,
                            creationflags=IDLE | SEM_JANELA)


def ultimo_evento(k: int) -> dict:
    """Última linha JSON da rodada da vaga k (para saber se a fila veio vazia ou se cedeu)."""
    try:
        linhas = (BASE / f"trab_{k}.log").read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
    except OSError:
        return {}
    for ln in reversed(linhas):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("ev") in ("fim", "reservado", "cede", "pausado", "reservar_falhou",
                                                    "baixar_falhou"):
            return d
    return {}


def _arvore(pid: int) -> list[psutil.Process]:
    try:
        p = psutil.Process(pid)
        return [p, *p.children(recursive=True)]
    except psutil.Error:
        return []


def main() -> int:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    BASE.mkdir(parents=True, exist_ok=True)
    ncpu = psutil.cpu_count() or 1
    trab: dict[int, dict] = {}            # vaga → {proc, desde, suspenso}
    espera_ate: dict[int, float] = {}     # vaga → não relançar antes de
    totais = {"rodadas": 0, "pdfs": 0, "paginas": 0}
    ultimo_lanc, ultimo_codigo, motivo_ant = 0.0, 0.0, None
    psutil.cpu_percent(None)
    log(ev="inicio", ncpu=ncpu, piso_gb=PISO_GB, max=MAX_TRAB, threads=THREADS)
    while True:
        time.sleep(CICLO_S)
        # rodadas que terminaram
        for k, t in list(trab.items()):
            if t["proc"].poll() is not None:
                ev = ultimo_evento(k)
                totais["rodadas"] += 1
                if ev.get("ev") == "fim":
                    totais["pdfs"] += ev.get("entregues", 0)
                    totais["paginas"] += ev.get("paginas", 0)
                vazia = ev.get("ev") in ("cede", "pausado", "reservar_falhou", "baixar_falhou") or \
                    (ev.get("ev") == "reservado" and not ev.get("itens")) or \
                    (ev.get("ev") == "fim" and not ev.get("feitos"))
                if vazia:
                    espera_ate[k] = time.time() + ESPERA_VAZIA_S
                log(ev="rodada_fim", vaga=k, rc=t["proc"].returncode, s=round(time.time() - t["desde"]),
                    ultimo=ev, espera_s=ESPERA_VAZIA_S if vazia else 0)
                del trab[k]
        mem = psutil.virtual_memory()
        disp = mem.available / 1e9
        cpu = psutil.cpu_percent(None)
        meus = 0.0
        for t in trab.values():
            for p in _arvore(t["proc"].pid):
                try:
                    meus += p.cpu_percent(None)
                except psutil.Error:
                    pass
        cpu_outros = max(0.0, cpu - meus / ncpu)
        ocioso = ocioso_s()
        # freio duro de memória: o dono nunca fica sem memória
        if disp < PISO_GB - 1.0 and trab:
            k = max(trab, key=lambda v: trab[v]["desde"])
            for p in reversed(_arvore(trab[k]["proc"].pid)):
                try:
                    p.kill()
                except psutil.Error:
                    pass
            log(ev="freio_memoria", vaga=k, disp_gb=round(disp, 1))
            espera_ate[k] = time.time() + ESPERA_VAZIA_S
        motivo = deve_pausar(PAUSA.exists(), ocioso, cpu_outros)
        for t in trab.values():
            if bool(motivo) != t["suspenso"]:
                for p in _arvore(t["proc"].pid):
                    try:
                        p.suspend() if motivo else p.resume()
                    except psutil.Error:
                        pass
                t["suspenso"] = bool(motivo)
        if motivo != motivo_ant:
            log(ev="pausa" if motivo else "retoma", motivo=motivo, ocioso_s=round(ocioso), cpu_outros=round(cpu_outros))
            motivo_ant = motivo
        quer = 0 if motivo else alvo(disp, cpu_outros, ncpu, len(trab))
        if len(trab) < quer and time.time() - ultimo_lanc > 60:
            livres = [k for k in range(1, MAX_TRAB + 1) if k not in trab and espera_ate.get(k, 0) < time.time()]
            if livres:
                if time.time() - ultimo_codigo > 1800 or not CODIGO.exists():
                    ok = atualizar_codigo()
                    ultimo_codigo = time.time()
                    if not ok:
                        continue
                k = livres[0]
                trab[k] = {"proc": lancar(k), "desde": time.time(), "suspenso": False}
                ultimo_lanc = time.time()
                log(ev="lancado", vaga=k, pid=trab[k]["proc"].pid, alvo=quer, disp_gb=round(disp, 1),
                    cpu_outros=round(cpu_outros))
        rss = {}
        for k, t in trab.items():
            rss[k] = 0
            for p in _arvore(t["proc"].pid):
                try:
                    rss[k] += p.memory_info().rss
                except psutil.Error:
                    pass
        tmp = ESTADO.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "t": time.strftime("%F %T"), "win_disp_gb": round(disp, 2), "win_total_gb": round(mem.total / 1e9, 1),
            "cpu_pct": round(cpu), "cpu_outros_pct": round(cpu_outros), "dono_ocioso_s": round(ocioso),
            "pausa": motivo, "alvo": quer, "piso_gb": PISO_GB,
            "trabalhadores": [{"vaga": k, "pid": t["proc"].pid, "rss_mb": round(rss[k] / 1e6),
                               "suspenso": t["suspenso"], "desde_s": round(time.time() - t["desde"])}
                              for k, t in sorted(trab.items())],
            "totais_desde_inicio": totais}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ESTADO)


if __name__ == "__main__":
    sys.exit(main())
