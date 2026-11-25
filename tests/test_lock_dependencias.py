# -*- coding: utf-8 -*-
"""O lock com hashes não pode ficar velho calado (O9.3).

`requirements*.lock` são gerados por `tools/lock_dependencias.py`, que grava no cabeçalho o sha256 de cada
`requirements*.txt` de entrada. Mudou um requirements sem regenerar o lock -> este teste falha e diz qual: o lock
passaria a instalar outra coisa que não a declarada, e a `pip install --require-hashes` da VM nova montaria um venv
diferente do que o requirements promete — o mesmo defeito do "requirements mentindo em silêncio" de 28/07/2026
(tests/test_requirements_declara_o_que_importa.py), um degrau abaixo.
"""
from __future__ import annotations

import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tools.lock_dependencias import CAMADAS, MARCA, sha256  # noqa: E402


def _entradas_divergentes(lock: pathlib.Path, raiz: pathlib.Path = RAIZ) -> list[str]:
    """Entradas cujo sha256 atual não bate com o registrado no cabeçalho do lock (ou que sumiram dele)."""
    registrado = dict(re.findall(rf"^{re.escape(MARCA)}(\S+) sha256=([0-9a-f]{{64}})$",
                                 lock.read_text(encoding="utf-8"), re.M))
    return [e for e in registrado if not (raiz / e).exists() or sha256(raiz / e) != registrado[e]]


def _pins(lock: pathlib.Path) -> dict[str, tuple[str, bool]]:
    """nome -> (versão, tem hash?) de cada pacote fixado no lock."""
    out = {}
    for bloco in re.split(r"\n(?=[A-Za-z0-9])", lock.read_text(encoding="utf-8")):
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==(\S+)", bloco)
        if m:
            out[m.group(1).lower()] = (m.group(2), "--hash=sha256:" in bloco)
    return out


def test_todo_requirements_tem_lock():
    declarados = {p.name for p in RAIZ.glob("requirements*.txt")}
    cobertos = {e for _, entradas, _ in CAMADAS for e in entradas}
    assert declarados <= cobertos, f"requirements sem lock: {sorted(declarados - cobertos)} — acrescente em CAMADAS"


def test_lock_regenerado_depois_do_requirements():
    velhos = {}
    for lock, entradas, _ in CAMADAS:
        caminho = RAIZ / lock
        assert caminho.exists(), f"{lock} ausente — rode: python tools/lock_dependencias.py"
        texto = caminho.read_text(encoding="utf-8")
        faltam = [e for e in entradas if f"{MARCA}{e} sha256=" not in texto]
        assert not faltam, f"{lock} não registra a entrada {faltam}"
        if div := _entradas_divergentes(caminho):
            velhos[lock] = div
    assert not velhos, f"requirements mudou sem regenerar o lock: {velhos} — rode: python tools/lock_dependencias.py"


def test_controle_positivo_requirements_alterado_e_acusado(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests>=2.31\n", encoding="utf-8")
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"{MARCA}requirements.txt sha256={sha256(tmp_path / 'requirements.txt')}\n", encoding="utf-8")
    assert _entradas_divergentes(lock, tmp_path) == []
    (tmp_path / "requirements.txt").write_text("requests>=2.31\nhttpx\n", encoding="utf-8")
    assert _entradas_divergentes(lock, tmp_path) == ["requirements.txt"]


def test_todo_pin_tem_hash_e_torch_e_cpu():
    for lock, _, _ in CAMADAS:
        pins = _pins(RAIZ / lock)
        assert len(pins) > 50, f"{lock} quase vazio ({len(pins)} pacotes) — o uv.lock de 52 bytes de novo?"
        sem_hash = sorted(n for n, (_, h) in pins.items() if not h)
        assert not sem_hash, f"{lock}: pin sem --hash (pip --require-hashes recusaria tudo): {sem_hash}"
        for nome in ("torch", "torchvision"):
            assert pins[nome][0].endswith("+cpu"), f"{lock}: {nome}=={pins[nome][0]} — o venv da VM é CPU-only"
        assert "/tmp/" not in (RAIZ / lock).read_text(encoding="utf-8"), f"{lock} vaza caminho temporário"


def test_mesma_versao_em_todas_as_camadas():
    pins = {lock: _pins(RAIZ / lock) for lock, _, _ in CAMADAS}
    nomes = set().union(*pins.values())
    divergem = {n: {lk: p[n][0] for lk, p in pins.items() if n in p} for n in nomes}
    divergem = {n: v for n, v in divergem.items() if len(set(v.values())) > 1}
    assert not divergem, f"pacote com versões diferentes entre camadas (instalar juntas conflitaria): {divergem}"
