# -*- coding: utf-8 -*-
"""Documento sem teor não pode derrubar a busca no processo — nem sumir sem aviso.

Medido em 2026-08-11, lendo o `SEI-030001/075841/2024` (o processo de R$ 88,0 mi do caso
AGILE/SEEDUC, 407 documentos): 12 documentos têm `texto` vazio no manifesto. `raiz / ""` é o
próprio DIRETÓRIO do processo, e o `read_text` levantava `IsADirectoryError` — a varredura morria
no documento 21 e **385 documentos nunca foram lidos**, com o traceback saindo depois dos poucos
resultados já impressos.

Esse é o pior formato de subnotificação: a saída parece uma busca completa. E o que estava sendo
procurado era a vedação do art. 75, VIII — a busca só encontrou as ocorrências decisivas (a
cláusula 2.2 do Contrato 31/2024) depois do conserto.

A regra da casa aplicada aqui: **ausência de ocorrência num documento não lido não é ausência no
processo**, e quem varre tem de declarar quantos ficaram de fora.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _monta(tmp_path, docs):
    # o script resolve o processo dentro de `data/sei_arquivo`; o teste aponta a raiz para o tmp
    proc = tmp_path / "sei_arquivo" / "030001_000001_2024"
    (proc / "texto").mkdir(parents=True)
    man = {"processo": "030001/000001/2024", "modalidade": "x", "docs": []}
    for i, (titulo, conteudo) in enumerate(docs):
        d = {"i": i, "fase": "planejamento", "tipo": "outro", "titulo": titulo, "texto": ""}
        if conteudo is not None:
            nome = f"texto/{i}.txt"
            (proc / nome).write_text(conteudo, encoding="utf-8")
            d["texto"] = nome
        man["docs"].append(d)
    (proc / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return proc


def _rodar(proc: Path, *args):
    import os
    env = dict(os.environ, JFN_SEI_ARQUIVO=str(proc.parent))
    return subprocess.run(
        [sys.executable, str(_REPO / "tools" / "sei_consultar.py"), "030001/000001/2024", *args],
        capture_output=True, text=True, cwd=_REPO, env=env)


def test_grep_atravessa_o_documento_sem_teor_e_acha_o_que_vem_depois(tmp_path):
    """O caso real: a ocorrência decisiva estava DEPOIS do documento vazio."""
    proc = _monta(tmp_path, [
        ("primeiro", "nada aqui"),
        ("vazio no manifesto", None),
        ("Contrato 31/2024", "É vedada a recontratação de empresa já contratada"),
    ])
    r = _rodar(proc, "--grep", "recontrata")
    assert r.returncode == 0, r.stderr
    assert "Contrato 31/2024" in r.stdout
    assert "Traceback" not in r.stderr


def test_grep_DECLARA_quantos_ficaram_de_fora(tmp_path):
    """Varredura que pula documento e não diz quantos entrega ausência que não mediu."""
    proc = _monta(tmp_path, [("a", None), ("b", None), ("c", "achou aqui")])
    r = _rodar(proc, "--grep", "achou")
    assert "2 de 3 documentos SEM TEOR" in r.stdout
    assert "NÃO é ausência no processo" in r.stdout


def test_sem_nenhum_documento_vazio_nao_ha_ressalva(tmp_path):
    """A ressalva é informação, não ruído: só aparece quando há lacuna de verdade."""
    proc = _monta(tmp_path, [("a", "achou aqui")])
    r = _rodar(proc, "--grep", "achou")
    assert "SEM TEOR" not in r.stdout


def test_pedir_UM_documento_sem_teor_diz_o_que_e_e_falha(tmp_path):
    """`--doc N` num documento sem teor devolvia traceback. Agora explica: está no manifesto e o
    acervo não tem o conteúdo — captura incompleta, não documento vazio."""
    proc = _monta(tmp_path, [("Parecer PGE", None)])
    r = _rodar(proc, "--doc", "0")
    assert r.returncode == 1
    assert "SEM TEOR" in r.stdout and "Parecer PGE" in r.stdout
    assert "Traceback" not in r.stderr
