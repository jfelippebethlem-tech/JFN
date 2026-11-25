# -*- coding: utf-8 -*-
"""Retomada da O3.6 item 6 — reprocessamento dos documentos MISTOS (página nativa + página escaneada nunca lida) em
SOMBRA, com o E5 ATUAL (`e5-3`) e a saída no formato que o E5 grava e consome. Plano mestre v2 §1.1 passo 6
(exceção da parada): "texto só onde vazio, motor@versão" — nada no PG, no `compliance.db`, no acervo ou no frio.

Saída (`--dir`, no it-campo `D:\\JFN-Frio\\sombra-o36-mistos`):
  fila.jsonl                 os mistos do C: (`/mnt/c/o36c/mistos.jsonl`) e do HD (perfil da O3.6, mesmo critério do
                             `ocr_bancada_o36.selecionar`), na ordem sorteada
  texto/<pasta>/<doc>.<sha16>.e5.json   lateral do E5, MESMO conteúdo que o `ocr._handler` grava (versao, processo,
                             doc_id, entrada_sha, e4_*, nativo, perfis + o resultado de `ocr_documento`)
  _dedup_imagem/             o `CacheImagem` do E5 (img_sha × motor@versão) — gravado PÁGINA A PÁGINA: a retomada é
                             idempotente por (sha256 do documento, página)
  resultados/<modo>.f<k>.jsonl  uma linha por documento: conferência do efeito do E5 (as MESMAS checagens do
                             `ocr.conferir`, sem o PG) + a medida da O3.6 (texto ganho, números novos, nível A do E6)
  governo.json               quantos processos podem pegar documento novo (o governador escreve; os workers leem)

Etapas: `fila`, `rodar --fatia k/n --modo cpu|gpu`, `governar --max N`, `medir_gpu` (GPU × CPU no controle nativo),
`resumo` (por lote de 100 documentos), `indice` (índice + md5 do que está no HD).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from tools import ocr_bancada_o36 as B  # noqa: E402

FONTES = (("c", Path("/mnt/c/o36c")), ("hd", Path("/mnt/c/o36")))
_RX_SEI = re.compile(r"\((\d{6,})\)\s*$")
# imagens guardadas por documento: o E5 guarda até 1,5 GB por job; 6 processos × 1,5 GB tiravam a folga de RAM do
# it-campo. Acima disto a página é renderizada de novo (contada em `repetidas`) — mesma imagem, mesmo hash
RASTER_SOMBRA = int(os.environ.get("JFN_SOMBRA_RASTER_MB", "256")) << 20


# ── fila ───────────────────────────────────────────────────────────────────────────────────────────────────────
def fila(d: Path) -> dict:
    """C: = a lista já sorteada da O3.6; HD = o perfil COMPLETO do HD (o `mistos.jsonl` de lá é de um perfil parcial)
    com o critério do `selecionar` — sem reescrever os arquivos do ouro/controle de lá."""
    out, vistos, por = [], set(), collections.Counter()
    for origem, base in FONTES:
        titulos = {r["hd"]: r.get("titulo") or "" for r in B._jl(base / "corpus.jsonl")}
        if origem == "c":
            xs = list(B._jl(base / "mistos.jsonl"))
        else:
            xs = []
            for r in B._jl(base / "perfil.jsonl"):
                if not r.get("erro") and r["perfil"] == "mista" and not r["invalido"] and not B._sim(r.get("ocr")) \
                        and r.get("img_sha") and any(pf == "nativa" for pf, _ in r["paginas"]):
                    xs.append({k: r[k] for k in ("hd", "tag", "i", "tipo", "processo")} |
                              {"escaneadas": sorted(int(n) for n in r["img_sha"])})
            xs.sort(key=lambda m: B._h(m["hd"]))
        for m in xs:
            if m["hd"] in vistos:
                continue
            vistos.add(m["hd"])
            sei = _RX_SEI.search(titulos.get(m["hd"], ""))
            out.append({"hd": m["hd"], "origem": origem, "processo": m.get("processo"), "tag": m["tag"], "i": m["i"],
                        "tipo": m.get("tipo"), "doc_id": f"sei:{sei.group(1)}" if sei else f"i{m['i']}",
                        "escaneadas": len(m["escaneadas"])})
            por[origem] += 1
    d.mkdir(parents=True, exist_ok=True)
    with (d / "fila.jsonl").open("w", encoding="utf-8") as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return {"documentos": len(out), "por_origem": dict(por),
            "paginas_escaneadas": sum(x["escaneadas"] for x in out),
            "sem_id_sei": sum(1 for x in out if not x["doc_id"].startswith("sei:"))}


# ── executores ─────────────────────────────────────────────────────────────────────────────────────────────────
def _executor_gpu():
    """RapidOCR do E5 (mesmos modelos, mesmo pós-processo de `sei_ocr_reserva`) no CUDA do onnxruntime-gpu. motor@versão
    DIZ que é GPU — a leitura da GPU nunca se passa pela da CPU no cache do E5."""
    from compliance_agent.aplicacao.estagios import ocr as O

    class ExecutorRapidGPU(O.ExecutorCPU):
        def motor(self) -> str:
            from importlib.metadata import version
            return f"rapidocr@{version('rapidocr')} PP-OCRv5 mobile+latin (GPU cuda ort{version('onnxruntime-gpu')}) " \
                   f"dpi{O.DPI}"

        def ler_img(self, img):
            if self._eng is None:
                import onnxruntime
                from rapidocr import RapidOCR
                from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion
                onnxruntime.preload_dlls()
                mem = int(float(os.environ.get("JFN_GPU_MEM_GB", "2")) * (1 << 30))
                self._eng = RapidOCR(params={
                    "Det.ocr_version": OCRVersion("PP-OCRv5"), "Det.model_type": ModelType("mobile"),
                    "Det.lang_type": LangDet("ch"), "Rec.ocr_version": OCRVersion("PP-OCRv5"),
                    "Rec.model_type": ModelType("mobile"), "Rec.lang_type": LangRec("latin"),
                    "Global.use_cls": False, "Global.text_score": 0.0, "Global.max_side_len": 4000,
                    "Global.log_level": "error", "EngineConfig.onnxruntime.use_cuda": True,
                    "EngineConfig.onnxruntime.cuda_ep_cfg.gpu_mem_limit": mem,
                    "EngineConfig.onnxruntime.cuda_ep_cfg.arena_extend_strategy": "kSameAsRequested",
                    "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
                    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 1})
            return super().ler_img(img)
    return ExecutorRapidGPU()


class _PorPagina:
    """Envolve um executor do E5: lê UMA página por vez e guarda no `CacheImagem` logo depois (mesma chave e origem
    que o `_ler_dedup` usaria). Interrompido no meio do documento, a retomada não relê o que já foi lido."""

    def __init__(self, inner, cache):
        self.inner, self.cache, self.familia = inner, cache, inner.familia

    def motor(self) -> str:
        return self.inner.motor()

    def ler(self, pdf: Path, paginas: list[int]) -> dict:
        from compliance_agent.aplicacao.estagios import ocr as O
        out, m = {}, self.inner.motor()
        for n in paginas:
            le = self.inner.ler(pdf, [n])[n]
            out[n] = le
            self.cache.guardar(O.hashes_imagem(pdf, [n])[n], m, le, f"{pdf.name}#p{n}")
        return out


class _GuardaVRAM:
    """A GPU do it-campo é dividida com o Voicebox (outro agente): fica sempre `LIVRE_GB` livre. Antes de carregar o
    modelo, espera ter `LIVRE_GB` + o que este processo vai ocupar; depois, se OUTRO processo subiu na GPU e a folga
    caiu abaixo de `LIVRE_GB`, este processo SAI (devolve a VRAM) — recua, nunca disputa."""
    LIVRE_GB = float(os.environ.get("JFN_GPU_LIVRE_GB", "4"))
    PROPRIO_GB = 3.2                                             # medido: arena de 2 GB + contexto CUDA ≈ 3,0 GB

    def __init__(self):
        self.base = None                                         # VRAM usada antes de este processo carregar

    @staticmethod
    def _uso() -> tuple[float, float]:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30, check=True)
        usado, total = (float(x) / 1024 for x in r.stdout.split(",")[:2])
        return usado, total

    def antes_do_documento(self) -> None:
        usado, total = self._uso()
        if self.base is None:
            while total - usado < self.LIVRE_GB + self.PROPRIO_GB:
                time.sleep(60)
                usado, total = self._uso()
            self.base = usado
            return
        if total - usado < self.LIVRE_GB and usado - self.base > self.PROPRIO_GB + 0.5:
            raise SystemExit(f"recuo da GPU: outro processo usa {usado - self.base - self.PROPRIO_GB:.1f} GB e a folga "
                             f"caiu a {total - usado:.1f} GB (< {self.LIVRE_GB} GB)")


# ── conferência do efeito do E5 sem PG ─────────────────────────────────────────────────────────────────────────
class _PGDaSombra:
    """Responde às duas consultas do `ocr.conferir` com o que a sombra GRAVARIA (transformação desta versão e versão
    de texto): todas as outras checagens do efeito rodam como no E5."""

    def __init__(self, texto_sha: str, motor: str, lateral_sha: str):
        self.t = (texto_sha, *motor.partition("@")[::2], {"lateral_sha": lateral_sha})

    def execute(self, sql: str, _params=None):
        r = self.t if "FROM transformacao" in sql else (1,) if "FROM versoes" in sql else None

        class _C:
            def fetchone(self_):
                return r
        return _C()


# ── rodar ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _feitos(d: Path) -> tuple[set, set]:
    hds, shas = set(), set()
    for arq in (d / "resultados").glob("*.jsonl"):
        for r in B._jl(arq):
            hds.add(r["hd"])
            if r.get("entrada_sha") and not r.get("erro"):
                shas.add(r["entrada_sha"])
    return hds, shas


def _permitidos(d: Path, padrao: int) -> int:
    try:
        return int(json.loads((d / "governo.json").read_text(encoding="utf-8"))["permitidos"])
    except (OSError, ValueError, KeyError):
        return padrao


def rodar(d: Path, modo: str, fatia: str, limite: int | None, dinamico: bool = False) -> dict:
    import sqlite3

    from compliance_agent.aplicacao.estagios import ErroPermanente
    from compliance_agent.aplicacao.estagios import confirmar_ocr as C
    from compliance_agent.aplicacao.estagios import ocr as O
    from compliance_agent.aplicacao.estagios import ocr_recorte as R
    from compliance_agent.aplicacao.estagios import texto as T
    from compliance_agent.sei import ocr_ia_prova as P
    k_f, n_f = (int(x) for x in fatia.split("/"))
    cache = O.CacheImagem(d / O.PASTA_DEDUP)
    principal = _PorPagina(_executor_gpu() if modo == "gpu" else O.ExecutorCPU(), cache)
    vram = _GuardaVRAM() if modo == "gpu" else None
    segundo = _PorPagina(O.ExecutorTesseract(), cache)
    leit = R.leitores_do_no()
    con = sqlite3.connect(f"file:{B.SNAPSHOT}?mode=ro&immutable=1", uri=True) if B.SNAPSHOT.exists() else None
    (d / "resultados").mkdir(exist_ok=True)
    saida = d / "resultados" / f"{modo}.f{k_f}.jsonl"
    hds, shas = _feitos(d)
    xs = [m for m in B._jl(d / "fila.jsonl") if m["hd"] not in hds and
          (dinamico or int(B._h(m["hd"])[:8], 16) % n_f == k_f)]
    reservas = Path(os.environ.get("JFN_SOMBRA_RESERVAS") or d / "reservas")   # dinâmico: quem pega primeiro, lê
    reservas.mkdir(parents=True, exist_ok=True)
    xs = xs[:limite] if limite else xs
    siafe: dict = {}
    n = 0
    with saida.open("a", encoding="utf-8") as f:
        for m in xs:
            while _permitidos(d, n_f) <= k_f:                   # governador: este processo não pega documento novo
                time.sleep(20)
            if modo == "gpu":
                vram.antes_do_documento()                        # GPU dividida com o Voicebox: espera ou recua
            if dinamico:
                try:                                             # reserva atômica (O_EXCL) — o script limpa ao subir
                    os.close(os.open(reservas / B._h(m["hd"]), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                except FileExistsError:
                    continue
            pdf = B._local(m["hd"])
            t0 = time.monotonic()
            base = {"hd": m["hd"], "origem": m["origem"], "modo": modo, "processo": m["processo"],
                    "doc_id": m["doc_id"], "em": time.strftime("%Y-%m-%d %H:%M:%S")}
            try:
                sha = T.sha256_arquivo(pdf)
                if sha in shas:                                  # mesmo binário já reprocessado por outra entrada
                    f.write(json.dumps(base | {"entrada_sha": sha, "duplicado": True}) + "\n")
                    f.flush()
                    continue
                with O.rasterizacao_unica(RASTER_SOMBRA) as ras:
                    e4 = T.extrair(pdf) | {"e4_implicito": True}
                    ocr = O.ocr_documento(pdf, e4, principal, segundo, cache)
                    t_ocr = time.monotonic() - t0
                    reusadas = ocr.pop("cache_reusadas")
                    processo = m["processo"] or m["tag"]
                    lat = T.caminho_lateral(processo, m["doc_id"], sha, "e5", d / "texto")
                    nat = {str(p["pagina"]): p.get("texto") or "" for p in e4["paginas"]}
                    lat_sha = T.gravar_lateral(lat, {"versao": O.VERSAO, "processo": processo, "doc_id": m["doc_id"],
                                                     "entrada_sha": sha, "e4_texto_sha": e4.get("texto_sha"),
                                                     "e4_implicito": True, "nativo": nat,
                                                     "perfis": {str(p["pagina"]): p["perfil"] for p in e4["paginas"]},
                                                     "sombra": {"hd": m["hd"], "o36": "mistos", "gravado_pg": False},
                                                     **ocr})
                    m1 = ocr["paginas"][str(ocr["alvo"][0])]["motor"]
                    gravado = not ocr["pendentes"]
                    conf = O.conferir(_PGDaSombra(ocr["texto_sha"], m1, lat_sha),
                                      {"gravado": gravado, "processo": processo, "doc_id": m["doc_id"],
                                       "entrada_sha": sha, "texto_sha": ocr["texto_sha"], "lateral": str(lat),
                                       "versao": O.VERSAO, "pendentes": ocr["pendentes"]}) if gravado else \
                        {"ok": False, "motivo": f"pendentes {ocr['pendentes']}"}
                    # E6 (medida da O3.6): barras primeiro, leitura independente, recorte, SIAFE do snapshot
                    nativo = T.texto_composto(e4)
                    kn, kc = B._chaves(nativo), B._chaves(ocr["texto_composto"])
                    nums = C.numeros_do_ocr(ocr)
                    pags = sorted({x["pagina"] for x in nums})
                    motores = {x["pagina"]: x["motor"] for x in nums}
                    bar = C.barras(pdf, pags) if nums else {"chaves": []}
                    leituras_ = C.leitura_independente(pdf, pags, motores) if nums else {}
                    rec = R.conferir(pdf, ocr, nums, leit) if nums else []
                    rast = ras.resumo()
            except (O.ErroInferencia, ErroPermanente, *B.ERROS_PDF) as e:
                f.write(json.dumps(base | {"erro": f"{type(e).__name__}: {str(e)[:160]}"}) + "\n")
                f.flush()
                continue
            ext: dict = {}
            if con is not None and m.get("processo"):
                if m["processo"] not in siafe:
                    siafe[m["processo"]] = {a: set(b) for a, b in P.fontes_externas(m["processo"], con).items()}
                ext = dict(siafe[m["processo"]])
            if bar.get("chaves"):
                ext["barras"] = {tuple(x) for x in bar["chaves"]}
            ext.update(R.chaves_confirmadas(rec))
            dec = C.decidir(nums, leituras_, ext)
            novos = kc - kn
            ok = [x for x in dec if x["estado"] == C.CONFIRMADO]
            pags_e5 = ocr["paginas"].values()
            res = base | {
                "entrada_sha": sha, "versao": O.VERSAO, "lateral": str(lat.relative_to(d)), "lateral_sha": lat_sha,
                "motores": ocr["motores"], "conferencia_e5": conf,
                "nativas_intactas": bool(conf.get("nativa_nao_lida") and conf.get("nativo_preservado")) if gravado
                else None,
                "paginas_escaneadas": len(ocr["alvo"]),
                "estados": dict(collections.Counter(v["estado"] for v in pags_e5)),
                "por_motor": dict(collections.Counter(v["motor"] for v in pags_e5 if v["estado"] == O.TEXTO)),
                "segundo_motor": sum(1 for v in pags_e5 if v.get("primeiro_vazio") or v.get("primeiro_incompleto")),
                "dedup_no_doc": len(ocr["dedup"]["reusadas"]), "dedup_cache": len(reusadas),
                "chars_nativo": len(nativo.strip()), "chars_composto": ocr["chars"],
                "novos": len(novos), "novos_por_tipo": dict(collections.Counter(t for t, _ in novos)),
                "numeros_ocr": len(dec), "confirmados": len(ok),
                "confirmados_por_tipo": dict(collections.Counter(x["tipo"] for x in ok)),
                "por_fonte": C._contar([x["fonte"] for x in ok]),
                "recorte": dict(collections.Counter(r["estado"] for r in rec)),
                "barras_chaves": len(bar.get("chaves") or []), "rasterizacao": rast,
                "s_ocr": round(t_ocr, 2), "s": round(time.monotonic() - t0, 2)}
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()
            shas.add(sha)
            n += 1
    return {"modo": modo, "fatia": fatia, "documentos": n}


# ── governador ─────────────────────────────────────────────────────────────────────────────────────────────────
_PS = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
_WSL = "/mnt/c/Windows/System32/wsl.exe"


def _host() -> tuple[float, float]:
    """(% CPU total do Windows, GB livres = min(livre no Windows, disponível no WSL))."""
    cmd = ("$c=(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter \"Name='_Total'\").PercentProcessorTime;"
           "$m=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory; \"$c $m\"")
    r = subprocess.run([_PS, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    cpu, livre_kb = r.stdout.split()[-2:]
    wsl = next(int(ln.split()[1]) for ln in Path("/proc/meminfo").read_text().splitlines()
               if ln.startswith("MemAvailable"))
    return float(cpu), min(int(livre_kb), wsl) / (1 << 20)


def governar(d: Path, maximo: int, teto_cpu: float, piso_gb: float, janela: int, passo: int) -> dict:
    """Simples: CPU total > teto OU RAM livre < piso durante `janela` s ⇒ um processo a menos pega documento novo
    (o documento em curso termina); folga (CPU < teto − 10 e RAM ≥ piso) durante `janela` s ⇒ um a mais, até `maximo`.
    Começa com `maximo`."""
    perm = maximo
    ruim = bom = limpou = 0.0
    log = d / "governo.log"
    while True:
        t = time.monotonic()
        try:
            cpu, gb = _host()
        except (subprocess.SubprocessError, ValueError, OSError) as e:
            cpu, gb = 100.0, 0.0                                  # sem medida = conta como sem folga
            print(f"medida falhou: {e}", flush=True)
        if gb < piso_gb and time.monotonic() - limpou > janela:
            # o cache de página do WSL (PDFs lidos) fica preso no vmmem do Windows: devolvê-lo antes de cortar processo
            subprocess.run([_WSL, "-d", "Ubuntu", "-u", "root", "--", "sh", "-c", "echo 1 > /proc/sys/vm/drop_caches"],
                           capture_output=True, timeout=60, check=False)
            limpou = time.monotonic()
        excesso = cpu > teto_cpu or gb < piso_gb
        folga = cpu < teto_cpu - 10 and gb >= piso_gb
        dt = max(float(passo), time.monotonic() - t)              # tempo REAL da volta (a medida demora)
        ruim = ruim + dt if excesso else 0.0
        bom = bom + dt if folga else 0.0
        antes = perm
        if ruim >= janela and perm > 0:
            perm, ruim = perm - 1, 0.0
        elif bom >= janela and perm < maximo:
            perm, bom = perm + 1, 0.0
        estado = {"permitidos": perm, "maximo": maximo, "cpu_%": cpu, "ram_livre_gb": round(gb, 2),
                  "em": time.strftime("%Y-%m-%d %H:%M:%S")}
        tmp = d / "governo.json.tmp"
        tmp.write_text(json.dumps(estado), encoding="utf-8")
        os.replace(tmp, d / "governo.json")
        if perm != antes:
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(estado | {"de": antes}) + "\n")
        time.sleep(max(1.0, passo - (time.monotonic() - t)))


# ── GPU × CPU no controle nativo ───────────────────────────────────────────────────────────────────────────────
def medir_gpu(d: Path, base: Path, limite: int | None, modos: list[str]) -> dict:
    """O MESMO controle nativo da O3.6 (páginas com camada de texto, renderizadas a 200 dpi; verdade = o texto nativo):
    RapidOCR CPU (2 threads) × RapidOCR GPU, mesmas páginas, mesma conta de acerto do `ocr_bancada_o36.medir`."""
    from compliance_agent.aplicacao.estagios import ocr as O
    verdade = B._controle_verdade(base)
    pngs = {r["img_sha"]: base / "png" / Path(r["png"]).name for r in B._jl(base / "render_controle.jsonl")
            if not r.get("erro") and r["img_sha"] in verdade}
    shas = sorted(pngs)[:limite] if limite else sorted(pngs)
    arq = d / "medir_gpu.json"
    out = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    out["paginas"] = len(shas)
    for nome in modos:
        ex = _executor_gpu() if nome == "gpu" else O.ExecutorCPU()
        ex.ler_img(B._img(str(pngs[shas[0]])))                    # aquece (carga do modelo fora da conta)
        tot = ok = emit = inv = 0
        t0 = time.monotonic()
        for s in shas:
            lidos = B._chaves(ex.ler_img(B._img(str(pngs[s]))).texto)
            v = verdade[s]
            ok, tot, emit, inv = ok + len(v & lidos), tot + len(v), emit + len(lidos), inv + len(lidos - v)
        seg = time.monotonic() - t0
        out[nome] = {"motor": ex.motor(), "segundos": round(seg, 1), "s_por_pagina": round(seg / len(shas), 3),
                     "paginas_por_min": round(60 * len(shas) / seg, 2), "verdadeiros": tot, "lidos": ok,
                     "acerto_%": round(100 * ok / tot, 2) if tot else None, "inventados": inv,
                     "inventado_%": round(100 * inv / emit, 2) if emit else None,
                     "em": time.strftime("%Y-%m-%d %H:%M:%S")}
        arq.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")   # um modo de cada vez
        del ex                                                   # solta a VRAM antes do próximo modo
    return out


# ── resumo e índice ────────────────────────────────────────────────────────────────────────────────────────────
def _medida(rs: list[dict]) -> dict:
    ok = [r for r in rs if not r.get("erro") and not r.get("duplicado")]
    s = lambda k: sum(r.get(k) or 0 for r in ok)                                  # noqa: E731
    conf = [r for r in ok if r["conferencia_e5"].get("ok")]
    nat = [r for r in ok if r.get("nativas_intactas") is not None]
    return {"documentos": len(rs), "erros": sum(1 for r in rs if r.get("erro")),
            "duplicados": sum(1 for r in rs if r.get("duplicado")), "paginas_escaneadas": s("paginas_escaneadas"),
            "estados_pagina": dict(sum((collections.Counter(r["estados"]) for r in ok), collections.Counter())),
            "efeito_e5_ok": len(conf), "efeito_e5_falhou": len(ok) - len(conf),
            "nativas_intactas_%": round(100 * sum(1 for r in nat if r["nativas_intactas"]) / len(nat), 2) if nat
            else None,
            "ganho_texto_%": round(100 * (s("chars_composto") - s("chars_nativo")) / max(s("chars_nativo"), 1), 2),
            "numeros_novos": s("novos"), "docs_com_numero_novo": sum(1 for r in ok if r["novos"]),
            "numeros_ocr": s("numeros_ocr"), "confirmados_nivel_a": s("confirmados"),
            "nivel_a_%": round(100 * s("confirmados") / s("numeros_ocr"), 2) if s("numeros_ocr") else None,
            "por_fonte": dict(sum((collections.Counter(r["por_fonte"]) for r in ok), collections.Counter())),
            "s_por_pagina": round(s("s") / max(s("paginas_escaneadas"), 1), 2)}


def resumo(d: Path, lote: int) -> dict:
    rs = sorted((r for arq in (d / "resultados").glob("*.jsonl") for r in B._jl(arq)), key=lambda r: r["em"])
    total_fila = sum(1 for _ in B._jl(d / "fila.jsonl"))
    out = {"fila": total_fila, "feitos": len(rs), "total": _medida(rs),
           "por_modo": {m: _medida([r for r in rs if r["modo"] == m]) for m in sorted({r["modo"] for r in rs})},
           "lotes": [{"lote": i // lote + 1, "de": rs[i]["em"], "ate": rs[min(i + lote, len(rs)) - 1]["em"],
                      **_medida(rs[i:i + lote])} for i in range(0, len(rs), lote)]}
    if len(rs) >= 2:
        from datetime import datetime
        ts = [datetime.strptime(r["em"], "%Y-%m-%d %H:%M:%S") for r in rs[-200:]]
        h = max((ts[-1] - ts[0]).total_seconds() / 3600, 1e-6)
        out["vazao_docs_por_hora_ultimos"] = round((len(ts) - 1) / h, 1)
        out["previsao_horas_restantes"] = round((total_fila - len(rs)) / max(out["vazao_docs_por_hora_ultimos"], 1e-6),
                                                1)
    (d / "resumo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def indice(d: Path) -> dict:
    """md5 de cada arquivo da sombra (regra da casa para o HD: índice + LEIAME + md5)."""
    linhas = []
    for p in sorted(x for x in d.rglob("*") if x.is_file() and x.name not in ("_indice_md5.tsv", "governo.json")):
        h = hashlib.md5(p.read_bytes()).hexdigest()
        linhas.append(f"{h}\t{p.stat().st_size}\t{p.relative_to(d).as_posix()}")
    (d / "_indice_md5.tsv").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return {"arquivos": len(linhas)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("etapa", choices=["fila", "rodar", "governar", "medir_gpu", "resumo", "indice"])
    ap.add_argument("--dir", default="/mnt/d/JFN-Frio/sombra-o36-mistos")
    ap.add_argument("--modo", choices=["cpu", "gpu"], default="cpu")
    ap.add_argument("--fatia", default="0/1", help="k/n: posição k no governador; sem --dinamico, também a fatia")
    ap.add_argument("--dinamico", action="store_true", help="documentos por reserva atômica (GPU e CPU juntos)")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--teto-cpu", type=float, default=75.0)
    ap.add_argument("--piso-gb", type=float, default=8.0)
    ap.add_argument("--janela", type=int, default=120)
    ap.add_argument("--passo", type=int, default=20)
    ap.add_argument("--lote", type=int, default=100)
    ap.add_argument("--base", default="/mnt/c/o36", help="medir_gpu: pasta da O3.6 com o controle renderizado")
    ap.add_argument("--modos", default="gpu,cpu", help="medir_gpu: gpu,cpu")
    a = ap.parse_args(argv)
    d = Path(a.dir)
    if a.etapa == "fila":
        r = fila(d)
    elif a.etapa == "rodar":
        r = rodar(d, a.modo, a.fatia, a.limite, a.dinamico)
    elif a.etapa == "governar":
        r = governar(d, a.max, a.teto_cpu, a.piso_gb, a.janela, a.passo)
    elif a.etapa == "medir_gpu":
        r = medir_gpu(d, Path(a.base), a.limite, a.modos.split(","))
    elif a.etapa == "resumo":
        r = resumo(d, a.lote)
    else:
        r = indice(d)
    print(json.dumps(r, ensure_ascii=False, default=list)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
