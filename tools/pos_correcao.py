#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Depois de mexer num detector: reavalia o acervo, regrava a fila e MOSTRA o antes/depois.

POR QUE EXISTE. Em 2026-08-04 esta sequência foi repetida **cinco vezes à mão** numa única
sessão — corrigir um detector, rodar a suíte, reavaliar 2.174 processos, regravar
`data/fila_fiscal_360.md`, e então medir na unha o que mudou. Cada repetição gastou minutos em
comandos ad-hoc, e duas delas me deram número errado: uma porque o script engolia exceção, outra
porque comparava uma chave de 19 caracteres com um conjunto de chaves de 20 — e devolveu um
"zero" limpo que quase virou relatório.

O ciclo é sempre o mesmo, então vira ferramenta: **medir → reavaliar → regravar → medir → diff**.

O QUE ELE NÃO FAZ, de propósito:
  · não roda a suíte (a casa manda rodar em LOTES, `tools/ci_lote.py`, e isso é decisão de quem
    está no teclado, não de um script que já está com o acervo na mão);
  · não é loop: passe ÚNICO, sem `while true`. O cron da casa é single-pass com timeout, e um
    lane que se relança sozinho já foi removido daqui por bom motivo;
  · não paralela nada: 2 vCPU é o gargalo, e com load >= 4 ele **espera**, nunca soma trabalho.

Uso:
    python -m tools.pos_correcao                 # mede, reavalia, regrava a fila, mostra o diff
    python -m tools.pos_correcao --so-medir      # só a fotografia de agora (não escreve nada)
    python -m tools.pos_correcao --sem-fila      # reavalia sem regravar a fila do fiscal
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB = RAIZ / "data" / "compliance.db"
FILA = RAIZ / "data" / "fila_fiscal_360.md"
LIMIAR_CARGA = 4.0
"""Regra da casa: load >= 4 em 2 vCPU manda ADIAR, nunca paralelizar."""
PAUSA = 30
ESPERAS_MAX = 20


def _carga() -> float:
    return os.getloadavg()[0]


def fotografia(db: Path | None = None) -> dict:
    """O estado que interessa comparar: faixas, achados por origem/código e motivos da fila."""
    caminho = Path(db or os.environ.get("JFN_DB") or DB)
    faixas: Counter = Counter()
    codigos: Counter = Counter()
    origens: Counter = Counter()
    if caminho.exists():
        con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        try:
            for faixa, aj in con.execute(
                    "SELECT faixa, achados_json FROM processo_avaliacao"):
                faixas[str(faixa)] += 1
                try:
                    for a in json.loads(aj or "[]"):
                        if isinstance(a, dict):
                            codigos[str(a.get("codigo") or "—")] += 1
                            origens[str(a.get("origem") or "—")] += 1
                except ValueError:
                    continue
        finally:
            con.close()
    motivos: Counter = Counter()
    if FILA.exists():
        for linha in FILA.read_text(encoding="utf-8").splitlines():
            for parte in linha.split("|")[-1].split(";"):
                p = parte.strip()
                if p and not p.startswith("-"):
                    motivos[p[:48]] += 1
    return {"faixas": dict(faixas), "codigos": dict(codigos), "origens": dict(origens),
            "motivos_da_fila": dict(motivos)}


def _diff(antes: dict, depois: dict, chave: str) -> list[str]:
    a, d = antes.get(chave, {}), depois.get(chave, {})
    linhas = []
    for k in sorted(set(a) | set(d)):
        va, vd = a.get(k, 0), d.get(k, 0)
        if va != vd:
            linhas.append(f"   {k[:52]:52s} {va:6d} → {vd:6d}  ({vd - va:+d})")
    return linhas


ESTADO = RAIZ / "data" / ".pos_correcao_estado.json"
"""Quem já foi reavaliado NESTA rodada. Some quando a rodada termina inteira."""


def _estado_ler() -> set[str]:
    try:
        return set(json.loads(ESTADO.read_text(encoding="utf-8")).get("feitos") or [])
    except (OSError, ValueError):
        return set()


def _estado_gravar(feitos: set[str]) -> None:
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps({"feitos": sorted(feitos)}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ESTADO)


def reavaliar(limite: int | None = None, retomar: bool = True) -> dict:
    """Reavalia e regrava TODOS os processos já avaliados. Passe único, cedendo a VM.

    RETOMÁVEL. Em 2026-08-04 duas passadas foram interrompidas no meio (uma por carga alta, outra
    porque o código mudara durante a execução) e **todo o trabalho já feito foi perdido** — 375 e
    100 processos reavaliados do zero na vez seguinte. O estado é gravado a cada lote de 25 e
    apagado quando a rodada termina inteira, então retomar é o padrão e recomeçar é a exceção
    (`--do-zero`).
    """
    sys.path.insert(0, str(RAIZ))
    from compliance_agent import processo_360 as P

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        alvos = [r[0] for r in con.execute(
            "SELECT numero_sei FROM processo_avaliacao ORDER BY score100 DESC")]
    finally:
        con.close()
    if limite:
        alvos = alvos[:limite]
    feitos = _estado_ler() if retomar else set()
    if feitos:
        antes_n = len(alvos)
        alvos = [a for a in alvos if a not in feitos]
        print(f"[pos-correcao] retomando: {antes_n - len(alvos)} já reavaliados numa rodada "
              f"anterior, {len(alvos)} restantes", flush=True)
    print(f"[pos-correcao] {len(alvos)} processos a reavaliar", flush=True)
    ok = erro = 0
    t0 = time.time()
    for i, num in enumerate(alvos, 1):
        if i % 25 == 0:
            esperas = 0
            while _carga() >= LIMIAR_CARGA and esperas < ESPERAS_MAX:
                time.sleep(PAUSA)
                esperas += 1
            _estado_gravar(feitos)
            print(f"[pos-correcao] {i}/{len(alvos)} · ok={ok} erro={erro} · "
                  f"load={_carga():.2f} · {time.time() - t0:.0f}s", flush=True)
        try:
            out = P.avaliar(num if str(num).startswith("SEI-") else f"SEI-{num}")
            if out.get("status") == "OK":
                P.gravar(out)
                ok += 1
            else:
                erro += 1
            feitos.add(num)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as e:
            # um processo ruim não derruba o passe — mas ele APARECE, porque script que engole
            # exceção foi exatamente o que me deu número errado nesta mesma sessão.
            erro += 1
            if erro <= 5:
                print(f"[pos-correcao] ERRO {num}: {type(e).__name__}: {str(e)[:90]}", flush=True)
    ESTADO.unlink(missing_ok=True)      # rodada inteira concluída: o estado deixa de existir
    print(f"[pos-correcao] reavaliação: ok={ok} erro={erro} · {time.time() - t0:.0f}s", flush=True)
    return {"ok": ok, "erro": erro, "segundos": round(time.time() - t0)}


def regravar_fila() -> bool:
    """Regrava `data/fila_fiscal_360.md` pelo ranking canônico."""
    try:
        saida = subprocess.run(
            [str(RAIZ / ".venv" / "bin" / "python"), str(RAIZ / "tools" / "processo_360_ranking.py"),
             "--top", "40", "--md"],
            capture_output=True, text=True, timeout=300, cwd=str(RAIZ), check=False)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[pos-correcao] fila NÃO regravada ({type(e).__name__}: {str(e)[:60]})")
        return False
    if saida.returncode != 0 or not saida.stdout.strip():
        print(f"[pos-correcao] fila NÃO regravada (rc={saida.returncode})")
        return False
    FILA.write_text(saida.stdout, encoding="utf-8")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--so-medir", action="store_true", help="só a fotografia de agora")
    ap.add_argument("--sem-fila", action="store_true", help="não regrava a fila do fiscal")
    ap.add_argument("--limite", type=int, default=0, help="reavalia só os N de maior score")
    ap.add_argument("--do-zero", action="store_true",
                    help="ignora o estado de uma rodada interrompida e recomeça do início")
    a = ap.parse_args(argv)

    antes = fotografia()
    if a.so_medir:
        print(json.dumps(antes, ensure_ascii=False, indent=1))
        return 0

    if _carga() >= LIMIAR_CARGA:
        print(f"[pos-correcao] load {_carga():.2f} — a regra da casa manda ADIAR. "
              "Rode quando ceder; a reavaliação cede sozinha entre lotes, mas começar já "
              "carregado é somar trabalho.")
        return 1

    reavaliar(a.limite or None, retomar=not a.do_zero)
    fila_ok = False if a.sem_fila else regravar_fila()
    depois = fotografia()

    print("\n=== O QUE MUDOU ===")
    for chave, rotulo in (("faixas", "faixas de risco"), ("codigos", "achados por código"),
                          ("origens", "achados por origem"),
                          ("motivos_da_fila", "motivos no top 40 da fila")):
        linhas = _diff(antes, depois, chave)
        print(f"\n{rotulo}:" + ("" if linhas else "  (sem mudança)"))
        for ln in linhas:
            print(ln)
    if not a.sem_fila:
        print(f"\nfila do fiscal regravada: {fila_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
