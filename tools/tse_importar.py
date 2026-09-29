#!/usr/bin/env python3
"""Importa candidatos do TSE trazidos de FORA da nuvem (o CDN recusa as VMs com 403).

Aceita o zip oficial (`consulta_cand_AAAA.zip`), um zip só com o CSV do RJ, ou o próprio
`consulta_cand_AAAA_RJ.csv`. Extrai o CSV do RJ para o cache `data/tse_cache/consulta_cand_AAAA_RJ.csv`,
que `tse_candidatos` e `comissionados_candidatos` leem antes de tentar o download.

    .venv/bin/python -m tools.tse_importar ARQUIVO [ARQUIVO ...] [--cruzar]

--cruzar: roda em seguida `tse_candidatos.coletar(anos=<importados>)` (folha inteira × candidaturas).
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from compliance_agent.pcrj.comissionados_candidatos import _cache_path


def _ano(nome: str, cabecalho: bytes) -> int | None:
    m = re.search(r"consulta_cand_(\d{4})", nome, re.I)
    if m:
        return int(m.group(1))
    linha = cabecalho.decode("latin-1").splitlines()[1:2]
    m = re.match(r'^"?[^;]*"?;"?[^;]*"?;"?(\d{4})"?;', linha[0]) if linha else None   # 3ª coluna = ANO_ELEICAO
    return int(m.group(1)) if m else None


def importar(caminho: Path) -> list[int]:
    anos = []
    if zipfile.is_zipfile(caminho):
        with zipfile.ZipFile(caminho) as z:
            for nm in z.namelist():
                if not nm.lower().endswith("_rj.csv"):
                    continue
                bruto = z.read(nm)
                ano = _ano(nm, bruto[:4000]) or _ano(caminho.name, bruto[:4000])
                if not ano:
                    print(f"  {nm}: ano não identificado — ignorado")
                    continue
                anos.append(_gravar(ano, bruto, f"{caminho.name}:{nm}"))
    else:
        bruto = caminho.read_bytes()
        ano = _ano(caminho.name, bruto[:4000])
        if not ano:
            raise SystemExit(f"{caminho}: ano não identificado")
        anos.append(_gravar(ano, bruto, caminho.name))
    if not anos:
        print(f"  {caminho.name}: nenhum CSV do RJ (_RJ.csv) dentro — nada importado")
    return anos


def _gravar(ano: int, bruto: bytes, origem: str) -> int:
    linhas = bruto.count(b"\n")
    if linhas < 100 or b"NM_CANDIDATO" not in bruto[:4000]:
        raise SystemExit(f"{origem}: não parece o consulta_cand do TSE ({linhas} linhas)")
    destino = _cache_path(ano)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(bruto)
    print(f"  {origem} → {destino.name}: {linhas:,} linhas".replace(",", "."))
    return ano


def main(argv: list[str]) -> None:
    arquivos = [Path(a) for a in argv if not a.startswith("--")]
    if not arquivos:
        raise SystemExit(__doc__)
    anos = sorted({a for f in arquivos for a in importar(f)})
    print("anos no cache:", anos)
    if "--cruzar" in argv and anos:
        from compliance_agent.pcrj.tse_candidatos import coletar
        print(coletar(anos=anos))


if __name__ == "__main__":
    main(sys.argv[1:])
