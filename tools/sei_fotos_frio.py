#!/usr/bin/env python3
"""Páginas escaneadas guardadas em `sei_arquivo/<proc>/fotos/` → arquivo frio na VM-2 (~/arquivo_frio/sei_fotos).
16/11/2026: dono "não vamos mais usar o it campo" — o destino era o it-campo (C:\\JFN-Arquivo\\sei_fotos); o que já foi
para lá continua lá (o `destino` de cada item no `fotos_frio.json` diz onde está).

Pedido do dono (15/11/2026): "pode mover as fotos antigas pro it campo também". Medido nesse dia: 250.003 JPG,
34,6 GB; numa amostra de 300, só 13% dos BYTES são fotografia (o resto é página de documento que o arquivador
preservou). Quem usa foto é `foto_medicao.reciclagem`, e ele DESCARTA o que `_triar_e_hashear` não hasheia.
Então só sai daqui o que esse mesmo critério já descarta: a fotografia de execução (prova) fica na VM-1 e o
detector enxerga exatamente o mesmo conjunto de antes. Nada é apagado: rsync confere e só então remove daqui.

Cada pasta tratada ganha `fotos_frio.json` (arquivo, bytes, sha256, destino) — é por ele que se acha a página.
Voltar uma pasta: rsync do `destino` registrado (`vm2-ts:~/arquivo_frio/sei_fotos/<proc>/fotos/` ou, antes de 16/11, o it-campo) para `fotos/`.

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
NO = "vm2-ts"
DEST = "/home/ubuntu/arquivo_frio/sei_fotos"
# 20/11/2026: VM-2 em 93% ("vm2-ts com 14 GB — parei") e o dono liberou o it-campo de novo ("uso o it campo pro que
# precisar"). Sem espaço na VM-2 → cai para o it-campo (C:\JFN-Arquivo\sei_fotos, onde já ficaram as de 15-16/11).
RESERVA = ("it-campo", "/mnt/c/JFN-Arquivo/sei_fotos", "wsl -d Ubuntu -e rsync", "wsl -d Ubuntu -e bash -s", "/mnt/c")
REGISTRO = "fotos_frio.json"
_SLUG = __import__("re").compile(r"^\d+_\d+_\d{4}$")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _compactas(pasta: Path) -> set[str]:
    try:
        r = json.loads((pasta / "compactado.json").read_text(encoding="utf-8"))
        return {Path(i["webp"]).name for i in r.get("itens") or []}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def nao_informativas(pasta: Path) -> list[Path]:
    """As imagens de `fotos/` que a reciclagem descarta (sem hash informativo). Ilegível NÃO sai (na dúvida, fica)."""
    out = []
    compactas = _compactas(pasta)
    for f in FM._fotos_do_processo(pasta):
        if f.name in compactas:   # versão compacta que sei_compactar deixou PARA ficar aqui (original já no it-campo)
            continue
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


def tratar(pasta: Path, ensaio: bool, alvo: tuple | None = None) -> int:
    no, dest, rsync_path = (alvo or (NO, DEST, None))[:3]
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
    r = subprocess.run(["rsync", "-a", "--remove-source-files", *([f"--rsync-path={rsync_path}"] if rsync_path else []),
                        f"--files-from={t.name}", str(ARQUIVO) + "/", f"{no}:{dest}/"],
                       capture_output=True, text=True, timeout=3600)
    Path(t.name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"  {pasta.name}: rsync rc={r.returncode} {r.stderr[-200:]}", flush=True)
        return 0
    reg = pasta / REGISTRO
    antigo = json.loads(reg.read_text(encoding="utf-8")) if reg.exists() else {"itens": []}
    antigo["itens"] += [{**i, "destino": f"{no}:{dest}/{pasta.name}/{i['arquivo']}"} for i in itens]
    antigo["em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    antigo["criterio"] = "foto_medicao._triar_e_hashear sem hash (página de documento; a reciclagem já descartava)"
    reg.write_text(json.dumps(antigo, ensure_ascii=False, indent=1), encoding="utf-8")
    with INDICE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"pasta": f"sei_arquivo/{pasta.name}/fotos", "n": len(itens),
                            "bytes": sum(i["bytes"] for i in itens), "destino": f"{no}:{dest}/{pasta.name}",
                            "em": antigo["em"], "rc": 0}, ensure_ascii=False) + "\n")
    return sum(i["bytes"] for i in itens)


LIVRE_MIN_GB = 20   # a VM-2 também captura: abaixo disso as fotos esperam na VM-1


def livre_no_gb(no: str = NO, remoto: str | None = None, fs: str = "/") -> int | None:
    try:
        cmd = f"df -BG --output=avail {fs} | tail -1"
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=15", no, remoto or cmd],
                           input=cmd if remoto else None, capture_output=True, text=True, timeout=60)
        return int("".join(c for c in r.stdout if c.isdigit())) if r.returncode == 0 else None
    except (subprocess.SubprocessError, ValueError):
        return None


def escolher_destino() -> tuple | None:
    """VM-2 se tiver ≥ LIVRE_MIN_GB; senão o it-campo (mesmo limite); senão None (nada sai da VM-1)."""
    livre = livre_no_gb()
    if livre is not None and livre >= LIVRE_MIN_GB:
        return (NO, DEST, None)
    print(f"{time.strftime('%F %T')} {NO} {'fora do ar' if livre is None else f'com {livre} GB'} — tento {RESERVA[0]}",
          flush=True)
    no, dest, rsync_path, remoto, fs = RESERVA
    livre2 = livre_no_gb(no, remoto, fs)
    if livre2 is not None and livre2 >= LIVRE_MIN_GB:
        return (no, dest, rsync_path)
    print(f"{time.strftime('%F %T')} {no} {'fora do ar' if livre2 is None else f'com {livre2} GB'} — parei", flush=True)
    return None


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
    alvo = None
    for i, p in enumerate(lista, 1):
        if not a.ensaio and i % 50 == 1:
            alvo = escolher_destino()
            if alvo is None:
                break
        total += tratar(p, a.ensaio, alvo)
        if i % 50 == 0:
            print(f"{time.strftime('%F %T')} {i}/{len(lista)} pastas · {total/1e9:.2f} GB", flush=True)
    print(json.dumps({"pastas": len(lista), "gb": round(total / 1e9, 2), "ensaio": a.ensaio}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
