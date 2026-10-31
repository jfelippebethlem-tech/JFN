#!/usr/bin/env python
"""Devolve ao manifesto os documentos que estão no disco e fora do índice.

O QUE ISTO CONSERTA (medido em 2026-08-03). Cada processo do acervo tem `manifest.json` (o índice)
e `texto/*.txt` (o teor). Quando um processo é RECAPTURADO, os novos `.txt` entram com nomes novos
— e em 6 processos o manifesto nunca foi reescrito. Resultado: o índice aponta para os arquivos da
captura ANTIGA, que são só a etiqueta (79-90 bytes), e a captura NOVA, com 7 a 38 KB por
documento, fica órfã — presente no disco e invisível para todo consumidor, porque todo consumidor
lê o manifesto.

    080001/001711/2026   manifesto: 97 docs, 2 com teor   ·   órfãos: 96, TODOS com teor
    510001/001309/2025   manifesto: 23 docs, 3 com teor   ·   órfãos: 39, TODOS com teor
    260007/004617/2024   manifesto: 626 docs, 107 c/ teor ·   órfãos: 108, TODOS com teor
    330020/000762/2021 · 080002/018240/2024 · 330005/000030/2026   (mesma forma)

POR QUE NÃO REAPONTAR PELO ÍNDICE DO NOME. `000_despacho_de_encaminhamento…txt` (vazio, declarado)
e `000_despacho_de_autoriza_o…txt` (7,6 KB, órfão) têm o mesmo índice e são documentos
DIFERENTES: a recaptura reordenou a árvore. Casar por índice colaria o teor de um documento no
título de outro — a falha "pasta com documentos alheios" que esta casa já pagou.

DE ONDE VEM O TÍTULO, ENTÃO. Da ETIQUETA que o próprio arquivo carrega na 1ª linha
(`[Anexo 01 - CARTA DE ENCAMINHAMENTO 3a MEDIÇÃO (118828428)] (fase: execucao · tipo: medicao)`).
Ela traz o título REAL, com acento e número do documento — melhor que o nome do arquivo, que é
slug sem acento. É o uso legítimo da etiqueta, o mesmo da `conferencia_captura`.

NÃO APAGA NADA. Os órfãos com teor entram com `i` novo e a marca `reconciliado`. As entradas da
captura SUBSTITUÍDA — as que apontam para arquivo sem teor — saem da lista de documentos e vão
para `docs_superados`, preservadas com o motivo: mantê-las ao lado das novas dobraria a contagem
(97 vazias + 96 reais = 193 documentos, cobertura 51% onde a verdade é ~100%) e a casa não troca
uma mentira por outra. Órfão SEM teor (4.893 no acervo — sobra de captura anterior) não entra:
não é documento, é resíduo.

Uso:  .venv/bin/python tools/sei_reconciliar_orfaos.py [--aplicar] [--processo TAG]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "sei_arquivo"
sys.path.insert(0, str(RAIZ))

from compliance_agent.sei import acervo_texto  # noqa: E402
from compliance_agent.sei.classificador_doc import classificar_doc  # noqa: E402
from compliance_agent.sei.fases import classificar_com_tipo  # noqa: E402


def _norm(s: str) -> str:
    """Título comparável: caixa e espaço não distinguem documento."""
    return re.sub(r"\s+", " ", (s or "").strip().casefold())


def _titulo_do_arquivo(f: Path) -> str:
    """O título REAL do documento: da etiqueta se houver, do nome do arquivo como último recurso."""
    try:
        with f.open(encoding="utf-8", errors="ignore") as fh:
            et = acervo_texto.etiqueta(fh.readline())
    except OSError:
        et = ""
    if et.startswith("["):
        dentro = et[1:et.rindex("]")] if "]" in et else ""
        if dentro.strip():
            return dentro.strip()
    base = f.stem
    _, _, resto = base.partition("_")
    return (resto or base).replace("_", " ").strip()


def reconciliar(dir_proc: Path, aplicar: bool) -> dict | None:
    mpath = dir_proc / "manifest.json"
    if not mpath.exists():
        return None
    try:
        man = json.loads(mpath.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    orfaos = [f for f in acervo_texto.orfaos(dir_proc) if acervo_texto.tem_conteudo(f)]
    if not orfaos:
        return None

    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
    usados = set()
    for d in docs:
        try:
            usados.add(int(str(d.get("i"))))
        except (TypeError, ValueError):
            continue
    proximo = (max(usados) + 1) if usados else 0

    novas = []
    for f in orfaos:
        titulo = _titulo_do_arquivo(f)
        texto = acervo_texto.sem_etiqueta(
            f.read_text(encoding="utf-8", errors="ignore"), titulo)
        tipo = classificar_doc(titulo, texto[:1200])
        fase = classificar_com_tipo(titulo, tipo)[0]
        novas.append({"i": proximo, "titulo": titulo, "fase": fase, "tipo": tipo,
                      "texto": f"texto/{f.name}", "chars": len(texto), "ocr": False,
                      "fotos": [], "reconciliado": True})
        proximo += 1

    # ENTRADA SUPERADA — e a prova exigida para dizer isso. Mantê-las ao lado das novas dobraria
    # a lista: o 080001/001711/2026 passaria a declarar 193 documentos (97 vazios + 96 reais) e a
    # cobertura sairia 51% onde a verdade é ~100% — errado para o outro lado, e a casa não troca
    # uma mentira por outra. Mas "vazia num processo recapturado" NÃO basta: no
    # 260007/004617/2024 isso marcaria 519 de 626 entradas como superadas quando só 88 têm
    # substituta — as outras 431 nunca foram capturadas e são exatamente o que a fila de
    # recaptura existe para achar. Converter "não capturado" em "superado" apagaria a fila.
    # A prova é o TÍTULO: só é superada a entrada vazia cujo título bate com o de um órfão
    # recuperado. Nada é apagado — vai para `docs_superados`, apontando quem a substituiu.
    por_titulo = {_norm(n["titulo"]): n for n in novas}
    vivos, superados = [], []
    for d in docs:
        rel = d.get("texto")
        vazia = bool(rel) and not acervo_texto.tem_conteudo(dir_proc / rel)
        substituta = por_titulo.get(_norm(str(d.get("titulo") or "")))
        if vazia and substituta:
            superados.append({**d, "superado_por": substituta["texto"]})
        else:
            vivos.append(d)

    novo = dict(man)
    novo["docs"] = vivos + novas
    if superados:
        novo["docs_superados"] = (man.get("docs_superados") or []) + superados
    novo["reconciliado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    novo["reconciliacao"] = (
        f"{len(novas)} documento(s) com teor estavam no disco e fora do índice (recaptura cujo "
        "manifesto não foi reescrito); título lido da etiqueta do próprio arquivo"
        + (f"; {len(superados)} entrada(s) da captura substituída movida(s) para docs_superados"
           if superados else ""))
    if aplicar:
        tmp = mpath.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(novo, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(mpath)
    return {"processo": dir_proc.name, "recuperados": len(novas),
            "chars": sum(d["chars"] for d in novas), "docs_antes": len(docs),
            "superados": len(superados)}




# ─────────────── órfão SEM teor: declarar o que se sabe, varrer o resíduo ───────────────

QUARENTENA = ARQUIVO / "_orfaos_residuo"


def tratar_vazios(dir_proc: Path, aplicar: bool) -> dict | None:
    """Órfão sem teor não é documento — mas pode ser a única prova de que o documento EXISTE.

    Medido em 2026-08-04: 5.106 arquivos órfãos sem teor em 86 processos (0,4 MB, 53-150 bytes,
    todos de julho/2026 — sobra de um esquema de nome anterior). Varrer todos seria o caminho
    óbvio e estaria errado: **2.832 deles carregam, na etiqueta, o título de um documento que o
    manifesto NÃO conhece** ("Termo de Referência (129952102)", "Despacho Autorizo de Despesas").
    Jogá-los fora apagaria a prova de que essas peças existem na árvore do SEI — é ler ausência
    como fato, ao contrário.

    Então o tratamento é duplo, e a etiqueta decide qual:
      · título DESCONHECIDO do manifesto → entra como documento DECLARADO com `chars=0`. Não se
        inventa teor: declara-se que a peça existe e não foi capturada, que é o que alimenta a
        fila de recaptura. INDISPONÍVEL ≠ 0.
      · título JÁ CONHECIDO → resíduo puro. Vai para `_orfaos_residuo/<processo>/`, quarentena,
        nunca apagado.
    """
    mpath = dir_proc / "manifest.json"
    if not mpath.exists():
        return None
    try:
        man = json.loads(mpath.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    vazios = [f for f in acervo_texto.orfaos(dir_proc) if not acervo_texto.tem_conteudo(f)]
    if not vazios:
        return None

    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
    conhecidos = {_norm(str(d.get("titulo") or ""))
                  for d in docs + (man.get("docs_superados") or []) if isinstance(d, dict)}
    usados = set()
    for d in docs:
        try:
            usados.add(int(str(d.get("i"))))
        except (TypeError, ValueError):
            continue
    proximo = (max(usados) + 1) if usados else 0

    declarados, residuo = [], []
    for f in vazios:
        titulo = _titulo_do_arquivo(f)
        if _norm(titulo) in conhecidos:
            residuo.append(f)
            continue
        conhecidos.add(_norm(titulo))
        tipo = classificar_doc(titulo, "")
        declarados.append({"i": proximo, "titulo": titulo,
                           "fase": classificar_com_tipo(titulo, tipo)[0], "tipo": tipo,
                           "texto": f"texto/{f.name}", "chars": 0, "ocr": False, "fotos": [],
                           "declarado_sem_teor": True})
        proximo += 1

    if aplicar:
        if declarados:
            novo_man = dict(man)
            novo_man["docs"] = docs + declarados
            novo_man["declarado_sem_teor_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            novo_man["declaracao"] = (
                f"{len(declarados)} documento(s) que a árvore do SEI tem e a captura não trouxe — "
                "estavam fora do índice, com título lido da etiqueta do próprio arquivo. "
                "chars=0 é declaração de INDISPONÍVEL, não de vazio.")
            tmp = mpath.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(novo_man, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(mpath)
        if residuo:
            destino = QUARENTENA / dir_proc.name
            destino.mkdir(parents=True, exist_ok=True)
            for f in residuo:
                alvo = destino / f.name
                if alvo.exists():
                    alvo = destino / f"{f.stem}__{f.stat().st_mtime_ns}{f.suffix}"
                shutil.move(str(f), str(alvo))
    return {"processo": dir_proc.name, "declarados": len(declarados), "residuo": len(residuo)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isso, só relata)")
    ap.add_argument("--processo", help="uma pasta específica (ex.: 080001_001711_2026)")
    ap.add_argument("--vazios", action="store_true",
                    help="trata os órfãos SEM teor: declara os de título desconhecido, "
                         "manda o resíduo para quarentena")
    a = ap.parse_args()
    alvos = ([ARQUIVO / a.processo] if a.processo
             else sorted(p for p in ARQUIVO.iterdir()
                         if p.is_dir() and not p.name.startswith("_")))
    if a.vazios:
        n = decl = res = 0
        for d in alvos:
            r = tratar_vazios(d, a.aplicar)
            if not r or not (r["declarados"] or r["residuo"]):
                continue
            n += 1
            decl += r["declarados"]
            res += r["residuo"]
            print(f"  {r['processo']}: {r['declarados']} declarado(s) sem teor · "
                  f"{r['residuo']} p/ quarentena")
        verbo = "tratados" if a.aplicar else "tratáveis (use --aplicar)"
        print(f"\n{n} processos {verbo} · {decl} documentos DECLARADOS (existem e não foram "
              f"capturados) · {res} arquivos de resíduo p/ quarentena")
        return 0
    n = docs = chars = 0
    for d in alvos:
        r = reconciliar(d, a.aplicar)
        if not r:
            continue
        n += 1
        docs += r["recuperados"]
        chars += r["chars"]
        print(f"  {r['processo']}: +{r['recuperados']} docs "
              f"({r['chars'] / 1024:.0f} KB) sobre {r['docs_antes']} declarados"
              + (f" · {r['superados']} entrada(s) superada(s)" if r["superados"] else ""))
    verbo = "reconciliados" if a.aplicar else "reconciliáveis (use --aplicar)"
    print(f"\n{n} processos {verbo} · {docs} documentos · {chars / 1024 / 1024:.1f} MB de texto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
