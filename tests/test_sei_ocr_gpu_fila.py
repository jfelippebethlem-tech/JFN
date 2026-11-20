"""Fila do OCR por IA e o arquivo frio novo (20/11/2026): `vm2:~/arquivo_frio/sei_pdfs` ficava fora da fila e a GPU
ociosa. Entra por link físico em `sei_cache` (conferido por inode); link que falhou fica fora; o disco do it-campo só
com `--itcampo-local`. Controle positivo e negativo em cada regra."""
from __future__ import annotations

import json
import subprocess
import sys

import tools.sei_ocr_gpu_fila as F
import tools.sei_ocr_reserva as R

TAG = "111_222_2024"
REL = [f"integra_{TAG}/{i:03d}.pdf" for i in range(5)]


def test_fila_inclui_sei_pdfs_so_com_link_conferido_e_itcampo_local_so_com_a_opcao(tmp_path, monkeypatch, capsys):
    arq = tmp_path / "sei_arquivo" / TAG
    arq.mkdir(parents=True)
    docs = [{"i": i, "tipo": "nota_fiscal", "chars": 0} for i in range(4)] + \
        [{"i": 4, "tipo": "nota_fiscal", "chars": 900, "ocr": "False"}]          # nativo (ocr como string): nunca
    (arq / "manifest.json").write_text(json.dumps({"docs": docs}))
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(F, "SAIDA", tmp_path / "fila.txt")
    monkeypatch.setattr(F, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(F, "tags_risco_alto", lambda: set())
    monkeypatch.setattr(R, "reservados_pela_reserva", lambda: set())
    monkeypatch.setattr(F, "pdfs_no_frio", lambda: ({REL[0]}, {REL[1], REL[2], REL[4]}))
    monkeypatch.setattr(F, "pdfs_no_itcampo", lambda: {REL[3]})
    pedidos: list[str] = []
    monkeypatch.setattr(F, "espelhar_no_sei_cache", lambda rs: pedidos.extend(rs) or {REL[1]})   # REL[2]: link falhou

    monkeypatch.setattr(sys, "argv", ["x", "--medir"])
    assert F.main() == 0
    assert not (tmp_path / "fila.txt").exists() and pedidos == []                     # medir não grava nem liga
    assert json.loads(capsys.readouterr().out)["por_origem"] == {"sei_cache": 1, "sei_pdfs": 2, "itcampo_local": 0}

    monkeypatch.setattr(sys, "argv", ["x"])
    F.main()
    assert sorted(pedidos) == [REL[1], REL[2]]                                        # o nativo nem pede link
    assert (tmp_path / "fila.txt").read_text().split() == [REL[0], REL[1]]

    monkeypatch.setattr(sys, "argv", ["x", "--itcampo-local"])
    F.main()
    assert (tmp_path / "fila.txt").read_text().split() == [REL[0], REL[1], REL[3]]


def test_link_fisico_do_sei_pdfs_no_sei_cache_nao_apaga_nem_sobrescreve(tmp_path, monkeypatch):
    """O script que roda na VM-2, executado aqui com HOME no tmp: liga `sei_pdfs/<rel>` em `sei_cache/<rel>` (mesmo
    inode); arquivo DIFERENTE já presente em `sei_cache` não é tocado nem devolvido; caminho com '..' nem sai daqui."""
    base = tmp_path / "arquivo_frio"
    pasta = base / "sei_pdfs" / "integra_1_2_2025"
    pasta.mkdir(parents=True)
    (pasta / "001.pdf").write_bytes(b"%PDF-a")
    (pasta / "002.pdf").write_bytes(b"%PDF-b")
    (base / "sei_cache" / "integra_1_2_2025").mkdir(parents=True)
    (base / "sei_cache" / "integra_1_2_2025" / "002.pdf").write_bytes(b"%PDF-outro")
    real = subprocess.run
    vistos = []

    def local(argv, **kw):                       # "ssh vm2 python3 -" → "python3 -" aqui
        vistos.append(kw["input"])
        return real([sys.executable, "-"], **kw, env={"HOME": str(tmp_path)})
    monkeypatch.setattr(F.subprocess, "run", local)
    ok = F.espelhar_no_sei_cache(["integra_1_2_2025/001.pdf", "integra_1_2_2025/002.pdf", "../x/001.pdf"])
    assert ok == {"integra_1_2_2025/001.pdf"}
    assert "../x" not in vistos[0]
    a, c = pasta / "001.pdf", base / "sei_cache" / "integra_1_2_2025" / "001.pdf"
    assert a.exists() and a.stat().st_ino == c.stat().st_ino
    assert (base / "sei_cache" / "integra_1_2_2025" / "002.pdf").read_bytes() == b"%PDF-outro"
    assert (pasta / "002.pdf").read_bytes() == b"%PDF-b"
