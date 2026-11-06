"""tools.fotos_reciclagem_acervo — reciclagem de foto no ACERVO inteiro (antes só rodava dentro de um dossiê)."""
import json
import sqlite3

from PIL import Image, ImageDraw

import tools.fotos_reciclagem_acervo as T


def _foto(path, cor=(120, 120, 120), n=6, tamanho=(320, 240)):
    img = Image.new("RGB", tamanho, cor)
    d = ImageDraw.Draw(img)
    larg, alt = tamanho
    for i in range(n):
        x, y = (i * larg) // n, (i * alt) // n
        tom = 0 if i % 2 else 255
        d.rectangle([x, y, x + larg // 3, y + alt // 3], fill=(tom, 255 - tom, (40 * i) % 256))
    img.save(path)


def test_mesma_foto_em_orgaos_diferentes_vem_primeiro_com_objeto(tmp_path, monkeypatch):
    arq = tmp_path / "sei_arquivo"
    for slug in ("080001_000001_2025", "130100_000002_2025", "130100_000003_2025"):
        (arq / slug / "fotos").mkdir(parents=True)
    # captura ANTIGA do mesmo processo em _substituido/ — não é outro processo, não pode virar reciclagem
    (arq / "_substituido" / "130100_000003_2025__20260815T021725" / "fotos").mkdir(parents=True)
    _foto(arq / "_substituido" / "130100_000003_2025__20260815T021725" / "fotos" / "c.jpg", cor=(5, 200, 5), n=2)
    _foto(arq / "080001_000001_2025" / "fotos" / "a.jpg")
    _foto(arq / "130100_000002_2025" / "fotos" / "b.jpg")                     # mesma foto, outro órgão
    _foto(arq / "130100_000003_2025" / "fotos" / "c.jpg", cor=(5, 200, 5), n=2)  # foto diferente
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sei_arvore (numero_sei TEXT, objeto TEXT, nivel_risco TEXT)")
    con.execute("INSERT INTO sei_arvore VALUES ('SEI-080001/000001/2025', 'reforma de escola', 'medio')")
    con.commit(); con.close()
    monkeypatch.setattr(T, "ARQUIVO", arq)
    monkeypatch.setattr(T, "DB", db)
    monkeypatch.setattr(T, "SAIDA", tmp_path / "saida.json")
    r = T.rodar()
    assert r["grau"] == "vermelho" and r["n_grupos"] == 1 and r["processos_examinados"] == 3
    g = r["grupos"][0]
    assert g["n_ugs"] == 2
    nums = {p["numero"]: p for p in g["processos"]}
    assert nums["SEI-080001/000001/2025"]["objeto"] == "reforma de escola"
    assert "SEI-130100/000002/2025" in nums
    assert json.loads((tmp_path / "saida.json").read_text())["n_grupos"] == 1


def test_sem_fotos_nao_acusa(tmp_path, monkeypatch):
    (tmp_path / "sei_arquivo" / "x_1_2025" / "fotos").mkdir(parents=True)
    monkeypatch.setattr(T, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(T, "DB", tmp_path / "nada.db")
    monkeypatch.setattr(T, "SAIDA", tmp_path / "s.json")
    r = T.rodar()
    assert r["grau"] == "nao_aplicavel" and r["processos_examinados"] == 0
