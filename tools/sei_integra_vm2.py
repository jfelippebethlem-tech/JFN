#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VM-2 como nó de cálculo das ÍNTEGRAS do SEI — as duas pontas num arquivo só.

POR QUE EXISTE. Medido em 13/11/2026: a VM-1 (jfn-core) roda com load 10-13 à tarde e à noite (sweep SEI,
OCR, navegadores de agentes) e a fila de íntegras se ADIA por carga — na madrugada de 13/11 a rodada `--geral`
de 2 h tentou 3 processos e encerrou com "três adiamentos seguidos por carga". A VM-2 (JFN-Agent-2) tem
load ~0,5. O SEI aceita a mesma conta em duas máquinas ao mesmo tempo: os sweeps das duas capturam juntos
desde 28/07 (fatias 0/2 e 1/2), com rc=0 nos dois lados no mesmo horário.

DESENHO (a VM-1 continua dona da verdade — banco, arquivo, painel):
  1. VM-2 → `ssh vm1 … exportar`: a VM-1 monta a fila com o MESMO critério de `sei_integra_fila`
     (caso ativo dos bombeiros → fila por dinheiro pago → geral: inscritos, não arquivados, re-ler por OB),
     filtra o que já tem conteúdo e o que voltou vazio há < 7 dias, e grava a RESERVA dos que despachou.
  2. VM-2 roda `sei_integra_fila.py --fila <exportada>` no clone git `~/JFN-worker` (código idêntico ao da VM-1).
  3. VM-2 → `devolver`: rsync de `data/sei_arquivo/<proc>/` e `data/sei_cache/integra_<proc>/` para a VM-1
     (caminho COMPLETO no destino; md5 do manifesto conferido nas duas pontas), e as linhas da rodada entram em
     `data/sei_integra_fila.log` da VM-1 — é dele que o motor `sei-integras` do AO VIVO mede o efeito. Só
     entra "proc: ok" no log da VM-1 o que CHEGOU lá; o que não chegou é reescrito como `nao-entregue`.
  4. `batida`: `data/.integras_na_vm2` na VM-1. Enquanto fresco (< 30 h), a fila da VM-1 cede a vez
     (`sei_integra_fila._delegado_vm2`). Apagar o arquivo — ou a VM-2 parar de bater — traz a fila de volta.

Uso:
    (VM-1) python -m tools.sei_integra_vm2 exportar --max 300 > fila.json
    (VM-1) python -m tools.sei_integra_vm2 aceita 040047_001174_2023 …
    (VM-1) python -m tools.sei_integra_vm2 batida
    (VM-2) python -m tools.sei_integra_vm2 devolver --desde <byte do log antes da rodada>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tools import sei_integra_fila as F  # noqa: E402

RESERVA = RAIZ / "data" / ".integras_vm2_reserva.json"
BATIDA = RAIZ / "data" / ".integras_na_vm2"
RESUMO = RAIZ / "data" / "vm2_integras_resumo.jsonl"
VM1 = os.environ.get("JFN_VM1_SSH", "vm1-ts")
VM1_JFN = os.environ.get("JFN_VM1_DIR", "/home/ubuntu/JFN")
K_BOMBEIROS = 6          # o caso ativo vem primeiro, como no timer da VM-1 (lá: --max 4)


# ───────────────────────────── lado VM-1 ─────────────────────────────

def _ler_fila(caminho: Path) -> list[dict]:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []


PRE = RAIZ / "data" / ".integras_fila_pre.json"
PRE_HORAS = 26


def precalcular() -> dict:
    """As duas partes CARAS da fila, uma vez por dia (cron 00:20 e 12:20 na VM-1). Medido em 13/11/2026 com
    load 20: `_fila_reler_por_ob` 528 s e `_fila_geral` 204 s — doze minutos de CPU a cada exportação. A lista
    pré-calculada é refiltrada na hora de exportar (`_arquivado_ok`/`_vazio_recente`), então não envelhece
    para o que importa: o que entrou no arquivo depois sai da fila mesmo assim."""
    t0 = time.time()
    d = {"ts": time.time(), "reler": F._fila_reler_por_ob(), "geral": [c["sei"] for c in F._fila_geral()]}
    d["segundos"] = round(time.time() - t0, 1)
    tmp = PRE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(PRE)
    return {"reler": len(d["reler"]), "geral": len(d["geral"]), "segundos": d["segundos"]}


def _pre() -> dict | None:
    try:
        d = json.loads(PRE.read_text(encoding="utf-8"))
        return d if time.time() - float(d.get("ts") or 0) < PRE_HORAS * 3600 else None
    except (OSError, ValueError, TypeError):
        return None


def _restritos_confirmados() -> set[str]:
    """Processos com status RESTRITO CONFIRMADO no registro da casa (`tools/sei_restritos.py`, ≥2 leituras
    consistentes). A conta tem UMA unidade: reabrir não traz documento (o caminho é a requisição formal,
    `tools/gerar_requisicoes.py`). Medido em 14/11/2026 no it-campo: processo restrito gasta ~3 min de sessão
    para devolver "Unidade atual não possui acesso". `RESTRITO?` (não confirmado) continua na fila."""
    try:
        d = json.loads((RAIZ / "data" / "sei_restritos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(d, dict):
        return set()
    return {F._proc_limpo(str(v.get("numero") or "")) for v in d.values()
            if isinstance(v, dict) and v.get("status") == "RESTRITO"} - {""}


def montar_fila(max_n: int, k_bombeiros: int = K_BOMBEIROS, excluir: set[str] | None = None) -> list[dict]:
    """Fila na ORDEM do código da VM-1: bombeiros (por score) → dinheiro (por valor pago) → geral.
    `excluir` = processos reservados por OUTRO nó (nenhum processo é capturado por dois nós ao mesmo tempo)."""
    excluir = set(excluir or set()) | _restritos_confirmados()
    bomb = sorted(_ler_fila(RAIZ / "data" / "bombeiros_sei_fila.json"), key=lambda e: -(e.get("score") or 0))
    dinheiro = _ler_fila(RAIZ / "data" / "sei_fila_dinheiro.json")
    pre = _pre()
    reler = pre["reler"] if pre else F._fila_reler_por_ob()
    geral_cdp = pre["geral"] if pre else [c["sei"] for c in F._fila_geral()]
    geral = list(dict.fromkeys(F._fila_inscrita() + geral_cdp + reler))
    fontes = [("bombeiros", [e.get("sei", "") for e in bomb], k_bombeiros),
              ("dinheiro", [e.get("sei", "") for e in dinheiro], max_n),
              ("geral", geral, max_n)]
    vistos: set[str] = set()
    out: list[dict] = []
    for fonte, seis, teto in fontes:
        n_fonte = 0
        for sei in seis:
            if len(out) >= max_n or n_fonte >= teto:
                break
            proc = F._proc_limpo(sei)
            if not proc or proc in vistos or proc in excluir:
                continue
            vistos.add(proc)
            pasta = F.ARQUIVO / proc.replace("/", "_")
            if F._arquivado_ok(pasta) and f"SEI-{proc}" not in reler:
                continue
            if F._vazio_recente(pasta):
                continue
            out.append({"sei": f"SEI-{proc}", "fonte": fonte})
            n_fonte += 1
    # `--fila` reordena por score: o score é a POSIÇÃO, para a VM-2 seguir exatamente esta ordem
    for i, e in enumerate(out):
        e["score"] = len(out) - i
    return out


def _reserva(no: str) -> Path:
    """Arquivo de reserva do nó. A VM-2 mantém o nome histórico; os demais nós ganham o seu."""
    return RESERVA if no == "vm2" else RAIZ / "data" / f".integras_{no}_reserva.json"


def _reservas_alheias(no: str) -> set[str]:
    """Processos reservados (reserva fresca) por qualquer OUTRO nó."""
    out: set[str] = set()
    for arq in (RAIZ / "data").glob(".integras_*_reserva.json"):
        if arq == _reserva(no):
            continue
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            if time.time() - float(d.get("ts") or 0) < float(d.get("validade_h") or 12) * 3600:
                out |= {str(p) for p in d.get("procs") or []}
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return out


def exportar(max_n: int, no: str = "vm2", validade_h: float | None = None,
             k_bombeiros: int = K_BOMBEIROS) -> list[dict]:
    fila = montar_fila(max_n, k_bombeiros=k_bombeiros, excluir=_reservas_alheias(no))
    reg = {"ts": time.time(), "host": no, "procs": [F._proc_limpo(e["sei"]) for e in fila]}
    if validade_h:
        reg["validade_h"] = validade_h
    alvo = _reserva(no)
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg), encoding="utf-8")
    tmp.replace(alvo)
    return fila


def aceita(tags: list[str]) -> list[str]:
    """Pastas que a VM-1 aceita receber de uma captura VAZIA: só onde ela não tem conteúdo.
    Uma releitura que voltou vazia não pode sobrescrever um arquivo bom (vazio ≠ ausência de documento)."""
    return [t for t in tags if re.fullmatch(r"\d{6}_\d{6}_\d{4}", t) and not F._arquivado_ok(F.ARQUIVO / t)]


def batida(no: str = "vm2") -> None:
    alvo = BATIDA if no == "vm2" else RAIZ / "data" / f".integras_na_{no}"
    alvo.write_text(f"{time.strftime('%F %T')} {socket.gethostname()} — fila de íntegras no nó {no} "
                    "(apagar este arquivo devolve a fila à VM-1)\n", encoding="utf-8")


# ───────────────────────────── lado VM-2 ─────────────────────────────

_RX_STATUS = re.compile(r"^\[[^\]]+\]\s+(\d{6}/\d{6}/\d{4}): (\w+)\s*$")
_ENTREGAR = {"ok", "vazio", "sem_arvore"}
# sem a causa do SEI ("RESTRITO: SEI diz …", registrada desde 13/11) e com o cracked sem achar a Pesquisa
_RX_CAUSA_METODO = re.compile(r"^\[[^\]]+\]\s+(\d{6}/\d{6}/\d{4}): SEM ÁRVORE \(processo não abriu\) — via=.*NÃO ESTÁ no DOM")


def _ssh(cmd: str, entrada: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VM1, cmd],
                          input=entrada, capture_output=True, text=True, timeout=timeout)


def _limpar_local(tag: str) -> None:
    """A VM-1 é a dona do acervo: depois de conferido lá, a cópia daqui sai (disco e `_arquivado_ok` local)."""
    import shutil
    shutil.rmtree(F.ARQUIVO / tag, ignore_errors=True)
    shutil.rmtree(F.CACHE / f"integra_{tag}", ignore_errors=True)
    for p in F.CACHE.glob(f"INTEGRA_{tag}*.pdf"):
        p.unlink(missing_ok=True)


def _tirar_da_fila(fila: Path, tentados: list[str]) -> None:
    """Tira da fila exportada o que já foi tentado (menos adiado/login, que não dizem nada do processo)."""
    try:
        d = json.loads(fila.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    sair = {f"SEI-{p}" for p in tentados}
    fila.write_text(json.dumps([e for e in d if e.get("sei") not in sair], ensure_ascii=False), encoding="utf-8")


def _amostra_texto(tag: str) -> tuple[str, str]:
    """(título, texto) do documento mais substancioso do arquivo — a amostra que o Claude julga."""
    try:
        m = json.loads((F.ARQUIVO / tag / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    docs = [d for d in (m.get("docs") or []) if isinstance(d, dict) and str(d.get("texto") or "").endswith(".txt")]
    if not docs:
        return "", ""
    d = max(docs, key=lambda d: F._chars(d))
    p = F.ARQUIVO / tag / "texto" / Path(str(d["texto"])).name
    try:
        return str(d.get("titulo") or ""), p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""


def devolver(desde: int, fila: Path | None = None) -> dict:
    """Monta um LOTE com o que a rodada produziu e entrega à VM-1, que CONFERE antes de importar
    (`tools/vm2_conferencia.py`): md5, documentos × árvore, texto legível, amostra × leitura da VM-1,
    juízo do Claude daqui. O log da fila da VM-1 só ganha "proc: ok" do que a conferência aprovou."""
    from tools import vm2_lote as L
    L.reenviar_pendentes()
    try:
        with F.LOG.open("rb") as f:
            f.seek(desde)
            linhas = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        linhas = []
    status: dict[str, str] = {}
    falha_de_metodo: set[str] = set()
    for ln in linhas:
        m = _RX_STATUS.match(ln)
        if m:
            status[m.group(1)] = m.group(2)
        m = _RX_CAUSA_METODO.match(ln)
        if m:
            falha_de_metodo.add(m.group(1))
    # "SEM ÁRVORE" com "link 'Pesquisa' NÃO ESTÁ no DOM": medido em 13/11 (tela capturada), o SEI responde
    # "Unidade atual não possui acesso ao processo restrito" — mas a captura NÃO registra essa causa, então
    # aqui não se sabe se foi restrição ou página fora do lugar. Não entregar (não dar 7 dias de espera a
    # quem pode não ter sido procurado); o processo volta na próxima exportação.
    a_entregar = [p for p, s in status.items() if s in _ENTREGAR and p not in falha_de_metodo]
    nao_entregues = {p: "SEM ÁRVORE sem causa registrada (página da Pesquisa ausente)" for p in falha_de_metodo}
    vazios = [p.replace("/", "_") for p in a_entregar if status[p] != "ok"]
    aceitos = set()
    if vazios:
        r = _ssh(f"cd {VM1_JFN} && PYTHONPATH=. .venv/bin/python -m tools.sei_integra_vm2 aceita {' '.join(vazios)}")
        aceitos = set(r.stdout.split()) if r.returncode == 0 else set()
    itens: dict[str, Path] = {}
    processos: dict[str, dict] = {}
    for proc in a_entregar:
        tag = proc.replace("/", "_")
        if status[proc] != "ok" and tag not in aceitos:
            nao_entregues[proc] = "VM-1 já tem conteúdo — vazio não sobrescreve"
            continue
        if not (F.ARQUIVO / tag / "manifest.json").exists():
            nao_entregues[proc] = "sem manifesto local"
            continue
        itens[f"arquivo/{tag}"] = F.ARQUIVO / tag
        if (F.CACHE / f"integra_{tag}").is_dir():
            itens[f"cache/integra_{tag}"] = F.CACHE / f"integra_{tag}"
        juizo = None
        if status[proc] == "ok":
            titulo, texto = _amostra_texto(tag)
            juizo = L.julgar(proc, titulo, texto)
        processos[proc] = {"status": status[proc], "juizo": juizo}
    res = None
    if processos or linhas:
        base = L.montar("integras", itens, processos, {"linhas_log": linhas, "nao_entregues": nao_entregues})
        for proc in list(processos) + list(nao_entregues):
            _limpar_local(proc.replace("/", "_"))     # a cópia está no lote (e o lote fica até a VM-1 conferir)
        res = L.enviar(base)
    if fila:
        _tirar_da_fila(fila, [p for p, s in status.items() if s not in ("adiado", "login")])
    resumo = {"ts": time.strftime("%F %T"), "status": status, "lote": res,
              "nao_entregues": nao_entregues, "juizos": {p: v.get("juizo") for p, v in processos.items()}}
    with RESUMO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(resumo, ensure_ascii=False) + "\n")
    return resumo


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar"); e.add_argument("--max", type=int, default=300)
    e.add_argument("--no", default="vm2", help="nó que reserva (vm2, itcampo, …)")
    e.add_argument("--validade-h", type=float, default=None, help="validade da reserva (padrão: 12 h)")
    e.add_argument("--k-bombeiros", type=int, default=K_BOMBEIROS)
    a = sub.add_parser("aceita"); a.add_argument("tags", nargs="*")
    b = sub.add_parser("batida"); b.add_argument("--no", default="vm2")
    sub.add_parser("precalcular")
    d = sub.add_parser("devolver"); d.add_argument("--desde", type=int, default=0)
    d.add_argument("--fila", default="")
    args = ap.parse_args()
    if args.cmd == "exportar":
        print(json.dumps(exportar(args.max, args.no, args.validade_h, args.k_bombeiros), ensure_ascii=False))
    elif args.cmd == "aceita":
        print(" ".join(aceita(args.tags)))
    elif args.cmd == "batida":
        batida(args.no)
    elif args.cmd == "precalcular":
        print(json.dumps(precalcular(), ensure_ascii=False))
    else:
        print(json.dumps(devolver(args.desde, Path(args.fila) if args.fila else None), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
