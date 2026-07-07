# -*- coding: utf-8 -*-
"""Guarda de cobertura: TODO detector (subclasse de Detector) precisa aparecer em algum teste.

A dívida "48% dos detectores sem teste" (MOC 06-24) foi paga; este teste impede que ela
volte: detector novo sem NENHUM teste que cite a classe → falha aqui com instrução.
Citação ≠ profundidade, mas garante o piso (o smoke/contrato mora no teste citado).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DETECTORES = REPO / "compliance_agent/detectores"
TESTS = Path(__file__).resolve().parent


def _classes_detector() -> dict[str, str]:
    """classe -> módulo, para toda subclasse direta de Detector."""
    out = {}
    for f in sorted(DETECTORES.glob("[a-z]*.py")):
        if f.name == "base.py":
            continue
        for m in re.finditer(r"^class ([A-Za-z0-9_]+)\(Detector\)", f.read_text(encoding="utf-8"), re.M):
            out[m.group(1)] = f.stem
    return out


def test_todo_detector_citado_em_teste():
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                       for p in TESTS.glob("test_*.py") if p.name != Path(__file__).name)
    classes = _classes_detector()
    sem_teste = [f"{cls} ({classes[cls]}.py)" for cls in classes if cls not in corpus]
    assert not sem_teste, (
        "Detector(es) sem NENHUM teste que cite a classe: " + ", ".join(sem_teste)
        + ". Crie tests/test_detector_<sigla>.py exercitando avaliar() com contexto mínimo."
    )


def test_inventario_minimo():
    # trava de sanidade: se a descoberta regredir (glob/regex quebrada), o teste acima passaria vazio
    assert len(_classes_detector()) >= 26
