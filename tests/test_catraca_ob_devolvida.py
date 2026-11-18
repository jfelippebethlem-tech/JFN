"""CATRACA — módulo que trata OB 'Contabilizado' como pago sem excluir a DEVOLVIDA pelo banco não pode crescer.

18/11/2026: 21.044 OB (R$ 5,57 bi, 2021–2026) seguem 'Contabilizado' no SIAFE com status_envio='Erro no Pagamento';
em amostra de 400, 72% têm reemissão do mesmo credor/UG/valor — somar as duas conta o pagamento duas vezes.
Regra canônica: `pericia_contabil.valor_efetivo_ob` (também desconta a Guia de Devolução parcial) ou, em SQL de
detector, `cruzamentos_intel._ob_paga(con)`. Um módulo "trata" quando cita 'Erro no Pagamento', `_ob_paga` ou
`valor_efetivo_ob`. Ao corrigir um módulo, ABAIXE a BASELINE para o novo valor (a catraca só desce).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BASELINE = 0           # 18/11/2026: 44 → 0 (43 corrigidos + dea_recorrente, que é NE e não OB, declarado)
_RAIZ = Path(__file__).resolve().parent.parent
_TRATA = ("Erro no Pagamento", "_ob_paga", "valor_efetivo_ob")


def _sem_tratar() -> list[str]:
    r = subprocess.run(["git", "grep", "--cached", "-l", "-E", r"status\s*=\s*'Contabilizado'", "--", "*.py"],
                       capture_output=True, text=True, cwd=_RAIZ)
    if r.returncode not in (0, 1):
        pytest.skip("cópia sem repositório git")
    out = []
    for f in r.stdout.split():
        if f.startswith("tests/"):
            continue
        txt = (_RAIZ / f).read_text(encoding="utf-8", errors="ignore") if (_RAIZ / f).exists() else ""
        if not any(t in txt for t in _TRATA):
            out.append(f)
    return out


def test_ob_devolvida_nao_cresce():
    sem = _sem_tratar()
    assert len(sem) <= BASELINE, (
        f"{len(sem)} módulos tratam OB 'Contabilizado' como pago sem excluir a devolvida pelo banco "
        f"(baseline {BASELINE}). Use pericia_contabil.valor_efetivo_ob ou cruzamentos_intel._ob_paga(con).")
