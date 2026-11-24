# -*- coding: utf-8 -*-
"""Catraca O4.5 — nenhum valor de TETO DE DISPENSA literal fora de `compliance_agent/limites_dispensa.py`.

Amplia a trava de `test_teto_dispensa_fonte_unica.py` (que só cobre os tetos da 14.133 de 2022+) para todos os
tetos que a O4.5 pôs na fonte única: §7º da 14.133 (2022+), os dobros do §2º, e os da 8.666 pós-Decreto 9.412
(17.600 / 33.000 e os 20% do art. 24 §1º, 35.200 / 66.000).

Só NÚMERO operando no código (tokenize): teto citado em comentário/docstring é documentação. Ficam FORA, de
propósito, os valores redondos (8.000, 15.000, 16.000, 30.000, 50.000, 100.000): aparecem legitimamente como
limiar, faixa ou paginação em qualquer módulo — a trava viraria ruído e seria desligada. Esses só existem na
fonte única por disciplina de revisão (e o grep do CI os mostra em `limites_dispensa.py`).

Exceções: `EXCECOES` (arquivo → justificativa). A lista só pode encolher.
"""
from __future__ import annotations

import io
import subprocess
import tokenize
from pathlib import Path

from compliance_agent.limites_dispensa import LIMITES, LIMITES_8666, LIMITES_PAR7

RAIZ = Path(__file__).resolve().parents[1]
FONTE_UNICA = "compliance_agent/limites_dispensa.py"

EXCECOES: dict[str, str] = {
    # nenhuma em 24/11/2026 (varredura: zero literal numérico desses tetos fora da fonte única)
}


def _tetos() -> set[float]:
    v = {float(LIMITES[a][t]) for a in LIMITES if a >= 2022 for t in ("compras", "obras")}
    v |= {round(2 * x, 2) for x in v}                                            # §2º (duplicados)
    v |= {float(LIMITES_PAR7[a]["valor"]) for a in LIMITES_PAR7 if a >= 2022}   # §7º atualizado
    pos9412 = LIMITES_8666[2019]
    v |= {float(pos9412["compras"]), float(pos9412["obras"]),
          round(2 * pos9412["compras"], 2), round(2 * pos9412["obras"], 2)}     # 8.666 art. 24 I/II e §1º
    return v


def _arquivos() -> list[str]:
    try:
        r = subprocess.run(["git", "ls-files", "*.py"], cwd=RAIZ, capture_output=True, text=True, check=True)
        arqs = r.stdout.split()
    except (OSError, subprocess.CalledProcessError):
        arqs = [str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*.py")]
    return [a for a in arqs if not a.startswith(("tests/", "docs/", "_SANDBOX/", "_PROTEGIDO/", "graphify-out/"))
            and a != FONTE_UNICA and (RAIZ / a).exists()]


def _literais(rel: str, tetos: set[float]) -> list[str]:
    try:
        toks = tokenize.generate_tokens(io.StringIO((RAIZ / rel).read_text(encoding="utf-8")).readline)
        achados = []
        for tok in toks:
            if tok.type != tokenize.NUMBER:
                continue
            try:
                x = float(tok.string.replace("_", ""))
            except ValueError:
                continue
            if any(abs(x - t) < 0.005 for t in tetos):
                achados.append(f"{rel}:{tok.start[0]} {tok.string}")
        return achados
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError, IndentationError):
        return []


def test_conjunto_de_tetos_cobre_o_que_a_O4_5_acrescentou():
    t = _tetos()
    assert 17600.0 in t and 33000.0 in t and 10478.74 in t and 130984.22 in t
    assert not t & {8000.0, 15000.0, 16000.0, 30000.0, 50000.0, 100000.0}


def test_nenhum_teto_literal_fora_da_fonte_unica():
    tetos = _tetos()
    achados = [x for a in _arquivos() for x in _literais(a, tetos)]
    fora = [x for x in achados if x.split(":")[0] not in EXCECOES]
    assert not fora, ("teto de dispensa literal fora de limites_dispensa.py — importe de lá "
                      f"(limite_dispensa / teto_dispensa / limite_par7): {fora}")


def test_excecoes_so_encolhem():
    """Exceção cujo arquivo já não tem literal sai da lista (senão vira licença permanente)."""
    tetos = _tetos()
    mortas = [a for a in EXCECOES if not _literais(a, tetos)]
    assert not mortas, f"exceções sem literal (remova): {mortas}"


def test_a_varredura_enxerga_o_literal():
    """Controle positivo: a fonte única TEM os literais — se a varredura não os vê lá, ela está cega."""
    assert _literais(FONTE_UNICA, _tetos())
