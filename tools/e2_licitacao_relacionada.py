# -*- coding: utf-8 -*-
"""Contrato → processo da LICITAÇÃO (regra única #53 do mapa O1.2, ex-`tools/bombeiros_achar_edital.py`, que só
existia para o FUNESBOM e sumiu com ele; auditoria de 27/11/2026).

Varre o texto do arquivo SEI (`data/sei_arquivo/<pasta>/texto/*.txt`) e, em cada DOCUMENTO que menciona pregão,
edital, concorrência ou tomada de preços, pega os nº de processo SEI citados que NÃO são o próprio. Esses são
candidatos a processo de licitação (edital, ata, desclassificações, TR) — destravam direcionamento e sobrepreço.

Diferença declarada do script: só a citação no MESMO documento que fala da licitação (o script pegava qualquer SEI do
processo inteiro e enfileirava tudo — genérico assim, explodiria o backlog do E2). Grava `data/sei_fila_licitacao.json`
(formato das filas antigas: [{"sei": nº, "origem": processo que cita, "documento": arquivo}]), que o semeador do E2
(`tools/e2_semear`) lê como fonte do nº — a ORDEM é a da prioridade única, nunca a deste arquivo. Idempotente.
Determinístico (regex). Indício ≠ acusação: é só "vale capturar".
    python -m tools.e2_licitacao_relacionada [--raiz data/sei_arquivo]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RE_LICITACAO = re.compile(r"preg[ãa]o|edital|concorr[êe]ncia|tomada\s+de\s+pre[çc]os", re.I)
RE_SEI = re.compile(r"SEI[-\s]?(\d{6})[/.](\d{6})[/.](\d{4})")
SAIDA = Path("data/sei_fila_licitacao.json")


def relacionados(texto: str, proprio: str) -> set[str]:
    """Nº SEI citados num documento que fala de licitação, menos o próprio processo. Puro."""
    if not RE_LICITACAO.search(texto or ""):
        return set()
    return {f"{a}/{b}/{c}" for a, b, c in RE_SEI.findall(texto)} - {proprio}


def varrer(raiz: Path) -> list[dict]:
    from compliance_agent.sei.acervo_texto import pasta_para_numero
    vistos: dict[str, dict] = {}
    for pasta in sorted(p for p in raiz.iterdir() if p.is_dir()):
        proprio = re.sub(r"^SEI-", "", pasta_para_numero(pasta.name))   # o nº vem com o prefixo SEI-
        for t in sorted((pasta / "texto").glob("*.txt")):
            try:
                txt = t.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for n in sorted(relacionados(txt, proprio)):
                vistos.setdefault(n, {"sei": n, "origem": proprio, "documento": f"{pasta.name}/texto/{t.name}"})
    return [vistos[k] for k in sorted(vistos)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raiz", default="data/sei_arquivo")
    ap.add_argument("--saida", default=str(SAIDA))
    a = ap.parse_args(argv)
    itens = varrer(Path(a.raiz))
    saida = Path(a.saida)
    tmp = saida.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(itens, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(saida)
    print(f"e2_licitacao_relacionada: {len(itens)} processo(s) de licitação candidato(s) gravado(s) em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
