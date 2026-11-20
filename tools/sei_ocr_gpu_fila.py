"""Fila do OCR por IA na GPU do it-campo: documentos do arquivo SEI lidos pelo Tesseract (ocr=True) ou sem texto,
cujo PDF ainda existe no arquivo frio da VM-2 — e que o integrador ainda não aplicou.

Prioridade (valor em R$ e prova de pagamento primeiro): nota fiscal, proposta → OB, liquidação, medição, atesto →
empenho, contrato, aditivo → autorização, parecer, ata → edital → resto. Sem texto vem antes de Tesseract.
Grava `data/sei_ocr_gpu_fila.txt` (caminhos `integra_<tag>/NNN.pdf` relativos a vm2:~/arquivo_frio/sei_cache), que o
trabalhador do it-campo puxa quando a fila dele acaba. Nativo nunca entra (texto do próprio PDF é a verdade).

RESERVA (18/11/2026, `tools/sei_ocr_reserva.py`): o que a reserva da VM-2 tem reservado ou entregue e ainda não aplicado
fica FORA (não duplicar com a GPU); o que a reserva já aplicou volta só no FIM da fila — o Surya é mais forte e
substitui o texto da reserva quando chegar (precedência em `tools/sei_ocr_gpu_integrar.py`).

ARQUIVO FRIO NOVO (20/11/2026): desde 16/11 o `sei_arquivo_frio.sh` leva os escaneados para `vm2:~/arquivo_frio/sei_pdfs`
(e de 15–16/11 para o disco do próprio it-campo, `C:\\JFN-Arquivo\\sei_pdfs`), mas a fila só olhava `sei_cache` — a GPU
ficava ociosa com a fila vazia. Agora a fila lista as duas pastas da VM-2; o PDF que só existe em `sei_pdfs` ganha um
LINK FÍSICO (hard link: mesmo inode, zero byte a mais, nada apagado) em `sei_cache/<mesmo caminho>` antes de entrar na
fila — assim o trabalhador da GPU, a reserva da VM-2 e os nós de CPU do it-campo, que buscam em `sei_cache`, leem sem
mudar nada neles. Os do disco do it-campo (`--itcampo-local`) só entram com o trabalhador novo, que lê local primeiro
(o antigo marcaria o PDF ausente como falha).

    python -m tools.sei_ocr_gpu_fila                    # grava a fila (e liga os links que ela precisa)
    python -m tools.sei_ocr_gpu_fila --medir            # só conta, por origem; não grava nem liga nada
    python -m tools.sei_ocr_gpu_fila --itcampo-local    # inclui C:\\JFN-Arquivo\\sei_pdfs (trabalhador novo no ar)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from compliance_agent.sei.acervo_texto import foi_ocr, numero_para_pasta

_REPO = Path(__file__).resolve().parent.parent
ARQUIVO = _REPO / "data" / "sei_arquivo"
SAIDA = _REPO / "data" / "sei_ocr_gpu_fila.txt"
LEDGER = _REPO / "data" / "sei_ocr_gpu_aplicado.jsonl"
PRIOR = {"nota_fiscal": 0, "proposta": 0, "planilha_preco": 0, "ordem_bancaria": 1, "liquidacao": 1, "medicao": 1, "atesto": 1,
         "empenho": 2, "contrato": 2, "termo_aditivo": 2, "autorizacao_despesa": 3, "parecer_juridico": 3, "ata": 3,
         "edital": 4}


def _chars(d: dict) -> int:
    try:
        return int(d.get("chars") or 0)
    except (TypeError, ValueError):
        return 0


_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
_REL = re.compile(r"^integra_[0-9A-Za-z_]+/[0-9]{3,}\.pdf$")     # nada de "..": o caminho vai a um script remoto


def pdfs_no_frio() -> tuple[set[str], set[str]]:
    """(em `sei_cache`, em `sei_pdfs`) do arquivo frio da VM-2, caminhos `integra_<tag>/NNN.pdf`."""
    r = subprocess.run([*_SSH, "vm2", "cd ~/arquivo_frio && find sei_cache sei_pdfs -name '*.pdf' -printf '%p\\n'"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"lista do arquivo frio indisponível: {r.stderr[-200:]}")
    cache, pdfs = set(), set()
    for ln in r.stdout.split():
        base, _, rel = ln.partition("/")
        (cache if base == "sei_cache" else pdfs).add(rel)
    return cache, pdfs


def pdfs_no_itcampo() -> set[str]:
    """PDFs no disco do it-campo (C:\\JFN-Arquivo\\sei_pdfs, levados para lá em 15–16/11/2026)."""
    r = subprocess.run([*_SSH, "it-campo", "wsl -d Ubuntu bash -s"],
                       input="cd /mnt/c/JFN-Arquivo/sei_pdfs && find . -name '*.pdf' -printf '%P\\n'\n",
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"lista do arquivo do it-campo indisponível: {r.stderr[-200:]}")
    return set(r.stdout.split())


_LIGAR = """import json, os
b = os.path.expanduser("~/arquivo_frio")
for rel in json.loads(%s):
    a, c = os.path.join(b, "sei_pdfs", rel), os.path.join(b, "sei_cache", rel)
    try:
        if not os.path.lexists(c):
            os.makedirs(os.path.dirname(c), exist_ok=True)
            os.link(a, c)
        if os.path.samefile(a, c):
            print(rel)
    except OSError:
        pass
"""


def espelhar_no_sei_cache(rels: list[str]) -> set[str]:
    """Link físico `sei_pdfs/<rel>` → `sei_cache/<rel>` na VM-2 (mesmo disco: mesmo inode, nenhum byte copiado, nada
    apagado nem sobrescrito). Devolve os `rel` cujo `sei_cache` É o arquivo de `sei_pdfs` (conferido por inode)."""
    rels = [r for r in rels if _REL.match(r)]
    if not rels:
        return set()
    r = subprocess.run([*_SSH, "vm2", "python3 -"], input=_LIGAR % json.dumps(json.dumps(rels)),
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"link no arquivo frio falhou: {r.stderr[-200:]}")
    return set(r.stdout.split()) & set(rels)


def tags_risco_alto() -> set[str]:
    """Processos com laudo de execução em risco alto (nota ≥ 7) ou sem documento de execução lido — o OCR deles vem
    antes (18/11/2026: metade dos "sem documento" tem as peças só como PDF escaneado ainda sem texto)."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{_REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=30)
        rows = con.execute("SELECT numero_sei FROM lex_execucao WHERE nota_risco >= 7 "
                           "OR execucao_comprovada IN ('nao', 'indeterminado')").fetchall()
        con.close()
    except sqlite3.Error:
        return set()
    return {numero_para_pasta(r[0]) for r in rows if r[0]}


def montar(frio: set[str], aplicados: set[tuple[str, int]], prioritarios: set[str] | None = None,
           reservados: set[str] | None = None) -> list[str]:
    prioritarios, reservados = prioritarios or set(), reservados or set()
    alvo: list[tuple[int, int, int, str]] = []
    for mp in ARQUIVO.glob("*/manifest.json"):
        tag = mp.parent.name
        try:
            docs = json.loads(mp.read_text(encoding="utf-8")).get("docs") or []
        except (OSError, ValueError):
            continue
        for d in docs:
            if not str(d.get("i", "")).isdigit() or str(d.get("ocr_motor", "")).startswith("surya"):
                continue
            i = int(d["i"])
            sem_texto, tess = _chars(d) < 40, foi_ocr(d) and _chars(d) >= 40
            if not (sem_texto or tess) or (tag, i) in aplicados:
                continue
            rel = f"integra_{tag}/{i:03d}.pdf"
            if rel in frio and rel not in reservados:
                classe = 2 if str(d.get("ocr_motor", "")).startswith("reserva") else 0 if tag in prioritarios else 1
                alvo.append((classe, PRIOR.get(d.get("tipo"), 5), 0 if sem_texto else 1, rel))
    alvo.sort()
    return [r for *_, r in alvo]


def main() -> int:
    ap = argparse.ArgumentParser(description="Fila do OCR por IA (GPU do it-campo)")
    ap.add_argument("--medir", action="store_true", help="só conta a fila por origem; não grava nem liga nada")
    ap.add_argument("--itcampo-local", action="store_true",
                    help="inclui C:\\JFN-Arquivo\\sei_pdfs do it-campo (só com o trabalhador que lê local no ar)")
    a = ap.parse_args()
    aplicados = set()
    if LEDGER.exists():
        for ln in LEDGER.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                e = json.loads(ln)
                if e.get("motor", "surya") != "reserva":       # o da reserva volta no fim (o Surya é mais forte)
                    aplicados.add((e["tag"], int(e["i"])))
    from tools.sei_ocr_reserva import reservados_pela_reserva
    cache, pdfs = pdfs_no_frio()
    local = pdfs_no_itcampo() if a.itcampo_local else set()
    fila = montar(cache | pdfs | local, aplicados, tags_risco_alto(), reservados_pela_reserva())
    so_pdfs = [r for r in fila if r not in cache and r in pdfs]
    conta = {"sei_cache": sum(r in cache for r in fila), "sei_pdfs": len(so_pdfs),
             "itcampo_local": sum(r not in cache and r not in pdfs for r in fila)}
    if a.medir:
        print(json.dumps({"fila": len(fila), "pastas": len({r.split("/")[0] for r in fila}), "por_origem": conta,
                          "ja_aplicados": len(aplicados)}))
        return 0
    ligados = espelhar_no_sei_cache(so_pdfs)
    fila = [r for r in fila if r in cache or r in ligados or r in local]     # link que falhou não entra
    tmp = SAIDA.with_suffix(".tmp")
    tmp.write_text("\n".join(fila) + ("\n" if fila else ""), encoding="utf-8")
    tmp.replace(SAIDA)
    print(json.dumps({"fila": len(fila), "por_origem": conta, "ligados": len(ligados),
                      "link_falhou": len(so_pdfs) - len(ligados), "ja_aplicados": len(aplicados)}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
