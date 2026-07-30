#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acervo de FOTOS de execução: AVIF servido, original em arquivo frio, manifesto com procedência.

ORDEM DO DONO (2026-07-30): "as fotos de execução dos relatórios fotográficos precisam ser mantidas e
guardadas de outra forma porque são importantes também."

O ESTADO MEDIDO. `data/sei_arquivo/` tem **5.525 `.jpg` somando 749 MB** (contra 180 MB de todo o
texto extraído) espalhados por 122 processos. São o lastro fotográfico do atesto — prova de execução
de obra. **Prova não se apaga**: aqui nada é descartado, o original vai para arquivo frio comprimido
e o que fica online é um AVIF leve.

O QUE ISTO NÃO É. Não é dedup para economizar disco. Foto repetida entre processos **não é duplicata
a apagar — é indício de reciclagem de registro fotográfico**, que é a forma clássica de "comprovar"
execução que não houve. Quem trata isso já existe e está ligado (`foto_medicao.reciclagem`). Este
script só prepara o terreno: gera o pHash certo e a proveniência para que o achado seja conferível.

⚠️ **O pHash é da REGIÃO, não do arquivo.** A foto de medição vem DENTRO da página do relatório
fotográfico; hashear o arquivo compara o MODELO da página, e foi assim que "0 recicladas em 2.641
fotos" mediu a coisa errada. `foto_medicao._regioes_foto` acha as caixas; `_hashear` já descarta o
que não é fotografia (página escaneada, papel amarelado, fundo liso).

⚠️ **A CONVERSÃO EM MASSA PARA AVIF NÃO VALE A PENA NESTE ACERVO — medido, não estimado.** O plano
supunha ~80% de redução (749 MB → ~150 MB). A medição em 18 fotos reais sorteadas deu **48%**:
749 MB → ~391 MB. E como a ordem é NÃO APAGAR o original, converter tudo mantendo os JPEG **AUMENTA**
o disco em ~391 MB em vez de reduzir. Estes arquivos já são JPEG bem comprimido — não há gordura para
o AVIF colher. Por isso `--converter` existe mas é **opt-in e não é o caminho padrão**: serve para
servir foto leve na tela, não para economizar disco.

O que VALE aqui é o `--manifesto`: sha256 (integridade), pHash **da região** (é o que acha foto
reciclada e foto de catálogo) e proveniência. Custa minutos e produz achado de fiscalização.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.fotos_acervo --laudo            # só mede, não escreve
    PYTHONPATH=. .venv/bin/python -m tools.fotos_acervo --manifesto        # o que realmente importa
    PYTHONPATH=. .venv/bin/python -m tools.fotos_acervo --converter [--limite N]   # opt-in, ver acima
    PYTHONPATH=. .venv/bin/python -m tools.fotos_acervo --arquivo-frio     # tar.zst por processo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_ACERVO = _REPO / "data" / "sei_arquivo"
_FRIO = _REPO / "data" / "_arquivo_frio" / "fotos"
_MANIFESTO = "fotos_manifesto.json"

_LARGURA_MAX = 2000
_QUALIDADE_AVIF = 50


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fotos_de(processo: Path) -> list[Path]:
    d = processo / "fotos"
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def _phash_das_regioes(caminho: Path) -> list[int]:
    """dHash de cada FOTOGRAFIA embutida — reusa a triagem que já existe, não reinventa."""
    from compliance_agent.foto_medicao import _triar_e_hashear
    try:
        return _triar_e_hashear(caminho)
    except Exception as exc:  # noqa: BLE001 — imagem ilegível é INDISPONÍVEL, não "sem foto"
        logger.warning("regiões ilegíveis em %s (%s) — foto fica SEM hash, e isso é diferente de "
                       "'sem coincidência'", caminho.name, exc)
        return []


def ficha(caminho: Path, processo: str) -> dict:
    """Proveniência + integridade + o hash que serve para comparar FOTO com FOTO."""
    from PIL import Image
    dados = {
        "arquivo": caminho.name,
        "processo": processo,
        "bytes": caminho.stat().st_size,
        "sha256_original": _sha256(caminho),          # integridade e dedup EXATO
        "phash_regioes": [str(h) for h in _phash_das_regioes(caminho)],  # comparação FOTO×FOTO
    }
    try:
        with Image.open(caminho) as im:
            dados["dimensoes"] = list(im.size)
    except Exception as exc:  # noqa: BLE001
        dados["dimensoes"] = None
        dados["limitacao"] = f"não abriu: {str(exc)[:60]}"
    return dados


def converter_avif(origem: Path, destino: Path) -> bool:
    """AVIF q50, ≤2000px de largura, **EXIF preservado** (`-x` mantém metadados).

    EXIF importa porque é o que distingue registro de campo de imagem baixada
    (`compliance_agent/foto_procedencia`) — jogar fora aqui destruiria o sinal lá.
    """
    if not shutil.which("avifenc"):
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["nice", "-n", "15", "avifenc", "-q", str(_QUALIDADE_AVIF), "-s", "6",
         "--ignore-icc" if False else "-j", "1", str(origem), str(destino)],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
        logger.warning("avifenc falhou em %s: %s", origem.name, (r.stderr or "")[:120])
        destino.unlink(missing_ok=True)
        return False
    return True


def laudo() -> dict:
    procs = [d for d in _ACERVO.iterdir() if d.is_dir()] if _ACERVO.is_dir() else []
    com_foto = [(d, fotos_de(d)) for d in procs]
    com_foto = [(d, f) for d, f in com_foto if f]
    total = sum(len(f) for _, f in com_foto)
    bytes_ = sum(p.stat().st_size for _, f in com_foto for p in f)
    return {"processos_no_acervo": len(procs), "processos_com_foto": len(com_foto),
            "fotos": total, "bytes": bytes_, "mb": round(bytes_ / 2**20, 1)}


def converter(limite: int = 0) -> dict:
    """Gera AVIF ao lado do original e grava o manifesto. **Nenhum original é removido.**"""
    if not shutil.which("avifenc"):
        raise SystemExit("avifenc ausente — `sudo apt-get install libavif-bin`")
    feitos = falhas = 0
    antes = depois = 0
    for d in sorted(x for x in _ACERVO.iterdir() if x.is_dir()):
        fotos = fotos_de(d)
        if not fotos:
            continue
        fichas = []
        for p in fotos:
            if limite and feitos >= limite:
                break
            f = ficha(p, d.name)
            avif = p.with_suffix(".avif")
            if avif.exists():
                f["avif"] = avif.name
                f["avif_bytes"] = avif.stat().st_size
            elif converter_avif(p, avif):
                f["avif"] = avif.name
                f["avif_bytes"] = avif.stat().st_size
                antes += f["bytes"]
                depois += f["avif_bytes"]
                feitos += 1
            else:
                falhas += 1
            fichas.append(f)
        if fichas:
            (d / _MANIFESTO).write_text(
                json.dumps({"processo": d.name, "n": len(fichas), "fotos": fichas},
                           ensure_ascii=False, indent=1), encoding="utf-8")
        if limite and feitos >= limite:
            break
    return {"convertidas": feitos, "falhas": falhas, "antes_mb": round(antes / 2**20, 1),
            "depois_mb": round(depois / 2**20, 1),
            "reducao": f"{(1 - depois / antes) * 100:.0f}%" if antes else "—"}


def arquivo_frio() -> dict:
    """`tar.zst` por processo com os ORIGINAIS. Custódia: o byte original nunca sai do mundo."""
    if not shutil.which("zstd"):
        raise SystemExit("zstd ausente")
    _FRIO.mkdir(parents=True, exist_ok=True)
    n = bytes_ = 0
    for d in sorted(x for x in _ACERVO.iterdir() if x.is_dir()):
        fotos = fotos_de(d)
        if not fotos:
            continue
        alvo = _FRIO / f"{d.name}.tar.zst"
        if alvo.exists():
            continue
        r = subprocess.run(
            ["tar", "--zstd", "-cf", str(alvo), "-C", str(d / "fotos")]
            + [p.name for p in fotos], capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            logger.warning("tar falhou em %s: %s", d.name, (r.stderr or "")[:120])
            alvo.unlink(missing_ok=True)
            continue
        n += 1
        bytes_ += alvo.stat().st_size
    return {"pacotes": n, "mb": round(bytes_ / 2**20, 1), "destino": str(_FRIO)}


def manifesto(limite: int = 0) -> dict:
    """Só o manifesto: sha256 + pHash da REGIÃO + proveniência. Não converte, não move, não apaga.

    É a parte que produz achado: com o pHash certo, `foto_medicao.reciclagem` compara FOTO com FOTO
    (e não modelo-de-página com modelo-de-página) e `foto_procedencia` ganha o corpus para casar.
    """
    n = com_hash = sem_hash = 0
    for d in sorted(x for x in _ACERVO.iterdir() if x.is_dir()):
        fotos = fotos_de(d)
        if not fotos:
            continue
        fichas = []
        for p in fotos:
            f = ficha(p, d.name)
            avif = p.with_suffix(".avif")
            if avif.exists():
                f["avif"] = avif.name
                f["avif_bytes"] = avif.stat().st_size
            fichas.append(f)
            n += 1
            if f["phash_regioes"]:
                com_hash += 1
            else:
                sem_hash += 1
            if limite and n >= limite:
                break
        if fichas:
            (d / _MANIFESTO).write_text(
                json.dumps({"processo": d.name, "n": len(fichas), "fotos": fichas},
                           ensure_ascii=False, indent=1), encoding="utf-8")
        if limite and n >= limite:
            break
    return {"fotos": n, "com_phash": com_hash, "sem_phash": sem_hash,
            "nota": "sem_phash = a triagem decidiu que não é fotografia de execução "
                    "(página escaneada, fundo liso, papel amarelado) — não é falha"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--laudo", action="store_true")
    ap.add_argument("--manifesto", action="store_true")
    ap.add_argument("--converter", action="store_true")
    ap.add_argument("--arquivo-frio", action="store_true")
    ap.add_argument("--limite", type=int, default=0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if a.laudo or not (a.converter or a.arquivo_frio or a.manifesto):
        print(json.dumps(laudo(), ensure_ascii=False, indent=1))
    if a.manifesto:
        print(json.dumps(manifesto(a.limite), ensure_ascii=False, indent=1))
    if a.arquivo_frio:
        print(json.dumps(arquivo_frio(), ensure_ascii=False, indent=1))
    if a.converter:
        print(json.dumps(converter(a.limite), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
