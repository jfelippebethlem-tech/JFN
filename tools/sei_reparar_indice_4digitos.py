"""Reparo dirigido dos arquivos SEI feitos com o índice de 3 dígitos (defeito corrigido em 80770d09, 18/11/2026).

O arquivador lia `int(pdf.name[:3])`: em processo com mais de 1.000 documentos, `1000.pdf`…`1009.pdf` viravam o
documento 100. O arquivo ficou com entradas repetidas e os documentos de 1.000 em diante marcados `nao_capturado`.
Os PDFs já saíram do cache da VM-1 (depurados → `NNN.txt` ao lado; escaneados → arquivo frio da VM-2).

Por processo, monta uma ORIGEM de reparo e roda o arquivador canônico (`sei_arquivar.arquivar(textos_soltos=True)`)
num destino novo; só troca as pastas depois de validar, e o arquivo antigo vai inteiro para o backup:
  - documento < 1.000 já capturado → o texto do arquivo atual (é o melhor que a casa tem: inclui OCR da GPU), com os
    campos de OCR restaurados depois. Na faixa 100–199 (a que colidia) o título gravado no teor é conferido; se não
    bate, o texto do arquivo é descartado e o documento sai da fonte.
  - demais → `NNN.txt` / `NNN.ocr.txt` do cache; sem eles, o PDF do arquivo frio da VM-2 (só os que faltam).

    python -m tools.sei_reparar_indice_4digitos --listar
    python -m tools.sei_reparar_indice_4digitos 210108_000169_2023 [--aplicar]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from tools.sei_arquivar import arquivar  # noqa: E402

ARQUIVO, CACHE = _REPO / "data" / "sei_arquivo", _REPO / "data" / "sei_cache"
OFICINA = _REPO / "data" / "backups" / "indice4_oficina"     # gitignored e no mesmo disco (a troca é rename)
BACKUP = _REPO / "data" / "backups" / "indice4_20261118"
FRIO = "vm2:arquivo_frio/sei_cache"
CAMPOS_OCR = ("ocr", "ocr_motor", "ocr_paginas", "ocr_cortado", "ocr_anterior",
              "texto_recuperado_ocr_gpu", "texto_recuperado_ocr_reserva")


def afetados() -> list[str]:
    """Arquivos com `i` repetido e árvore > 1.000 — a assinatura do defeito."""
    out = []
    for mp in sorted(ARQUIVO.glob("*/manifest.json")):
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ta = m.get("total_arvore")
        docs = [d for d in m.get("docs") or [] if isinstance(d, dict)]
        if isinstance(ta, int) and ta > 1000 and len({str(d.get("i")) for d in docs}) < len(docs):
            out.append(mp.parent.name)
    return out


def _corpo(p: Path) -> str:
    t = p.read_text(encoding="utf-8", errors="replace")
    return t.split("\n\n", 1)[1] if "\n\n" in t else ""


def titulo_confere(i: int, titulo: str, corpo: str) -> bool:
    """Na faixa que colidia (100–199), o teor nativo começa com `[título]` (gravar_doc); tem de ser o deste documento."""
    if not 100 <= i <= 199:
        return True
    m = re.match(r"\s*\[(.+?)\]", corpo)
    return m is None or m.group(1).strip()[:60] == (titulo or "").strip()[:60]


def montar_origem(tag: str, antigo: dict, cache_man: dict, origem: Path) -> tuple[list[int], dict[int, dict]]:
    """Escreve a origem de reparo. Devolve (índices a buscar no frio, entradas antigas a restaurar)."""
    origem.mkdir(parents=True, exist_ok=True)
    (origem / "manifest.json").write_text(json.dumps(cache_man, ensure_ascii=False), encoding="utf-8")
    cache = CACHE / f"integra_{tag}"
    velhos: dict[int, dict] = {}
    for d in antigo.get("docs") or []:
        if isinstance(d, dict) and not d.get("nao_capturado") and str(d.get("i", "")).isdigit():
            velhos.setdefault(int(d["i"]), d)              # 1ª entrada de cada i: a do próprio documento
    restaurar: dict[int, dict] = {}
    buscar: list[int] = []
    for e in cache_man.get("docs") or []:
        i, titulo = int(e["i"]), e.get("titulo") or ""
        v = velhos.get(i) if i < 1000 else None
        if v and v.get("texto") and (ARQUIVO / tag / v["texto"]).is_file():
            corpo = _corpo(ARQUIVO / tag / v["texto"])
            if corpo.strip() and titulo_confere(i, titulo, corpo):
                (origem / f"{i:03d}.txt").write_text(corpo, encoding="utf-8")
                restaurar[i] = v
                continue
        for nome in (f"{i:03d}.txt", f"{i:03d}.ocr.txt", f"{i:03d}.pdf"):
            if (cache / nome).is_file():
                shutil.copy2(cache / nome, origem / nome)
                break
        else:
            buscar.append(i)
    return buscar, restaurar


def buscar_no_frio(tag: str, indices: list[int], origem: Path) -> int:
    if not indices:
        return 0
    lista = origem / ".frio.txt"
    lista.write_text("".join(f"integra_{tag}/{i:03d}.pdf\n" for i in indices), encoding="utf-8")
    subprocess.run(["nice", "-n", "19", "rsync", "-a", "--files-from", str(lista), FRIO + "/", str(origem / "_frio")],
                   check=False, timeout=7200)
    n = 0
    for i in indices:
        p = origem / "_frio" / f"integra_{tag}" / f"{i:03d}.pdf"
        if p.is_file():
            p.replace(origem / f"{i:03d}.pdf")
            n += 1
    shutil.rmtree(origem / "_frio", ignore_errors=True)
    lista.unlink(missing_ok=True)
    return n


def reparar(tag: str, aplicar: bool = False) -> dict:
    atual = ARQUIVO / tag
    antigo = json.loads((atual / "manifest.json").read_text(encoding="utf-8"))
    cache_man = json.loads((CACHE / f"integra_{tag}" / "manifest.json").read_text(encoding="utf-8"))
    origem, destino = OFICINA / f"origem_{tag}", OFICINA / f"arquivo_{tag}"
    shutil.rmtree(origem, ignore_errors=True)
    shutil.rmtree(destino, ignore_errors=True)
    buscar, restaurar = montar_origem(tag, antigo, cache_man, origem)
    trazidos = buscar_no_frio(tag, buscar, origem)
    (destino / "texto").mkdir(parents=True)
    if (atual / "fotos").is_dir():
        shutil.copytree(atual / "fotos", destino / "fotos")
    novo = arquivar(origem, destino, processo=antigo.get("processo") or tag.replace("_", "/"),
                    ocr=False, textos_soltos=True)
    for d in novo["docs"]:
        v = restaurar.get(d["i"])
        if v is None:
            continue
        d.update({k: v[k] for k in CAMPOS_OCR if k in v})
        d.pop("via_texto_solto", None)
        guarda = v.get("ocr_anterior")
        if guarda and (atual / guarda).is_file():
            shutil.copy2(atual / guarda, destino / guarda)
    novo["reparo_indice_4digitos"] = {"em": time.strftime("%F %T"), "backup": str(BACKUP / tag),
                                      "do_frio": trazidos, "sem_fonte": len(buscar) - trazidos}
    (destino / "manifest.json").write_text(json.dumps(novo, ensure_ascii=False, indent=1), encoding="utf-8")

    ids = [d["i"] for d in novo["docs"]]
    cap = lambda m: len({str(d.get("i")) for d in m.get("docs") or [] if not d.get("nao_capturado")})  # noqa: E731
    res = {"tag": tag, "arvore": cache_man.get("total_arvore"), "entradas_antes": len(antigo.get("docs") or []),
           "distintos_capturados_antes": cap(antigo), "entradas_depois": len(ids),
           "distintos_capturados_depois": cap(novo), "nao_capturados_depois": novo["nao_capturados"],
           "do_frio": trazidos, "sem_fonte": len(buscar) - trazidos, "restaurados_do_arquivo": len(restaurar)}
    ok = len(ids) == len(set(ids)) and res["distintos_capturados_depois"] >= res["distintos_capturados_antes"]
    res["valido"] = ok
    if aplicar and ok:
        BACKUP.mkdir(parents=True, exist_ok=True)
        if (BACKUP / tag).exists():
            raise RuntimeError(f"backup de {tag} já existe — não sobrescrevo")
        atual.rename(BACKUP / tag)            # o arquivo antigo inteiro vai para o backup (mesmo disco: rename)
        destino.rename(atual)
        shutil.rmtree(origem, ignore_errors=True)
        res["aplicado"] = True
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    if a.listar:
        print("\n".join(afetados()))
        return 0
    for tag in a.tags or afetados():
        print(json.dumps(reparar(tag, aplicar=a.aplicar), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
