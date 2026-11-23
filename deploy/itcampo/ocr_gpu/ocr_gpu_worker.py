"""OCR por IA na GPU do it-campo (Surya 2.5 via vLLM local) dos PDFs escaneados do arquivo frio do SEI.

Medido em 18/11/2026 com gabarito (79 páginas nativas 'sujadas' como escaneado): Surya acerta 99,7% dos valores em
R$ (Tesseract, o OCR de produção: 78,0%), 100% das datas (89,8%), 95,7% dos CNPJ (92,5%), 1,24 s/página.

Fila: ocr_fila.txt (caminhos integra_X/NNN.pdf no vm2-ts:~/arquivo_frio/sei_cache). Por lote: baixa da VM-2,
renderiza a 200 dpi, OCR, grava out/integra_X/NNN.ocr.txt (+ .ocr.json com motor/páginas/tempo) e ENTREGA à VM-1
(rsync --ignore-existing: nunca sobrescreve texto que já exista lá). Retoma de onde parou (feitos.txt).
Cede memória às sessões SEI: abaixo de 3 GB livres no WSL, espera.

VAZÃO (18/11/2026, bench_vazao.py com a produção pausada): (1) página NATIVA (texto visível ≥ 200 caracteres, sem
camada invisível, imagens < 10% da página) não vai à GPU — o texto do próprio PDF é a verdade; na amostra de 40 PDFs
da fila, 98 de 263 páginas eram nativas (NF-e impressa do portal etc.). (2) FLUXO contínuo: a rasterização roda num
fio próprio e OCR_EM_VOO páginas ficam sempre em voo no vLLM — o laço antigo (grupos de 48 com barreira) deixava o
vLLM com 0 requisições em ~18% das amostras do /metrics e com poucas na cauda de cada grupo.

ARQUIVO FRIO NOVO (20/11/2026): o PDF que já está no disco do próprio it-campo (`C:\\JFN-Arquivo\\sei_pdfs`, levado para lá
em 15–16/11) é lido de lá, sem baixar; o resto vem da VM-2 (`sei_cache`, onde `tools/sei_ocr_gpu_fila.py` liga por link
físico o que mora em `sei_pdfs`). ENTREGA conferida: rsync --ignore-existing e md5 de cada arquivo nas duas pontas (a
mesma conferência da reserva, `tools/sei_ocr_reserva.entregar`); só o conferido sai de `out/`.
Lote avulso sem mexer no trabalhador vivo: OCR_BASE=<outra pasta> OCR_UMA_VEZ=1 (lê <pasta>/ocr_fila.txt e sai no fim).
"""
from __future__ import annotations

import hashlib
import html as _html
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
from PIL import Image

BASE = Path(os.environ.get("OCR_BASE", str(Path.home() / "jfn-gpu" / "ocr")))
UMA_VEZ = os.environ.get("OCR_UMA_VEZ") == "1"          # lote avulso: acabou a fila, sai (não puxa a da VM-1)
ARQUIVO_LOCAL = Path(os.environ.get("OCR_ARQUIVO_LOCAL", "/mnt/c/JFN-Arquivo/sei_pdfs"))
FILA, FEITOS, FALHAS = BASE / "ocr_fila.txt", BASE / "feitos.txt", BASE / "falhas.txt"
TMP, OUT = BASE / "tmp", BASE / "out"
LOTE = int(os.environ.get("OCR_LOTE", "40"))
MAX_PAG = int(os.environ.get("OCR_MAX_PAG", "120"))   # 200 dpi RGB ≈ 12 MB/página: 120 ≈ 1,4 GB no WSL
EM_VOO = int(os.environ.get("OCR_EM_VOO", "32"))   # páginas em voo no vLLM (KV cache de 2,1 GiB segura ~26 rodando)
VM1 = "vm1-ts:JFN/data/sei_cache/"
SINAL = Path.home() / "jfn-gpu" / "ocr" / "SESSAO_ATIVA"   # tocado pelo ocr_servico a cada página das sessões SEI


def ceder_as_sessoes(max_s: int = 600) -> None:
    """Captura ao vivo tem prioridade: enquanto uma sessão SEI pediu OCR há < 20 s, o lote espera (até 10 min)."""
    t0 = time.time()
    while SINAL.exists() and time.time() - SINAL.stat().st_mtime < 20 and time.time() - t0 < max_s:
        time.sleep(5)


def log(**kw):
    with (BASE / "ocr_gpu.log").open("a") as f:
        f.write(json.dumps({"t": time.strftime("%F %T"), **kw}, ensure_ascii=False) + "\n")
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def devolver_memoria() -> None:
    """19/11/2026: o trabalhador chegou a 5,7 GB de RSS em 10 h (o desenho prevê ~1,4 GB) — as imagens das páginas,
    alocadas em 32 threads, fragmentam as arenas do glibc e a memória livre nunca volta ao WSL; com isso o próprio
    trabalhador ficava em `espera_memoria` (182 de 300 eventos) e a GPU parada. Depois de cada lote: coleta e trim."""
    import ctypes
    import gc
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def mem_livre_gb() -> float:
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) / 1e6
    return 99.0


def _txt(h: str) -> str:
    h = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", h or "")
    h = re.sub(r"</t[dh]>", " | ", h)
    return _html.unescape(re.sub(r"<[^>]+>", "", h))


def pagina_nativa(pg) -> bool:
    """Texto visível ≥ 200 caracteres, nada invisível (camada de OCR antiga) e imagens < 10% da página."""
    area = abs(pg.rect) or 1.0
    cobertura = sum(abs(r & pg.rect) for x in pg.get_images() for r in pg.get_image_rects(x[0])) / area
    invisivel = any(s.get("type") == 3 for s in pg.get_texttrace())
    return cobertura < 0.10 and not invisivel and len(pg.get_text().strip()) >= 200


def _texto(res) -> str:
    return "\n".join(_txt(b.html) for b in sorted(res.blocks, key=lambda b: b.reading_order or 0))


def ler_lote(pdfs, rec, em_voo: int = EM_VOO):
    """OCR de um lote [(rel, caminho)] em fluxo contínuo. Devolve ({rel: {textos, nativas, paginas, paginas_pdf}},
    ruins = PDFs que não abrem, refazer = PDFs com alguma página falhada na GPU — voltam inteiros à fila)."""
    res, ruins, refazer, falhou = {}, [], [], set()
    fila: queue.Queue = queue.Queue(maxsize=em_voo * 2)       # ~12 MB por página a 200 dpi: limita a memória

    def produtor():
        try:
            for rel, caminho in pdfs:
                try:
                    with fitz.open(caminho) as doc:
                        n = min(doc.page_count, MAX_PAG)
                        r = res[rel] = {"textos": [None] * n, "nativas": [], "paginas": n, "paginas_pdf": doc.page_count}
                        for i in range(n):
                            pg = doc.load_page(i)
                            if pagina_nativa(pg):
                                r["textos"][i] = pg.get_text()
                                r["nativas"].append(i)
                                continue
                            ceder_as_sessoes()
                            img = Image.open(io.BytesIO(pg.get_pixmap(dpi=200).tobytes("png"))).convert("RGB")
                            fila.put((rel, i, img))
                except (OSError, ValueError, RuntimeError, MemoryError) as e:   # PDF ruim não para o lote
                    res.pop(rel, None)
                    ruins.append(rel)
                    log(ev="pdf_falhou", pdf=rel, erro=f"{type(e).__name__}: {str(e)[:200]}")
        finally:
            for _ in range(em_voo):
                fila.put(None)

    def consumidor():
        while (item := fila.get()) is not None:
            rel, i, img = item
            if rel in falhou:
                continue
            try:
                pagina = rec([img])[0]
                # 22/11/2026: o Surya ENGOLE o erro de inferência (vLLM fora, reinício) e devolve o bloco com
                # error=True e html vazio — o PDF saía "feito" com páginas vazias, o integrador descartava a entrega e
                # a fila o reapresentava para sempre (95 documentos; relidos, 38 de 40 tinham texto). Bloco com erro
                # e sem texto = falha da chamada: o PDF volta à fila como qualquer outra falha.
                if any(getattr(b, "error", False) and not getattr(b, "html", "") for b in pagina.blocks):
                    raise RuntimeError("bloco com erro de inferência (Surya devolveu vazio)")
                res[rel]["textos"][i] = _texto(pagina)
            except (OSError, ValueError, RuntimeError) as e:    # falha da chamada: o PDF volta à fila
                falhou.add(rel)
                log(ev="pagina_falhou", pdf=rel, pagina=i + 1, erro=f"{type(e).__name__}: {str(e)[:200]}")

    threading.Thread(target=produtor, daemon=True).start()
    with ThreadPoolExecutor(em_voo) as ex:
        for f in [ex.submit(consumidor) for _ in range(em_voo)]:
            f.result()
    for rel, _ in pdfs:
        if rel in falhou:
            res.pop(rel, None)
            refazer.append(rel)
    return res, ruins, refazer


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def entregar() -> tuple[int, list[str]]:
    """Entrega à VM-1 o que está em out/ (só o que não existe lá: --ignore-existing) e confere o md5 de CADA arquivo
    nas duas pontas. Conferido → apagado de out/; divergente ou não entregue → fica em out/ e volta no próximo lote.
    Devolve (rc do rsync, arquivos com md5 divergente)."""
    arqs = sorted(p.relative_to(OUT).as_posix() for suf in (".ocr_gpu.txt", ".ocr_gpu.json") for p in OUT.rglob(f"*{suf}"))
    if not arqs:
        return 0, []
    r = subprocess.run(["rsync", "-a", "--ignore-existing", "--include=*/", "--include=*.ocr_gpu.txt",
                        "--include=*.ocr_gpu.json", "--exclude=*", str(OUT) + "/", VM1],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        return r.returncode, []
    host, _, pasta = VM1.partition(":")
    rr = subprocess.run(["ssh", "-o", "BatchMode=yes", host, f"cd {pasta} && xargs -d '\\n' md5sum --"],
                        input=("\n".join(arqs) + "\n").encode(), capture_output=True, timeout=600)
    remoto = {ln[34:]: ln[:32] for ln in rr.stdout.decode("utf-8", "replace").splitlines()}
    ruins = []
    for a in arqs:
        if remoto.get(a) == _md5(OUT / a):
            (OUT / a).unlink()
        else:
            ruins.append(a)
    return (0 if rr.returncode in (0, 1) else rr.returncode), ruins     # md5sum rc 1 = algum ausente (vira ruim)


def main() -> int:
    import surya_utf8  # acentos: o modelo gera ç/ã em Latin-1 (ver o módulo)
    surya_utf8.instalar()
    from surya import RecognitionPredictor, SuryaInferenceManager
    rec = RecognitionPredictor(SuryaInferenceManager())
    for d in (TMP, OUT):
        d.mkdir(parents=True, exist_ok=True)
    feitos = set(FEITOS.read_text().split()) if FEITOS.exists() else set()
    falhas = set(FALHAS.read_text().split()) if FALHAS.exists() else set()
    fila = [p for p in FILA.read_text().split() if p not in feitos and p not in falhas] if FILA.exists() else []
    log(ev="inicio", pendentes=len(fila), feitos=len(feitos))
    if any(OUT.rglob("*.ocr_gpu.txt")):     # sobra de lote interrompido: entrega antes de seguir
        rc, ruins = entregar()
        log(ev="sobra_entregue", rc=rc, md5_divergente=ruins[:20])
    while True:
        if not fila and UMA_VEZ:
            log(ev="fim_uma_vez", feitos=len(feitos))
            return 0
        if not fila:      # acabou: puxa a fila que a VM-1 remonta (tools/sei_ocr_gpu_fila.py); nada novo → 1 h
            r = subprocess.run(["rsync", "-a", "vm1-ts:JFN/data/sei_ocr_gpu_fila.txt", str(FILA)],
                               capture_output=True, text=True, timeout=300)
            fila = [p for p in FILA.read_text().split() if p not in feitos and p not in falhas] \
                if r.returncode == 0 and FILA.exists() else []
            log(ev="fila_da_vm1", rc=r.returncode, pendentes=len(fila))
            if not fila:
                time.sleep(3600)
                continue
        if (BASE / "PAUSA").exists():
            time.sleep(60); continue
        if mem_livre_gb() < 3.0:
            log(ev="espera_memoria", livre_gb=round(mem_livre_gb(), 1)); time.sleep(120); continue
        lote, fila = fila[:LOTE], fila[LOTE:]
        locais = {rel: ARQUIVO_LOCAL / rel for rel in lote if (ARQUIVO_LOCAL / rel).is_file()}   # disco do it-campo
        remotos = [rel for rel in lote if rel not in locais]
        lst = TMP / "lote.txt"
        lst.write_text("\n".join(remotos) + "\n")
        r = subprocess.run(["rsync", "-a", "--files-from", str(lst), "vm2-ts:arquivo_frio/sei_cache/", str(TMP) + "/"],
                           capture_output=True, text=True, timeout=1800) if remotos else None
        if r is not None and r.returncode not in (0, 23):
            log(ev="rsync_vm2_falhou", rc=r.returncode, erro=r.stderr[-300:]); fila = lote + fila; time.sleep(300); continue
        t_lote, pags_lote, nativas_lote = time.time(), 0, 0
        res, ruins, refazer = ler_lote([(rel, locais.get(rel, TMP / rel)) for rel in lote], rec)   # ausente = ruim
        devolver_memoria()
        for rel in ruins:
            with FALHAS.open("a") as f:
                f.write(rel + "\n")
        if refazer:
            fila = refazer + fila
            time.sleep(60)
        for rel, r in res.items():
            texto = "\n\n".join(f"[página {i + 1}]\n{t}" for i, t in enumerate(r["textos"]))
            destino = OUT / rel[:-4]
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.with_suffix(".ocr_gpu.txt").write_text(texto, encoding="utf-8")
            destino.with_suffix(".ocr_gpu.json").write_text(json.dumps(
                {"motor": "surya-ocr-2.5 (vLLM, RTX 5070, it-campo)", "paginas": r["paginas"],
                 "paginas_pdf": r["paginas_pdf"], "cortado": r["paginas_pdf"] > r["paginas"],
                 "paginas_nativas": [i + 1 for i in r["nativas"]], "chars": len(texto),
                 "leitura_conferida": True,      # nenhuma página com erro de inferência: vazio aqui é vazio de fato
                 "em": time.strftime("%F %T")}, ensure_ascii=False))
            pags_lote += r["paginas"]
            nativas_lote += len(r["nativas"])
            feitos.add(rel)
            with FEITOS.open("a") as f:
                f.write(rel + "\n")
        for rel in lote:
            if rel not in refazer:
                (TMP / rel).unlink(missing_ok=True)
        # entrega à VM-1 — só o que não existe lá, md5 conferido nas duas pontas
        rc, divergentes = entregar()
        dt = time.time() - t_lote
        log(ev="lote", pdfs=len(lote), paginas=pags_lote, nativas=nativas_lote, s=round(dt),
            s_por_pag=round(dt / max(pags_lote, 1), 2), locais=len(locais),
            entregue=rc == 0 and not divergentes, md5_divergente=divergentes[:20], restantes=len(fila))
    return 0


if __name__ == "__main__":
    sys.exit(main())
