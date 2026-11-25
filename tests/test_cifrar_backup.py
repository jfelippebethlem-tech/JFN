# -*- coding: utf-8 -*-
"""tools/cifrar_backup.sh (25/11/2026): o backup só sobe cifrado com age para as chaves SSH das máquinas, e só depois
de a volta (decifrar com a chave local) conferir o sha256. Sem destinatário ou com a prova falhando: sai ≠ 0 e o claro
fica onde estava — nada sobe em claro e nada se perde. A chave aqui é descartável, criada no tmp do teste."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "tools" / "cifrar_backup.sh"
pytestmark = pytest.mark.skipif(not (shutil.which("age") and shutil.which("ssh-keygen")), reason="precisa de age e ssh-keygen")


def _chave(d: Path, nome: str) -> Path:
    k = d / nome
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(k)], check=True)
    return k


def _rodar(arq: Path, rec: Path, ident: Path):
    env = dict(os.environ, BACKUP_AGE_RECIPIENTS=str(rec), BACKUP_AGE_IDENTITY=str(ident))
    return subprocess.run(["bash", str(SCRIPT), str(arq)], capture_output=True, text=True, env=env, timeout=60)


def test_cifra_para_todas_as_chaves_confere_a_volta_e_apaga_o_claro(tmp_path):
    a, b = _chave(tmp_path, "a"), _chave(tmp_path, "b")
    rec = tmp_path / "rec.txt"
    rec.write_text("# comentário\n" + (a.with_suffix(".pub")).read_text() + b.with_suffix(".pub").read_text())
    arq = tmp_path / "compliance-x.db.gz"
    dado = os.urandom(200_000)
    arq.write_bytes(dado)
    r = _rodar(arq, rec, a)
    assert r.returncode == 0, r.stderr
    saida = Path(r.stdout.strip().splitlines()[-1])
    assert saida == arq.with_name(arq.name + ".age") and saida.exists() and not arq.exists()
    assert "2 destinatário" in r.stderr
    for k in (a, b):                                    # qualquer máquina restaura com a própria chave
        dec = subprocess.run(["age", "-d", "-i", str(k), str(saida)], capture_output=True, check=True).stdout
        assert hashlib.sha256(dec).digest() == hashlib.sha256(dado).digest()


def test_sem_destinatario_nao_cifra_nem_apaga(tmp_path):
    a = _chave(tmp_path, "a")
    rec = tmp_path / "vazio.txt"
    rec.write_text("# só comentário\n")
    arq = tmp_path / "x.db.gz"
    arq.write_bytes(b"dado")
    r = _rodar(arq, rec, a)
    assert r.returncode != 0 and arq.exists() and not arq.with_name("x.db.gz.age").exists()
    assert "NÃO sobe em claro" in r.stderr


def test_volta_que_nao_confere_mantem_o_claro(tmp_path):
    a, alheia = _chave(tmp_path, "a"), _chave(tmp_path, "alheia")
    rec = tmp_path / "rec.txt"
    rec.write_text(alheia.with_suffix(".pub").read_text())   # cifra para chave que ESTA máquina não tem
    arq = tmp_path / "x.db.gz"
    arq.write_bytes(b"dado" * 100)
    r = _rodar(arq, rec, a)
    assert r.returncode != 0 and arq.exists() and not arq.with_name("x.db.gz.age").exists()
    assert "não confere" in r.stderr
