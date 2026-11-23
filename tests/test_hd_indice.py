# -*- coding: utf-8 -*-
"""Índice do HD externo (dono, 23/11/2026: "deixe todo o hd super organizado também. e índice de tudo que moveu e
onde está"). Só sai da VM-2 o que foi CONFERIDO por hash e NÃO está na fila do OCR (OCR anda sem o it-campo)."""
import json

from tools import hd_indice as H


def test_indice_marca_conferido_e_so_libera_o_que_nao_espera_ocr(tmp_path):
    lista = [{"Path": "integra_1/001.pdf", "Size": 10, "Hashes": {"md5": "aa"}},
             {"Path": "integra_1/002.pdf", "Size": 20, "Hashes": {"md5": "bb"}},
             {"Path": "integra_2/001.pdf", "Size": 30, "Hashes": {"md5": "cc"}}]
    check = "= integra_1/001.pdf\n= integra_2/001.pdf\n* integra_1/002.pdf\n"     # 002 diferente
    fila_ocr = {"integra_2/001.pdf"}
    linhas = H.montar("sei_pdfs", "sei/pdfs_escaneados", lista, check, fila_ocr, em="2026-11-23 12:00")
    por = {ln["origem_rel"]: ln for ln in linhas}
    assert por["integra_1/001.pdf"] == {
        "caminho_hd": "D:/JFN-Frio/sei/pdfs_escaneados/integra_1/001.pdf", "origem": "vm2:~/arquivo_frio/sei_pdfs",
        "origem_rel": "integra_1/001.pdf", "bytes": 10, "md5": "aa", "conferido": True, "pendente_ocr": False,
        "sai_da_vm2": True, "em": "2026-11-23 12:00"}
    assert por["integra_1/002.pdf"]["conferido"] is False and por["integra_1/002.pdf"]["sai_da_vm2"] is False
    assert por["integra_2/001.pdf"]["pendente_ocr"] is True and por["integra_2/001.pdf"]["sai_da_vm2"] is False


def test_leiame_resume_o_que_tem_e_as_regras():
    linhas = [{"caminho_hd": "D:/JFN-Frio/sei/pdfs_escaneados/a.pdf", "bytes": 2_000_000_000, "conferido": True,
               "sai_da_vm2": True, "origem": "vm2:~/arquivo_frio/sei_pdfs"}]
    t = H.leiame(linhas, em="2026-11-23 12:00")
    assert "sei/pdfs_escaneados" in t and "2,00 GB" in t and "INDISPONÍVEL" in t and "_indice/indice.jsonl" in t
    json.dumps(linhas)
