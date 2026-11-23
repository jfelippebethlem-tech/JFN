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
    monkeypatch.setattr(F, "pdfs_no_hd", lambda: set())
    pedidos: list[str] = []
    monkeypatch.setattr(F, "espelhar_no_sei_cache", lambda rs: pedidos.extend(rs) or {REL[1]})   # REL[2]: link falhou

    monkeypatch.setattr(sys, "argv", ["x", "--medir"])
    assert F.main() == 0
    assert not (tmp_path / "fila.txt").exists() and pedidos == []                     # medir não grava nem liga
    assert json.loads(capsys.readouterr().out)["por_origem"] == {"sei_cache": 1, "sei_pdfs": 2, "itcampo_local": 0, "hd": 0}

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



def test_fila_enxerga_o_hd_pelo_indice_e_prioriza_quem_libera_o_processo_inteiro(tmp_path, monkeypatch, capsys):
    """23/11/2026 (Fase 5): os PDFs de vm2 sei_pdfs foram para o HD do it-campo (índice conferido por md5); a fila
    os enxerga pelo índice. Processo com captura completa, todo documento com texto e ≤ 5 documentos de OCR é
    'liberador': relida a sua parte de OCR, ele inteiro pode ir à leitura integral — vai primeiro."""
    base = tmp_path / "sei_arquivo"
    grande, pequeno = "333_444_2024", "555_666_2024"
    for tag, n in ((grande, 8), (pequeno, 2)):
        (base / tag).mkdir(parents=True)
        docs = [{"i": i, "tipo": "despacho", "chars": 500, "ocr": True, "texto": f"texto/{i:03d}.txt"} for i in range(n)]
        (base / tag / "manifest.json").write_text(json.dumps({"captura_completa": True, "docs": docs}))
    rels = [f"integra_{grande}/{i:03d}.pdf" for i in range(8)] + [f"integra_{pequeno}/{i:03d}.pdf" for i in range(2)]
    indice = tmp_path / "hd_migracao"
    indice.mkdir()
    (indice / "indice_sei_pdfs.jsonl").write_text("".join(json.dumps({"origem_rel": r, "conferido": True}) + "\n"
                                                         for r in rels))
    monkeypatch.setattr(F, "HD_MIGRACAO", indice)
    assert F.pdfs_no_hd() == set(rels)
    monkeypatch.setattr(F, "ARQUIVO", base)
    monkeypatch.setattr(F, "SAIDA", tmp_path / "fila.txt")
    monkeypatch.setattr(F, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(F, "tags_risco_alto", lambda: set())
    monkeypatch.setattr(R, "reservados_pela_reserva", lambda: set())
    monkeypatch.setattr(F, "pdfs_no_frio", lambda: (set(), set()))
    monkeypatch.setattr(F, "pdfs_no_itcampo", lambda: set())
    monkeypatch.setattr(F, "espelhar_no_sei_cache", lambda rs: set())
    monkeypatch.setattr(sys, "argv", ["x", "--itcampo-local"])
    F.main()
    fila = (tmp_path / "fila.txt").read_text().split()
    assert len(fila) == 10 and fila[:2] == [f"integra_{pequeno}/000.pdf", f"integra_{pequeno}/001.pdf"]
    assert json.loads(capsys.readouterr().out)["por_origem"]["hd"] == 10
