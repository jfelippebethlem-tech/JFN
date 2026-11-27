# -*- coding: utf-8 -*-
"""Governador de capacidade (plano mestre v2 §3.4): quantos jobs de cada recurso este nó pode reservar AGORA.

Mede pressão, não carga: `/proc/pressure/{cpu,memory,io}` (PSI, conferido nas 3 máquinas), disco livre e swap. O
load average não entra — 2 vCPU com load 6 em espera de rede não é máquina cheia, e a VM-1 já caiu com load baixo e
swap em 100%. As decisões são funções PURAS (recebem o texto do /proc): o teste fixa o cenário sem depender da máquina.

| condição (avg10)                                   | estado    | efeito                                     |
|----------------------------------------------------|-----------|--------------------------------------------|
| cpu some < 40 e mem full < 1                       | folga     | reserva tudo o que o slot permitir         |
| entre os dois                                      | neutro    | leve sim, pesado novo não                  |
| cpu some > 60 ou mem some > 10                     | contido   | só o que não gasta CPU (llm, materializar) |
| contido por N leituras seguidas                    | (ação)    | suspender o maior job (SIGSTOP)            |
| mem full > 5                                       | (ação)    | matar o maior job (SIGKILL) se ≥ 512 MB    |
| disco livre < 10 %                                 | (recurso) | nada de pesado nem disco                   |
"""
from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass, field
from typing import Mapping

# Slots iniciais da §3.4 (o O1.6/O1.10 ajusta). Recurso ausente vale 0 no nó. `disco` (E7/E17) não estava na
# tabela: 1 por nó para o arquivamento e a manutenção não ficarem sem lugar.
SLOTS_INICIAIS: dict[str, dict[str, int]] = {
    "vm1": {"cpu_leve": 2, "cpu_pesado": 1, "llm": 2, "materializar": 1, "disco": 1},
    "vm2": {"cpu_leve": 2, "cpu_pesado": 1, "navegador": 1, "llm": 3, "disco": 1},
    # disco 1→4 (27/11): E7 arquivar levava ~40 s/job, limitado pela VAGA (entravam ~590/h, saíam ~175/h, fila
    # 7.906→9.031); o trabalho é rede (Drive) e o índice é SQLite WAL com timeout 60 s. A VM-2 fica com 1 (PG).
    "itcampo": {"cpu_leve": 10, "cpu_pesado": 8, "navegador": 6, "gpu": 1, "llm": 4, "disco": 4},
}
PESADOS = frozenset({"cpu_pesado", "navegador", "gpu", "disco"})
SEM_CPU = frozenset({"llm", "materializar"})        # espera de rede / painel: seguem mesmo contido

CPU_FOLGA, MEM_FULL_FOLGA = 40.0, 1.0
CPU_CONTIDO, MEM_SOME_CONTIDO = 60.0, 10.0
MEM_FULL_MATAR = 5.0
# 26/11/2026: matar job só alivia quando a memória está acabando. Com mais que isto disponível, a pressão vem de outra
# coisa (brain-index fora do motor, reclaim de cache): o governador para de reservar pesado, não mata.
MEM_DISP_MATAR_PCT = 20.0
DISCO_MIN_PCT = 10.0
LEITURAS_PARA_SUSPENDER = 3
# SIGKILL só vale num job que pesa (RSS do grupo de processos): com a pressão vinda de fora dos jobs, matar filho de
# 15 MB não alivia nada e virava uma fila de mortes (25/11/2026: 12 em 3 min).
MATAR_MIN_KB = 512 * 1024


def vale_matar(rss_kb: int) -> bool:
    return rss_kb >= MATAR_MIN_KB


@dataclass
class Medida:
    cpu_some: float = 0.0
    mem_some: float = 0.0
    mem_full: float = 0.0
    io_some: float = 0.0
    io_full: float = 0.0
    swap_pct: float = 0.0
    disco_livre_pct: float = 100.0
    mem_disp_pct: float = 0.0          # MemAvailable/MemTotal; 0 = desconhecido (vale a regra antiga: pode matar)
    cpu_some_sistema: float = 0.0      # o PSI de CPU da máquina inteira (registro); a decisão usa o dos jobs

    def como_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decisao:
    estado: str                                    # folga | neutro | contido
    livres: dict[str, int]
    acao: str | None = None                        # None | 'suspender' | 'matar'
    motivos: list[str] = field(default_factory=list)


def ler_psi(texto: str) -> dict[str, float]:
    """'some avg10=1.68 avg60=…\\nfull avg10=0.00 …' → {'some': 1.68, 'full': 0.0} (só o avg10, que é o que decide).
    O /proc/pressure/cpu de kernel antigo não tem a linha `full`: vale 0."""
    out = {"some": 0.0, "full": 0.0}
    for ln in texto.splitlines():
        partes = ln.split()
        if not partes or partes[0] not in out:
            continue
        for p in partes[1:]:
            if p.startswith("avg10="):
                out[partes[0]] = float(p.split("=", 1)[1])
    return out


def ler_swap_pct(meminfo: str) -> float:
    v = {}
    for ln in meminfo.splitlines():
        nome, _, resto = ln.partition(":")
        if nome in ("SwapTotal", "SwapFree"):
            v[nome] = float(resto.split()[0])
    total = v.get("SwapTotal", 0.0)
    return 0.0 if total <= 0 else round(100.0 * (total - v.get("SwapFree", total)) / total, 1)


def montar_medida(psi_cpu: str, psi_mem: str, psi_io: str, meminfo: str, disco_livre_pct: float) -> Medida:
    c, m, i = ler_psi(psi_cpu), ler_psi(psi_mem), ler_psi(psi_io)
    return Medida(cpu_some=c["some"], mem_some=m["some"], mem_full=m["full"], io_some=i["some"], io_full=i["full"],
                  swap_pct=ler_swap_pct(meminfo), disco_livre_pct=disco_livre_pct, mem_disp_pct=ler_disp_pct(meminfo))


def ler_disp_pct(meminfo: str) -> float:
    v = {}
    for ln in meminfo.splitlines():
        k, _, resto = ln.partition(":")
        if resto.strip():
            v[k.strip()] = float(resto.split()[0])
    tot = v.get("MemTotal", 0.0)
    return round(100.0 * v.get("MemAvailable", 0.0) / tot, 1) if tot else 0.0


def fatia_dos_jobs() -> str:
    """A fatia systemd (do usuário) onde o supervisor põe os jobs: jfn.slice ⊃ jfn-coletor.slice/jfn-jobs.slice."""
    uid = os.getuid()
    return f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/jfn.slice"


def medir(proc: str = "/proc", disco: str = "/", cgroup: str | None = None) -> Medida:
    """A única função que toca a máquina. PSI ausente (kernel sem CONFIG_PSI) cai em 0 — e o supervisor registra
    no nó que a medida não existe, em vez de fingir folga calado.

    CPU: a pressão sobre os JOBS DO MOTOR (PSI da fatia jfn.slice), não a da máquina — 26/11/2026: a VM-2 ficou
    contida com 0 job rodando (sistema 79,5 % por um processo de fora freado pela cota; fatia 0,5 %). Painel e PG se
    protegem por peso de cgroup (§3.4). Sem a fatia legível, vale o PSI do sistema (regra antiga)."""
    def ler(caminho: str) -> str:
        try:
            with open(caminho, encoding="ascii") as f:
                return f.read()
        except OSError:
            return ""
    u = shutil.disk_usage(disco)
    cpu_sis = ler(os.path.join(proc, "pressure", "cpu"))
    cg = cgroup or (fatia_dos_jobs() if proc == "/proc" else None)      # /proc de teste: não lê a fatia real
    cpu_jobs = ler(os.path.join(cg, "cpu.pressure")) if cg else ""
    m = montar_medida(cpu_jobs or cpu_sis, ler(os.path.join(proc, "pressure", "memory")),
                      ler(os.path.join(proc, "pressure", "io")), ler(os.path.join(proc, "meminfo")),
                      round(100.0 * u.free / u.total, 1))
    m.cpu_some_sistema = ler_psi(cpu_sis)["some"]
    return m


def classificar(m: Medida) -> tuple[str, list[str]]:
    motivos = []
    if m.cpu_some > CPU_CONTIDO:
        motivos.append(f"cpu some {m.cpu_some:.1f} > {CPU_CONTIDO:.0f}")
    if m.mem_some > MEM_SOME_CONTIDO:
        motivos.append(f"mem some {m.mem_some:.1f} > {MEM_SOME_CONTIDO:.0f}")
    # swap OCUPADO não contém (25/11/2026, religação O9.0): páginas velhas no swap com RAM livre e PSI 0 seguraram a
    # fila >1 h. A pressão real de memória é o PSI (mem some acima); swap_pct segue medido e exibido no nó.
    if motivos:
        return "contido", motivos
    if m.cpu_some < CPU_FOLGA and m.mem_full < MEM_FULL_FOLGA:
        return "folga", []
    return "neutro", [f"cpu some {m.cpu_some:.1f} / mem full {m.mem_full:.1f} acima da folga"]


def decidir(m: Medida, base: Mapping[str, int], ocupados: Mapping[str, int] | None = None,
            contido_seguidas: int = 0) -> Decisao:
    """Slots livres por recurso = base − ocupados, cortados conforme o estado. `contido_seguidas` = quantas leituras
    anteriores já foram 'contido' (o supervisor conta): pressão sustentada pede suspender o maior job."""
    ocupados = ocupados or {}
    estado, motivos = classificar(m)
    livres = {r: max(0, int(n) - int(ocupados.get(r, 0))) for r, n in base.items()}
    if estado != "folga":
        for r in PESADOS & livres.keys():
            livres[r] = 0
    if estado == "contido":
        for r in livres:
            if r not in SEM_CPU:
                livres[r] = 0
    if m.disco_livre_pct < DISCO_MIN_PCT:
        motivos.append(f"disco livre {m.disco_livre_pct:.0f}% < {DISCO_MIN_PCT:.0f}%")
        for r in PESADOS & livres.keys():
            livres[r] = 0
    acao = None
    if m.mem_full > MEM_FULL_MATAR and m.mem_disp_pct and m.mem_disp_pct >= MEM_DISP_MATAR_PCT:
        motivos.append(f"mem full {m.mem_full:.1f} > {MEM_FULL_MATAR:.0f} com {m.mem_disp_pct:.0f}% disponível: "
                       "pressão de fora dos jobs — não mata, só segura pesado")
        for r in PESADOS & livres.keys():
            livres[r] = 0
    elif m.mem_full > MEM_FULL_MATAR:
        acao = "matar"
        motivos.append(f"mem full {m.mem_full:.1f} > {MEM_FULL_MATAR:.0f}")
    elif estado == "contido" and contido_seguidas + 1 >= LEITURAS_PARA_SUSPENDER:
        acao = "suspender"
    return Decisao(estado=estado, livres=livres, acao=acao, motivos=motivos)
