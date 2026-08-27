#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arquiva processos SEI a partir do TEXTO QUE JÁ ESTÁ NO CACHE — sem browser, sem login, sem SEI.

Achado que originou a ferramenta (2026-07-24): o sweep lê o processo e guarda o texto em
`data/sei_cache/cdp_*.json` (campo `conteudo_documentos`), mas o ARQUIVO consultável
(`data/sei_arquivo/<proc>/`) só era montado pela fila de íntegras, que precisa de browser e sessão. O
resultado medido:

    5.401 processos no cache
      346 arquivados
    4.655 COM TEXTO no cache e NÃO arquivados — 107.951.833 caracteres parados

Ou seja: o SEI já serviu 108 milhões de caracteres, e o motor de análise (execução, parecer da PGE,
fracionamento, direcionamento) não enxergava nada disso, porque todos leem o ARQUIVO. Converter é de
graça e instantâneo — é só transpor o formato.

Honesto: o arquivo gerado declara `origem: cache CDP` e `via` de cada documento (leitura direta ou OCR),
para nunca se confundir com a captura completa da íntegra (que traz também fotos e anexos binários).
Idempotente: pula o que já está arquivado com texto; nunca sobrescreve captura boa.

Uso:
    python -m tools.sei_arquivar_do_cache                 # relatório (não escreve)
    python -m tools.sei_arquivar_do_cache --aplicar       # arquiva tudo o que dá
    python -m tools.sei_arquivar_do_cache --aplicar --max 500
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.sei.cache_arquivo import glob_cache, ler_json

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"
MIN_CHARS = 500          # cache com menos que isso não vale arquivar (é cabeçalho/erro)

# ── VERIFICAÇÃO DE INTEGRIDADE (2026-07-24, depois de o dono perguntar "estão íntegros?") ──
# Comparando, nos 47 processos que têm AS DUAS fontes, o texto do cache com o PDF da íntegra capturada
# por browser, apareceu o corte: `cache 400 vs pdf 7.926 chars`, `400 vs 8.317`, repetidamente. Parte dos
# caches guarda só uma AMOSTRA de ~400 caracteres por documento — e o número de documentos também não
# bate (cache 2-7 docs contra 7-137 PDFs).
# Arquivar isso seria pior que não arquivar: o processo PARECERIA capturado e o motor daria veredito
# sobre migalhas. Medido no acervo: 1.831 caches completos (110 M chars) contra 3.219 amostras.
_CORTE_MIN, _CORTE_MAX = 390, 410      # a faixa exata onde o corte do sweep para
_FRACAO_AMOSTRA = 0.8                  # ≥80% dos docs no corte ⇒ é amostra, não conteúdo


def qualidade_cache(conteudo_documentos: list) -> str:
    """'completo' | 'amostra' | 'misto' — só 'completo' pode virar arquivo consultável."""
    # EXCERTO DE STORAGE FORA DA CONTA. `_trimado` marca documento JÁ LIDO cujo texto cru virou
    # excerto de 400 chars depois que a ficha foi extraída (tools/sei_sweep.py) — é política de
    # armazenamento, não captura rasa. Medido 2026-08-09: num processo RELIDO por inteiro a fusão
    # de cache preserva os excertos antigos, e 8 deles ao lado de 34 leituras íntegras davam
    # 9/42 = 21% na faixa do corte ⇒ "misto" ⇒ arquivador RECUSAVA o processo mais bem lido do
    # lote. Sem eles: 1/34 = 3% ⇒ "completo". Se SÓ houver excertos, não há leitura a arquivar e
    # o caminho de baixo devolve "amostra" como antes.
    lidos = [x for x in (conteudo_documentos or [])
             if not (isinstance(x, dict) and x.get("_trimado"))]
    tam = [len(str(x.get("conteudo") or x.get("texto") or "")) for x in lidos]
    if not tam:
        return "amostra"
    frac = sum(1 for t in tam if _CORTE_MIN <= t <= _CORTE_MAX) / len(tam)
    if frac >= _FRACAO_AMOSTRA:
        return "amostra"
    return "completo" if frac <= 0.2 else "misto"


def _slug_processo(numero: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (numero or "").replace("SEI-", "")).strip("_")


def _slug_arquivo(titulo: str, i: int) -> str:
    t = unicodedata.normalize("NFD", (titulo or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:60] or "documento"
    return f"{i:03d}_{t}.txt"


def _ja_arquivado(numero: str) -> bool:
    d = ARQUIVO / _slug_processo(numero)
    if not (d / "manifest.json").exists():
        return False
    td = d / "texto"
    return td.is_dir() and any(f.stat().st_size > 200 for f in td.glob("*.txt"))


def candidatos(min_chars: int = MIN_CHARS) -> list[dict]:
    """Caches com texto suficiente e ainda não arquivados, do maior conteúdo para o menor."""
    out = []
    # `glob_cache`/`ler_json`, NÃO `Path.glob` + `read_text`: 5.660 dos 6.195 blobs do acervo
    # estão em `.json.zst`, e com o glob cru este arquivador enxergava **535 (8,6%)**. O resto do
    # cache — texto já pago, já lido do SEI — simplesmente não tinha caminho para virar arquivo
    # consultável. É a terceira ferramenta desta casa cega à compressão; as duas primeiras estão
    # no catálogo, e uma delas era a ÚNICA que gravava `sei_ficha`.
    for f in glob_cache(CACHE, "cdp_*.json"):
        f = Path(f)
        try:
            d = ler_json(f)
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        numero = (d.get("numero") or "").strip()
        cd = d.get("conteudo_documentos") or []
        if not numero or not cd:
            continue
        if _ja_arquivado(numero):
            # RE-arquiva quando o CACHE é mais novo que o arquivo (releitura pós-cura do cap de
            # 20k, 2026-08-01): sem isto, o sweep relia o processo e o arquivo truncado ficava
            # para sempre. `arquivar()` afasta o arquivo antigo p/ _substituido/ (nada se apaga).
            man = ARQUIVO / _slug_processo(numero) / "manifest.json"
            try:
                if man.stat().st_mtime >= f.stat().st_mtime:
                    continue
            except OSError:
                continue
        chars = sum(len(str(x.get("conteudo") or x.get("texto") or "")) for x in cd)
        q = qualidade_cache(cd)
        if q != "completo":
            continue          # amostra truncada NÃO vira arquivo (veredito sobre migalha é pior que nada)
        if chars >= min_chars:
            out.append({"numero": numero, "cache": f, "dados": d, "n_docs": len(cd), "chars": chars,
                        "qualidade": q,
                        # O TAMANHO DA ÁRVORE É UM FATO QUE ESTE ARQUIVO JÁ TINHA EM MÃOS e jogava
                        # fora. Sem ele o manifesto saía com `lacunas: []` sobre 40 de 956
                        # documentos, e o motor lia ausência de prova como ausência do fato.
                        "na_arvore": len(d.get("documentos") or [])})
    out.sort(key=lambda e: -e["chars"])
    return out


def arquivar(item: dict, aplicar: bool = False) -> dict:
    """Monta `data/sei_arquivo/<proc>/` (manifest.json + texto/) no MESMO formato da captura de íntegra,
    para que todo o motor de análise leia sem saber a diferença."""
    from compliance_agent.sei.classificador_doc import classificar_doc
    from compliance_agent.sei.fases import linha_do_tempo

    numero = item["numero"]
    destino = ARQUIVO / _slug_processo(numero)
    # arquivo antigo (re-arquivamento por cache mais novo): AFASTA, nunca apaga — escrever por
    # cima misturaria txt de duas gerações com conjuntos de docs diferentes.
    if aplicar and (destino / "manifest.json").exists():
        # NUNCA substituir por versão com MENOS informação: arquivo vindo da ÍNTEGRA pode ter
        # docs além do teto SEI_MAX_DOCS do cache (ex.: 070026/000410/2021, 246 docs na árvore,
        # pareceres no doc 92/204). Se o antigo tem mais docs com texto, mantém o antigo.
        try:
            velho = json.loads((destino / "manifest.json").read_text())
            docs_velho = sum(1 for x in (velho.get("docs") or []) if int(x.get("chars") or 0) > 50)
        except (OSError, json.JSONDecodeError, ValueError):
            docs_velho = 0
        docs_novo = sum(1 for x in (item["dados"].get("conteudo_documentos") or [])
                        if len(str(x.get("conteudo") or x.get("texto") or "")) > 50)
        if docs_velho > docs_novo:
            # SAIR DO LAÇO SEM APAGAR NADA. A decisão de manter o antigo é certa, mas ela não mexia
            # no manifesto — e a fila é montada por "cache mais novo que o manifesto". Resultado
            # medido em 2026-08-15: o `070002/019153/2024` reaparecia em TODO disparo do lane
            # (a cada 20 min), era recontado como "arquivado" e nada era escrito; o manifesto seguia
            # com a data da véspera. Tocar o `mtime` encerra a repetição e não perde informação: o
            # conteúdo do arquivo continua exatamente o mesmo.
            try:
                (destino / "manifest.json").touch()
            except OSError:
                pass
            return {"numero": numero, "docs": 0, "chars": 0, "escritos": 0,
                    "mantido_antigo": f"{docs_velho} docs c/ texto no arquivo × {docs_novo} no cache"}
        import shutil
        sub = ARQUIVO / "_substituido" / f"{destino.name}__{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        sub.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destino), str(sub))
    docs_manifest, titulos, escritos = [], [], 0
    for i, doc in enumerate(item["dados"].get("conteudo_documentos") or []):
        titulo = str(doc.get("doc") or doc.get("titulo") or f"documento {i}").strip()
        conteudo = str(doc.get("conteudo") or doc.get("texto") or "").strip()
        via = str(doc.get("via") or "").strip()
        rel = f"texto/{_slug_arquivo(titulo, i)}"
        titulos.append(titulo)
        docs_manifest.append({
            "i": str(i), "titulo": titulo,
            "fase": "", "tipo": classificar_doc(titulo, conteudo[:1500]),
            "texto": rel, "chars": str(len(conteudo)),
            "ocr": "True" if via == "ocr" else "False", "fotos": "[]", "via_cache": via or "leitura",
        })
        if aplicar:
            f = destino / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            cabecalho = f"[{titulo}] (tipo: {docs_manifest[-1]['tipo']})\n\n"
            f.write_text(cabecalho + conteudo, encoding="utf-8")
            escritos += 1
    manifest = {
        "processo": numero.replace("SEI-", ""),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # deixa explícito que veio do cache: não tem fotos nem anexos binários, ao contrário da íntegra
        "origem": f"cache CDP ({item['cache'].name}) — texto já lido pelo sweep, arquivado sem browser",
        "modalidade": "", "docs": docs_manifest,
        "linha_do_tempo": linha_do_tempo(titulos),
        "docs_na_arvore": item.get("na_arvore") or len(docs_manifest),
        "lacunas": ([] if (item.get("na_arvore") or 0) <= len(docs_manifest) else
                    [{"tipo": "captura_truncada",
                      "detalhe": (f"a árvore do processo tem {item['na_arvore']} documentos e o "
                                  f"cache trouxe {len(docs_manifest)} — faltam "
                                  f"{item['na_arvore'] - len(docs_manifest)}"),
                      "faltam": item["na_arvore"] - len(docs_manifest),
                      "consequencia": ("ausência de documento NESTE arquivo é lacuna de CAPTURA, "
                                       "não do processo — nenhuma acusação de ausência pode se "
                                       "apoiar nele até a recaptura")}]),
        "fotos_total": 0,
        "aviso": ("arquivo montado a partir do CACHE do sweep: contém o TEXTO dos documentos, não os "
                  "anexos binários nem as fotos de medição — para esses, capturar a íntegra"),
        "qualidade_cache": item.get("qualidade", "completo"),
        "verificacao": ("integridade conferida: caches com corte fixo de ~400 chars/doc (amostra) são "
                        "recusados; este veio de cache com texto completo"),
    }
    if aplicar:
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (destino / "fotos").mkdir(exist_ok=True)
    return {"numero": numero, "docs": len(docs_manifest), "chars": item["chars"], "escritos": escritos}


def retro_arvore(aplicar: bool = False) -> dict:
    """Grava `docs_na_arvore` nos manifestos JÁ ESCRITOS, lendo o tamanho da árvore no cache.

    SEM ISTO O CONSERTO NÃO ALCANÇA O ACERVO. Os 2.216 arquivos existentes foram montados por uma
    versão que jogava fora o tamanho da árvore, e o gate de captura íntegra continuaria decidindo
    por heurística — o número redondo 40 — sobre todos eles. Medido em 2026-08-07: dos 198 parados
    em 40, **171 estão de fato truncados** (o pior tem 40 de 956) e **21 têm árvore de exatamente
    40**, isto é, estão completos e vinham sendo excluídos da análise à toa.

    Idempotente e conservador: só escreve onde o campo falta E o cache traz a árvore. Manifesto
    sem cache correspondente fica como está — inventar o número seria pior que não tê-lo.
    """
    idx = {}
    for c in glob_cache(CACHE, "cdp_*.json"):
        nome = Path(c).name.replace(".zst", "").replace(".json", "")[4:]
        idx[re.sub(r"\D", "", nome)] = c

    r = {"manifestos": 0, "ja_tinham": 0, "sem_cache": 0, "gravados": 0,
         "truncados": 0, "completos_liberados": 0}
    for pasta in sorted(ARQUIVO.iterdir()):
        man = pasta / "manifest.json"
        if not man.is_file():
            continue
        r["manifestos"] += 1
        try:
            j = json.loads(man.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(j.get("docs_na_arvore"), int):
            r["ja_tinham"] += 1
            continue
        c = idx.get(re.sub(r"\D", "", pasta.name))
        if not c:
            r["sem_cache"] += 1
            continue
        try:
            d = ler_json(c)
        except (json.JSONDecodeError, OSError, ValueError):
            r["sem_cache"] += 1
            continue
        arv = len(d.get("documentos") or [])
        if arv <= 0:
            r["sem_cache"] += 1
            continue
        n = len(j.get("docs") or [])
        j["docs_na_arvore"] = arv
        if arv > n:
            r["truncados"] += 1
            faltam = arv - n
            lac = [x for x in (j.get("lacunas") or []) if x.get("tipo") != "captura_truncada"]
            lac.append({"tipo": "captura_truncada",
                        "detalhe": (f"a árvore do processo tem {arv} documentos e o arquivo tem "
                                    f"{n} — faltam {faltam}"),
                        "faltam": faltam,
                        "consequencia": ("ausência de documento NESTE arquivo é lacuna de CAPTURA, "
                                         "não do processo — nenhuma acusação de ausência pode se "
                                         "apoiar nele até a recaptura")})
            j["lacunas"] = lac
        elif n == 40:
            # árvore de exatamente 40: o arquivo está COMPLETO e a heurística o punia
            r["completos_liberados"] += 1
        if aplicar:
            man.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        r["gravados"] += 1
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="limita quantos processos arquivar (0 = todos)")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    # `--so`: arquivar UM processo. A passada de recaptura (`sweep_recaptura_integral`) relê um
    # processo por vez com o teto levantado e precisa materializar SÓ ele — varrer o acervo
    # inteiro a cada processo relido custaria minutos por iteração numa VM de 2 vCPU.
    ap.add_argument("--so", default="", help="arquivar apenas este processo (número SEI)")
    ap.add_argument("--retro-arvore", action="store_true",
                    help="grava docs_na_arvore nos manifestos já escritos (não arquiva nada novo)")
    a = ap.parse_args(argv)
    if a.retro_arvore:
        r = retro_arvore(aplicar=a.aplicar)
        for k, v in r.items():
            print(f"{k:22s} {v:,}")
        if not a.aplicar:
            print("\n(SIMULAÇÃO — use --aplicar)")
        return 0
    alvos = candidatos(a.min_chars)
    if a.so:
        alvo_norm = re.sub(r"\D", "", a.so)
        alvos = [x for x in alvos if re.sub(r"\D", "", x["numero"]) == alvo_norm]
    if a.max:
        alvos = alvos[:a.max]
    total_chars = sum(x["chars"] for x in alvos)
    # RÓTULO É CONTRATO SEMÂNTICO. Esta linha dizia "sem arquivo", texto congelado na população
    # original — mas `candidatos()` passou a incluir também quem TEM arquivo DESATUALIZADO
    # (re-arquivamento por frescor, 2026-08-01). Medido em 2026-08-27: o lane imprimia "0" disparo
    # após disparo enquanto 98 processos tinham cache mais novo que o manifesto, 32 deles já
    # `completo` — um com 787.668 chars parados. Fila que se declara vazia não é investigada.
    novos = sum(1 for x in alvos
                if not (ARQUIVO / _slug_processo(x["numero"]) / "manifest.json").exists())
    print(f"processos do cache a arquivar: {len(alvos):,} — {total_chars:,} caracteres "
          f"({novos:,} sem arquivo · {len(alvos) - novos:,} com cache mais novo que o arquivo)")
    if not alvos:
        return 0
    feitos = mantidos = 0
    chars_escritos = 0
    for x in alvos:
        r = arquivar(x, aplicar=a.aplicar)
        feitos += 1
        if r.get("mantido_antigo"):
            mantidos += 1
        else:
            chars_escritos += r.get("chars") or 0
        if feitos <= 5 or feitos % 500 == 0:
            print(f"  {feitos:5d}. {r['numero']:28s} {r['docs']:3d} docs  {r['chars']:>9,} chars"
                  + (f"  [mantido: {r['mantido_antigo']}]" if r.get("mantido_antigo") else ""))
    # CONTAR O QUE FOI ESCRITO, NÃO O QUE ENTROU NA FILA. O total saía de `alvos` — o ESPERADO — e
    # somava também os processos em que nada foi escrito. O `070002/019153/2024` era relatado como
    # "arquivados: 1 processos · 185.203 caracteres" em todo disparo, com zero bytes gravados.
    # Prometer entrega que não houve é o vício de ler o `200` como prova de entrega.
    print(f"\n{'arquivados' if a.aplicar else 'arquivaria'}: {feitos - mantidos:,} processos · "
          f"{chars_escritos:,} caracteres"
          + (f" · {mantidos:,} mantidos (arquivo existente é mais completo que o cache)"
             if mantidos else "")
          + ("" if a.aplicar else "  (SIMULAÇÃO — use --aplicar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
