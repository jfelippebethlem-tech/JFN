#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sei_descontaminar — tira da pasta arquivada as peças que são de OUTRO processo.

CONTEXTO. `compliance_agent/sei/documentos_alheios` já impede a contaminação em arquivamentos
NOVOS (ver `docs/RETOMADA-2026-07-29-CONTAMINACAO-DE-PASTA.md`). O que ficou pendente é o acervo
JÁ arquivado: as pastas contaminadas seguem alimentando dossiê e `agente_processo` com fatos e
RESPONSÁVEIS de processos alheios — o pior caso medido tem **1 documento próprio e 37 alheios**.

A CHAVE DE JUNÇÃO, e por que não é o título. O manifest arquivado não guarda `contexto`; quem
guarda é o manifest da ÍNTEGRA em `data/sei_cache/integra_<processo>/`. Ligar os dois por título
casaria mal — o arquivado normaliza o texto ("programa o de desembolso" para "Programação de
Desembolso"). O que liga com segurança é o **prefixo numérico do arquivo de texto**
(`000_....txt` ↔ índice 0 da íntegra), verificado em 35 de 35 documentos antes de qualquer
escrita.

NADA É APAGADO. As peças alheias vão para `_alheios/` dentro da própria pasta, com um índice que
diz **de qual processo** cada uma veio — que é o que permite devolvê-las ao lugar certo depois. O
manifest original é copiado para `manifest.json.antes-descontaminar`. Reverter é mover de volta.

E A REGRA QUE NÃO SE INVERTE: documento **sem** número no contexto FICA. Ausência de dado não
prova que a peça é alheia, e descartá-la trocaria contaminação por perda silenciosa — que é pior,
porque some sem deixar rastro.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_descontaminar --listar
    PYTHONPATH=. .venv/bin/python -m tools.sei_descontaminar --processo 080001_000744_2024
    PYTHONPATH=. .venv/bin/python -m tools.sei_descontaminar --todos --aplicar
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from compliance_agent.sei.documentos_alheios import separar_alheios

_REPO = Path(__file__).resolve().parents[1]
_CACHE = _REPO / "data" / "sei_cache"
_ARQ = _REPO / "data" / "sei_arquivo"

_RE_PREFIXO = re.compile(r"^(\d{3,4})_")


def _integra(processo: str) -> list[dict] | None:
    man = _CACHE / f"integra_{processo}" / "manifest.json"
    if not man.exists():
        return None
    try:
        d = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, list) and d else None


def _indice_do_doc(doc: dict) -> int | None:
    """O prefixo numérico do arquivo de texto é o índice na íntegra. Sem ele, não se decide."""
    m = _RE_PREFIXO.match(Path(str(doc.get("texto") or "")).name)
    return int(m.group(1)) if m else None


def diagnosticar(processo: str) -> dict[str, Any]:
    """O que há de alheio nesta pasta — sem escrever nada."""
    docs_int = _integra(processo)
    if docs_int is None:
        return {"processo": processo, "estado": "sem_integra",
                "motivo": "não há manifest de íntegra com contexto — não avaliável por esta régua"}
    if not any(d.get("contexto") for d in docs_int):
        return {"processo": processo, "estado": "sem_contexto",
                "motivo": "manifest de íntegra em formato antigo, sem o campo `contexto`"}

    sep = separar_alheios(docs_int, processo)
    alheios_por_indice = {d.get("i") for d in sep["alheios"]}
    origem = {}
    from compliance_agent.sei.documentos_alheios import numero_do_contexto
    for d in sep["alheios"]:
        origem[d.get("i")] = numero_do_contexto(d.get("contexto"))

    man_arq = _ARQ / processo / "manifest.json"
    if not man_arq.exists():
        return {"processo": processo, "estado": "sem_pasta_arquivada",
                "alheios_na_integra": len(sep["alheios"])}
    arq = json.loads(man_arq.read_text(encoding="utf-8"))
    docs_arq = arq.get("docs") or []

    a_remover, sem_indice = [], 0
    for doc in docs_arq:
        i = _indice_do_doc(doc)
        if i is None:
            sem_indice += 1        # sem índice não se decide — o documento FICA
            continue
        if i in alheios_por_indice:
            a_remover.append({"i": i, "titulo": doc.get("titulo"), "texto": doc.get("texto"),
                              "de_processo": origem.get(i)})
    return {"processo": processo, "estado": "avaliado",
            "docs_arquivados": len(docs_arq), "a_remover": len(a_remover),
            "ficam": len(docs_arq) - len(a_remover), "sem_indice": sem_indice,
            "sem_numero_no_contexto": sep["sem_numero"],
            "por_processo_alheio": sep["por_processo_alheio"], "itens": a_remover}


def aplicar(processo: str) -> dict[str, Any]:
    """Move as peças alheias para `_alheios/` e reescreve o manifest. Reversível."""
    d = diagnosticar(processo)
    if d.get("estado") != "avaliado" or not d["a_remover"]:
        return {**d, "aplicado": False}

    pasta = _ARQ / processo
    destino = pasta / "_alheios"
    destino.mkdir(exist_ok=True)

    backup = pasta / "manifest.json.antes-descontaminar"
    if not backup.exists():
        shutil.copy2(pasta / "manifest.json", backup)

    movidos = []
    for item in d["itens"]:
        rel = item.get("texto")
        if not rel:
            continue
        origem = pasta / rel
        if origem.exists():
            alvo = destino / Path(rel).name
            shutil.move(str(origem), str(alvo))
            movidos.append({**item, "movido_para": f"_alheios/{Path(rel).name}"})
        else:
            movidos.append({**item, "movido_para": None, "nota": "texto já ausente em disco"})

    arq = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    fora = {i["i"] for i in d["itens"]}
    arq["docs"] = [x for x in (arq.get("docs") or [])
                   if _indice_do_doc(x) not in fora]
    arq["descontaminado"] = {
        "em": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "removidos": len(movidos),
        "restantes": len(arq["docs"]),
        "por_processo_alheio": d["por_processo_alheio"],
        "regra": ("documento cujo `contexto` na íntegra aponta OUTRO número de processo; peça sem "
                  "número no contexto FICA — ausência de dado não prova que é alheia"),
        "reversivel": "as peças estão em _alheios/ e o manifest anterior em "
                      "manifest.json.antes-descontaminar",
    }
    (pasta / "manifest.json").write_text(
        json.dumps(arq, ensure_ascii=False, indent=1), encoding="utf-8")

    (destino / "_indice.json").write_text(
        json.dumps({"processo": processo, "itens": movidos}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return {**d, "aplicado": True, "movidos": len(movidos)}


def contaminadas() -> list[str]:
    """Processos cujo cache de íntegra acusa peça de outro processo."""
    fora = []
    for man in sorted(_CACHE.glob("integra_*/manifest.json")):
        proc = man.parent.name.replace("integra_", "")
        d = diagnosticar(proc)
        if d.get("estado") == "avaliado" and d["a_remover"]:
            fora.append(proc)
    return fora


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description="Descontamina pastas do arquivo SEI")
    ap.add_argument("--processo")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--aplicar", action="store_true", help="sem isto, só diagnostica")
    a = ap.parse_args(argv)

    if a.listar or (not a.processo and not a.todos):
        alvos = contaminadas()
        print(f"contaminadas: {len(alvos)}")
        for p in alvos:
            d = diagnosticar(p)
            print(f"  {p}: ficam {d['ficam']} de {d['docs_arquivados']} "
                  f"(remover {d['a_remover']}, sem índice {d['sem_indice']})")
        return 0

    alvos = [a.processo] if a.processo else contaminadas()
    for p in alvos:
        r = aplicar(p) if a.aplicar else diagnosticar(p)
        r.pop("itens", None)
        print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
