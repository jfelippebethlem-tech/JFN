# -*- coding: utf-8 -*-
"""O que é PARCERIA (Lei 13.019/2014, MROSC) no acervo — porta comum dos padrões mrosc_* e gestor_recebe_da_osc.

Seleção barata, só pelos TÍTULOS do manifesto (não abre .txt): o processo é de parceria quando algum documento é
termo de fomento/colaboração, relatório de execução da OSC, comissão de monitoramento e avaliação, ou plano de trabalho
junto de prestação de contas. Convênio com município (Lei 8.666 art. 116 / Decreto) entra como plano de trabalho +
prestação de contas — os sinais desta família (execução escrita no limiar, atesto que o próprio relatório nega) valem
igual para ele; o fundamento citado muda (`norma`).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_FORTE = re.compile(r"termo de (fomento|colabora)|relat[oó]rio\s+(de\s+)?execu[cç][aã]o\s+(da\s+)?osc|\bOSC\b|"
                    r"monitoramento e avalia|mrosc|13\.019|termo\s+(aditivo\s+.{0,12})?(de|do)\s+conv[eê]nio|"
                    r"registro da assinatura do conv[eê]nio|coordenador\w*\s+(geral\s+)?(de\s+)?conv[eê]nio|"
                    r"gestor\w*\s+do\s+conv[eê]nio", re.I)
_PLANO = re.compile(r"plano de trabalho", re.I)
_PC = re.compile(r"presta[cç][aã]o de contas", re.I)


def eh_parceria(man: dict) -> bool:
    ts = [str(d.get("titulo") or "") for d in (man.get("docs") or []) if isinstance(d, dict)]
    if any(_FORTE.search(t) for t in ts):
        return True
    return any(_PLANO.search(t) for t in ts) and any(_PC.search(t) for t in ts)


def plano(texto: str) -> str:
    """Texto em uma linha (as quebras do PDF não podem cortar a frase)."""
    return re.sub(r"\s+", " ", texto or "")


_CACHE = Path(__file__).resolve().parents[2] / "data" / "padroes" / "_universo_parcerias.json"
VALIDADE_CACHE_S = 6 * 3600


def tags_parceria(limite: int | None = None) -> list[str]:
    """Tags das pastas de parceria; lista cacheada por 6 h (as 4 passadas da família leem 10 mil manifestos só 1×)."""
    from compliance_agent.padroes import _pagamento_comum as C
    if not limite and _CACHE.is_file() and time.time() - _CACHE.stat().st_mtime < VALIDADE_CACHE_S:
        try:
            return json.loads(_CACHE.read_text(encoding="utf-8"))["tags"]
        except (OSError, ValueError, KeyError):
            pass
    ps = C.pastas()
    if limite:
        ps = ps[:limite]
    tags = [p.name for p in ps if (m := C.manifesto(p)) and eh_parceria(m)]
    if not limite:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE.with_name(f"{_CACHE.name}.{os.getpid()}.tmp")   # único por processo: --paralelo
        tmp.write_text(json.dumps({"pastas": len(ps), "tags": tags}), encoding="utf-8")
        tmp.replace(_CACHE)
    return tags
