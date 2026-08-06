# -*- coding: utf-8 -*-
"""Baseline versionado dos achados do motor — a catraca que faltava.

O QUE ESTAVA DESPROTEGIDO. `tools/pos_correcao.fotografia()` produz, a cada rodada, exatamente o
número que serviria de baseline — faixas de risco e achados por código·grau — e **nada dele era
versionado**. Um detector que saltasse de 40 para 400 achados, ou caísse para 0, subia em silêncio:
nenhum teste comparava "hoje" com "o commit anterior". O `_drift` do `tools/autoauditoria.py` só
compara com a última execução LOCAL, e ninguém a executava.

POR QUE ISSO IMPORTA AQUI. Em 2026-08-05 e 06, sete correções mudaram contagens de família inteira
— I6 de 6 para 2, CD_ de 24 para 10, `F_EXECUCAO_SEM_EVIDENCIA` de 319 críticas para 251,
`X_PAGAMENTO_SEM_ATESTACAO` nascendo com 109. **Todas foram deliberadas e cada uma passou por
leitura dos autos.** O risco não é a mudança: é a mudança que ninguém pretendeu.

O CONTRATO. Este arquivo NÃO mede o banco, mede o MOTOR: quantos achados de cada código·grau o
acervo produz. Se a coleta trouxer processos novos, os números mudam — e a regravação é legítima,
desde que o commit diga por quê. É a mesma disciplina do `tests/golden/server_rotas.txt`, que só se
regrava por flag explícita.

    python -m tools.baseline_achados            # compara e mostra o diff
    python -m tools.baseline_achados --gravar   # regrava (mudança deliberada)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ALVO = RAIZ / "tests" / "golden" / "achados_360.json"

_CABECALHO = (
    "Baseline do MOTOR, não do banco. Um detector que salte de 40 para 400 achados — ou caia "
    "para 0 — subia em silêncio: `pos_correcao.fotografia()` produzia exatamente este número e "
    "nada dele era versionado. Regravar SÓ com mudança deliberada, e o commit tem de dizer "
    "POR QUE cada linha mudou (foi assim que I6 caiu 6→2 e CD_ caiu 24→10 em 2026-08-05/06, "
    "cada passo com leitura dos autos). Comando: python -m tools.baseline_achados --gravar"
)


def ler() -> dict:
    if not ALVO.exists():
        return {}
    try:
        return json.loads(ALVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def medir() -> dict:
    from tools.pos_correcao import fotografia

    f = fotografia()
    return {"faixas": f["faixas"], "graus": f["graus"],
            "_processos_avaliados": sum(f["faixas"].values())}


def comparar(base: dict, agora: dict) -> list[str]:
    """Linhas do diff, vazio quando idênticos. Compara faixas e código·grau."""
    fora: list[str] = []
    for chave in ("faixas", "graus"):
        a, b = base.get(chave) or {}, agora.get(chave) or {}
        for k in sorted(set(a) | set(b)):
            va, vb = int(a.get(k, 0)), int(b.get(k, 0))
            if va != vb:
                fora.append(f"{chave}: {k:52s} {va:6d} → {vb:6d}  ({vb - va:+d})")
    return fora


def gravar(agora: dict, medido_em: str) -> None:
    ALVO.parent.mkdir(parents=True, exist_ok=True)
    ALVO.write_text(json.dumps(
        {"_leia_isto": _CABECALHO, "_medido_em": medido_em,
         "_processos_avaliados": agora["_processos_avaliados"],
         "faixas": agora["faixas"], "graus": agora["graus"]},
        ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    from datetime import date

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gravar", action="store_true",
                    help="regrava o baseline (só com mudança DELIBERADA, e diga no commit por quê)")
    a = ap.parse_args()

    agora = medir()
    base = ler()
    linhas = comparar(base, agora)
    if a.gravar:
        gravar(agora, date.today().isoformat())
        print(f"baseline regravado em {ALVO}")
        for x in linhas:
            print("  " + x)
        return 0
    if not linhas:
        print("baseline em dia — nenhuma variação de faixa ou de código·grau.")
        return 0
    print(f"{len(linhas)} variação(ões) em relação ao baseline:")
    for x in linhas:
        print("  " + x)
    print("\nSe foi deliberado: python -m tools.baseline_achados --gravar (e explique no commit).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
