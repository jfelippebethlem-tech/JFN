#!/usr/bin/env python3
"""Páginas escaneadas guardadas em `sei_arquivo/<proc>/fotos/` → arquivo frio no it-campo (C:\\JFN-Arquivo\\sei_fotos).

Pedido do dono (15/11/2026): "pode mover as fotos antigas pro it campo também". Medido nesse dia: 250.003 JPG,
34,6 GB; numa amostra de 300, só 13% dos BYTES são fotografia (o resto é página de documento que o arquivador
preservou). Quem usa foto é `foto_medicao.reciclagem`, e ele DESCARTA o que `_triar_e_hashear` não hasheia.
Então só sai daqui o que esse mesmo critério já descarta: a fotografia de execução (prova) fica na VM-1 e o
detector enxerga exatamente o mesmo conjunto de antes. Nada é apagado: rsync confere e só então remove daqui.

Cada pasta tratada ganha `fotos_frio.json` (arquivo, bytes, sha256, destino) — é por ele que se acha a página.
Voltar uma pasta: rsync de `it-campo:/mnt/c/JFN-Arquivo/sei_fotos/<proc>/fotos/` para `fotos/`.

    nice -n 19 .venv/bin/python -m tools.sei_fotos_frio [--limite N] [--ensaio]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from compliance_agent import foto_medicao as FM  # noqa: E402
from PIL import Image  # noqa: E402

ARQUIVO = RAIZ / "data" / "sei_arquivo"
INDICE = RAIZ / "data" / "sei_arquivo_frio.jsonl"
DEST = "/mnt/c/JFN-Arquivo/sei_fotos"
REGISTRO = "fotos_frio.json"
_SLUG = __import__("re").compile(r"^\d+_\d+_\d{4}$")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def nao_informativas(pasta: Path) -> list[Path]:
    """As imagens de `fotos/` que a reciclagem descarta (sem hash informativo). Ilegível NÃO sai (na dúvida, fica)."""
    out = []
    for f in FM._fotos_do_processo(pasta):
        try:
            if not FM._triar_e_hashear(f):
                out.append(f)
        except (OSError, ValueError, Image.DecompressionBombError) as e:  # imagem que não abre fica onde está
            print(f"  {f}: não li ({type(e).__name__}) — fica", flush=True)
    return out


def pastas(idade_min_h: float) -> list[Path]:
    agora = time.time()
    res = []
    # Idade = da FOTO mais nova, não do manifest.json: a captura/conferência regrava o manifesto o tempo todo
    # (15/11: 780 de 841 pastas com manifesto <24 h) e o critério antigo quase nunca deixava a pasta passar.
    for d in ARQUIVO.iterdir():
        f = d / "fotos"
        if not (d.is_dir() and _SLUG.match(d.name) and f.is_dir() and (d / "manifest.json").exists()):
            continue
        mtimes = [x.stat().st_mtime for x in f.iterdir() if x.is_file()]
        if not mtimes or agora - max(mtimes) < idade_min_h * 3600:
            continue
        reg = d / REGISTRO
        if reg.exists() and reg.stat().st_mtime >= max(mtimes):
            continue   # já vista e nada novo em fotos/
        res.append((max(mtimes), d))
    return [d for _, d in sorted(res)]


def tratar(pasta: Path, ensaio: bool) -> int:
    sai = nao_informativas(pasta)
    if not sai:
        if not ensaio:   # marca a pasta como vista: a próxima rodada não re-hasheia as fotografias
            reg = pasta / REGISTRO
            r = json.loads(reg.read_text(encoding="utf-8")) if reg.exists() else {"itens": []}
            r["em"] = time.strftime("%Y-%m-%d %H:%M:%S")
            reg.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    itens = [{"arquivo": f"fotos/{f.name}", "bytes": f.stat().st_size, "sha256": _sha256(f)} for f in sai]
    if ensaio:
        print(f"  {pasta.name}: {len(sai)} página(s), {sum(i['bytes'] for i in itens)/1e6:.1f} MB (ensaio)")
        return sum(i["bytes"] for i in itens)
    with tempfile.NamedTemporaryFile("w", delete=False) as t:
        t.write("".join(f"{pasta.name}/{i['arquivo']}\n" for i in itens))
    r = subprocess.run(["rsync", "-a", "--remove-source-files", "--rsync-path=wsl -d Ubuntu -e rsync",
                        f"--files-from={t.name}", str(ARQUIVO) + "/", f"it-campo:{DEST}/"],
                       capture_output=True, text=True, timeout=3600)
    Path(t.name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"  {pasta.name}: rsync rc={r.returncode} {r.stderr[-200:]}", flush=True)
        return 0
    reg = pasta / REGISTRO
    antigo = json.loads(reg.read_text(encoding="utf-8")) if reg.exists() else {"itens": []}
    antigo["itens"] += [{**i, "destino": f"it-campo:{DEST}/{pasta.name}/{i['arquivo']}"} for i in itens]
    antigo["em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    antigo["criterio"] = "foto_medicao._triar_e_hashear sem hash (página de documento; a reciclagem já descartava)"
    reg.write_text(json.dumps(antigo, ensure_ascii=False, indent=1), encoding="utf-8")
    with INDICE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"pasta": f"sei_arquivo/{pasta.name}/fotos", "n": len(itens),
                            "bytes": sum(i["bytes"] for i in itens), "destino": f"it-campo:{DEST}/{pasta.name}",
                            "em": antigo["em"], "rc": 0}, ensure_ascii=False) + "\n")
    return sum(i["bytes"] for i in itens)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--idade-min-h", type=float, default=2.0)
    ap.add_argument("--ensaio", action="store_true")
    a = ap.parse_args(argv)
    lista = pastas(a.idade_min_h)
    if a.limite:
        lista = lista[:a.limite]
    total = 0
    for i, p in enumerate(lista, 1):
        total += tratar(p, a.ensaio)
        if i % 50 == 0:
            print(f"{time.strftime('%F %T')} {i}/{len(lista)} pastas · {total/1e9:.2f} GB", flush=True)
    print(json.dumps({"pastas": len(lista), "gb": round(total / 1e9, 2), "ensaio": a.ensaio}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
