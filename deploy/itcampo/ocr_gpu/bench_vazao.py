"""Bench de VAZÃO do OCR por IA (Surya 2.5 via vLLM, it-campo) — mesma amostra, modos de alimentação diferentes.

Pergunta (18/11/2026): o vLLM passava ~18% das amostras com 0 requisições em voo e boa parte do resto com poucas —
o trabalhador manda grupos de 48 páginas e ESPERA o grupo inteiro (cauda) e só então rasteriza o próximo (CPU).

    python bench_vazao.py grupo            # o trabalhador de produção: grupos de 48 com barreira
    python bench_vazao.py fluxo 32         # rasterização em fio próprio + 32 páginas sempre em voo, sem barreira
    SURYA_INFERENCE_LOGPROBS=false python bench_vazao.py fluxo 32
    python bench_vazao.py worker 32        # o ler_lote do ocr_gpu_worker.py novo (fluxo + página nativa fora da GPU)

Amostra: PDFs em ~/jfn-gpu/bench_vazao/pdfs (cópias fora da fila). Saída: uma linha JSON por rodada em
bench_vazao/resultados.jsonl e os textos por página em bench_vazao/textos_<modo>.json (para conferir que o modo não
muda o texto). Mede também, pelo /metrics do vLLM, a média de requisições em voo e a fração do tempo com zero.
"""
from __future__ import annotations

import html as _html
import io
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
from PIL import Image

BASE = Path.home() / "jfn-gpu" / "bench_vazao"
DPI = int(os.environ.get("OCR_DPI", "200"))
MAX_PAG = int(os.environ.get("BENCH_MAX_PAG", "30"))
METRICS = "http://127.0.0.1:8790/metrics"


def _txt(h: str) -> str:
    h = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", h or "")
    h = re.sub(r"</t[dh]>", " | ", h)
    return _html.unescape(re.sub(r"<[^>]+>", "", h))


def _texto(res) -> str:
    return "\n".join(_txt(b.html) for b in sorted(res.blocks, key=lambda b: b.reading_order or 0))


def paginas_da_amostra() -> list[tuple[str, int]]:
    out = []
    for p in sorted((BASE / "pdfs").glob("*.pdf")):
        with fitz.open(p) as d:
            out += [(p.name, i) for i in range(min(d.page_count, MAX_PAG))]
    return out


def rasterizar(nome: str, i: int) -> Image.Image:
    with fitz.open(BASE / "pdfs" / nome) as d:
        return Image.open(io.BytesIO(d.load_page(i).get_pixmap(dpi=DPI).tobytes("png"))).convert("RGB")


class Monitor(threading.Thread):
    """Amostra vllm:num_requests_running a cada 0,5 s."""

    def __init__(self):
        super().__init__(daemon=True)
        self.amostras: list[float] = []
        self.parar = threading.Event()

    def run(self):
        while not self.parar.is_set():
            try:
                with urllib.request.urlopen(METRICS, timeout=2) as r:
                    for ln in r.read().decode().splitlines():
                        if ln.startswith("vllm:num_requests_running{"):
                            self.amostras.append(float(ln.rsplit(" ", 1)[1]))
            except (OSError, ValueError):
                pass
            time.sleep(0.5)


def modo_grupo(rec, pags, por_chamada=48):
    """Réplica do laço do ocr_gpu_worker.py de produção (md5 2ffe0ec1…): rasteriza até 48, chama, espera, repete."""
    textos, t_raster, k = {}, 0.0, 0
    while k < len(pags):
        t0 = time.time()
        bloco = pags[k:k + por_chamada]
        imgs = [rasterizar(n, i) for n, i in bloco]
        t_raster += time.time() - t0
        for (n, i), r in zip(bloco, rec(imgs)):
            textos[f"{n}#{i}"] = _texto(r)
        k += por_chamada
    return textos, t_raster


def modo_fluxo(rec, pags, em_voo: int):
    """Produtor rasteriza num fio; `em_voo` fios consomem uma página por chamada — o vLLM nunca fica sem fila."""
    fila: queue.Queue = queue.Queue(maxsize=em_voo * 2)
    textos, t_raster = {}, [0.0]

    def produtor():
        for n, i in pags:
            t0 = time.time()
            img = rasterizar(n, i)
            t_raster[0] += time.time() - t0
            fila.put((n, i, img))
        for _ in range(em_voo):
            fila.put(None)

    def consumidor():
        while (item := fila.get()) is not None:
            n, i, img = item
            textos[f"{n}#{i}"] = _texto(rec([img])[0])

    threading.Thread(target=produtor, daemon=True).start()
    with ThreadPoolExecutor(em_voo) as ex:
        for f in [ex.submit(consumidor) for _ in range(em_voo)]:
            f.result()
    return textos, t_raster[0]


def main() -> int:
    modo = sys.argv[1]
    em_voo = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    import surya_utf8  # acentos: o modelo gera ç/ã em Latin-1 (ver o módulo)
    surya_utf8.instalar()
    from surya import RecognitionPredictor, SuryaInferenceManager
    rec = RecognitionPredictor(SuryaInferenceManager())
    pags = paginas_da_amostra()
    rec([rasterizar(*pags[0])])                       # aquecimento fora do cronômetro
    mon = Monitor()
    mon.start()
    t0 = time.time()
    if modo == "worker":
        sys.path.insert(0, os.environ.get("BENCH_WORKER_DIR", str(Path.home() / "jfn-gpu" / "novo")))  # candidato
        import ocr_gpu_worker as W
        W.BASE = BASE                                   # log de erro do candidato fica no bench, não no da produção
        pdfs = sorted({n for n, _ in pags})
        res, _, _ = W.ler_lote([(n, BASE / "pdfs" / n) for n in pdfs], rec, em_voo)
        textos = {f"{n}#{i}": t for n in pdfs for i, t in enumerate(res[n]["textos"])}
        t_raster = 0.0
    elif modo == "grupo":
        textos, t_raster = modo_grupo(rec, pags)
    else:
        textos, t_raster = modo_fluxo(rec, pags, em_voo)
    dt = time.time() - t0
    mon.parar.set()
    a = mon.amostras or [0.0]
    rot = f"{modo}{em_voo or ''}_dpi{DPI}_lp{os.environ.get('SURYA_INFERENCE_LOGPROBS', 'true').lower()}"
    res = {"rodada": rot, "em": time.strftime("%F %T"), "paginas": len(pags), "s": round(dt, 1),
           "s_por_pag": round(dt / len(pags), 3), "pags_por_h": round(3600 * len(pags) / dt),
           "raster_s_por_pag": round(t_raster / len(pags), 3), "em_voo_medio": round(sum(a) / len(a), 1),
           "frac_zero_em_voo": round(sum(x == 0 for x in a) / len(a), 3),
           "fffd": sum("�" in t for t in textos.values()), "chars": sum(map(len, textos.values()))}
    (BASE / f"textos_{rot}.json").write_text(json.dumps(textos, ensure_ascii=False), encoding="utf-8")
    with (BASE / "resultados.jsonl").open("a") as f:
        f.write(json.dumps(res, ensure_ascii=False) + "\n")
    print(json.dumps(res, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
