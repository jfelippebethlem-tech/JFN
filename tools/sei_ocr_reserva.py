"""OCR de RESERVA nas VMs — lê os PDFs escaneados do SEI quando a GPU do it-campo NÃO está trabalhando.

POR QUE EXISTE (dono, 18/11/2026: "liga o paddle nas vms como reserva ou algo que seja 100% e resolva o ocr bem").
O OCR principal é o Surya 2.5 na RTX 5070 do it-campo (`deploy/itcampo/ocr_gpu/`). Quando o it-campo desliga, pausa
ou trava, a fila para. A reserva roda na VM-2 (CPU ARM) e continua a fila com o melhor motor de CPU MEDIDO no mesmo
gabarito do bench da GPU (79 páginas nativas 'sujadas' como escaneado, seed 7):

    motor (CPU ARM da VM-2, 2 vCPU)                          CNPJ    valores R$   datas    s/página
    Tesseract (produção antiga)                              89,2%     81,1%      92,2%      4,3
    PaddleOCR 3.7 mobile + correção decimal (referência)     98,9%     98,7%      99,5%     32,5
    RapidOCR 3.10 (ONNX) PP-OCRv5 mobile det + latin rec     100,0%    98,1%      99,5%     13,4  ← ESCOLHIDO
      + correção decimal  (mesmas imagens: Paddle relido em 3 páginas deu texto idêntico; it-campo x86: 4,45 s/pág)
    PP-OCRv5 SERVER det (RapidOCR)                           morto por OOM na VM-2 (5,7 GB) e no freio do it-campo
  Valores: 312 × 314 acertos de 318 — as 2 diferenças líquidas são células "0,00"/"0,33" (um erra 1, o outro 3);
  CNPJ 93 × 92 de 93. Mesma família de modelos do Paddle, 2,4× mais rápido, 1,1 GB de pico num PDF real de 19 páginas.

A correção decimal (`corrigir`) devolve a vírgula a valores lidos com ponto em tabela miúda (1.234.56 → 1.234,56).

DESENHO (a VM-1 é a dona da verdade: estado, fila, integração; a VM-2 só calcula):
  · PULSO REAL da GPU (`pulso_gpu`, nunca suposição): pelo ssh do it-campo — processo `ocr_gpu_worker.py` vivo,
    arquivo PAUSA, idade do último evento "lote" do ocr_gpu.log (relógio do próprio it-campo). Parada = PAUSA, ou
    processo morto, ou último lote há > PARADA_MIN. Sem ssh: parada só se a VM-1 não recebe entrega da GPU há
    > PARADA_MIN + 30 min (registro do integrador); senão INDETERMINADO → não roda.
  · SEM DUPLICAR COM A GPU (`reservar`, sob trava na VM-1): o worker da GPU consome a fila da FRENTE para trás, 40
    por lote, e RELÊ `ocr_fila.txt` a cada lote. A reserva pega só do FIM, nunca dos MARGEM primeiros pendentes, e
    TIRA do `ocr_fila.txt` do it-campo o que reservou (troca atômica, só se o md5 do arquivo for o que ela leu —
    senão desiste). O worker, ao reler, não vê mais o item; a VM-1 (`sei_ocr_gpu_fila`) também o exclui. Sem ssh,
    a reserva pega do fim da fila da VM-1 e a retirada fica pendente até o primeiro contato (`tirar_pendente`).
  · ENTREGA: `integra_<tag>/NNN.ocr_reserva.txt` (+ `.json` com o motor) em data/sei_cache da VM-1, rsync
    --ignore-existing e md5 conferido nas duas pontas. O integrador (`sei_ocr_gpu_integrar`) aplica com
    precedência: nativo intocado > Surya > reserva > Tesseract > sem texto.
  · CARGA: VM-2 com nice 19/ionice idle, 1 processo (flock), cede quando load1 > 1,5 por núcleo (descontada a própria
    linha de execução) ou memória livre < MEM_MIN_GB. A VM-1 NÃO calcula OCR (load 6–10 em 2 vCPU, medido 18/11).

Uso:
  (VM-1) python -m tools.sei_ocr_reserva pulso                 # mede e imprime o pulso da GPU
  (VM-1) python -m tools.sei_ocr_reserva reservar --n 12 --no vm2
  (VM-1) python -m tools.sei_ocr_reserva concluir --no vm2 < resultado.json
  (VM-1) python -m tools.sei_ocr_reserva devolver --no vm2     # desligar: devolve à fila da GPU o não entregue
  (VM-2) python -m tools.sei_ocr_reserva rodar --orcamento 3000 --n 12
Pausar: `data/.pause_ocr_reserva` (na VM-1 para tudo; na VM-2 só aquele nó).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
CACHE = DATA / "sei_cache"
ESTADO = DATA / "sei_ocr_reserva_estado.json"      # VM-1: rel → {estado: reservado|entregue|falha, no, em, …}
LOG = DATA / "sei_ocr_reserva.log"                 # VM-1: uma linha JSON por decisão (sentinela do SLO)
LEDGER = DATA / "sei_ocr_gpu_aplicado.jsonl"
FILA_VM1 = DATA / "sei_ocr_gpu_fila.txt"
PAUSA = DATA / ".pause_ocr_reserva"
ITCAMPO = os.environ.get("JFN_ITCAMPO_SSH", "it-campo")
VM1 = os.environ.get("JFN_VM1_SSH", "vm1-ts")
VM1_JFN = os.environ.get("JFN_VM1_DIR", "/home/ubuntu/JFN")
FRIO = Path(os.environ.get("JFN_ARQUIVO_FRIO", str(Path.home() / "arquivo_frio" / "sei_cache")))
BASE_NO = Path(os.environ.get("JFN_OCR_RESERVA_DIR", str(Path.home() / "ocr-reserva")))
FRIO_REMOTO = os.environ.get("JFN_FRIO_REMOTO", "")   # nó sem o arquivo frio (it-campo): baixa o lote da VM-2

PARADA_MIN = 75      # lote da GPU dura 21–31 min (ocr_gpu.log, 18/11/2026): 75 min sem lote = parada
MARGEM = 400         # pendentes da cabeça da fila da GPU que a reserva nunca toca (10 lotes ≈ 5 h de GPU)
VALIDADE_H = 24      # reserva mais velha que isto volta para a fila da VM-1 (a reserva morreu)
LOAD_POR_NUCLEO = 1.5
MEM_MIN_GB = float(os.environ.get("JFN_OCR_MEM_MIN_GB", "2.0"))   # it-campo: 3,0 (vLLM + 6 sessões SEI)
MAX_PAG = 120        # o mesmo teto do worker da GPU
DPI = 200            # idem
THREADS = int(os.environ.get("JFN_OCR_THREADS", "2"))
MOTOR = "reserva:rapidocr-3.10 PP-OCRv5 mobile det + latin_PP-OCRv5 mobile rec (ONNX, CPU) + correção decimal"
BENCH = {"gabarito": "79 páginas nativas sujadas (seed 7), ~/ocr-bench na VM-2, 18/11/2026",
         "rapidocr_v5_mobile+corr": {"cnpj": 100.0, "valores": 98.1, "datas": 99.5, "s_pag_vm2": 13.39, "s_pag_itcampo": 4.45},
         "paddle_v5_mobile+corr": {"cnpj": 98.9, "valores": 98.7, "datas": 99.5, "s_pag_vm2": 32.5},
         "tesseract": {"cnpj": 89.2, "valores": 81.1, "datas": 92.2, "s_pag_vm2": 4.34}}

_DEC = re.compile(r"\b(\d{1,3}(?:\.\d{3})+)\.(\d{2})\b(?!\.\d)")


def corrigir(t: str) -> str:
    """Vírgula decimal lida como ponto (tabela miúda): 94.999.98 → 94.999,98. Só com separador de milhar presente
    e sem continuação numérica — '1.234.567.89' (CNPJ/código) e '3.14' ficam como estão."""
    return _DEC.sub(r"\1,\2", t)


def _agora() -> str:
    return time.strftime("%F %T")


def _log(**kw) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": _agora(), **kw}, ensure_ascii=False) + "\n")


def _ler_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar_estado(e: dict) -> None:
    tmp = ESTADO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    os.replace(tmp, ESTADO)


class _Trava:
    def __enter__(self):
        (DATA / "locks").mkdir(exist_ok=True)
        self.f = open(DATA / "locks" / "sei_ocr_reserva.lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)          # bloqueante: reservar/concluir são curtos
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _arq_reserva(rel: str) -> Path:
    return CACHE / (rel[:-len(".pdf")] + ".ocr_reserva.txt")


def _ledger() -> tuple[set[str], set[tuple[str, int]]]:
    arqs, docs = set(), set()
    if LEDGER.exists():
        for ln in LEDGER.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                e = json.loads(ln)
                arqs.add(e["arq"])
                docs.add((e["tag"], int(e["i"])))
    return arqs, docs


def _rel_doc(rel: str) -> tuple[str, int]:
    pasta, nome = rel.split("/", 1)
    return pasta[len("integra_"):], int(nome.split(".")[0])


def reservados_pela_reserva(estado: dict | None = None, agora: float | None = None) -> set[str]:
    """O que a fila da GPU (VM-1) deve EXCLUIR: reservado há < VALIDADE_H, ou entregue e ainda não aplicado."""
    estado = _ler_estado() if estado is None else estado
    agora = agora or time.time()
    aplicados = _ledger()[0]
    out = set()
    for rel, e in estado.items():
        if e.get("estado") == "reservado" and agora - float(e.get("ts", 0)) < VALIDADE_H * 3600:
            out.add(rel)
        elif e.get("estado") == "entregue" and str(_arq_reserva(rel)) not in aplicados:
            out.add(rel)
    return out


# ───────────────────────────── pulso da GPU (VM-1) ─────────────────────────────

_SONDA = r"""
B=~/jfn-gpu/ocr
echo "agora=$(date +%s)"
echo "vivo=$(pgrep -f '[o]cr_gpu_worker.py' | head -1)"
echo "pausa=$([ -e $B/PAUSA ] && echo 1 || echo 0)"
L=$(grep '"ev": "lote"' $B/ocr_gpu.log 2>/dev/null | tail -1)
T=$(printf '%s' "$L" | sed -nE 's/.*"t": "([^"]+)".*/\1/p')
[ -n "$T" ] && echo "lote_epoch=$(date -d "$T" +%s)"
echo "fila_md5=$(md5sum < $B/ocr_fila.txt 2>/dev/null | cut -d' ' -f1)"
echo "---pendentes---"
cat $B/feitos.txt $B/falhas.txt 2>/dev/null | awk 'NR==FNR{x[$0]=1;next} !($0 in x)' - $B/ocr_fila.txt 2>/dev/null
"""


def _wsl(script: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ITCAMPO, "wsl -d Ubuntu -- bash -s"],
                          input=script, capture_output=True, text=True, timeout=timeout)


def _ultima_entrega_gpu_vm1() -> float | None:
    """Época da última entrega da GPU que o integrador da VM-1 registrou (sinal que independe do ssh)."""
    if not LEDGER.exists():
        return None
    ult = None
    for ln in LEDGER.read_text(encoding="utf-8").splitlines()[-2000:]:
        if ln.strip():
            e = json.loads(ln)
            if e.get("motor", "surya") == "surya":
                ult = e.get("em")
    return time.mktime(time.strptime(ult, "%Y-%m-%d %H:%M:%S")) if ult else None


def interpretar_pulso(saida: str | None, ultima_entrega: float | None, agora: float | None = None) -> dict:
    """Decide se a GPU está PARADA a partir do que foi MEDIDO. `saida` None = ssh falhou."""
    agora = agora or time.time()
    if saida is None:
        idade = None if ultima_entrega is None else round((agora - ultima_entrega) / 60)
        parada = idade is not None and idade > PARADA_MIN + 30
        return {"ssh": False, "parada": parada, "pendentes": None,
                "motivo": (f"it-campo inacessível e última entrega da GPU na VM-1 há {idade} min" if idade is not None
                           else "it-campo inacessível e nenhuma entrega da GPU registrada — INDETERMINADO")
                if parada else f"it-campo inacessível; última entrega há {idade} min — INDETERMINADO, não roda"}
    cab, _, corpo = saida.partition("---pendentes---")
    kv = dict(ln.split("=", 1) for ln in cab.split() if "=" in ln)
    agora_ic = int(kv.get("agora") or agora)
    idade = round((agora_ic - int(kv["lote_epoch"])) / 60) if kv.get("lote_epoch") else None
    vivo, pausa = bool(kv.get("vivo")), kv.get("pausa") == "1"
    motivos = ([] if vivo else ["processo ocr_gpu_worker.py morto"]) + (["PAUSA presente"] if pausa else []) + \
        ([f"último lote há {idade} min (> {PARADA_MIN})"] if idade is None or idade > PARADA_MIN else [])
    if idade is None:
        motivos[-1] = "nenhum lote no ocr_gpu.log"
    return {"ssh": True, "parada": bool(motivos), "vivo": vivo, "pausa": pausa, "lote_ha_min": idade,
            "fila_md5": kv.get("fila_md5", ""), "pendentes": corpo.split(),
            "motivo": "; ".join(motivos) if motivos else f"GPU ativa (último lote há {idade} min)"}


def pulso_gpu() -> dict:
    try:
        r = _wsl(_SONDA)
        saida = r.stdout if r.returncode == 0 and "agora=" in r.stdout else None
    except (OSError, subprocess.TimeoutExpired):
        saida = None
    return interpretar_pulso(saida, _ultima_entrega_gpu_vm1())


def _tirar_da_fila_gpu(rels: list[str], md5: str) -> str:
    """Troca atômica no it-campo: só reescreve ocr_fila.txt se o md5 ainda for o lido (ninguém mexeu no meio)."""
    lista = "\n".join(rels)
    script = f"""
B=~/jfn-gpu/ocr; F=$B/ocr_fila.txt
[ "$(md5sum < $F | cut -d' ' -f1)" = "{md5}" ] || {{ echo CAS_MUDOU; exit 0; }}
cat > $B/.reserva_tirar.txt <<'LISTA_RESERVA'
{lista}
LISTA_RESERVA
grep -v -x -F -f $B/.reserva_tirar.txt $F > $F.reserva.tmp
cp -p $F $F.antes_reserva
[ "$(md5sum < $F | cut -d' ' -f1)" = "{md5}" ] || {{ rm -f $F.reserva.tmp; echo CAS_MUDOU; exit 0; }}
mv $F.reserva.tmp $F && cat $B/.reserva_tirar.txt >> $B/reserva_tirados.txt && echo "OK $(wc -l < $F)"
"""
    try:
        r = _wsl(script)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"FALHOU {type(e).__name__}"
    return (r.stdout.strip().splitlines() or [f"FALHOU rc={r.returncode}"])[-1]


# ───────────────────────────── reservar / concluir / devolver (VM-1) ─────────────────────────────

def escolher(pendentes: list[str], excluir: set[str], n: int, margem: int = MARGEM) -> list[str]:
    """Do FIM para a frente, nunca os `margem` primeiros: a GPU consome da frente, 40 por lote."""
    if n <= 0 or len(pendentes) <= margem:
        return []
    out = []
    for rel in reversed(pendentes[margem:]):
        if rel not in excluir and rel.endswith(".pdf") and "/" in rel:
            out.append(rel)
            if len(out) == n:
                break
    return out


def reservar(n: int, no: str, paralelo: bool = False) -> dict:
    """`paralelo` (nó de CPU do it-campo, ao lado do Surya): reserva mesmo com a GPU ATIVA — a disjunção não depende
    da GPU estar parada (só do FIM + MARGEM + retirada da fila), mas exige o ssh do it-campo (retirada imediata)."""
    with _Trava():
        if PAUSA.exists():
            _log(ev="reservar", no=no, itens=0, motivo="pausado (data/.pause_ocr_reserva)")
            return {"itens": [], "motivo": "pausado"}
        estado = _ler_estado()
        agora = time.time()
        p = pulso_gpu()
        sobra = sorted(r for r, e in estado.items() if e.get("estado") == "reservado" and e.get("no") == no)
        # retirada que ficou pendente (it-campo inacessível na hora da reserva): faz no primeiro contato
        pend = sorted(r for r, e in estado.items() if e.get("tirar_pendente"))
        if p["ssh"] and pend:
            r = _tirar_da_fila_gpu(pend, p["fila_md5"])
            if r.startswith("OK"):
                for rel in pend:
                    estado[rel].pop("tirar_pendente", None)
                p = pulso_gpu()                          # o md5 mudou com a retirada
            _log(ev="retirada_pendente", itens=len(pend), resultado=r)
        novos: list[str] = []
        if (p["parada"] or (paralelo and p["ssh"])) and len(sobra) < n:
            aplicados_arq, aplicados_doc = _ledger()
            pendentes = p["pendentes"] if p["ssh"] else \
                (FILA_VM1.read_text(encoding="utf-8").split() if FILA_VM1.exists() else [])
            excluir = set(estado) | {rel for rel in pendentes if _rel_doc(rel) in aplicados_doc
                                     or (CACHE / (rel[:-4] + ".ocr_gpu.txt")).exists() or _arq_reserva(rel).exists()}
            novos = escolher(pendentes, excluir, n - len(sobra))
            if novos and p["ssh"]:
                r = _tirar_da_fila_gpu(novos, p["fila_md5"])
                if not r.startswith("OK"):
                    _log(ev="reservar", no=no, itens=0, motivo=f"troca da fila do it-campo não feita: {r}")
                    novos = []
            for rel in novos:
                estado[rel] = {"estado": "reservado", "no": no, "em": _agora(), "ts": agora,
                               **({} if p["ssh"] else {"tirar_pendente": True})}
        for rel in sobra:
            estado[rel].update(em=_agora(), ts=agora)
        _gravar_estado(estado)
        itens = sobra + novos
        _log(ev="reservar", no=no, itens=len(itens), sobra=len(sobra), novos=len(novos), gpu_parada=p["parada"],
             ssh=p["ssh"], pendentes_gpu=None if p["pendentes"] is None else len(p["pendentes"]), motivo=p["motivo"])
        return {"itens": itens, "gpu_parada": p["parada"], "motivo": p["motivo"]}


def concluir(no: str, res: dict) -> dict:
    """res = {entregues: [rel], falhas: [rel], nao_feitos: [rel], s_por_pag, paginas}."""
    with _Trava():
        estado = _ler_estado()
        cont = {"entregues": 0, "falhas": 0, "nao_feitos": 0}
        for chave, novo in (("entregues", "entregue"), ("falhas", "falha")):
            for rel in res.get(chave) or []:
                if rel in estado and estado[rel].get("no") == no:
                    estado[rel].update(estado=novo, em=_agora(), ts=time.time())
                    cont[chave] += 1
        cont["nao_feitos"] = len(res.get("nao_feitos") or [])      # continuam reservados: voltam na próxima rodada
        _gravar_estado(estado)
        _log(ev="concluir", no=no, **cont, paginas=res.get("paginas"), s_por_pag=res.get("s_por_pag"),
             motivo_fim=res.get("motivo_fim"))
        return cont


def devolver(no: str) -> dict:
    """DESLIGAR: o que a reserva tirou da fila da GPU e não entregou volta ao FIM do ocr_fila.txt do it-campo."""
    with _Trava():
        estado = _ler_estado()
        volta = sorted(r for r, e in estado.items() if e.get("estado") in ("reservado", "falha") and e.get("no") == no)
        if not volta:
            return {"devolvidos": 0}
        lista = "\n".join(volta)
        r = _wsl(f"""
F=~/jfn-gpu/ocr/ocr_fila.txt
cat >> $F <<'LISTA_RESERVA'
{lista}
LISTA_RESERVA
echo "OK $(wc -l < $F)"
""")
        if r.returncode != 0 or "OK" not in r.stdout:
            return {"devolvidos": 0, "erro": (r.stderr or r.stdout)[-200:]}
        for rel in volta:
            estado.pop(rel)
        _gravar_estado(estado)
        _log(ev="devolver", no=no, itens=len(volta))
        return {"devolvidos": len(volta)}


# ───────────────────────────── OCR (VM-2) ─────────────────────────────

def _linhas(itens: list[tuple[float, float, float, str]]) -> str:
    """Ordem de leitura: agrupa por linha (centro y, tolerância meia altura) e ordena por x — a mesma do bench."""
    itens.sort()
    ls, atual, y0 = [], [], None
    for y, x, h, t in itens:
        if y0 is not None and abs(y - y0) > max(h, 8) * 0.5:
            ls.append(" ".join(t for _, t in sorted(atual)))
            atual = []
        atual.append((x, t))
        y0 = y if not atual[:-1] else y0
    if atual:
        ls.append(" ".join(t for _, t in sorted(atual)))
    return "\n".join(ls)


def motor_ocr():
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion
    return RapidOCR(params={
        "Det.ocr_version": OCRVersion("PP-OCRv5"), "Det.model_type": ModelType("mobile"), "Det.lang_type": LangDet("ch"),
        "Rec.ocr_version": OCRVersion("PP-OCRv5"), "Rec.model_type": ModelType("mobile"), "Rec.lang_type": LangRec("latin"),
        "Global.use_cls": False, "Global.text_score": 0.0, "Global.max_side_len": 4000, "Global.log_level": "error",
        "EngineConfig.onnxruntime.intra_op_num_threads": THREADS,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1})


def ler_pdf(eng, pdf: Path) -> tuple[str, int, int]:
    import pymupdf as fitz
    import numpy as np
    doc = fitz.open(pdf)
    n = min(doc.page_count, MAX_PAG)
    partes = []
    for k in range(n):
        pix = doc.load_page(k).get_pixmap(dpi=DPI)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        r = eng(np.ascontiguousarray(img))
        it = []
        for b, t in zip(r.boxes if r.boxes is not None else [], r.txts or []):
            b = np.asarray(b)
            it.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
        partes.append(corrigir(_linhas(it)))
    return "\n\n".join(f"[página {i + 1}]\n{t}" for i, t in enumerate(partes)), n, doc.page_count


def carga() -> tuple[float, float]:
    load1 = os.getloadavg()[0]
    mem = 99.0
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            mem = int(ln.split()[1]) / 1e6
    return load1, mem


def pode_rodar(load1: float, mem_gb: float, nucleos: int, proprio: int = 0) -> tuple[bool, str]:
    """Cede à captura SEI: load (descontadas as `proprio` linhas da reserva) > 1,5/núcleo ou memória < MEM_MIN_GB."""
    if mem_gb < MEM_MIN_GB:
        return False, f"memória livre {mem_gb:.1f} GB < {MEM_MIN_GB}"
    if load1 - proprio > LOAD_POR_NUCLEO * nucleos:
        return False, f"load {load1:.1f} (−{proprio} da reserva) > {LOAD_POR_NUCLEO * nucleos:.1f}"
    return True, ""


def _ssh_vm1(cmd: str, entrada: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VM1,
                           f"cd {VM1_JFN} && PYTHONPATH=. nice -n 10 .venv/bin/python -m tools.sei_ocr_reserva {cmd}"],
                          input=entrada, capture_output=True, text=True, timeout=timeout)


def _md5s(arqs: list[str], base: Path) -> dict[str, str]:
    r = subprocess.run(["md5sum", "--", *arqs], cwd=base, capture_output=True, text=True)
    return {ln[34:]: ln[:32] for ln in r.stdout.splitlines()}


def entregar(rels: list[str], saida: Path) -> tuple[list[str], list[str]]:
    """rsync --ignore-existing para a VM-1 (caminho COMPLETO no destino) e md5 conferido nas duas pontas."""
    arqs = [f"{rel[:-4]}{suf}" for rel in rels for suf in (".ocr_reserva.txt", ".ocr_reserva.json")]
    lst = saida.parent / f"entrega_{saida.name}.lst"
    lst.write_text("\n".join(arqs) + "\n", encoding="utf-8")
    r = subprocess.run(["rsync", "-a", "--ignore-existing", "--files-from", str(lst), str(saida) + "/",
                        f"{VM1}:{VM1_JFN}/data/sei_cache/"], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        print(json.dumps({"ev": "rsync_falhou", "rc": r.returncode, "erro": r.stderr[-300:]}), flush=True)
        return [], rels
    local = _md5s(arqs, saida)
    rr = subprocess.run(["ssh", "-o", "BatchMode=yes", VM1, f"cd {VM1_JFN}/data/sei_cache && xargs -d '\\n' md5sum --"],
                        input="\n".join(arqs) + "\n", capture_output=True, text=True, timeout=300)
    remoto = {ln[34:]: ln[:32] for ln in rr.stdout.splitlines()}
    ok, ruim = [], []
    for rel in rels:
        par = [f"{rel[:-4]}{s}" for s in (".ocr_reserva.txt", ".ocr_reserva.json")]
        (ok if all(local.get(a) and local.get(a) == remoto.get(a) for a in par) else ruim).append(rel)
    for rel in ok:                                   # conferido dos dois lados → apaga a cópia local
        for s in (".ocr_reserva.txt", ".ocr_reserva.json"):
            (saida / f"{rel[:-4]}{s}").unlink(missing_ok=True)
    return ok, ruim


def _baixar(itens: list[str], destino: Path) -> Path:
    """Nó sem arquivo frio local: baixa os PDFs do lote da VM-2 (o mesmo caminho do worker da GPU)."""
    destino.mkdir(parents=True, exist_ok=True)
    lst = destino.parent / f"baixar_{destino.name}.lst"
    lst.write_text("\n".join(itens) + "\n", encoding="utf-8")
    r = subprocess.run(["rsync", "-a", "--files-from", str(lst), FRIO_REMOTO, str(destino) + "/"],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode not in (0, 23):                 # 23 = parte ausente: vira falha do PDF, não da rodada
        raise RuntimeError(f"rsync do arquivo frio rc={r.returncode}: {r.stderr[-200:]}")
    return destino


def rodar(orcamento: int, n: int, no: str, paralelo: bool = False) -> int:
    t0 = time.time()
    saida = BASE_NO / "out" / no              # um diretório por nó/processo: a entrega não pega o alheio
    if PAUSA.exists():
        print(json.dumps({"ev": "pausado"}), flush=True)
        return 0
    nucleos = os.cpu_count() or 2
    ok, porque = pode_rodar(*carga(), nucleos)
    if not ok:
        print(json.dumps({"ev": "cede", "motivo": porque}, ensure_ascii=False), flush=True)
        return 0
    r = _ssh_vm1(f"reservar --n {n} --no {no}" + (" --paralelo" if paralelo else ""))
    if r.returncode != 0:
        print(json.dumps({"ev": "reservar_falhou", "erro": r.stderr[-300:]}, ensure_ascii=False), flush=True)
        return 1
    res = json.loads(r.stdout.strip().splitlines()[-1])
    itens = res["itens"]
    print(json.dumps({"ev": "reservado", "itens": len(itens), "motivo": res.get("motivo")}, ensure_ascii=False), flush=True)
    if not itens:
        return 0
    saida.mkdir(parents=True, exist_ok=True)
    frio = FRIO
    if FRIO_REMOTO:
        try:
            frio = _baixar(itens, BASE_NO / "pdfs" / no)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            print(json.dumps({"ev": "baixar_falhou", "erro": str(e)[:300]}, ensure_ascii=False), flush=True)
            return 1
    eng = motor_ocr()
    feitos, falhas, paginas, t_ocr, motivo_fim = [], [], 0, 0.0, "fila da rodada concluída"
    for k, rel in enumerate(itens):
        if time.time() - t0 > orcamento:
            motivo_fim = f"orçamento de {orcamento}s"
            break
        ok, porque = pode_rodar(*carga(), nucleos, proprio=THREADS if k else 0)
        if not ok:
            motivo_fim = f"cedeu: {porque}"
            break
        pdf = frio / rel
        destino = saida / rel[:-4]
        try:
            t1 = time.time()
            texto, npag, total = ler_pdf(eng, pdf)
            dt = time.time() - t1
        except (OSError, ValueError, RuntimeError, MemoryError, IndexError) as e:   # PDF ruim/ausente: vira falha, não para a rodada
            print(json.dumps({"ev": "pdf_falhou", "pdf": rel, "erro": f"{type(e).__name__}: {str(e)[:200]}"},
                             ensure_ascii=False), flush=True)
            falhas.append(rel)
            continue
        finally:
            if FRIO_REMOTO:
                (frio / rel).unlink(missing_ok=True)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.with_suffix(".ocr_reserva.txt").write_text(texto, encoding="utf-8")
        destino.with_suffix(".ocr_reserva.json").write_text(json.dumps(
            {"motor": MOTOR, "no": no, "paginas": npag, "paginas_pdf": total, "cortado": total > npag,
             "s": round(dt, 1), "chars": len(texto), "em": _agora()}, ensure_ascii=False), encoding="utf-8")
        feitos.append(rel)
        paginas += npag
        t_ocr += dt
        print(json.dumps({"ev": "pdf", "pdf": rel, "paginas": npag, "s": round(dt, 1)}), flush=True)
    nao_feitos = [r for r in itens if r not in feitos and r not in falhas]
    # sobra de rodada anterior que ficou sem entregar (rsync caiu) vai junto
    pendentes_locais = sorted({str(p.relative_to(saida))[:-len(".ocr_reserva.txt")] + ".pdf"
                               for p in saida.rglob("*.ocr_reserva.txt")})
    entregues, ruins = entregar(pendentes_locais, saida) if pendentes_locais else ([], [])
    s_pag = round(t_ocr / paginas, 2) if paginas else None
    cont = _ssh_vm1(f"concluir --no {no}", entrada=json.dumps(
        {"entregues": entregues, "falhas": falhas, "nao_feitos": nao_feitos + ruins, "paginas": paginas,
         "s_por_pag": s_pag, "motivo_fim": motivo_fim}))
    print(json.dumps({"ev": "fim", "feitos": len(feitos), "entregues": len(entregues), "md5_divergente": ruins,
                      "falhas": len(falhas), "nao_feitos": len(nao_feitos), "paginas": paginas, "s_por_pag": s_pag,
                      "motivo_fim": motivo_fim, "concluir_rc": cont.returncode, "s": round(time.time() - t0)},
                     ensure_ascii=False), flush=True)
    return 0 if cont.returncode == 0 and not ruins else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pulso")
    a = sub.add_parser("reservar"); a.add_argument("--n", type=int, default=12); a.add_argument("--no", default="vm2")
    a.add_argument("--paralelo", action="store_true")
    a = sub.add_parser("concluir"); a.add_argument("--no", default="vm2")
    a = sub.add_parser("devolver"); a.add_argument("--no", default="vm2")
    a = sub.add_parser("rodar")
    a.add_argument("--orcamento", type=int, default=3000); a.add_argument("--n", type=int, default=12)
    a.add_argument("--no", default="vm2"); a.add_argument("--paralelo", action="store_true")
    g = ap.parse_args()
    if g.cmd == "pulso":
        p = pulso_gpu()
        p["pendentes"] = None if p["pendentes"] is None else len(p["pendentes"])
        print(json.dumps(p, ensure_ascii=False))
    elif g.cmd == "reservar":
        print(json.dumps(reservar(g.n, g.no, g.paralelo), ensure_ascii=False))
    elif g.cmd == "concluir":
        print(json.dumps(concluir(g.no, json.loads(sys.stdin.read())), ensure_ascii=False))
    elif g.cmd == "devolver":
        print(json.dumps(devolver(g.no), ensure_ascii=False))
    else:
        return rodar(g.orcamento, g.n, g.no, g.paralelo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
