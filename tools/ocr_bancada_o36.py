# -*- coding: utf-8 -*-
"""Bancada da O3.6 (OCR) — mede, sobre CÓPIAS dos PDFs do frio no HD do it-campo, o que o plano mestre v2 §7 pede:
perfil por página, dedup por hash de imagem, código de barras/QR em NF, reprocessamento dos documentos MISTOS (OCR só
nas páginas escaneadas), ouro congelado por tipo e GPU × CPU × PP-OCRv6. Parada de obras: NADA aqui grava no PG, no
acervo (`data/sei_arquivo`), no `compliance.db` ou no frio — só arquivos de trabalho na pasta `--dir`. O texto lido
fica nos JSONL de trabalho (no it-campo); os relatórios levam só contagens.

Etapas (cada uma retoma de onde parou — linha já escrita não é refeita):
  perfil     corpus.jsonl → perfil.jsonl     perfil de cada página (E4) + img_sha das escaneadas (E5), N processos
  dedup      perfil.jsonl → dedup.json       páginas escaneadas repetidas (no documento, entre documentos)
  selecionar perfil+corpus → mistos.jsonl, ouro_cand.jsonl, controle.jsonl, paginas_<lista>.jsonl
  render     paginas_*.jsonl → png/<img_sha>.png (200 dpi, os mesmos pixels do E5; sha conferido)
  ler        --motor rapidocr|tesseract|surya|ppocrv6 → leituras_<motor>.jsonl  (texto, linhas+bbox, segundos)
  barras     NF: decodifica código de barras/QR (zxing-cpp e pyzbar, 200 e 300 dpi) → barras.json
  mistos     reprocessamento dos mistos (E5 com as leituras feitas + E6: leitura, recorte, barras, SIAFE) → mistos.json
  ouro       rótulo por consenso de 2 famílias + recorte; congela; lista de revisão → ouro/
  medir      acerto/inventado de cada motor no controle nativo e no ouro + tempos → medir.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import multiprocessing as mp
import os
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DPI = 200
# os motores que a `medir` compara; oxr/paddlevl vêm do leitor EXTERNO (tools/ocr_bancada_externo.py, ambientes
# isolados no it-campo) e ppocrv6_arm é o PP-OCRv6 em CPU na VM-2 (ARM) — a volta sem it-campo (26/11/2026)
MOTORES_MEDIDOS = ("surya", "rapidocr", "ppocrv6", "tesseract", "oxr", "paddlevl", "ppocrv6_arm")
ERROS_PDF = (RuntimeError, ValueError, OSError)            # fitz.FileDataError ⊂ RuntimeError
# o snapshot só-leitura de 24/11 (o do HD passa pelo 9P: a consulta do SIAFE travava em D-state); cópia local primeiro
SNAPSHOT = Path(os.environ.get("JFN_O36_SNAPSHOT") or "/mnt/d/JFN-Frio/snapshot-20261124/compliance.db")


def _local(hd: str) -> Path:
    """O caminho do HD no SO que roda: `JFN_O36_RAIZ="/mnt/d/=D:/;/mnt/c/=C:/"` lê o MESMO arquivo direto no Windows (o /mnt/d
    do WSL passa pelo 9P: medido 3,3 PDFs/s com 75% da CPU ociosa em D-state)."""
    for par in (os.environ.get("JFN_O36_RAIZ") or "").split(";"):
        de, _, para = par.partition("=")
        if de and hd.startswith(de):
            return Path(para + hd[len(de):])
    return Path(hd)


def _jl(arq: Path):
    if not arq.exists():
        return
    with arq.open(encoding="utf-8") as f:
        for ln in f:
            if ln.strip() and ln.endswith("\n"):            # a linha ainda sendo escrita (sem \n) fica para depois
                yield json.loads(ln)


def _feitos(arq: Path, chave: str) -> set:
    return {r[chave] for r in _jl(arq)}


def _sim(v) -> bool:
    return str(v) == "True"


# ── perfil ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _perfil(r: dict) -> dict:
    from compliance_agent.aplicacao.estagios import ErroPermanente
    from compliance_agent.aplicacao.estagios import ocr as O
    from compliance_agent.aplicacao.estagios import texto as T
    out = {k: r.get(k) for k in ("hd", "tag", "i", "tipo", "processo", "ocr")}
    t0 = time.monotonic()
    pdf = _local(r["hd"])
    if not pdf.is_file():
        return out | {"erro": "ausente no HD"}
    try:
        ex = T.extrair(pdf)
        esc = [n for n in ex["escaneadas"] if n <= O.MAX_PAGINAS]
        shas = O.hashes_imagem(pdf, esc) if esc else {}
    except (ErroPermanente, *ERROS_PDF) as e:
        return out | {"erro": f"{type(e).__name__}: {str(e)[:160]}"}
    return out | {"perfil": ex["perfil"], "invalido": bool(ex["invalido"]),
                  "paginas": [[q["perfil"], q["chars"]] for q in ex["paginas"]],
                  "img_sha": {str(n): s for n, s in shas.items()}, "s": round(time.monotonic() - t0, 3)}


def perfil(d: Path, procs: int, limite: int | None) -> dict:
    saida = d / "perfil.jsonl"
    feitos = _feitos(saida, "hd")
    vistos, fila = set(), []
    for r in _jl(d / "corpus.jsonl"):
        k = (r["tag"], r["i"])
        if k in vistos:
            continue
        vistos.add(k)
        if r["hd"] not in feitos:                         # sem stat aqui: no /mnt/d (9P) custa ~5 ms por arquivo
            fila.append(r)
        if limite and len(fila) >= limite:
            break
    # primeiro o que o ouro sorteia (tipo de um grupo, processo reservado): a seleção do ouro fica completa cedo, sem
    # esperar o corpus inteiro (o HD é de disco giratório: ~7 PDFs/s com 22 processos)
    from compliance_agent.qualidade import ouro_ocr as OO
    fila.sort(key=lambda r: (not (OO.grupo_do_tipo(r.get("tipo")) and r.get("processo") and
                                  OO.reservado(r["processo"])), r["hd"]))
    t0 = time.monotonic()
    n = 0
    with saida.open("a", encoding="utf-8") as f, mp.get_context("spawn").Pool(procs, maxtasksperchild=300) as pool:
        for res in pool.imap_unordered(_perfil, fila, chunksize=8):
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            n += 1
            if n % 2000 == 0:
                f.flush()
                print(f"perfil {n}/{len(fila)} {time.monotonic() - t0:.0f}s", flush=True)
    return {"novos": n, "segundos": round(time.monotonic() - t0, 1), "ja_feitos": len(feitos)}


# ── dedup ──────────────────────────────────────────────────────────────────────────────────────────────────────
def dedup(d: Path) -> dict:
    por_sha: dict[str, list] = collections.defaultdict(list)
    docs = esc_docs = paginas = 0
    for r in _jl(d / "perfil.jsonl"):
        if r.get("erro"):
            continue
        docs += 1
        shas = r.get("img_sha") or {}
        if shas:
            esc_docs += 1
        for n, s in shas.items():
            paginas += 1
            por_sha[s].append((r["hd"], int(n), r.get("tipo")))
    distintas = len(por_sha)
    no_doc = entre = 0
    for occ in por_sha.values():
        if len(occ) < 2:
            continue
        docs_da_img = {o[0] for o in occ}
        no_doc += len(occ) - len(docs_da_img)                   # repetições dentro do mesmo PDF
        entre += len(docs_da_img) - 1                           # repetições em outros PDFs
    repetidas = paginas - distintas
    top = sorted(por_sha.values(), key=len, reverse=True)[:10]
    por_tipo = collections.Counter()
    for occ in por_sha.values():
        for o in occ[1:]:
            por_tipo[o[2]] += 1
    return {"docs": docs, "docs_com_escaneada": esc_docs, "paginas_escaneadas": paginas,
            "imagens_distintas": distintas, "paginas_repetidas": repetidas,
            "repetidas_%": round(100 * repetidas / paginas, 2) if paginas else None,
            "repetidas_no_mesmo_pdf": no_doc, "repetidas_em_outro_pdf": entre,
            "maiores_grupos": [len(o) for o in top], "repetidas_por_tipo": dict(por_tipo.most_common(12))}


# ── seleção ────────────────────────────────────────────────────────────────────────────────────────────────────
def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def selecionar(d: Path, por_grupo: int, controle_por_grupo: int) -> dict:
    from compliance_agent.qualidade import ouro_ocr as OO
    mistos, cand, ctrl = [], collections.defaultdict(list), collections.defaultdict(list)
    vistos = set()
    perfis = collections.Counter()
    for r in _jl(d / "perfil.jsonl"):
        if r.get("erro"):
            perfis["erro"] += 1
            continue
        perfis[r["perfil"]] += 1
        # misto que PRECISA de OCR = tem página nativa E página escaneada (nativa + branca é "mista" no E4 e não pede
        # OCR); `ocr` False no manifesto = o texto arquivado é só o nativo (as escaneadas nunca foram lidas)
        if r["perfil"] == "mista" and not r["invalido"] and not _sim(r.get("ocr")) and r.get("img_sha") and \
                any(pf == "nativa" for pf, _ in r["paginas"]):
            mistos.append({k: r[k] for k in ("hd", "tag", "i", "tipo", "processo")} |
                          {"escaneadas": sorted(int(n) for n in r["img_sha"]), "img_sha": r["img_sha"]})
        g = OO.grupo_do_tipo(r.get("tipo"))
        if not g or not r.get("processo") or r["invalido"] or not OO.reservado(r["processo"]) or \
                OO.vazamentos([r["processo"]], []):
            continue
        for n, s in (r.get("img_sha") or {}).items():
            if s not in vistos:
                vistos.add(s)
                cand[g].append({"hd": r["hd"], "pagina": int(n), "img_sha": s, "grupo": g, "tipo": r["tipo"],
                                "processo": r["processo"], "tag": r["tag"], "i": r["i"]})
        for k, (pf, chars) in enumerate(r["paginas"], start=1):
            if pf == "nativa" and chars >= 300 and k <= 120:
                ctrl[g].append({"hd": r["hd"], "pagina": k, "grupo": g, "tipo": r["tipo"], "processo": r["processo"],
                                "tag": r["tag"], "i": r["i"]})
    ouro = []
    for g, xs in sorted(cand.items()):
        xs.sort(key=lambda x: _h(x["img_sha"]))                  # sorteio determinístico, 1 página por imagem
        por_doc = collections.Counter()
        escolhidas: list = []
        for teto in (3, 10 ** 6):                               # 1ª passada: até 3 páginas por documento (diversidade);
            for x in xs:                                        # 2ª: completa o grupo (contrato é documento longo)
                if len(escolhidas) < por_grupo and por_doc[x["hd"]] < teto and x not in escolhidas:
                    escolhidas.append(x)
                    por_doc[x["hd"]] += 1
        ouro += escolhidas
    controle = []
    for g, xs in sorted(ctrl.items()):
        xs.sort(key=lambda x: _h(f"{x['hd']}#{x['pagina']}"))
        por_doc = collections.Counter()
        for x in xs:
            if por_doc[x["hd"]] < 1 and sum(1 for y in controle if y["grupo"] == g) < controle_por_grupo:
                controle.append(x)
                por_doc[x["hd"]] += 1
    mistos.sort(key=lambda m: _h(m["hd"]))
    for nome, xs in (("mistos", mistos), ("ouro_cand", ouro), ("controle", controle)):
        with (d / f"{nome}.jsonl").open("w", encoding="utf-8") as f:
            for x in xs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    paginas = [{"hd": m["hd"], "pagina": n, "img_sha": m["img_sha"][str(n)]} for m in mistos for n in m["escaneadas"]]
    paginas += [{k: x[k] for k in ("hd", "pagina", "img_sha")} for x in ouro]
    unicas = {p["img_sha"]: p for p in paginas}
    with (d / "paginas_ocr.jsonl").open("w", encoding="utf-8") as f:
        for p in unicas.values():
            f.write(json.dumps(p) + "\n")
    mistos.sort(key=lambda m: _h(m["hd"]))                     # ordem sorteada: rodada parcial = amostra aleatória
    with (d / "paginas_mistos.jsonl").open("w", encoding="utf-8") as f:
        for m in mistos:
            for n in m["escaneadas"]:
                f.write(json.dumps({"hd": m["hd"], "pagina": n, "img_sha": m["img_sha"][str(n)]}) + "\n")
    with (d / "paginas_ouro.jsonl").open("w", encoding="utf-8") as f:     # o ouro antes dos mistos (HD giratório)
        for x in ouro:
            f.write(json.dumps({k: x[k] for k in ("hd", "pagina", "img_sha")}) + "\n")
    with (d / "paginas_controle.jsonl").open("w", encoding="utf-8") as f:
        for x in controle:
            f.write(json.dumps({"hd": x["hd"], "pagina": x["pagina"]}) + "\n")
    return {"perfis": dict(perfis), "mistos": len(mistos), "paginas_escaneadas_mistos":
            sum(len(m["escaneadas"]) for m in mistos), "ouro_candidatos_por_grupo": {g: len(v) for g, v in cand.items()},
            "ouro": dict(collections.Counter(x["grupo"] for x in ouro)),
            "controle": dict(collections.Counter(x["grupo"] for x in controle)), "paginas_ocr_unicas": len(unicas)}


# ── render ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _render(job: dict) -> dict:
    from PIL import Image

    from compliance_agent.aplicacao.estagios import ocr as O
    out_dir = Path(job["_png"])
    try:
        _, img, _, _ = next(O._imagens(_local(job["hd"]), [job["pagina"]]))
    except (StopIteration, *ERROS_PDF) as e:
        return {"hd": job["hd"], "pagina": job["pagina"], "erro": f"{type(e).__name__}: {str(e)[:120]}"}
    sha = O.sha_imagem(img)
    if job.get("img_sha") and job["img_sha"] != sha:
        return {"hd": job["hd"], "pagina": job["pagina"], "erro": "img_sha diferente do perfil"}
    png = out_dir / f"{sha}.png"                         # no índice vai só o nome: Windows e WSL leem a mesma pasta
    if not png.exists():
        tmp = png.with_suffix(f".tmp{os.getpid()}.png")
        Image.fromarray(img).save(tmp, optimize=False, compress_level=1)
        os.replace(tmp, png)
    return {"hd": job["hd"], "pagina": job["pagina"], "img_sha": sha, "png": png.name}


def render(d: Path, lista: str, procs: int) -> dict:
    (d / "png").mkdir(exist_ok=True)
    saida = d / f"render_{lista}.jsonl"
    feitos = {(r["hd"], r["pagina"]) for r in _jl(saida)}
    fila = [r | {"_png": str(d / "png")} for r in _jl(d / f"paginas_{lista}.jsonl") if (r["hd"], r["pagina"]) not in feitos]
    n = err = 0
    with saida.open("a", encoding="utf-8") as f, mp.get_context("spawn").Pool(procs) as pool:
        for res in pool.imap_unordered(_render, fila, chunksize=4):
            f.write(json.dumps(res) + "\n")
            n += 1
            err += bool(res.get("erro"))
    return {"novos": n, "erros": err}


# ── ler ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _img(png: str):
    import numpy as np
    from PIL import Image
    with Image.open(png) as im:
        return np.ascontiguousarray(np.asarray(im.convert("RGB")))


_LEITOR = {}


def _leitor(motor: str):
    if motor not in _LEITOR:
        from compliance_agent.aplicacao.estagios import ocr as O
        _LEITOR[motor] = {"rapidocr": O.ExecutorCPU, "tesseract": O.ExecutorTesseract}[motor]()
    return _LEITOR[motor]


def _ler_cpu(job: dict) -> dict:
    ex = _leitor(job["_motor"])
    t0 = time.monotonic()
    le = ex.ler_img(_img(job["png"]))
    return {"img_sha": job["img_sha"], "motor": ex.motor(), "texto": le.texto, "linhas": le.linhas,
            "largura": le.largura, "altura": le.altura, "s": round(time.monotonic() - t0, 3)}


def _ppocrv6(threads: int):
    """PP-OCRv6 medium det+rec (CPU, paddle) com o MESMO pós-processo da reserva — a montagem da bancada de 23/11."""
    import numpy as np
    from paddleocr import PaddleOCR

    from tools import sei_ocr_reserva as R
    eng = PaddleOCR(text_detection_model_name="PP-OCRv6_medium_det", text_recognition_model_name="PP-OCRv6_medium_rec",
                    use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                    device="cpu", cpu_threads=threads)
    from importlib.metadata import version
    motor = f"ppocrv6@paddleocr{version('paddleocr')} medium det+rec (CPU {threads}t) dpi{DPI}"

    def ler(png: str) -> dict:
        it, linhas = [], []
        for r in eng.predict(png):
            for b, t in zip(r["rec_polys"], r["rec_texts"]):
                b = np.asarray(b)
                it.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
                linhas.append({"texto": t, "bbox": [round(float(b[:, 0].min()), 1), round(float(b[:, 1].min()), 1),
                                                    round(float(b[:, 0].max()), 1), round(float(b[:, 1].max()), 1)]})
        return {"texto": R.corrigir(R._linhas(it)), "linhas": linhas}
    return motor, ler


def ler(d: Path, lista: str, motor: str, procs: int, lote: int, limite: int | None, so_ouro: bool = False,
        fatia: str | None = None) -> dict:
    so = {x["img_sha"] for x in _jl(d / "ouro_cand.jsonl")} if so_ouro else None
    k_fatia, n_fatia = (int(x) for x in fatia.split("/")) if fatia else (0, 1)
    saida = d / (f"leituras_{motor}.jsonl" if lista == "ocr" else f"leituras_{motor}_{lista}.jsonl")
    if fatia:                                             # processos paralelos de um motor sequencial (PP-OCRv6)
        saida = saida.with_name(saida.stem + f".f{k_fatia}.jsonl")
    feitos = set(leituras(d, motor, lista))               # o que QUALQUER arquivo deste motor já leu (fatias e o principal)
    fila, vistos = [], set()
    renders = [d / f"render_{lista}.jsonl"] + ([d / "render_ouro.jsonl"] if lista == "ocr" else [])
    for r in (x for arq in renders for x in _jl(arq)):
        if r.get("erro") or r["img_sha"] in feitos or r["img_sha"] in vistos or (so is not None and r["img_sha"] not in so) \
                or int(r["img_sha"][:8], 16) % n_fatia != k_fatia:
            continue
        vistos.add(r["img_sha"])
        fila.append(r | {"png": str(d / "png" / Path(r["png"]).name)})
    fila = fila[:limite] if limite else fila
    t0 = time.monotonic()
    n = erros = 0
    with saida.open("a", encoding="utf-8") as f:
        def grava(res):
            nonlocal n
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            n += 1
            if n % 200 == 0:
                f.flush()
                print(f"{motor} {n}/{len(fila)} {time.monotonic() - t0:.0f}s", flush=True)
        if motor in ("rapidocr", "tesseract"):
            with mp.get_context("spawn").Pool(procs, maxtasksperchild=500) as pool:
                for res in pool.imap_unordered(_ler_cpu, [r | {"_motor": motor} for r in fila], chunksize=2):
                    grava(res)
        elif motor == "ppocrv6":
            m, leitor = _ppocrv6(int(os.environ.get("JFN_PPOCR_THREADS", "6")))
            for r in fila:
                t1 = time.monotonic()
                grava({"img_sha": r["img_sha"], "motor": m, **leitor(r["png"]), "s": round(time.monotonic() - t1, 3)})
        elif motor == "surya":
            from compliance_agent.aplicacao.estagios import ocr as O
            ex = O.ExecutorGPU()
            m = ex.motor()
            for k in range(0, len(fila), lote):
                grupo = fila[k:k + lote]
                t1 = time.monotonic()
                try:
                    les = ex.ler_imgs([_img(r["png"]) for r in grupo])
                except O.ErroInferencia as e:
                    erros += 1
                    print(f"surya lote {k}: {e}", flush=True)
                    continue
                s = (time.monotonic() - t1) / len(grupo)
                for r, le in zip(grupo, les):
                    grava({"img_sha": r["img_sha"], "motor": m, "texto": le.texto, "linhas": le.linhas,
                           "largura": le.largura, "altura": le.altura, "s": round(s, 3), "lote": len(grupo)})
        else:
            raise SystemExit(f"motor desconhecido: {motor}")
    seg = time.monotonic() - t0
    return {"motor": motor, "paginas": n, "erros_lote": erros, "segundos": round(seg, 1),
            "paginas_por_min": round(60 * n / seg, 2) if seg and n else None, "procs": procs, "lote": lote}


def leituras(d: Path, motor: str, lista: str = "ocr") -> dict[str, dict]:
    base = f"leituras_{motor}" if lista == "ocr" else f"leituras_{motor}_{lista}"
    out = {r["img_sha"]: r for r in _jl(d / f"{base}.jsonl")}
    for arq in sorted(d.glob(f"{base}.f*.jsonl")):
        out.update({r["img_sha"]: r for r in _jl(arq)})
    return out


# ── código de barras ───────────────────────────────────────────────────────────────────────────────────────────
def _barras_doc(job: dict) -> dict:
    import fitz
    import numpy as np
    import zxingcpp
    from pyzbar import pyzbar

    from compliance_agent.aplicacao.estagios import confirmar_ocr as C
    out = {"hd": job["hd"], "paginas": 0}
    try:
        doc = fitz.open(_local(job["hd"]))
    except ERROS_PDF as e:
        return out | {"erro": type(e).__name__}
    res = {}
    with doc:
        nat = "\n".join(doc.load_page(i).get_text("text") or "" for i in range(min(doc.page_count, 10)))
        out["paginas"] = min(doc.page_count, 10)
        for dpi in (200, 300):
            for nome in ("zxing", "pyzbar"):
                res[f"{nome}@{dpi}"] = {"textos": [], "s": 0.0}
            for i in range(out["paginas"]):
                pix = doc.load_page(i).get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                t0 = time.monotonic()
                txt = [r.text for r in zxingcpp.read_barcodes(img)]
                res[f"zxing@{dpi}"]["s"] += time.monotonic() - t0
                res[f"zxing@{dpi}"]["textos"] += txt
                t0 = time.monotonic()
                txt = [r.data.decode("ascii", "ignore") for r in pyzbar.decode(img)]
                res[f"pyzbar@{dpi}"]["s"] += time.monotonic() - t0
                res[f"pyzbar@{dpi}"]["textos"] += txt
    nat_chaves = {c for c in C.chaves_de_barras([nat])}
    for k, v in res.items():
        v["chaves"] = sorted(C.chaves_de_barras(v["textos"]))
        v["qr"] = any("http" in t.lower() or "chnfe" in t.lower() for t in v["textos"])
        v["n"] = len(v["textos"])
        v["s"] = round(v["s"], 3)
        v["textos"] = [t[:120] for t in v["textos"]][:6]
    out |= {"res": res, "chave_no_texto_nativo": sorted(nat_chaves), "escaneado": bool(job.get("escaneado"))}
    return out


def barras(d: Path, procs: int, limite: int) -> dict:
    nfs = []
    for r in _jl(d / "perfil.jsonl"):
        if r.get("tipo") == "nota_fiscal" and not r.get("erro") and not r.get("invalido"):
            nfs.append({"hd": r["hd"], "escaneado": bool(r.get("img_sha"))})
    nfs.sort(key=lambda r: _h(r["hd"]))
    nfs = nfs[:limite]
    saida = d / "barras.jsonl"
    feitos = _feitos(saida, "hd")
    with saida.open("a", encoding="utf-8") as f, mp.get_context("spawn").Pool(procs) as pool:
        for res in pool.imap_unordered(_barras_doc, [r for r in nfs if r["hd"] not in feitos], chunksize=2):
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
    rs = [r for r in _jl(saida) if not r.get("erro")]
    out = {"nf_docs": len(rs), "escaneados": sum(r["escaneado"] for r in rs)}
    for k in ("zxing@200", "pyzbar@200", "zxing@300", "pyzbar@300"):
        com = [r for r in rs if r["res"][k]["chaves"]]
        out[k] = {"docs_com_chave44": len(com), "%": round(100 * len(com) / len(rs), 2) if rs else None,
                  "docs_com_qr": sum(r["res"][k]["qr"] for r in rs),
                  "escaneados_com_chave44": sum(1 for r in com if r["escaneado"]),
                  "s_por_doc_p50": round(statistics.median(r["res"][k]["s"] for r in rs), 3) if rs else None}
    uniao = [r for r in rs if any(r["res"][k]["chaves"] for k in r["res"])]
    out["qualquer_decodificador"] = {"docs_com_chave44": len(uniao), "%": round(100 * len(uniao) / len(rs), 2)
                                     if rs else None}
    # exatidão: onde o texto nativo traz a chave, o decodificado é igual?
    conf = [r for r in rs if r["chave_no_texto_nativo"] and any(r["res"][k]["chaves"] for k in r["res"])]
    out["com_chave_nativa_e_decodificada"] = len(conf)
    out["decodificada_igual_a_nativa"] = sum(
        1 for r in conf if set(map(tuple, r["chave_no_texto_nativo"])) &
        {tuple(c) for k in r["res"] for c in r["res"][k]["chaves"]})
    out["decodificada_diverge_da_nativa"] = sum(
        1 for r in conf if not ({tuple(c) for k in r["res"] for c in r["res"][k]["chaves"]}
                                <= set(map(tuple, r["chave_no_texto_nativo"]))))
    return out


# ── reprocessamento dos mistos ─────────────────────────────────────────────────────────────────────────────────
class _Despejo:
    """Executor do E5 que devolve a leitura JÁ FEITA (`ler`), pela imagem: o E5 roda inteiro, sem reler."""

    def __init__(self, familia: str, por_sha: dict):
        self.familia, self.por_sha = familia, por_sha
        self._m = next((v["motor"] for v in por_sha.values()), familia)

    def motor(self) -> str:
        return self._m

    def ler(self, pdf: Path, paginas: list[int]) -> dict:
        from compliance_agent.aplicacao.estagios import ocr as O
        out = {}
        for n, s in O.hashes_imagem(pdf, paginas).items():
            r = self.por_sha.get(s)
            if r is None:
                raise O.ErroInferencia(f"{pdf.name} p{n}: sem leitura {self.familia} para a imagem {s[:12]}")
            out[n] = O.Leitura(r["texto"], r["linhas"], r.get("largura") or 0, r.get("altura") or 0)
        return out


def _chaves(texto: str, tolerante: bool = False) -> set:
    from compliance_agent.sei import ocr_ia_prova as P
    return {(x["tipo"], x["norma"]) for x in P.extrair(texto or "", tolerante=tolerante)}


def mistos(d: Path, limite: int | None) -> dict:
    import sqlite3

    from compliance_agent.aplicacao.estagios import confirmar_ocr as C
    from compliance_agent.aplicacao.estagios import ocr as O
    from compliance_agent.aplicacao.estagios import ocr_recorte as R
    from compliance_agent.aplicacao.estagios import texto as T
    from compliance_agent.sei import ocr_ia_prova as P
    lt = {m: leituras(d, m, "mistos") for m in ("surya", "rapidocr", "tesseract")}
    if lt["surya"]:                                            # E5 no it-campo: GPU (Surya) + 2º motor RapidOCR
        principal, segundo, tess = _Despejo("gpu", lt["surya"]), _Despejo("rapidocr", lt["rapidocr"]), lt["tesseract"]
    else:                                                      # E5 na volta CPU: RapidOCR + 2º motor Tesseract
        principal, segundo, tess = _Despejo("rapidocr", lt["rapidocr"]), _Despejo("tesseract", lt["tesseract"]), \
            lt["tesseract"]
    leit = R.leitores_do_no()
    con = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro&immutable=1", uri=True) if SNAPSHOT.exists() else None
    siafe_cache: dict = {}
    saida = d / "mistos_resultado.jsonl"
    feitos = _feitos(saida, "hd")
    xs = [m for m in _jl(d / "mistos.jsonl") if m["hd"] not in feitos]
    xs = xs[:limite] if limite else xs
    with saida.open("a", encoding="utf-8") as f:
        for k, m in enumerate(xs):
            pdf = _local(m["hd"])
            t0 = time.monotonic()
            try:
                e4 = T.extrair(pdf)
                ocr = O.ocr_documento(pdf, e4, principal, segundo)
            except (O.ErroInferencia, *ERROS_PDF) as e:
                f.write(json.dumps({"hd": m["hd"], "erro": f"{type(e).__name__}: {str(e)[:160]}"}) + "\n")
                continue
            nativo = T.texto_composto(e4)
            kn, kc = _chaves(nativo), _chaves(ocr["texto_composto"])
            nums = C.numeros_do_ocr(ocr)
            pags = sorted({x["pagina"] for x in nums})
            lt2: dict[str, list] = {}
            for n in pags:                                       # 2ª leitura = Tesseract das mesmas páginas (E6)
                s = ocr["paginas"][str(n)]["img_sha"]
                if s in tess and not ocr["paginas"][str(n)]["motor"].startswith("tesseract"):   # outra família
                    lt2.setdefault(f"leitura:{tess[s]['motor']}", []).append(tess[s]["texto"])
            leituras_ = {f: "\n".join(v) for f, v in lt2.items()}
            rec = R.conferir(pdf, ocr, nums, leit) if nums else []
            bar = C.barras(pdf, pags) if nums else {"chaves": []}
            ext = {}
            if con is not None and m.get("processo"):
                if m["processo"] not in siafe_cache:
                    siafe_cache[m["processo"]] = {k2: set(v) for k2, v in P.fontes_externas(m["processo"], con).items()}
                ext = dict(siafe_cache[m["processo"]])
            if bar.get("chaves"):
                ext["barras"] = {tuple(x) for x in bar["chaves"]}
            ext.update(R.chaves_confirmadas(rec))
            dec = C.decidir(nums, leituras_, ext)
            novos = kc - kn
            res = {"hd": m["hd"], "tipo": m["tipo"], "paginas_escaneadas": len(ocr["alvo"]),
                   "estados": collections.Counter(v["estado"] for v in ocr["paginas"].values()),
                   "chars_nativo": len(nativo.strip()), "chars_composto": ocr["chars"],
                   "nativo_preservado": len(ocr["compostas"]) == len(e4["paginas"]) and all(
                       c.startswith((p["texto"] or "").rstrip()) for c, p in zip(ocr["compostas"], e4["paginas"])),
                   "novos_por_tipo": dict(collections.Counter(t for t, _ in novos)),
                   "novos": len(novos), "numeros_ocr": len(dec),
                   "confirmados": sum(x["estado"] == C.CONFIRMADO for x in dec),
                   "por_fonte": C._contar([x["fonte"] for x in dec if x["estado"] == C.CONFIRMADO]),
                   "por_fonte_concordante": C._contar([fx for x in dec if x["estado"] == C.CONFIRMADO
                                                       for fx in {C._familia_fonte(y) for y in x["concordantes"]}]),
                   "confirmados_por_tipo": dict(collections.Counter(x["tipo"] for x in dec
                                                                    if x["estado"] == C.CONFIRMADO)),
                   "numeros_por_tipo": dict(collections.Counter(x["tipo"] for x in dec)),
                   "recorte": dict(collections.Counter(r["estado"] for r in rec)),
                   "dedup": ocr["dedup"], "s": round(time.monotonic() - t0, 2)}
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            if k % 100 == 0:
                f.flush()
                print(f"mistos {k}/{len(xs)}", flush=True)
    return resumo_mistos(d)


def mistos_e5(d: Path, modo: str, fatia: str | None, limite: int | None) -> dict:
    """Reprocessamento dos mistos com os EXECUTORES REAIS do E5 (sem PNG intermediário): `modo=gpu` = Surya + 2º
    motor RapidOCR (o E5 no it-campo); `modo=cpu` = RapidOCR + 2º motor Tesseract (a volta CPU do E5). E6 real:
    código de barras primeiro, leitura independente, recorte, SIAFE do snapshot. O lateral do E5 vai a
    `<dir>/laterais` (sombra; nada no PG). `fatia` k/n reparte os documentos entre processos; a ordem é a sorteada
    do `selecionar` (rodada parcial = amostra aleatória dos mistos)."""
    import sqlite3

    from compliance_agent.aplicacao.estagios import ErroPermanente
    from compliance_agent.aplicacao.estagios import confirmar_ocr as C
    from compliance_agent.aplicacao.estagios import ocr as O
    from compliance_agent.aplicacao.estagios import ocr_recorte as R
    from compliance_agent.aplicacao.estagios import texto as T
    from compliance_agent.sei import ocr_ia_prova as P
    principal, segundo = (O.ExecutorGPU(), O.ExecutorCPU()) if modo == "gpu" else (O.ExecutorCPU(),
                                                                                  O.ExecutorTesseract())
    cache = O.CacheImagem(d / O.PASTA_DEDUP)
    leit = R.leitores_do_no()
    con = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro&immutable=1", uri=True) if SNAPSHOT.exists() else None
    k_f, n_f = (int(x) for x in fatia.split("/")) if fatia else (0, 1)
    saida = d / f"mistos_e5.{modo}.f{k_f}.jsonl"
    feitos = {r["hd"] for arq in d.glob("mistos_e5.*.jsonl") for r in _jl(arq)}
    xs = [m for m in _jl(d / "mistos.jsonl") if m["hd"] not in feitos and int(_h(m["hd"])[:8], 16) % n_f == k_f]
    xs = xs[:limite] if limite else xs
    siafe_cache: dict = {}
    with saida.open("a", encoding="utf-8") as f:
        for m in xs:
            pdf = _local(m["hd"])
            t0 = time.monotonic()
            try:
                e4 = T.extrair(pdf)
                ocr = O.ocr_documento(pdf, e4, principal, segundo, cache)
            except (O.ErroInferencia, ErroPermanente, *ERROS_PDF) as e:
                f.write(json.dumps({"hd": m["hd"], "modo": modo, "erro": f"{type(e).__name__}: {str(e)[:160]}"}) + "\n")
                f.flush()
                continue
            t_ocr = time.monotonic() - t0
            reusadas = ocr.pop("cache_reusadas")
            T.gravar_lateral(T.caminho_lateral(m["processo"] or m["tag"], f"i{m['i']}", T.sha256_arquivo(pdf), "e5",
                                               d / "laterais"), {"hd": m["hd"], **ocr})
            nativo = T.texto_composto(e4)
            kn, kc = _chaves(nativo), _chaves(ocr["texto_composto"])
            nums = C.numeros_do_ocr(ocr)
            pags = sorted({x["pagina"] for x in nums})
            motores = {x["pagina"]: x["motor"] for x in nums}
            bar = C.barras(pdf, pags) if nums else {"chaves": []}
            leituras_ = C.leitura_independente(pdf, pags, motores) if nums else {}
            rec = R.conferir(pdf, ocr, nums, leit) if nums else []
            ext: dict = {}
            if con is not None and m.get("processo"):
                if m["processo"] not in siafe_cache:
                    siafe_cache[m["processo"]] = {a: set(b) for a, b in P.fontes_externas(m["processo"], con).items()}
                ext = dict(siafe_cache[m["processo"]])
            if bar.get("chaves"):
                ext["barras"] = {tuple(x) for x in bar["chaves"]}
            ext.update(R.chaves_confirmadas(rec))
            dec = C.decidir(nums, leituras_, ext)
            novos = kc - kn
            conf = [x for x in dec if x["estado"] == C.CONFIRMADO]
            res = {"hd": m["hd"], "modo": modo, "tipo": m["tipo"], "paginas_escaneadas": len(ocr["alvo"]),
                   "estados": dict(collections.Counter(v["estado"] for v in ocr["paginas"].values())),
                   "segundo_motor": sum(1 for v in ocr["paginas"].values()
                                        if v.get("primeiro_vazio") or v.get("primeiro_incompleto")),
                   "incompletas_do_primeiro": sum(1 for v in ocr["paginas"].values() if v.get("primeiro_incompleto")),
                   "dedup_no_doc": len(ocr["dedup"]["reusadas"]), "dedup_cache": len(reusadas),
                   "chars_nativo": len(nativo.strip()), "chars_composto": ocr["chars"],
                   "nativo_preservado": len(ocr["compostas"]) == len(e4["paginas"]) and all(
                       c.startswith((p["texto"] or "").rstrip()) for c, p in zip(ocr["compostas"], e4["paginas"])),
                   "novos": len(novos), "novos_por_tipo": dict(collections.Counter(t for t, _ in novos)),
                   "numeros_ocr": len(dec), "numeros_por_tipo": dict(collections.Counter(x["tipo"] for x in dec)),
                   "confirmados": len(conf), "confirmados_por_tipo": dict(collections.Counter(x["tipo"] for x in conf)),
                   "por_fonte": C._contar([x["fonte"] for x in conf]),
                   "por_fonte_concordante": C._contar([fx for x in conf
                                                       for fx in {C._familia_fonte(y) for y in x["concordantes"]}]),
                   "recorte": dict(collections.Counter(r["estado"] for r in rec)),
                   "barras_chaves": len(bar.get("chaves") or []), "s_ocr": round(t_ocr, 2),
                   "s": round(time.monotonic() - t0, 2)}
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()
    return resumo_mistos(d)


def resumo_mistos(d: Path) -> dict:
    rs = list(_jl(d / "mistos_resultado.jsonl")) + [r for arq in sorted(d.glob("mistos_e5.*.jsonl")) for r in _jl(arq)]
    ok = [r for r in rs if not r.get("erro")]
    soma = lambda k: sum(r[k] for r in ok)                     # noqa: E731
    cnt = lambda k: dict(sum((collections.Counter(r[k]) for r in ok), collections.Counter()))  # noqa: E731
    return {"documentos": len(rs), "erros": len(rs) - len(ok), "paginas_escaneadas": soma("paginas_escaneadas"),
            "estados_pagina": cnt("estados"), "nativo_preservado_em_todos": all(r["nativo_preservado"] for r in ok),
            "chars_nativo": soma("chars_nativo"), "chars_composto": soma("chars_composto"),
            "ganho_chars_%": round(100 * (soma("chars_composto") - soma("chars_nativo")) / max(soma("chars_nativo"), 1),
                                   2),
            "docs_com_numero_novo": sum(1 for r in ok if r["novos"]), "numeros_novos": soma("novos"),
            "novos_por_tipo": cnt("novos_por_tipo"), "numeros_ocr": soma("numeros_ocr"),
            "confirmados": soma("confirmados"), "confirmados_por_tipo": cnt("confirmados_por_tipo"),
            "numeros_por_tipo": cnt("numeros_por_tipo"), "por_fonte": cnt("por_fonte"),
            "por_fonte_concordante": cnt("por_fonte_concordante"), "recorte": cnt("recorte"),
            "s_por_doc_p50": round(statistics.median(r["s"] for r in ok), 2) if ok else None}


# ── ouro ───────────────────────────────────────────────────────────────────────────────────────────────────────
_LEIT_REC: dict = {}


def _rotular(job: dict) -> dict:
    """Um item do ouro: recorte dos números recortáveis (motor de outra família na bbox da 1ª linha que o contém),
    rótulo por consenso e recortes PNG da revisão. Roda num processo do pool."""
    from PIL import Image

    from compliance_agent.aplicacao.estagios import ocr_recorte as R
    from compliance_agent.qualidade import ouro_ocr as OO
    if not _LEIT_REC:
        _LEIT_REC.update(R.leitores_do_no())
    x, ls, rev_dir = job["x"], job["ls"], Path(job["rev_dir"])
    s = x["img_sha"]
    img = _img(job["png"])
    cand = set().union(*(OO.chaves(v["texto"]) for v in ls.values()))
    ok_rec, onde = set(), {}
    lidos_bbox: dict[tuple, set] = {}                         # o bloco grande do Surya é lido UMA vez por página
    for k in sorted(cand):
        if k[0] not in R.TIPOS_RECORTE:
            continue
        for m in ("rapidocr", "surya", "tesseract"):                # a 1ª linha que contém o número, nesta ordem
            if m not in ls:
                continue
            bbs = R.linhas_com(ls[m], *k)
            lr = _LEIT_REC.get(R.familia_para(ls[m]["motor"]) or "")
            if not bbs or lr is None:
                continue
            onde[k] = bbs[0]
            chave_bb = (tuple(bbs[0]), lr.familia)
            if chave_bb not in lidos_bbox:
                c = R.recortar(img, bbs[0])
                lidos_bbox[chave_bb] = _chaves(R.compactar(lr.ler_imagem(c)), tolerante=True) if c is not None else set()
            if k in lidos_bbox[chave_bb]:
                ok_rec.add(k)
            break
    rot, rev = OO.rotular_pagina({v["motor"]: v["texto"] for v in ls.values()}, ok_rec, set(R.TIPOS_RECORTE))
    item = f"{x['tag']}/{int(x['i']):03d}.pdf#{x['pagina']}"
    revisao = []
    for r in rev:
        t, n = r["numero"].split(":", 1)
        bb = onde.get((t, n))
        c = R.recortar(img, bb) if bb is not None else None
        if c is not None:
            arq = rev_dir / f"{s[:16]}_{_h(r['numero'])[:10]}.png"
            Image.fromarray(c).save(arq)
            r["recorte_png"], r["bbox"] = arq.name, bb
        revisao.append({"img_sha": s, "item": item, **r,
                        "leituras": {m: sorted(f"{a}:{b}" for a, b in OO.chaves(v["texto"]) if a == t)
                                     for m, v in ls.items()}})
    return {"pagina": {"item": item, "processo": x["processo"], "grupo": x["grupo"], "tipo_doc": x["tipo"],
                       "img_sha": s, "rotulos": rot, "revisar": rev,
                       "motores": sorted(v["motor"] for v in ls.values())}, "revisao": revisao,
            "recorte_tentado": len(onde), "recorte_confere": len(ok_rec)}


def ouro(d: Path, congelado_em: str, procs: int) -> dict:
    """Rótulos do ouro com os TRÊS motores de família distinta (Surya, RapidOCR, Tesseract); o PP-OCRv6 fica de fora
    do rótulo de propósito — é medido contra ele (rotular com o motor avaliado inflaria a nota dele)."""
    from compliance_agent.qualidade import ouro_ocr as OO
    lt = {m: leituras(d, m) for m in ("surya", "rapidocr", "tesseract")}
    png = {r["img_sha"]: str(d / "png" / Path(r["png"]).name) for arq in ("render_ocr.jsonl", "render_ouro.jsonl")
           for r in _jl(d / arq) if not r.get("erro")}
    rev_dir = d / "ouro" / "revisao"
    rev_dir.mkdir(parents=True, exist_ok=True)
    falta, jobs = collections.Counter(), []
    for x in _jl(d / "ouro_cand.jsonl"):
        s = x["img_sha"]
        ls = {m: lt[m][s] for m in lt if s in lt[m]}
        if len({OO.familia(v["motor"]) for v in ls.values()}) < 3 or s not in png:
            falta[x["grupo"]] += 1
            continue
        jobs.append({"x": x, "ls": ls, "png": png[s], "rev_dir": str(rev_dir)})
    pags, revisao, tent, conf = [], [], 0, 0
    from concurrent.futures import ProcessPoolExecutor
    # ProcessPoolExecutor, não Pool: processo filho morto (25/11: 10 de 10 defuntos e o Pool parado para sempre) vira
    # BrokenProcessPool visível. SEM max_tasks_per_child: com map() tudo é submetido de uma vez e o executor não repõe
    # o filho que saiu pelo teto — trava calado (medido: 2ª rodada parada em ~600 de 805)
    parcial = d / "ouro" / f"parcial-{congelado_em}.jsonl"
    feitos = {r["pagina"]["img_sha"]: r for r in _jl(parcial)}
    falta_ler = [j for j in jobs if j["x"]["img_sha"] not in feitos]
    with parcial.open("a", encoding="utf-8") as fp, \
            ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as pool:
        for res in pool.map(_rotular, falta_ler, chunksize=1):
            fp.write(json.dumps(res, ensure_ascii=False) + "\n")
            fp.flush()
            feitos[res["pagina"]["img_sha"]] = res
    for j in jobs:
        res = feitos[j["x"]["img_sha"]]
        pg = res["pagina"]
        pags.append(OO.PaginaOuro(**{**pg, "rotulos": tuple(pg["rotulos"]), "revisar": tuple(pg["revisar"]),
                                     "motores": tuple(pg["motores"])}, rotulado_em=congelado_em))
        revisao += res["revisao"]
        tent += res["recorte_tentado"]
        conf += res["recorte_confere"]
    arq = OO.congelar(pags, d / "ouro", congelado_em)
    with (d / "ouro" / f"revisao-{congelado_em}.jsonl").open("w", encoding="utf-8") as f:
        for r in sorted(revisao, key=lambda r: (r["img_sha"], r["numero"])):
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    man = json.loads(arq.with_name(arq.name.replace(".jsonl", ".manifesto.json")).read_text())
    return man | {"sem_tres_familias": dict(falta), "revisao_itens": len(revisao),
                  "revisao_por_motivo": dict(collections.Counter(r["motivo"] for r in revisao)),
                  "revisao_com_recorte_png": sum(1 for r in revisao if r.get("recorte_png")),
                  "recorte_tentado": tent, "recorte_confere": conf,
                  "paginas_sem_numero": sum(1 for p in pags if not p.rotulos and not p.revisar)}


def validar_rotulo(d: Path, procs: int) -> dict:
    """CONTROLE POSITIVO DO PRÓPRIO MÉTODO DE RÓTULO: roda o mesmo consenso (3 famílias + recorte) nas páginas
    NATIVAS do controle e compara com a verdade do texto nativo. precisão = rótulo que é verdade; cobertura = verdade
    que virou rótulo. Se o método errasse aqui, o ouro não valeria."""
    from concurrent.futures import ProcessPoolExecutor
    lt = {m: leituras(d, m, "controle") for m in ("surya", "rapidocr", "tesseract")}
    tmp = d / "validar_rotulo_recortes"
    tmp.mkdir(exist_ok=True)
    jobs = []
    for r in _jl(d / "render_controle.jsonl"):
        s = r.get("img_sha")
        if r.get("erro") or not all(s in lt[m] for m in lt):
            continue
        x = {"img_sha": s, "tag": "controle", "i": 0, "pagina": r["pagina"], "processo": "", "grupo": "nota_fiscal",
             "tipo": "controle"}
        jobs.append({"x": x, "ls": {m: lt[m][s] for m in lt}, "png": str(d / "png" / Path(r["png"]).name),
                     "rev_dir": str(tmp)})
    verdade = _controle_verdade(d)
    rot = ver = acerto = 0
    errados = collections.Counter()
    with ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as pool:
        for job, res in zip(jobs, pool.map(_rotular, jobs, chunksize=1)):
            v = {f"{a}:{b}" for a, b in verdade.get(job["x"]["img_sha"], set())}
            rs = set(res["pagina"]["rotulos"])
            rot += len(rs)
            ver += len(v)
            acerto += len(rs & v)
            for e in rs - v:
                errados[e.split(":", 1)[0]] += 1
    return {"paginas": len(jobs), "rotulos": rot, "verdadeiros": ver, "rotulos_verdadeiros": acerto,
            "precisao_%": round(100 * acerto / rot, 2) if rot else None,
            "cobertura_%": round(100 * acerto / ver, 2) if ver else None, "rotulos_fora_da_verdade_por_tipo": dict(errados),
            "_nota": "rótulo fora da verdade nativa inclui número visível na imagem que a camada de texto não tem"}


# ── medir ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _controle_verdade(d: Path) -> dict[str, set]:
    """{img_sha: números do TEXTO NATIVO} das páginas nativas renderizadas (a verdade é a camada de texto)."""
    import fitz
    out = {}
    for r in _jl(d / "render_controle.jsonl"):
        if r.get("erro"):
            continue
        with fitz.open(_local(r["hd"])) as doc:
            out[r["img_sha"]] = _chaves(doc.load_page(r["pagina"] - 1).get_text("text") or "")
    return out


def medir(d: Path, congelado: str | None) -> dict:
    from compliance_agent.qualidade import ouro_ocr as OO
    out: dict = {"controle_nativo": {}, "ouro": {}, "tempos": {}}
    verdade = _controle_verdade(d)
    for m in MOTORES_MEDIDOS:
        for nome, lista in (("controle_nativo", "controle"), ("ouro", "ocr")):
            rs = leituras(d, m, lista)
            if not rs:
                continue
            ss = [r["s"] for r in rs.values() if r.get("s") is not None]
            out["tempos"].setdefault(m, {})[nome] = {"paginas": len(ss), "s_p50": round(statistics.median(ss), 3),
                                                     "s_media": round(statistics.mean(ss), 3)} if ss else {}
            if nome == "controle_nativo":
                tot = ok = emit = inv = 0
                por_tipo = collections.Counter()
                por_pag = []
                for s, v in verdade.items():
                    if s not in rs:
                        continue
                    lidos = _chaves(rs[s]["texto"])
                    if v:
                        por_pag.append(len(v & lidos) / len(v))
                    ok += len(v & lidos)
                    tot += len(v)
                    emit += len(lidos)
                    inv += len(lidos - v)
                    for t, _ in lidos - v:
                        por_tipo[t] += 1
                out[nome][m] = {"paginas": sum(1 for s in verdade if s in rs), "verdadeiros": tot, "lidos": ok,
                                "acerto_%": round(100 * ok / tot, 2) if tot else None, "emitidos": emit,
                                "inventados": inv, "inventado_%": round(100 * inv / emit, 2) if emit else None,
                                "inventados_por_tipo": dict(por_tipo),
                                "paginas_com_numero": len(por_pag),
                                "acerto_pagina_p50_%": round(100 * statistics.median(por_pag), 1) if por_pag else None,
                                "paginas_>=95%": sum(1 for x in por_pag if x >= 0.95),
                                "paginas_<50%": sum(1 for x in por_pag if x < 0.5)}
    if congelado:
        pags = OO.ler_congelado(Path(congelado))
        for m in MOTORES_MEDIDOS:
            lt = {s: {r["motor"]: r["texto"]} for s, r in leituras(d, m).items()}
            if lt:
                out["ouro"][m] = OO.medir(pags, lt) | {"por_grupo": {
                    g: OO.medir([p for p in pags if p.grupo == g], lt) for g in OO.GRUPOS}}
        out["ouro"]["_nota"] = ("o ouro é rotulado pelo CONSENSO dos próprios motores (+ recorte): mede concordância "
                                "com o consenso, não verdade humana; a verdade absoluta é o controle nativo")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etapa", choices=["perfil", "dedup", "selecionar", "render", "ler", "barras", "mistos", "ouro",
                                      "medir", "resumo_mistos", "mistos_e5", "validar_rotulo"])
    ap.add_argument("--modo", choices=["gpu", "cpu"], default="cpu")
    ap.add_argument("--dir", default=str(Path.home() / "o36"))
    ap.add_argument("--procs", type=int, default=max((os.cpu_count() or 4) - 4, 1))
    ap.add_argument("--limite", type=int)
    ap.add_argument("--lista", default="ocr")
    ap.add_argument("--motor")
    ap.add_argument("--lote", type=int, default=8)
    ap.add_argument("--por-grupo", type=int, default=200)
    ap.add_argument("--controle-por-grupo", type=int, default=40)
    ap.add_argument("--congelado-em")
    ap.add_argument("--congelado")
    ap.add_argument("--fatia", help="ler: k/n — só as imagens com hash ≡ k (mod n), saída .f<k>.jsonl")
    ap.add_argument("--so-ouro", action="store_true", help="ler: só as páginas do ouro (antes dos mistos)")
    ap.add_argument("--extra-site", help="site-packages extra (ao FIM do sys.path) para o venv da GPU")
    a = ap.parse_args(argv)
    if a.extra_site:
        sys.path.append(a.extra_site)
    d = Path(a.dir)
    if a.etapa == "perfil":
        r = perfil(d, a.procs, a.limite)
    elif a.etapa == "dedup":
        r = dedup(d)
    elif a.etapa == "selecionar":
        r = selecionar(d, a.por_grupo, a.controle_por_grupo)
    elif a.etapa == "render":
        r = render(d, a.lista, a.procs)
    elif a.etapa == "ler":
        r = ler(d, a.lista, a.motor, a.procs, a.lote, a.limite, a.so_ouro, a.fatia)
    elif a.etapa == "barras":
        r = barras(d, a.procs, a.limite or 2000)
    elif a.etapa == "mistos":
        r = mistos(d, a.limite)
    elif a.etapa == "mistos_e5":
        r = mistos_e5(d, a.modo, a.fatia, a.limite)
    elif a.etapa == "validar_rotulo":
        r = validar_rotulo(d, a.procs)
    elif a.etapa == "resumo_mistos":
        r = resumo_mistos(d)
    elif a.etapa == "ouro":
        r = ouro(d, a.congelado_em or time.strftime("%Y-%m-%d"), a.procs)
    else:
        r = medir(d, a.congelado)
    r = {"etapa": a.etapa, "em": time.strftime("%Y-%m-%d %H:%M:%S%z"), **r}
    nome = a.etapa + (f"_{a.motor}_{a.lista}" if a.etapa == "ler" else f"_{a.lista}" if a.etapa == "render" else "")
    (d / f"{nome}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, default=list)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
