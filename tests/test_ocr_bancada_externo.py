"""26/11/2026: o leitor externo da bancada de OCR tira o texto da resposta do motor (markdown em qualquer nível; tabela
em HTML vira texto com as células) — se errasse calado, o motor seria medido pior (ou melhor) do que é."""
from tools import ocr_bancada_externo as X


def test_texto_de_resposta_aninhada_com_tabela_html():
    r = {"data": {"pages": [{"markdown": "Valor <b>R$ 1.234,56</b>"},
                            {"blocks": [{"markdown": "<table><tr><td>CNPJ</td><td>00.604.122/0001-97</td></tr></table>"}]}]},
         "outro": "ignorar"}
    t = X._texto_de(r)
    assert "R$ 1.234,56" in t and "00.604.122/0001-97" in t and "<" not in t and "ignorar" not in t


def test_multipart_leva_campos_e_arquivo(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG-fake")
    corpo, tipo = X._multipart([("api_key", "dummy")], png)
    assert tipo.startswith("multipart/form-data; boundary=") and b'name="api_key"' in corpo and b"PNG-fake" in corpo
