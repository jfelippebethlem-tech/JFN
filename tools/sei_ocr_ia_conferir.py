"""Conferência dos números críticos lidos pelo OCR por IA (Surya na GPU / reserva RapidOCR) — trava em
`compliance_agent/sei/ocr_ia_prova.py` (leia o cabeçalho de lá: por que, estados e fontes).

    python -m tools.sei_ocr_ia_conferir confirmar --limite 20 [--ensaio] [--tag T] [--sem-pdf]
        segunda leitura automática por documento de IA: outro motor ao lado, Tesseract/nativo na MESMA página do PDF,
        SIAFE (OB/NE) e documentos não-IA do mesmo processo. Grava o resultado no registro (não com --ensaio).
    python -m tools.sei_ocr_ia_conferir pendentes [--limite 50] [--json]
        divergentes e a conferir, primeiro os de processo que alimenta laudo de execução em risco, depois o valor.
    python -m tools.sei_ocr_ia_conferir ficha <tag> <doc> [--saida DIR]
        folha de conferência HTML: a página (imagem) + leitura da IA + segunda leitura + números em disputa.
    python -m tools.sei_ocr_ia_conferir marcar <tag> <doc> <numero> confirmado|errado --por <quem> [--tipo T]
        decisão de quem olhou a página (vale sobre a automática).
    python -m tools.sei_ocr_ia_conferir opus [--limite 20] [--ensaio]
        põe os DIVERGENTES na fila única de conferência do Opus (`llm/conferencia_opus`, assinatura; nunca API paga).

O PDF vem de `data/sei_cache/integra_<tag>/NNN.pdf`; senão do cache do frio (`armazenamento.cache_frio()`), trazido
da VM-2 (`~/arquivo_frio/{sei_cache,sei_pdfs}`) ou pelo índice do armazenamento (`armazenamento.obter`). Sem PDF, a
confirmação usa só as outras fontes — o número continua a conferir, nunca vira zero. VM de 2 vCPU: o Tesseract roda
com nice 19, uma página por vez, só nas páginas onde a IA leu número (marcadores `[página N]` da entrega crua).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from compliance_agent.sei import acervo_texto
from compliance_agent.sei import ocr_ia_prova as P

DATA = P.DATA
CACHE = DATA / "sei_cache"
FICHAS = DATA / "sei_ocr_ia_fichas"
_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


# ── documentos de IA e o PDF de cada um ──────────────────────────────────────────────────────────
def docs_ia(tag: str | None = None):
    """(pasta, doc) de cada documento cujo texto canônico veio do OCR por IA."""
    pastas = [acervo_texto.RAIZ / tag] if tag else sorted(p.parent for p in acervo_texto.RAIZ.glob("*/manifest.json"))
    for pasta in pastas:
        for d in (acervo_texto.manifesto(pasta) or {}).get("docs") or []:
            if isinstance(d, dict) and P.eh_ocr_ia(d) and str(d.get("i", "")).isdigit():
                yield pasta, d


def _rel(tag: str, i) -> str:
    return f"integra_{tag}/{int(i):03d}.pdf"


def pdf_do_documento(tag: str, i, trazer: bool = True) -> Path | None:
    rel = _rel(tag, i)
    local = CACHE / rel
    if local.exists():
        return local
    from compliance_agent import armazenamento
    frio = armazenamento.cache_frio() / "sei_ocr_ia" / rel
    if frio.exists():
        return frio
    if not trazer:
        return None
    frio.parent.mkdir(parents=True, exist_ok=True)
    for base in ("sei_cache", "sei_pdfs"):        # VM-2: o arquivo frio dos escaneados (`sei_ocr_gpu_fila`)
        try:
            r = subprocess.run([*_SSH, "vm2", f"cat ~/arquivo_frio/{base}/{rel}"],
                               capture_output=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            break
        if r.returncode == 0 and r.stdout[:5] == b"%PDF-":
            tmp = frio.with_suffix(".tmp")
            tmp.write_bytes(r.stdout)
            tmp.replace(frio)
            return frio
    try:
        return armazenamento.obter(local)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None


def entrega_crua(tag: str, i, motor: str) -> str:
    """Texto cru que o trabalhador entregou (com `[página N]`) — dá a página de cada número."""
    suf = ".ocr_gpu.txt" if motor.startswith("surya") else ".ocr_reserva.txt"
    p = CACHE / f"integra_{tag}" / f"{int(i):03d}{suf}"
    for q in (p, p.with_name(p.name + ".zst")):
        try:
            if q.suffix == ".zst":
                import zstandard
                return zstandard.ZstdDecompressor().decompress(q.read_bytes()).decode("utf-8", "replace")
            return q.read_text(encoding="utf-8", errors="replace")
        except (OSError, ImportError, ValueError):
            continue
    return ""


# ── confirmar ────────────────────────────────────────────────────────────────────────────────────
def confirmar_documento(pasta: Path, d: dict, *, usar_pdf: bool = True, con=None) -> dict:
    tag, i = pasta.name, int(d["i"])
    texto = acervo_texto.ler(pasta, d)
    numeros = P.extrair(texto)
    out = {"tag": tag, "i": i, "tipo_doc": d.get("tipo"), "motor": d.get("ocr_motor"), "numeros": len(numeros),
           "pdf": None, "paginas": [], "segundos_ocr": 0.0, "resultados": []}
    if not numeros:
        return out
    leituras = P.leituras_ao_lado(pasta, d)
    if usar_pdf:
        pdf = pdf_do_documento(tag, i)
        out["pdf"] = str(pdf) if pdf else "INDISPONÍVEL"
        if pdf:
            paginas = P.paginas_com(numeros, P.paginas_da_ia(entrega_crua(tag, i, str(d.get("ocr_motor") or ""))))
            t0 = time.monotonic()
            try:
                lido = P.ler_pdf(pdf, paginas or None)
                leituras.update(lido["leituras"])
                out["paginas"], out["seg_por_pagina"] = lido["paginas"], lido["segundos"]
            except (OSError, RuntimeError, ValueError) as e:          # PDF ilegível: as outras fontes seguem
                out["pdf"] = f"ilegível: {type(e).__name__}"
            out["segundos_ocr"] = round(time.monotonic() - t0, 1)
    externos, outros = _do_processo(pasta, con)
    res = P.confirmar_numeros(numeros, leituras, externos, outros)
    out["resultados"] = [{"tag": tag, "i": i, **r} for r in res]
    return out


_PROC: dict = {}


def _do_processo(pasta: Path, con=None) -> tuple[dict, dict]:
    """(SIAFE do processo, números dos documentos NÃO-IA) — uma vez por processo (o lote anda processo a processo;
    um processo de 280 peças custava ~20 s por documento relido)."""
    if pasta.name not in _PROC:
        _PROC.clear()
        numero_sei = acervo_texto.pasta_para_numero(pasta.name)
        externos = P.fontes_externas(numero_sei, con)
        externos["proprio_processo"] = {("processo", P.normalizar("processo", numero_sei.replace("SEI-", "")))}
        _PROC[pasta.name] = (externos, P.outros_documentos(pasta, None))
    return _PROC[pasta.name]


def _ja_decidido(pasta: Path, d: dict) -> bool:
    texto = acervo_texto.ler(pasta, d)
    return all(P.decisao(pasta.name, d["i"], n["tipo"], n["norma"]) for n in P.extrair(texto))


def cmd_confirmar(a) -> int:
    try:
        os.nice(19)
    except OSError as ex:
        print(f"  aviso: sem baixar prioridade (os.nice): {ex}", file=sys.stderr)
    con = None
    feitos, conta, t0 = [], {e: 0 for e in P.ESTADOS}, time.monotonic()
    for pasta, d in docs_ia(a.tag):
        if len(feitos) >= a.limite:
            break
        if not a.refazer and _ja_decidido(pasta, d):
            continue
        r = confirmar_documento(pasta, d, usar_pdf=not a.sem_pdf, con=con)
        feitos.append(r)
        for x in r["resultados"]:
            conta[x["estado"]] += 1
        if not a.ensaio:
            P.registrar(r["resultados"])
        print(json.dumps({k: r[k] for k in ("tag", "i", "tipo_doc", "numeros", "pdf", "paginas", "segundos_ocr")}
                         | {"estados": {e: sum(x["estado"] == e for x in r["resultados"]) for e in P.ESTADOS}},
                         ensure_ascii=False), flush=True)
    resumo = {"documentos": len(feitos), "numeros": sum(conta.values()), **conta,
              "por_fonte": _por_fonte(feitos), "por_tipo": _por_tipo(feitos),
              "segundos": round(time.monotonic() - t0, 1), "gravado": not a.ensaio}
    print(json.dumps(resumo, ensure_ascii=False))
    if a.saida:
        Path(a.saida).write_text(json.dumps(feitos, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def _por_fonte(feitos) -> dict:
    c: dict[str, int] = {}
    for r in feitos:
        for x in r["resultados"]:
            if x["estado"] == "confirmado":
                f = x["fonte"].split("_")[0] if x["fonte"].startswith("documento_") else x["fonte"]
                c[f] = c.get(f, 0) + 1
    return c


def _por_tipo(feitos) -> dict:
    c: dict[str, dict] = {}
    for r in feitos:
        for x in r["resultados"]:
            c.setdefault(x["tipo"], {e: 0 for e in P.ESTADOS})[x["estado"]] += 1
    return c


# ── pendentes ────────────────────────────────────────────────────────────────────────────────────
def pendentes() -> list[dict]:
    """Divergentes e a conferir (decisão automática sem humana), priorizados: processo com laudo de execução em risco
    (o que alimenta laudo/alerta) → divergente antes de a conferir → maior valor."""
    auto, humano = P._carregar()
    try:
        from tools.sei_ocr_gpu_fila import tags_risco_alto
        risco = tags_risco_alto()
    except (ImportError, OSError):
        risco = set()
    out = []
    for k, e in auto.items():
        if k in humano or e.get("estado") not in ("divergente", "a_conferir"):
            continue
        valor = float(e["norma"]) if e["tipo"] == "valor" else 0.0
        out.append({**e, "risco_alto": e["tag"] in risco, "valor": valor})
    out.sort(key=lambda e: (not e["risco_alto"], e["estado"] != "divergente", -e["valor"]))
    return out


def cmd_pendentes(a) -> int:
    lst = pendentes()[: a.limite]
    if a.json:
        print(json.dumps(lst, ensure_ascii=False, indent=1))
        return 0
    for e in lst:
        print(f"{'!' if e['risco_alto'] else ' '} {e['estado']:<10} {e['tag']} doc {e['i']:<4} {e['tipo']:<8} "
              f"IA={e['literal']!s:<22} 2ª={e.get('literal_2') or '—'}  ({e.get('fonte') or 'sem 2ª fonte'})")
    print(f"{len(lst)} de {len(pendentes())} pendente(s). Ficha: python -m tools.sei_ocr_ia_conferir ficha <tag> <doc>")
    return 0


# ── ficha ────────────────────────────────────────────────────────────────────────────────────────
def _png_pagina(pdf: Path, pagina: int, dpi: int = 110) -> str:
    import fitz
    with fitz.open(pdf) as doc:
        return base64.b64encode(doc.load_page(pagina - 1).get_pixmap(dpi=dpi).tobytes("png")).decode()


def _realce(texto: str, literais: set[str]) -> str:
    t = html.escape(texto)
    for lit in sorted(literais, key=len, reverse=True):
        t = t.replace(html.escape(lit), f"<mark>{html.escape(lit)}</mark>")
    return t


def ficha(tag: str, i: int, saida: Path | None = None) -> Path:
    pasta = acervo_texto.RAIZ / tag
    d = next((x for x in (acervo_texto.manifesto(pasta) or {}).get("docs") or [] if str(x.get("i")) == str(i)), None)
    if d is None:
        raise SystemExit(f"documento {i} não está no manifesto de {tag}")
    texto = acervo_texto.ler(pasta, d)
    nums = {(n["tipo"], n["norma"]): n for n in P.extrair(texto)}
    por_pag = P.paginas_da_ia(entrega_crua(tag, i, str(d.get("ocr_motor") or "")))
    linhas, disputa = [], set()
    for (tipo, norma), n in nums.items():
        e = P.decisao(tag, i, tipo, norma) or {}
        est = e.get("estado", "a_conferir")
        if est != "confirmado":
            disputa.add(n["literal"])
        linhas.append(f"<tr class='{est}'><td>{tipo}</td><td><b>{html.escape(n['literal'])}</b></td>"
                      f"<td>{html.escape(str(e.get('literal_2') or '—'))}</td><td>{est}</td>"
                      f"<td>{html.escape(str(e.get('fonte') or e.get('por') or '—'))}</td>"
                      f"<td>{', '.join(str(p) for p in P.paginas_com([n], por_pag)) or '?'}</td>"
                      f"<td><code>marcar {tag} {i} {html.escape(n['literal'])} confirmado|errado --por …</code></td></tr>")
    pdf = pdf_do_documento(tag, i)
    paginas = sorted({p for n in nums.values() if n["literal"] in disputa for p in P.paginas_com([n], por_pag)})[:6] \
        or [1]                     # sem página conhecida: a 1ª (e, sem entrega crua, o texto inteiro da IA)
    blocos = []
    for p in paginas:
        ia = por_pag.get(p) or (texto if not por_pag else "")
        seg = ""
        if pdf:
            try:
                seg = P.ler_pdf(pdf, [p])["leituras"]
                seg = "\n".join(seg.values())
            except (OSError, RuntimeError, ValueError):
                seg = "(PDF ilegível)"
        img = f"<img src='data:image/png;base64,{_png_pagina(pdf, p)}'>" if pdf else "<p>PDF INDISPONÍVEL</p>"
        blocos.append(f"<section><h2>Página {p}</h2><div class='g'><div>{img}</div>"
                      f"<div><h3>Leitura da IA ({html.escape(str(d.get('ocr_motor')))})</h3>"
                      f"<pre>{_realce(ia, disputa)}</pre></div>"
                      f"<div><h3>Segunda leitura (Tesseract/nativo)</h3><pre>{_realce(seg, disputa)}</pre></div>"
                      f"</div></section>")
    doc_html = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Conferência OCR IA {tag} doc {i}</title>
<style>:root{{--fg:#1b1f24;--bg:#fff;--mut:#5b6470;--lin:#d0d7de}}
body{{font:14px/1.45 system-ui,sans-serif;color:var(--fg);background:var(--bg);margin:16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid var(--lin);padding:4px 6px;text-align:left}}
tr.divergente{{background:#fde2e1}}tr.a_conferir{{background:#fff4ce}}tr.confirmado{{background:#e6f4ea}}
tr.errado{{background:#f2d0d0}}.g{{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:12px}}
img{{max-width:100%;border:1px solid var(--lin)}}pre{{white-space:pre-wrap;font-size:12px;max-height:80vh;overflow:auto}}
mark{{background:#ffd33d}}p.n{{color:var(--mut)}}</style>
<h1>Folha de conferência — OCR por IA</h1>
<p>Processo <b>{html.escape(acervo_texto.pasta_para_numero(tag))}</b> · documento {i} ·
{html.escape(str(d.get('titulo') or ''))} · tipo {html.escape(str(d.get('tipo') or ''))}</p>
<p class="n">Só <b>confirmado</b> vale como prova. Olhe a IMAGEM e decida cada número em disputa — não confie em
nenhuma das duas leituras: ambas são OCR. Gerado em {time.strftime('%d/%m/%Y %H:%M')}.</p>
<table><tr><th>Tipo</th><th>Leitura IA</th><th>2ª leitura</th><th>Estado</th><th>Fonte</th><th>Pág.</th><th>Comando</th></tr>
{''.join(linhas)}</table>{''.join(blocos)}</html>"""
    saida = Path(saida or FICHAS)
    saida.mkdir(parents=True, exist_ok=True)
    alvo = saida / f"{tag}_{int(i):03d}.html"
    alvo.write_text(doc_html, encoding="utf-8")
    return alvo


def cmd_ficha(a) -> int:
    print(ficha(a.tag, a.doc, Path(a.saida) if a.saida else None))
    return 0


# ── marcar ───────────────────────────────────────────────────────────────────────────────────────
def marcar(tag: str, i: int, numero: str, decisao: str, por: str, tipo: str | None = None, nota: str = "") -> dict:
    if decisao not in ("confirmado", "errado"):
        raise ValueError("decisão é confirmado ou errado")
    if not por.strip():
        raise ValueError("--por é obrigatório (quem olhou a página)")
    pasta = acervo_texto.RAIZ / tag
    d = next((x for x in (acervo_texto.manifesto(pasta) or {}).get("docs") or [] if str(x.get("i")) == str(i)), None)
    if d is None:
        raise ValueError(f"documento {i} não está no manifesto de {tag}")
    do_doc = P.extrair(acervo_texto.ler(pasta, d))
    cands = [(t, P.normalizar(t, numero)) for t in ([tipo] if tipo else P.TIPOS)]
    alvo = next(((t, n) for t, n in cands if n and any((x["tipo"], x["norma"]) == (t, n) for x in do_doc)), None)
    if alvo is None:
        raise ValueError(f"{numero!r} não é um número crítico lido pela IA no documento {i} de {tag}")
    e = {"tag": tag, "i": int(i), "tipo": alvo[0], "norma": alvo[1], "literal": numero, "estado": decisao,
         "por": por.strip(), **({"nota": nota} if nota else {})}
    P.registrar([e])
    return e


def cmd_marcar(a) -> int:
    print(json.dumps(marcar(a.tag, a.doc, a.numero, a.decisao, a.por, a.tipo, a.nota or ""), ensure_ascii=False))
    return 0


# ── fila do Opus (assinatura) ────────────────────────────────────────────────────────────────────
TAREFA_OPUS = "ocr_ia_numero"
_PERGUNTA = """Conferência de OCR. Duas leituras independentes do MESMO trecho de um documento escaneado discordam num
número crítico ({tipo}). Você NÃO vê a imagem: só pode decidir com base OBJETIVA no próprio texto — dígito verificador
do CNPJ, valor escrito por extenso, soma/conta da tabela, o mesmo número repetido em outro ponto. Sem base objetiva,
responda "indecidivel" (é o esperado; não adivinhe).

Leitura A (IA): {a}
Leitura B (segunda leitura): {b}

Contexto da leitura A:
{ctx_a}

Contexto da leitura B:
{ctx_b}

Responda só JSON: {{"decisao": "A"|"B"|"indecidivel", "base": "dv"|"extenso"|"soma"|"repeticao"|"nenhuma",
"justificativa": "<uma frase citando o trecho>"}}"""


def _contexto(texto: str, literal: str, folga: int = 300) -> str:
    k = (texto or "").find(literal)
    return texto[max(0, k - folga): k + len(literal) + folga] if k >= 0 else "(não localizado)"


def cmd_opus(a) -> int:
    from compliance_agent.llm import conferencia_opus as CO
    n = 0
    for e in pendentes():
        if n >= a.limite:
            break
        if e["estado"] != "divergente":
            continue
        pasta = acervo_texto.RAIZ / e["tag"]
        d = next((x for x in (acervo_texto.manifesto(pasta) or {}).get("docs") or []
                  if str(x.get("i")) == str(e["i"])), {})
        ia = acervo_texto.ler(pasta, d)
        seg = "\n".join(P.leituras_ao_lado(pasta, d).values())
        pdf = pdf_do_documento(e["tag"], e["i"], trazer=False)
        if pdf and e.get("literal_2") and e["literal_2"] not in seg:
            try:
                seg += "\n" + "\n".join(P.ler_pdf(pdf, P.paginas_com(
                    P.extrair(e["literal"]), P.paginas_da_ia(entrega_crua(e["tag"], e["i"],
                                                                          str(d.get("ocr_motor") or "")))) or None,
                    max_paginas=3)["leituras"].values())
            except (OSError, RuntimeError, ValueError) as ex:
                print(f"  aviso: 2ª leitura do PDF indisponível ({e['tag']}#{e['i']}): {type(ex).__name__}: {ex}",
                      file=sys.stderr)
        entrada = _PERGUNTA.format(tipo=e["tipo"], a=e["literal"], b=e.get("literal_2"),
                                   ctx_a=_contexto(ia, e["literal"]), ctx_b=_contexto(seg, e.get("literal_2") or ""))
        item = json.dumps({"tag": e["tag"], "i": e["i"], "tipo": e["tipo"], "norma": e["norma"],
                           "literal": e["literal"], "norma_2": e.get("leitura_2")}, ensure_ascii=False)
        if a.ensaio:
            print(item)
            n += 1
        elif CO.enfileirar(TAREFA_OPUS, item, entrada, motor=f"ocr_ia:{d.get('ocr_motor')}", resposta="",
                           motivo="número divergente entre leituras de OCR", valor=e["valor"] or None):
            n += 1
    print(json.dumps({"enfileirados" if not a.ensaio else "seriam_enfileirados": n}, ensure_ascii=False))
    return 0


def aplicar_conferencia(item: str, resposta: str, modelo: str, concorda) -> bool:
    """Aplicador da fila do Opus (`conferencia_opus.APLICADORES`): só registra decisão com BASE objetiva no texto
    (DV, extenso, soma, repetição); "indecidivel" ou sem base → o número segue divergente, para olho humano."""
    import re
    it = json.loads(item)
    m = re.search(r"\{.*\}", resposta or "", re.S)
    try:
        r = json.loads(m.group(0)) if m else {}
    except ValueError:
        return False
    if r.get("decisao") not in ("A", "B") or r.get("base") not in ("dv", "extenso", "soma", "repeticao"):
        return False
    P.registrar([{"tag": it["tag"], "i": int(it["i"]), "tipo": it["tipo"], "norma": it["norma"],
                  "literal": it["literal"], "estado": "confirmado" if r["decisao"] == "A" else "errado",
                  "por": f"opus:{modelo}", "nota": f"{r['base']}: {str(r.get('justificativa'))[:300]}"}])
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Conferência dos números críticos do OCR por IA")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("confirmar")
    c.add_argument("--limite", type=int, default=20)
    c.add_argument("--ensaio", action="store_true", help="mede e imprime; não grava o registro")
    c.add_argument("--tag")
    c.add_argument("--sem-pdf", action="store_true", help="sem Tesseract: só ao lado, SIAFE e outros documentos")
    c.add_argument("--refazer", action="store_true", help="inclui documentos já decididos")
    c.add_argument("--saida", help="grava o resultado completo (JSON) neste arquivo")
    p = sub.add_parser("pendentes")
    p.add_argument("--limite", type=int, default=50)
    p.add_argument("--json", action="store_true")
    f = sub.add_parser("ficha")
    f.add_argument("tag")
    f.add_argument("doc", type=int)
    f.add_argument("--saida")
    m = sub.add_parser("marcar")
    m.add_argument("tag")
    m.add_argument("doc", type=int)
    m.add_argument("numero")
    m.add_argument("decisao", choices=("confirmado", "errado"))
    m.add_argument("--por", required=True)
    m.add_argument("--tipo", choices=P.TIPOS)
    m.add_argument("--nota")
    o = sub.add_parser("opus")
    o.add_argument("--limite", type=int, default=20)
    o.add_argument("--ensaio", action="store_true")
    a = ap.parse_args(argv)
    return {"confirmar": cmd_confirmar, "pendentes": cmd_pendentes, "ficha": cmd_ficha, "marcar": cmd_marcar,
            "opus": cmd_opus}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
