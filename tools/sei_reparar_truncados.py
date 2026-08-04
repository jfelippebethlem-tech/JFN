# -*- coding: utf-8 -*-
"""Devolve à fila os processos SEI cujo cache foi gravado TRUNCADO.

Defeito reparado (2026-07-23): o `timeout` do orquestrador matava o Chromium
junto com o Python (faltava `--foreground`). A árvore já extraída era gravada com
`conteudo_documentos: []` e o checkpoint marcava `n_docs>0` — pelo `_pular` do
sweep, esses processos NUNCA mais voltavam à fila. O SEI serviu; nós jogamos fora.

Este reparo é idempotente e NÃO apaga nada: move o cache suspeito para
`data/sei_cache/_truncados/` (auditoria) e zera a entrada no progress, para o
sweep relê-los normalmente. A guarda que impede novos casos vive em
`tools/sei_reader.leitura_truncada`.

    python -m tools.sei_reparar_truncados            # relatório (não escreve)
    python -m tools.sei_reparar_truncados --aplicar  # quarentena + volta à fila
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
PROGRESS = CACHE / "sei_sweep_progress.json"
QUARENTENA = CACHE / "_truncados"


def _numero_do_cache(caminho: Path) -> str | None:
    """cdp_SEI_270131_000140_2023.json → SEI-270131/000140/2023."""
    m = re.match(r"cdp_SEI_(\d+)_(\d+)_(\d+)\.json$", caminho.name)
    return f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None


def encontrar_truncados() -> list[tuple[Path, str | None, int]]:
    """Caches com árvore extraída mas ZERO conteúdo → leitura interrompida."""
    achados = []
    for f in sorted(CACHE.glob("cdp_SEI_*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        n_docs = len(d.get("documentos") or [])
        if n_docs > 0 and not (d.get("conteudo_documentos") or []):
            achados.append((f, _numero_do_cache(f), n_docs))
    return achados


def reparar(aplicar: bool = False) -> dict:
    achados = encontrar_truncados()
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {"feitos": {}}
    feitos = prog.setdefault("feitos", {})
    bloqueados = [n for _, n, _ in achados if n and (feitos.get(n, {}).get("n_docs") or 0) > 0]

    if aplicar and achados:
        QUARENTENA.mkdir(parents=True, exist_ok=True)
        for f, numero, _ in achados:
            shutil.move(str(f), str(QUARENTENA / f.name))
            if numero:
                # zera SEMPRE (não só se a chave existir): o `_pular` do sweep decide por
                # `n_docs>0` no progress — afastar o cache sem zerar aqui deixa o processo
                # marcado como lido E sem cache, que é o pior dos dois mundos (2026-08-02).
                feitos[numero] = {"n_docs": 0, "tentativas": 0,
                                  "em": datetime.now().isoformat(),
                                  "reparado_truncado_em": datetime.now().isoformat()}
        tmp = PROGRESS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prog, ensure_ascii=False))
        tmp.replace(PROGRESS)

    return {"encontrados": len(achados), "bloqueando_a_fila": len(bloqueados),
            "aplicado": aplicar, "quarentena": str(QUARENTENA)}


_JANELA_CAP = (19_800, 20_005)
"""Faixa de caracteres que denuncia o corte no cap de 20.000 do `sei_reader` (mesmo critério da
medição de 2026-08-01, mantido para comparar rodada com rodada)."""


def tags_no_cap() -> list[str]:
    """Processos com ao menos um documento parado na janela do cap — medidos AGORA, no acervo.

    Ordena pelo número de documentos cortados: quem perdeu mais texto volta primeiro.
    """
    from compliance_agent.sei import acervo_texto, manifesto_norm
    base = RAIZ / "data" / "sei_arquivo"
    if not base.is_dir():
        return []
    contagem: dict[str, int] = {}
    for pasta in sorted(base.iterdir()):
        mf = pasta / "manifest.json"
        if not pasta.is_dir() or not mf.exists():
            continue
        try:
            man = manifesto_norm.normalizar(json.loads(mf.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        n = 0
        for d in man.get("docs") or []:
            tam = len(acervo_texto.ler(pasta, d) or "")
            if _JANELA_CAP[0] <= tam <= _JANELA_CAP[1]:
                n += 1
        if n:
            contagem[pasta.name] = n
    return [tag for tag, _ in sorted(contagem.items(), key=lambda kv: kv[1], reverse=True)]


def reparar_cap(aplicar: bool = False, max_n: int = 40, tags: list[str] | None = None) -> dict:
    """Devolve à fila (bounded) os processos TRUNCADOS PELO CAP de 20k chars/doc (curado
    2026-08-01, SEI_MAX_CHARS_DOC=60000). Lista vem de data/recaptura_cap21k.json (gerada na
    medição: 1.660 docs no cap em 375 processos). Mesma mecânica da quarentena: cache afastado
    + progress zerado → o sweep relê no ritmo normal; com o cache fresco, o
    sei_arquivar_do_cache re-arquiva sozinho (candidatura por frescor, mesma data). Rodar aos
    poucos (--max) para não esvaziar a fila de leitura nova."""
    # A LISTA ERA ESTÁTICA PARA UM ALVO QUE SE MOVE. `data/recaptura_cap21k.json` foi curada uma
    # vez (2026-08-01, 375 processos) e nunca mais regerada; medido em 2026-08-04, o acervo tem
    # **2.025 documentos no cap em 446 processos** — a lista cobre 343, ignora **103 novos** e
    # ainda traz 32 já resolvidos. Processo capturado depois da curadoria nunca voltaria à fila.
    #
    # A medição em tempo de execução se autocorrige e dispensa a lista de "prioridade": um
    # processo já recapturado com o cap novo (60k) simplesmente não tem mais documento parado em
    # 20.000, então sai sozinho do conjunto — não há cache fresco a afastar por engano.
    # `tags` explícito atende o alvo DIRIGIDO: um processo com um único documento cortado fica no
    # fim da ordenação por perda e nunca entraria numa rodada bounded — foi o caso do
    # SEI-030001/111011/2025, segundo da fila do fiscal, cujo contrato para em 20.000 exatamente
    # onde ficam a assinatura e a data. Refilar à mão (mover cache + zerar progresso) é a mesma
    # operação com risco de errar; aqui ela é a rotina testada.
    tags = list(tags) if tags else tags_no_cap()
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {"feitos": {}}
    feitos = prog.setdefault("feitos", {})
    alvos = []
    for t in tags:
        for cand in (CACHE / f"cdp_SEI_{t}.json", CACHE / f"cdp_SEI_{t}.json.zst"):
            if cand.exists():
                alvos.append((cand, f"SEI-{t.replace('_', '/', 1).replace('_', '/', 1)}"))
                break
        if len(alvos) >= max_n:
            break
    sumidos = 0
    if aplicar and alvos:
        QUARENTENA.mkdir(parents=True, exist_ok=True)
        for f, numero in alvos:
            try:
                shutil.move(str(f), str(QUARENTENA / f.name))
            except FileNotFoundError:
                # O cache existia na varredura e sumiu antes do move: o compactador troca
                # `.json` por `.json.zst` (e o reindex recria o bruto) enquanto isto roda. A
                # exceção subia e MATAVA a rodada depois de já ter afastado os caches
                # anteriores — e o progresso, escrito só no fim, nunca era gravado: os
                # processos ficavam sem cache E marcados como lidos, que é exatamente o que o
                # comentário de `reparar()` adverte. Medido no cron de 05:40 (2026-08-03).
                sumidos += 1
                continue
            feitos[numero] = {"n_docs": 0, "tentativas": 0,
                              "em": datetime.now().isoformat(),
                              "reparado_cap21k_em": datetime.now().isoformat()}
        tmp = PROGRESS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prog, ensure_ascii=False))
        tmp.replace(PROGRESS)
    return {"encontrados": len(alvos), "aplicado": aplicar, "sumidos_no_move": sumidos,
            "quarentena": str(QUARENTENA)}


def reparar_sem_texto(aplicar: bool = False, max_n: int = 60) -> dict:
    """Processos ARQUIVADOS sem nenhum documento com texto — captura incompleta virada acervo.

    Achados pela `sentinela_integridade` (147 em 2026-08-02, todos de `integra_*` de julho, com
    os PDFs ausentes do disco: o manifest listava documentos, o texto nunca existiu). Para o
    motor, isso é indistinguível de "processo sem conteúdo" — a mesma mentira por omissão do
    cache-caixa. A cura é a da casa: **declarar** (`captura_vazia: true`, que o manifest já
    prevê e a sentinela respeita) e devolver à fila zerando o progress. Nada é apagado.
    """
    from compliance_agent.sei import manifesto_norm  # noqa: F401  (garante o pacote no path)
    arquivo = RAIZ / "data" / "sei_arquivo"
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {"feitos": {}}
    feitos = prog.setdefault("feitos", {})
    alvos = []
    for man in sorted(arquivo.glob("*/manifest.json")):
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("captura_vazia"):
            continue
        docs = m.get("docs") or []
        if any(int(d.get("chars") or 0) > 50 for d in docs):
            continue
        alvos.append((man, m))
        if len(alvos) >= max_n:
            break
    if aplicar:
        for man, m in alvos:
            m["captura_vazia"] = True
            m["aviso"] = ("captura INCOMPLETA: o manifest lista documentos mas nenhum texto foi "
                          "extraído e os PDFs não estão no cache. NÃO interpretar como processo "
                          "sem documentos — reprocessar (marcado em 2026-08-02).")
            tmp = man.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
            tmp.replace(man)
            p = man.parent.name.split("_")
            if len(p) == 3:
                numero = f"SEI-{p[0]}/{p[1]}/{p[2]}"
                feitos[numero] = {"n_docs": 0, "tentativas": 0,
                                  "em": datetime.now().isoformat(),
                                  "reparado_sem_texto_em": datetime.now().isoformat()}
        tmp = PROGRESS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prog, ensure_ascii=False))
        tmp.replace(PROGRESS)
    return {"encontrados": len(alvos), "aplicado": aplicar}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true",
                    help="move os caches truncados p/ quarentena e devolve à fila")
    ap.add_argument("--cap", action="store_true",
                    help="modo cauda-longa do cap 20k: requeue bounded da lista recaptura_cap21k.json")
    ap.add_argument("--max", type=int, default=40, help="(com --cap/--sem-texto) teto por rodada")
    ap.add_argument("--processo", action="append", default=[],
                    help="(com --cap) refila SÓ estes processos, por tag (ex.: 030001_111011_2025)")
    ap.add_argument("--sem-texto", action="store_true",
                    help="declara captura_vazia e refila os processos arquivados sem texto algum")
    args = ap.parse_args()
    if args.sem_texto:
        r = reparar_sem_texto(aplicar=args.aplicar, max_n=args.max)
        print(f"arquivos sem texto: {r['encontrados']} na rodada · aplicado={r['aplicado']}")
        return
    if args.cap:
        r = reparar_cap(aplicar=args.aplicar, max_n=args.max, tags=args.processo or None)
        print(f"cap21k: {r['encontrados']} cache(s) na rodada · aplicado={r['aplicado']}"
              + (f" · {r['sumidos_no_move']} sumiram antes do move"
                 if r.get("sumidos_no_move") else "")
              + (f" · {r.get('erro')}" if r.get("erro") else ""))
        return
    r = reparar(aplicar=args.aplicar)
    print(f"caches truncados encontrados : {r['encontrados']}")
    print(f"  ...que travavam a fila     : {r['bloqueando_a_fila']}")
    if not args.aplicar:
        print("\n(relatório apenas — rode com --aplicar para reparar)")
    else:
        print(f"movidos para                 : {r['quarentena']}")
        print("progress zerado — os processos voltam à fila no próximo sweep.")


if __name__ == "__main__":
    main()
