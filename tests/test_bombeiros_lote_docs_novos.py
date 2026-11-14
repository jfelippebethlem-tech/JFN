# -*- coding: utf-8 -*-
"""O supervisor dos bombeiros só roda os passos de depois (lex, edital, reconciliação, árvore, depurar,
cobertura, arquivar) quando o lote trouxe documento NOVO. Medido em 13/11/2026: o lex fez 891 passadas
em 23 dias com 0 perícia, e a reconciliação repetia o mesmo resultado a cada volta do laço."""
import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "tools" / "lib" / "bombeiros_lote.sh"


def _docs(tmp_path, texto: str, desde: int = 0) -> str:
    out = tmp_path / "sweep.out"
    out.write_text(texto, encoding="utf-8")
    r = subprocess.run(["bash", "-c", f'source "{LIB}"; docs_novos_do_lote "{out}" {desde}'],
                       capture_output=True, text=True)
    return r.stdout.strip()


def test_lote_com_documento(tmp_path):
    assert _docs(tmp_path, "[x] FIM: 2 com docs (125 docs), 5 sem documento — CAUSA\n") == "2"


def test_lote_sem_documento(tmp_path):
    assert _docs(tmp_path, "[x] FIM: 0 com docs (0 docs), 10 sem documento — CAUSA\n") == "0"


def test_so_conta_o_fim_deste_lote(tmp_path):
    antigo = "[x] FIM: 3 com docs (9 docs), 0 sem documento\n"
    texto = antigo + "[y] login OK\n"                      # este lote morreu antes do FIM
    assert _docs(tmp_path, texto, desde=len(antigo.encode())) == "0"


def test_arquivo_ausente(tmp_path):
    r = subprocess.run(["bash", "-c", f'source "{LIB}"; docs_novos_do_lote "{tmp_path}/nao" 0'],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "0"
