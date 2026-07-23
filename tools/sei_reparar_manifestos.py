#!/usr/bin/env python
"""Repara manifesto ZERADO cujo texto extraído ainda está no disco.

Em 2026-07-06 um rerun com cache vazio sobrescreveu o manifesto de 33 processos:
`docs: []` no manifesto, mas `texto/*.txt` intacto no disco (num caso, 210
documentos / 5 MB). Efeito: o conteúdo virou invisível para todo consumidor
(todos leem o manifesto) E a fila passou a tratá-los como prontos, porque a
checagem de "arquivado ok" olha justamente a pasta texto/ — zona morta.

Este reparo reconstrói as entradas a partir dos .txt (o nome do arquivo carrega
índice e título: `000_despacho_de_encaminhamento_de_processo.txt`) e reclassifica
fase/tipo pelo mesmo classificador do arquivamento. É recuperação de dado já
capturado — não inventa nada e não vai à rede.

Uso:  .venv/bin/python tools/sei_reparar_manifestos.py [--aplicar]
      (sem --aplicar só relata; nada é escrito)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "sei_arquivo"
sys.path.insert(0, str(RAIZ))

from compliance_agent.sei.fases import FASES, classificar, lacunas  # noqa: E402


def _titulo_do_arquivo(nome: str) -> tuple[int, str]:
    """`012_termo_de_referencia.txt` → (12, 'termo de referencia')."""
    base = nome[:-4] if nome.endswith(".txt") else nome
    idx, _, resto = base.partition("_")
    try:
        i = int(idx)
    except ValueError:
        i, resto = -1, base
    return i, resto.replace("_", " ").strip()


def reparar(dir_proc: Path, aplicar: bool) -> dict | None:
    mpath = dir_proc / "manifest.json"
    if not mpath.exists():
        return None
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if m.get("docs"):
        return None                      # manifesto saudável: não tocar
    txts = sorted((dir_proc / "texto").glob("*.txt")) if (dir_proc / "texto").is_dir() else []
    if not txts:
        # Vazio de verdade (a fila reprocessa). Mas o manifesto gravado pelo código
        # antigo ainda acusa "🔴 falta Seleção/Contrato" — acusação falsa: nós é que
        # não baixamos nada. Sanear é obrigatório mesmo sem ter o que recuperar.
        if not m.get("lacunas") and m.get("captura_vazia") is True:
            return None                  # já saneado
        limpo = dict(m)
        limpo.update({
            "lacunas": [], "captura_vazia": True,
            "aviso": ("Nada foi capturado desta íntegra (falha/pendência de coleta). "
                      "NÃO interpretar como processo sem documentos — reprocessar."),
            "saneado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        if aplicar:
            mpath.write_text(json.dumps(limpo, ensure_ascii=False, indent=1), encoding="utf-8")
        limpo["_saneado"] = True
        return limpo

    docs, tipos = [], set()
    for t in txts:
        i, titulo = _titulo_do_arquivo(t.name)
        fase, tipo = classificar(titulo)
        tipos.add(tipo)
        conteudo = t.read_text(encoding="utf-8", errors="ignore")
        fotos = sorted(p.name for p in (dir_proc / "fotos").glob(f"{i:03d}_*.jpg")) \
            if (dir_proc / "fotos").is_dir() else []
        docs.append({"i": i, "titulo": titulo, "fase": fase, "tipo": tipo,
                     "texto": f"texto/{t.name}", "chars": len(conteudo), "ocr": False,
                     "fotos": [f"fotos/{f}" for f in fotos]})
    docs.sort(key=lambda d: d["i"])
    fases_presentes = {d["fase"] for d in docs} - {"indefinida"}
    modalidade = "dispensa" if "dispensa" in tipos else ""
    novo = dict(m)
    novo.update({
        "docs": docs,
        "linha_do_tempo": {f: sum(1 for d in docs if d["fase"] == f) for f in FASES},
        "lacunas": lacunas(fases_presentes, modalidade,
                           com_pagamento=any(d["fase"] == "despesa" for d in docs)),
        "captura_vazia": False,
        "fotos_total": sum(len(d["fotos"]) for d in docs),
        "reparado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reparo": "manifesto reconstruído a partir do texto já extraído em disco "
                  "(manifesto havia sido zerado por rerun com cache vazio)",
    })
    if aplicar:
        mpath.write_text(json.dumps(novo, ensure_ascii=False, indent=1), encoding="utf-8")
    return novo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isso, só relata)")
    a = ap.parse_args()
    n = docs = chars = saneados = 0
    for d in sorted(ARQUIVO.iterdir()):
        if not d.is_dir():
            continue
        r = reparar(d, a.aplicar)
        if r and r.get("_saneado"):
            saneados += 1
        elif r:
            n += 1
            docs += len(r["docs"])
            chars += sum(x["chars"] for x in r["docs"])
            print(f"  {d.name}: {len(r['docs'])} docs recuperados "
                  f"({sum(x['chars'] for x in r['docs'])/1024:.0f} KB)")
    verbo = "reparados" if a.aplicar else "reparáveis (use --aplicar)"
    print(f"\n{n} processos {verbo} · {docs} documentos · {chars/1024/1024:.1f} MB de texto")
    print(f"{saneados} capturas vazias saneadas (lacuna falsa removida)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
