# -*- coding: utf-8 -*-
"""cron → fluxo: as linhas do JFN que AINDA rodam no crontab da VM-1 (e os timers da VM-2) depois da parada de obras
viram rotinas do config/fluxo.yaml; este script as tira do cron NA O9.0 — e sabe desfazer (pedido do dono, 24/11/2026).

NÃO MEXE EM NADA SEM `--aplicar`. Durante a parada o cron segue ligado de propósito: o motor de fluxo não roda, e sem
o cron o banco ficaria sem guarda (backup, WAL, guardião, painel). Na O9.0, junto do `tools/religar_o90.py`:

    python -m tools.cron_para_fluxo                         # tabela cron → rotina (só lê o crontab)
    python -m tools.cron_para_fluxo --aplicar               # comenta as linhas migradas com `#FLUXO-AAAAMMDD `
    python -m tools.cron_para_fluxo --desfazer [--marca #FLUXO-20261124]   # descomenta (volta ao cron)
    python -m tools.cron_para_fluxo --timers [--aplicar|--desfazer]        # na VM-2: timers do usuário

Regras: só comenta linha VIVA cuja rotina existe no config/fluxo.yaml (rotina ausente ⇒ recusa tudo, nada muda);
`fora_do_jfn` (polimonitor, backup git do vault) e `fica_no_cron` nunca são tocadas; antes de escrever, guarda o
crontab inteiro em ~/.config/jfn/backups/; depois de escrever, relê e confere a contagem (efeito, não palavra).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MARCA_PREFIXO = "#FLUXO-"
MARCA_PARADA = "#PARADA-20261124 "

# (trecho que identifica a linha do cron, rotina do config/fluxo.yaml) — a ordem importa: o primeiro que casa vale
CRON_VM1: list[tuple[str, str]] = [
    ("tools/backup_compliance.sh", "backup_compliance"),
    ("tools/backup_evidencias_pg.sh", "backup_evidencias_pg"),
    ("graphify-out && ls -d 20", "graphify_retencao"),
    ("GRAPH_REPORT.md", "graph_report_brain"),
    ("compliance_agent.llm.ritmo_assinatura --medir", "ritmo_assinatura"),
    ("checkpoint_wal", "checkpoint_wal"),
    ("zelador.py --perfil vm1 --aplicar", "zelador_vm1_aplicar"),
    ("zelador.py --vigiar", "zelador_vm1"),
    ("jfn-vm1.conf", "logrotate_vm1"),
    ("nuvens-manter-vivas.sh", "nuvens_manter_vivas"),
    ("mediafire_sessao.py", "mediafire_sessao"),
    ("tools/guardiao_db_malformed.sh", "remediar_painel_shm"),
    ("bin/painel_vigia.sh", "remediar_painel_travado"),
]
FORA_DO_JFN = [("/polimonitor/", "polimonitor (fora do JFN)"), ("/vault && git add", "backup git do vault (fora do JFN)")]
FICA_NO_CRON = [("@reboot", "boot da máquina: só limpa o lock do navegador (sem sentido no fluxo)")]

TIMERS_VM2: dict[str, str] = {"jfn-sentinela-integridade.timer": "sentinela_integridade",
                              "jfn-logrotate.timer": "logrotate_vm2",
                              "zelador-armazenamento.timer": "zelador_vm2_aplicar"}
TIMERS_FORA = {"brain-index.timer": "indexador do brain (fora do JFN)", "hermes-update.timer": "Hermes (fora do JFN)",
               "launchpadlib-cache-clean.timer": "sistema operacional"}


@dataclass
class Linha:
    n: int
    texto: str
    classe: str                 # migrar | fora_do_jfn | fica_no_cron | desconhecida | parada | migrada
    rotina: str | None = None
    motivo: str = ""


def _e_job(s: str) -> bool:
    st = s.strip()
    return bool(st) and not st.startswith("#") and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", st)


def classificar(texto: str) -> list[Linha]:
    """Cada linha de job do crontab → classe. Puro."""
    out = []
    for n, ln in enumerate(texto.splitlines(), 1):
        st = ln.strip()
        if st.startswith(MARCA_PARADA):
            out.append(Linha(n, ln, "parada", motivo="comentada pela parada (religar_o90 cuida)"))
            continue
        if st.startswith(MARCA_PREFIXO):
            corpo = st.split(" ", 1)[1] if " " in st else ""
            rot = next((r for t, r in CRON_VM1 if t in corpo), None)
            out.append(Linha(n, ln, "migrada", rot, motivo=st.split(" ", 1)[0]))
            continue
        if not _e_job(ln):
            continue
        rot = next((r for t, r in CRON_VM1 if t in ln), None)
        if rot:
            out.append(Linha(n, ln, "migrar", rot))
            continue
        fora = next((m for t, m in FORA_DO_JFN if t in ln), None)
        if fora:
            out.append(Linha(n, ln, "fora_do_jfn", motivo=fora))
            continue
        fica = next((m for t, m in FICA_NO_CRON if st.startswith(t)), None)
        out.append(Linha(n, ln, "fica_no_cron" if fica else "desconhecida", motivo=fica or "sem destino declarado"))
    return out


def marca_de(hoje: str | None = None) -> str:
    return f"{MARCA_PREFIXO}{hoje or time.strftime('%Y%m%d')} "


def comentar(texto: str, rotinas: dict[str, bool], marca: str) -> tuple[str, list[Linha]]:
    """Comenta as linhas `migrar` com a marca. `rotinas` = {id: ativa} do yaml. Rotina AUSENTE ⇒ ValueError (nada
    muda); rotina INATIVA (bloqueio declarado, ex.: mediafire_sessao) ⇒ a linha FICA no cron — senão o trabalho
    sumiria dos dois lados. Puro."""
    ls = classificar(texto)
    alvo = [x for x in ls if x.classe == "migrar"]
    falta = sorted({x.rotina for x in alvo} - set(rotinas))
    if falta:
        raise ValueError(f"rotina(s) ausente(s) no config/fluxo.yaml: {falta} — nada foi comentado")
    alvo = [x for x in alvo if rotinas[x.rotina]]
    linhas = texto.splitlines(keepends=True)
    for x in alvo:
        linhas[x.n - 1] = marca + linhas[x.n - 1]
    return "".join(linhas), alvo


def descomentar(texto: str, marca: str | None = None) -> tuple[str, int]:
    """Tira a marca `#FLUXO-…` (todas, ou só a `marca` dada) do começo das linhas. Puro."""
    rx = re.compile(rf"^{re.escape(marca.strip())} " if marca else rf"^{re.escape(MARCA_PREFIXO)}\d{{8}} ")
    n, out = 0, []
    for ln in texto.splitlines(keepends=True):
        novo = rx.sub("", ln, count=1)
        n += novo != ln
        out.append(novo)
    return "".join(out), n


# ── o mundo (crontab, yaml, systemctl) ─────────────────────────────────────────────────────────────────────────────
def ler_crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"crontab -l falhou: {r.stderr.strip()[:200]}")
    return r.stdout


def gravar_crontab(texto: str) -> None:
    r = subprocess.run(["crontab", "-"], input=texto, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"crontab - falhou: {r.stderr.strip()[:200]}")


def guardar_copia(texto: str) -> Path:
    d = Path.home() / ".config" / "jfn" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"crontab-antes-cron_para_fluxo-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    p.write_text(texto, encoding="utf-8")
    return p


def rotinas_do_yaml() -> dict[str, bool]:
    sys.path.insert(0, str(RAIZ))
    from compliance_agent.fluxo import grafo as G
    return {k: r.ativa for k, r in G.carregar().rotinas.items()}


def tabela(ls: list[Linha]) -> str:
    out = [f"{'linha':>5}  {'classe':<13} {'rotina':<24} comando / motivo"]
    for x in ls:
        cmd = re.sub(r"/home/[^/ ]+", "~", x.texto.strip())[:110]
        out.append(f"{x.n:>5}  {x.classe:<13} {x.rotina or '-':<24} {cmd}" + (f"  [{x.motivo}]" if x.motivo else ""))
    return "\n".join(out)


def timers(acao: str | None) -> int:
    rotinas = rotinas_do_yaml()
    falta = sorted(r for r in TIMERS_VM2.values() if not rotinas.get(r))
    print("\n".join(f"{u:<36} → {r}" for u, r in TIMERS_VM2.items()))
    print("\n".join(f"{u:<36} · fica: {m}" for u, m in TIMERS_FORA.items()))
    if acao is None:
        return 0
    if falta:
        print(f"recuso: rotina(s) ausente(s) no yaml: {falta}", file=sys.stderr)
        return 1
    verbo = ["disable", "--now"] if acao == "aplicar" else ["enable", "--now"]
    rc = 0
    for u in TIMERS_VM2:
        r = subprocess.run(["systemctl", "--user", *verbo, u], capture_output=True, text=True, timeout=60)
        ativo = subprocess.run(["systemctl", "--user", "is-enabled", u], capture_output=True, text=True,
                               timeout=30).stdout.strip()
        esperado = "disabled" if acao == "aplicar" else "enabled"
        ok = r.returncode == 0 and ativo == esperado
        rc |= 0 if ok else 1
        print(f"cron_para_fluxo timer {u}: {ativo} ({'conferido' if ok else 'NÃO conferido'})")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.cron_para_fluxo")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--aplicar", action="store_true")
    g.add_argument("--desfazer", action="store_true")
    ap.add_argument("--marca", default=None, help="só esta marca no --desfazer (ex.: #FLUXO-20261124)")
    ap.add_argument("--timers", action="store_true", help="timers do usuário (VM-2) em vez do crontab")
    a = ap.parse_args(argv)
    if a.timers:
        return timers("aplicar" if a.aplicar else "desfazer" if a.desfazer else None)
    texto = ler_crontab()
    if not (a.aplicar or a.desfazer):
        ativas = rotinas_do_yaml()
        ls = classificar(texto)
        for x in ls:
            if x.classe == "migrar" and not ativas.get(x.rotina, False):
                x.classe, x.motivo = "fica_no_cron", "rotina inativa ou ausente no yaml: a linha fica até ela ligar"
        print(tabela(ls))
        return 0
    copia = guardar_copia(texto)
    if a.aplicar:
        marca = marca_de()
        try:
            novo, alvo = comentar(texto, rotinas_do_yaml(), marca)
        except ValueError as e:
            print(f"cron_para_fluxo: {e}", file=sys.stderr)
            return 1
        esperado = len(alvo)
    else:
        novo, esperado = descomentar(texto, a.marca)
    gravar_crontab(novo)
    relido = classificar(ler_crontab())
    migradas = sum(x.classe == "migrada" for x in relido)
    vivas_migrar = sum(x.classe == "migrar" for x in relido)
    restam = sum(x.classe == "migrada" and (a.marca is None or x.motivo == a.marca.strip()) for x in relido)
    ok = (migradas >= esperado) if a.aplicar else restam == 0
    print(f"cron_para_fluxo: {'aplicado' if a.aplicar else 'desfeito'} — {esperado} linha(s); cópia em {copia.name}; "
          f"{'conferido' if ok else 'NÃO conferido'} (migradas={migradas}, a migrar vivas={vivas_migrar})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
