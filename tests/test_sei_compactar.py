"""tools/sei_compactar: página escaneada → .webp local + original no it-campo conferido por sha256.

Controles negativos: fotografia de execução não é tocada; cópia que não confere sha256 (ou rsync que falha) não
remove nada; ensaio não grava nada. E a reciclagem dá o mesmo resultado antes e depois.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil

import pytest
from PIL import Image, ImageDraw

from compliance_agent import foto_medicao as FM
from tools import sei_compactar as C
from tools import sei_fotos_frio as F


def _pagina(p):
    """Página de documento: papel branco, linhas de 'texto' preto."""
    im = Image.new("RGB", (1700, 2300), "white")
    d = ImageDraw.Draw(im)
    rnd = random.Random(1)
    for y in range(120, 2200, 34):
        x = 100
        while x < 1550:
            w = rnd.randint(20, 90)
            d.rectangle((x, y, x + w, y + 16), fill=(20, 20, 20))
            x += w + rnd.randint(10, 25)
    im.save(p, "JPEG", quality=92)


def _fotografia(p):
    """Fotografia de campo: cor e meio-tom (gradiente + ruído), sem fundo de papel."""
    rnd = random.Random(2)
    im = Image.new("RGB", (900, 700))
    px = im.load()
    for y in range(700):
        for x in range(900):
            px[x, y] = ((x * 255 // 900 + rnd.randint(-30, 30)) % 256, (y * 255 // 700) % 256,
                        (90 + rnd.randint(-40, 40)) % 256)
    im.save(p, "JPEG", quality=90)


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def acervo(tmp_path, monkeypatch):
    arq = tmp_path / "sei_arquivo"
    proc = arq / "070002_000001_2024"
    (proc / "fotos").mkdir(parents=True)
    (proc / "texto").mkdir()
    (proc / "texto" / "001_x.txt").write_text("teor", encoding="utf-8")
    (proc / "manifest.json").write_text("{}", encoding="utf-8")
    _pagina(proc / "fotos" / "001_p01.jpg")
    _fotografia(proc / "fotos" / "002_p01.jpg")
    remoto = tmp_path / "itcampo"
    monkeypatch.setattr(C, "ARQUIVO", arq)
    monkeypatch.setattr(C, "INDICE", tmp_path / "indice.jsonl")

    def enviar(pasta, nomes):
        (remoto / pasta.name).mkdir(parents=True, exist_ok=True)
        for n in nomes:
            shutil.copy2(pasta / "fotos" / n, remoto / pasta.name / n)
        return True

    def sha_remoto(pasta, nomes):
        return {n: _sha(remoto / pasta.name / n) for n in nomes if (remoto / pasta.name / n).exists()}

    monkeypatch.setattr(C, "enviar", enviar)
    monkeypatch.setattr(C, "sha_remoto", sha_remoto)
    return proc, remoto


def test_criterio_da_amostra(acervo):
    proc, _ = acervo
    assert FM._triar_e_hashear(proc / "fotos" / "001_p01.jpg") == []      # página: a reciclagem descarta
    assert FM._triar_e_hashear(proc / "fotos" / "002_p01.jpg")            # fotografia: tem hash


def test_pagina_vira_webp_original_conferido_e_fotografia_intocada(acervo):
    proc, remoto = acervo
    foto = proc / "fotos" / "002_p01.jpg"
    sha_foto, sha_pag = _sha(foto), _sha(proc / "fotos" / "001_p01.jpg")
    texto_antes = (proc / "texto" / "001_x.txt").read_bytes()
    rec_antes = FM.reciclagem([proc])
    r = C.tratar(proc, ensaio=False)
    assert r["paginas"] == 1 and r["fotografias"] == 1 and r["liberado"] > 0
    assert not (proc / "fotos" / "001_p01.jpg").exists()
    assert (proc / "fotos" / "001_p01.webp").exists()
    assert _sha(remoto / proc.name / "001_p01.jpg") == sha_pag              # original íntegro do lado de lá
    assert _sha(foto) == sha_foto and not (proc / "fotos" / "002_p01.webp").exists()   # prova intocada
    assert not list((proc / "fotos").glob(".*.tmp"))
    reg = json.loads((proc / "compactado.json").read_text(encoding="utf-8"))
    it = reg["itens"][0]
    assert it["sha256"] == sha_pag and it["arquivo"] == "fotos/001_p01.jpg" and it["webp"] == "fotos/001_p01.webp"
    assert it["bytes_depois"] < it["bytes_antes"] and it["destino"].endswith(f"{proc.name}/001_p01.jpg")
    rec_depois = FM.reciclagem([proc])
    assert {k: rec_depois[k] for k in ("grau", "n_fotos", "n_grupos")} == \
        {k: rec_antes[k] for k in ("grau", "n_fotos", "n_grupos")}
    assert (proc / "texto" / "001_x.txt").read_bytes() == texto_antes
    assert FM.foto_local(proc, "fotos/001_p01.jpg") == proc / "fotos" / "001_p01.webp"
    assert FM.foto_local(proc, "fotos/002_p01.jpg") == foto
    # idempotente: segunda rodada não acha nada novo e não re-hasheia a fotografia
    assert C.tratar(proc, ensaio=False)["paginas"] == 0


def test_sha_que_nao_confere_nao_remove_nada(acervo, monkeypatch):
    proc, _ = acervo
    monkeypatch.setattr(C, "sha_remoto", lambda pasta, nomes: {n: "0" * 64 for n in nomes})
    antes = _sha(proc / "fotos" / "001_p01.jpg")
    r = C.tratar(proc, ensaio=False)
    assert r["liberado"] == 0
    assert _sha(proc / "fotos" / "001_p01.jpg") == antes
    assert not (proc / "fotos" / "001_p01.webp").exists() and not list((proc / "fotos").glob(".*.tmp"))
    assert not json.loads((proc / "compactado.json").read_text(encoding="utf-8")).get("itens")


def test_rsync_que_falha_nao_remove_nada(acervo, monkeypatch):
    proc, _ = acervo
    monkeypatch.setattr(C, "enviar", lambda pasta, nomes: False)
    C.tratar(proc, ensaio=False)
    assert (proc / "fotos" / "001_p01.jpg").exists() and not (proc / "fotos" / "001_p01.webp").exists()
    assert not list((proc / "fotos").glob(".*.tmp"))


def test_ensaio_nao_grava(acervo):
    proc, remoto = acervo
    r = C.tratar(proc, ensaio=True)
    assert r["paginas"] == 1 and r["depois"] < r["antes"]
    assert sorted(x.name for x in (proc / "fotos").iterdir()) == ["001_p01.jpg", "002_p01.jpg"]
    assert not (proc / "compactado.json").exists() and not remoto.exists()


def test_compacta_que_ganharia_hash_nao_troca(acervo, monkeypatch):
    proc, _ = acervo
    orig = FM._triar_e_hashear
    monkeypatch.setattr(C.FM, "_triar_e_hashear", lambda p: [1] if str(p).endswith(".tmp") else orig(p))
    C.tratar(proc, ensaio=False)
    assert (proc / "fotos" / "001_p01.jpg").exists() and not (proc / "fotos" / "001_p01.webp").exists()


def test_fotos_frio_nao_leva_a_versao_compacta(acervo):
    proc, _ = acervo
    C.tratar(proc, ensaio=False)
    assert (proc / "fotos" / "001_p01.webp") not in F.nao_informativas(proc)


def test_fotos_frio_cai_para_o_itcampo(monkeypatch):
    monkeypatch.setattr(F, "livre_no_gb", lambda no=F.NO, remoto=None, fs="/": 14 if no == F.NO else 218)
    assert F.escolher_destino()[0] == "it-campo"
    monkeypatch.setattr(F, "livre_no_gb", lambda no=F.NO, remoto=None, fs="/": 50)
    assert F.escolher_destino()[0] == F.NO
    monkeypatch.setattr(F, "livre_no_gb", lambda no=F.NO, remoto=None, fs="/": None)
    assert F.escolher_destino() is None


def test_arquivador_e_reparo_enxergam_o_webp(tmp_path):
    from tools import sei_arquivar
    (tmp_path / "fotos").mkdir()
    for n in ("003_p01.jpg", "003_p02.webp", "003_p03.png", "004_p01.webp"):
        (tmp_path / "fotos" / n).write_bytes(b"x")
    assert sorted(f.name for f in sei_arquivar._fotos_do_doc(tmp_path, 3)) == ["003_p01.jpg", "003_p02.webp"]


def test_falha_no_meio_do_lote_nao_deixa_tmp_nem_remove(acervo, monkeypatch):
    """20/11/2026, rodada real: decode do retorno do Windows derrubou o lote e deixou 61 .tmp órfãos."""
    proc, _ = acervo

    def explode(pasta, nomes):
        raise UnicodeDecodeError("utf-8", b"\xe3", 0, 1, "invalid continuation byte")

    monkeypatch.setattr(C, "sha_remoto", explode)
    with pytest.raises(UnicodeDecodeError):
        C.tratar(proc, ensaio=False)
    assert (proc / "fotos" / "001_p01.jpg").exists() and not (proc / "fotos" / "001_p01.webp").exists()
    assert not list((proc / "fotos").glob(".*.tmp"))


def test_orfao_de_rodada_interrompida_e_limpo(acervo):
    proc, _ = acervo
    (proc / "fotos" / ".001_p01.webp.tmp").write_bytes(b"meio")
    C.tratar(proc, ensaio=True)
    assert not list((proc / "fotos").glob(".*.tmp"))


def test_remoto_com_saida_latin1_nao_explode(monkeypatch):
    import subprocess
    r = subprocess.run(["printf", "n\\343o"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert "o" in r.stdout
    chamadas = []
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    monkeypatch.setattr(C.subprocess, "run",
                        lambda *a, **k: chamadas.append(1) or (_ for _ in ()).throw(subprocess.TimeoutExpired("ssh", 1)))
    assert C._remoto("true").returncode == 255 and len(chamadas) == 3     # repete (idempotente) antes de desistir


def test_sha_remoto_pergunta_de_novo_pelo_que_faltou(monkeypatch):
    """20/11/2026, rodada real: o sha256sum do WSL voltou vazio com os 26 originais íntegros lá."""
    import subprocess
    from pathlib import Path
    respostas = iter(["", "a" * 64 + "  x.jpg\n", "b" * 64 + "  y.jpg\n"])
    pedidos = []
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    monkeypatch.setattr(C, "_remoto", lambda script, timeout=0: pedidos.append(script) or
                        subprocess.CompletedProcess([], 0, next(respostas), ""))
    assert C.sha_remoto(Path("p"), ["x.jpg", "y.jpg"]) == {"x.jpg": "a" * 64, "y.jpg": "b" * 64}
    assert "y.jpg" in pedidos[2] and "x.jpg" not in pedidos[2]
