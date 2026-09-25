"""Foto RECICLADA no acervo inteiro — a mesma fotografia lastreando processos DIFERENTES.

`foto_medicao.reciclagem()` existia e era testada, mas só rodava entre os processos de UM dossiê
(`capitulos_dossie`). Em 24/09/2026 o acervo tinha 3.818 processos e 17.492 arquivos em `fotos/` e o
confronto de todos contra todos nunca tinha sido feito — que é justamente onde a reciclagem aparece:
o mesmo registro "comprovando" a execução de dois contratos distintos.

Offline, sem IA, sem custo (dHash). Grava `data/fotos_reciclagem_acervo.json` com cada grupo, os processos,
os arquivos e o objeto/órgão de cada processo, para conferir lado a lado. Indício ≠ acusação: foto
institucional (fachada da sede, logotipo fotografado) pode se repetir legitimamente — o laudo diz quantos
processos e de quais órgãos, e a conferência é humana.

Uso:
    nice -n 19 ionice -c3 .venv/bin/python -m tools.fotos_reciclagem_acervo
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from compliance_agent import foto_medicao as FM  # noqa: E402

ARQUIVO = RAIZ / "data" / "sei_arquivo"
SAIDA = RAIZ / "data" / "fotos_reciclagem_acervo.json"
DB = RAIZ / "data" / "compliance.db"


_SLUG = re.compile(r"^\d+_\d+_\d{4}$")


def _processos_com_foto() -> list[Path]:
    """Só pastas de PROCESSO (UG_SEQ_ANO). `_substituido/` guarda 3.078 capturas ANTIGAS dos mesmos processos e
    `_orfaos_residuo/` sobras: na 1ª rodada (24/09/2026) a pasta de substituídas entrou como "processo" e 22 fotos
    "recicladas" eram o processo contra a própria captura anterior."""
    return sorted(d for d in ARQUIVO.iterdir() if d.is_dir() and _SLUG.match(d.name) and FM._fotos_do_processo(d))


def _contexto(slugs: set[str]) -> dict[str, dict]:
    """Objeto, órgão e risco de cada processo (sei_arvore/sei_ficha), para o laudo dizer O QUE a foto comprova."""
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error:
        return out
    try:
        for s in slugs:
            ug, seq, ano = (s.split("_") + ["", "", ""])[:3]
            numero = f"SEI-{ug}/{seq}/{ano}"
            r = None
            for tab in ("sei_arvore", "sei_ficha"):
                try:
                    r = con.execute(f"SELECT objeto, nivel_risco FROM {tab} WHERE numero_sei=?", (numero,)).fetchone()
                except sqlite3.Error:
                    r = None
                if r:
                    break
            out[s] = {"numero": numero, "ug": ug, "objeto": (r["objeto"] if r else None), "nivel_risco": (r["nivel_risco"] if r else None)}
    finally:
        con.close()
    return out


def rodar() -> dict:
    t0 = time.time()
    dirs = _processos_com_foto()
    r = FM.reciclagem(dirs)
    slugs = {o["processo"] for g in r.get("grupos", []) for o in g["ocorrencias"]}
    ctx = _contexto(slugs)
    for g in r.get("grupos", []):
        procs = sorted({o["processo"] for o in g["ocorrencias"]})
        g["processos"] = [ctx.get(p, {"numero": p}) for p in procs]
        g["n_ugs"] = len({ctx.get(p, {}).get("ug") for p in procs})
    # mais processos e mais órgãos distintos primeiro: foto repetida em UGs diferentes é o caso mais forte
    r["grupos"] = sorted(r.get("grupos", []), key=lambda g: (-g["n_ugs"], -g["n_processos"]))
    r["gerado_em"] = datetime.now().isoformat(timespec="seconds")
    r["segundos"] = round(time.time() - t0, 1)
    r["processos_examinados"] = len(dirs)
    tmp = SAIDA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SAIDA)
    return r


if __name__ == "__main__":
    r = rodar()
    print(f"{r['processos_examinados']} processos com foto · {r.get('n_fotos', 0)} fotos · "
          f"{r.get('n_grupos', 0)} grupo(s) reciclado(s) · grau {r.get('grau')} · {r['segundos']} s")
    for g in r.get("grupos", [])[:10]:
        print(f"  {g['n_processos']} processos / {g['n_ugs']} UG(s): "
              + " | ".join(f"{p['numero']} {str(p.get('objeto') or '')[:50]}" for p in g["processos"][:4]))
