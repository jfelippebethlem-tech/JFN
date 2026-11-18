"""Acentos do OCR por IA (it-campo): UTF-8 com recuo para Latin-1 só no byte inválido — 18/11/2026."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "surya_utf8", Path(__file__).resolve().parent.parent / "deploy/itcampo/ocr_gpu/surya_utf8.py")
U = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(U)


def test_byte_latin1_solto_vira_o_caractere_e_utf8_valido_passa_igual():
    # 'Liquida' + 0xE7 (ç Latin-1) + 0xE3 (ã Latin-1) + 'o'  — como o modelo gerou
    assert U.utf8_com_recuo(b"Liquida\xe7\xe3o") == "Liquidação"
    assert U.utf8_com_recuo("Março até CERTIDÃO".encode("utf-8")) == "Março até CERTIDÃO"
    assert U.utf8_com_recuo(b"Mar\xe7o at\xc3\xa9") == "Março até"        # mistura dos dois


def test_mapa_de_bytes_do_bpe():
    m = U._bytes_to_unicode()
    assert len(m) == 256 and m[0xE7] == "ç" and m[0x20] == "Ġ" and U._DEC["ç"] == 0xE7


def test_caractere_fora_do_mapa_nao_vira_interrogacao(monkeypatch):
    class TK:
        added_tokens_decoder = {}
        def convert_ids_to_tokens(self, ids):
            return ["N.", "º", " ", "1458"]
    monkeypatch.setattr(U, "_TK", TK())
    assert U.texto_dos_ids([1, 2, 3, 4]) == "N.º 1458"
