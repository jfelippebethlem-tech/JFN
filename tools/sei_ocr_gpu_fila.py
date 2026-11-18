"""Fila do OCR por IA na GPU do it-campo: documentos do arquivo SEI lidos pelo Tesseract (ocr=True) ou sem texto,
cujo PDF ainda existe no arquivo frio da VM-2 — e que o integrador ainda não aplicou.

Prioridade (valor em R$ e prova de pagamento primeiro): nota fiscal, proposta → OB, liquidação, medição, atesto →
empenho, contrato, aditivo → autorização, parecer, ata → edital → resto. Sem texto vem antes de Tesseract.
Grava `data/sei_ocr_gpu_fila.txt` (caminhos `integra_<tag>/NNN.pdf` relativos a vm2:~/arquivo_frio/sei_cache), que o
trabalhador do it-campo puxa quando a fila dele acaba. Nativo nunca entra (texto do próprio PDF é a verdade).

RESERVA (18/11/2026, `tools/sei_ocr_reserva.py`): o que a reserva da VM-2 tem reservado ou entregue e ainda não aplicado
fica FORA (não duplicar com a GPU); o que a reserva já aplicou volta só no FIM da fila — o Surya é mais forte e
substitui o texto da reserva quando chegar (precedência em `tools/sei_ocr_gpu_integrar.py`).

    python -m tools.sei_ocr_gpu_fila
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def pdfs_no_frio() -> set[str]:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "vm2",
                        "cd ~/arquivo_frio/sei_cache && find . -name '*.pdf' -printf '%P\\n'"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"lista do arquivo frio indisponível: {r.stderr[-200:]}")
    return set(r.stdout.split())


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
    return {str(r[0]).replace("SEI-", "").replace("/", "_") for r in rows if r[0]}


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
            sem_texto, tess = _chars(d) < 40, bool(d.get("ocr")) and _chars(d) >= 40
            if not (sem_texto or tess) or (tag, i) in aplicados:
                continue
            rel = f"integra_{tag}/{i:03d}.pdf"
            if rel in frio and rel not in reservados:
                classe = 2 if str(d.get("ocr_motor", "")).startswith("reserva") else 0 if tag in prioritarios else 1
                alvo.append((classe, PRIOR.get(d.get("tipo"), 5), 0 if sem_texto else 1, rel))
    alvo.sort()
    return [r for *_, r in alvo]


def main() -> int:
    aplicados = set()
    if LEDGER.exists():
        for ln in LEDGER.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                e = json.loads(ln)
                if e.get("motor", "surya") != "reserva":       # o da reserva volta no fim (o Surya é mais forte)
                    aplicados.add((e["tag"], int(e["i"])))
    from tools.sei_ocr_reserva import reservados_pela_reserva
    fila = montar(pdfs_no_frio(), aplicados, tags_risco_alto(), reservados_pela_reserva())
    tmp = SAIDA.with_suffix(".tmp")
    tmp.write_text("\n".join(fila) + ("\n" if fila else ""), encoding="utf-8")
    tmp.replace(SAIDA)
    print(json.dumps({"fila": len(fila), "ja_aplicados": len(aplicados)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
