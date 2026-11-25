#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Índice do HD externo do it-campo (D:\\JFN-Frio) — plano de reescrita, Fase 0 (23/11/2026).

Dono: "deixe todo o hd super organizado também. e índice de tudo que moveu e onde está no brain etc". E: o HD é
LUGAR, não cópia extra — o re-obtível vai para lá e SAI da VM. Regra que mantém o OCR andando sem o it-campo: o PDF
na fila do OCR (`data/sei_ocr_gpu_fila.txt`) NÃO sai da VM-2 até o OCR terminar.

Entrada (gerada pela migração em data/hd_migracao/): `lista_<src>.json` (rclone lsjson --hash md5 da VM-2),
`check_<src>.txt` (rclone check --combined: "= caminho" igual; outros sinais = diferente/faltando).
Saída: `data/hd_migracao/indice_<src>.jsonl`, `data/hd_migracao/sai_da_vm2_<src>.txt` (só conferido e fora da fila
de OCR) e `00-LEIAME.md`; `--publicar` sobe índice e LEIAME para D:\\JFN-Frio\\_indice e D:\\JFN-Frio.

Uso:  python -m tools.hd_indice [--publicar]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MIG = RAIZ / "data" / "hd_migracao"
HD = "D:/JFN-Frio"
PARES = {"sei_pdfs": "sei/pdfs_escaneados", "sei_cache": "sei/integras_cache",
         # O0.2 (24/11/2026): o resto do arquivo frio da VM-2 (re-obtível; quarentena/substituídos de tools/vm2_conferencia)
         "sei_fotos": "sei/fotos", "sei_arquivo_substituido": "sei/arquivo_substituido",
         "vm2_quarentena": "vm2/quarentena", "vm2_substituidos": "vm2/substituidos"}
RCLONE = str(Path.home() / ".local" / "bin" / "rclone")
DESTINO = (":sftp,host=100.75.118.110,user=iterj,key_file=/home/ubuntu/.ssh/id_itcampo,shell_type=powershell,"
           "known_hosts_file=/home/ubuntu/.ssh/known_hosts:")


def montar(src: str, dst: str, lista: list[dict], check: str, fila_ocr: set[str], em: str) -> list[dict]:
    iguais = {ln[2:].strip() for ln in check.splitlines() if ln.startswith("= ")}
    out = []
    for item in lista:
        rel = item["Path"]
        conferido = rel in iguais
        pend = rel in fila_ocr
        out.append({"caminho_hd": f"{HD}/{dst}/{rel}", "origem": f"vm2:~/arquivo_frio/{src}", "origem_rel": rel,
                    "bytes": int(item.get("Size") or 0), "md5": (item.get("Hashes") or {}).get("md5"),
                    "conferido": conferido, "pendente_ocr": pend, "sai_da_vm2": conferido and not pend, "em": em})
    return out


def _gb(n: int) -> str:
    return f"{n / 1e9:,.2f} GB".replace(",", "X").replace(".", ",").replace("X", ".")


def leiame(linhas: list[dict], em: str) -> str:
    por: dict[str, list[int]] = {}
    for ln in linhas:
        rel_hd = ln["caminho_hd"][len(HD) + 1:]
        pasta = next((d for d in PARES.values() if rel_hd.startswith(d + "/")), rel_hd.split("/integra_")[0])
        q = por.setdefault(pasta, [0, 0, 0])
        q[0] += 1
        q[1] += ln["bytes"]
        q[2] += ln["conferido"]
    def _n(k: int) -> str:
        return f"{k:,}".replace(",", ".")
    tab = "\n".join(f"| `{p}` | {_n(q[0])} | {_gb(q[1])} | {_n(q[2])} |" for p, q in sorted(por.items()))
    return f"""# JFN-Frio — HD externo do it-campo (Seagate Portable 1 TB)

Atualizado: {em} · gerado por `~/JFN/tools/hd_indice.py` · plano: `~/JFN/docs/PLANO-PLATAFORMA-EVIDENCIAS.md`

## O que é
Depósito MORNO do JFN: arquivos re-obtíveis (PDFs do SEI, lotes antigos de captura) que saíram das VMs para liberar
espaço. O HD é **lugar, não cópia extra** (dono, 23/11/2026). O que não se recaptura nunca fica só aqui.

## Regras
- **HD ausente ⇒ INDISPONÍVEL**, nunca "não existe": quem procura um arquivo daqui e não acha o HD declara a lacuna.
- Nada sai da origem sem **md5 conferido** nos dois lados (`rclone check`).
- PDF na fila do OCR **fica na VM-2** até o OCR terminar (o OCR precisa andar com o it-campo desligado).
- Organizar só por pasta de destino abaixo; nunca editar arquivo daqui à mão.

## Conteúdo
| Pasta | Arquivos | Tamanho | Conferidos por md5 |
|---|---|---|---|
{tab}

## Como achar algo
`_indice/indice.jsonl` — uma linha por arquivo: `caminho_hd`, `origem` (máquina:pasta), `origem_rel`, `bytes`,
`md5`, `conferido`, `pendente_ocr`, `sai_da_vm2`, `em`. Na VM-1: `grep <processo> ~/JFN/data/hd_migracao/indice_*.jsonl`.
"""


def _fila_ocr(rels: list[str] | None = None) -> set[str]:
    """Pendentes de OCR = os da fila da GPU MAIS todo PDF cujo documento no manifesto do arquivo ainda não tem
    texto (< 40 caracteres). 23/11/2026: a fila sozinha deu 0 pendentes num lote em que 15 estavam sem texto."""
    f = RAIZ / "data" / "sei_ocr_gpu_fila.txt"
    out = {ln.strip() for ln in f.read_text().splitlines() if ln.strip()} if f.is_file() else set()
    mans: dict[str, dict] = {}
    for rel in rels or []:
        pasta, _, arq = rel.partition("/")
        if not (pasta.startswith("integra_") and arq[:3].isdigit()):
            continue
        tag = pasta[len("integra_"):]
        if tag not in mans:
            try:
                mans[tag] = {str(d.get("i")): d for d in json.loads((RAIZ / "data" / "sei_arquivo" / tag /
                                                                     "manifest.json").read_text()).get("docs") or []}
            except (OSError, ValueError):
                mans[tag] = {}
        d = mans[tag].get(str(int(arq[:3])))
        if d is not None and int(d.get("chars") or 0) < 40:
            out.add(rel)
    # O0.2 (24/11/2026): também o Tesseract ainda não relido pelo Surya (mesma regra da fila da GPU, sem a exclusão
    # da reserva) e o que a reserva da VM-2 tem reservado/entregue — PDF que o OCR ainda vai ler não sai da VM-2.
    if rels:
        from tools import sei_ocr_gpu_fila as fila_gpu
        from tools.sei_ocr_reserva import reservados_pela_reserva
        aplicados = set()
        if fila_gpu.LEDGER.exists():
            for ln in fila_gpu.LEDGER.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    e = json.loads(ln)
                    if e.get("motor", "surya") != "reserva":
                        aplicados.add((e["tag"], int(e["i"])))
        out |= set(fila_gpu.montar(set(rels), aplicados, set(), set())) | reservados_pela_reserva()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Índice do HD externo")
    ap.add_argument("--publicar", action="store_true", help="sobe índice e LEIAME para o HD")
    a = ap.parse_args(argv)
    em = time.strftime("%Y-%m-%d %H:%M")
    todas: list[dict] = []
    for src, dst in PARES.items():
        lista_f, check_f = MIG / f"lista_{src}.json", MIG / f"check_{src}.txt"
        if not (lista_f.is_file() and check_f.is_file()):
            print(f"{src}: migração ainda sem lista/conferência — nada a indexar", file=sys.stderr)
            continue
        idx_f = MIG / f"indice_{src}.jsonl"
        if idx_f.is_file() and idx_f.stat().st_mtime >= max(lista_f.stat().st_mtime, check_f.stat().st_mtime):
            # rodada sem lista/conferência nova: o índice dela é histórico (o que saiu, saiu) — não se recalcula
            todas += [json.loads(t) for t in idx_f.read_text().splitlines() if t.strip()]
            print(f"{src}: sem rodada nova — índice mantido")
            continue
        lista = json.loads(lista_f.read_text())
        fila = _fila_ocr([x["Path"] for x in lista]) if src in ("sei_pdfs", "sei_cache") else set()
        linhas = montar(src, dst, lista, check_f.read_text(), fila, em)
        # Merge (O0.2, 24/11/2026): a lista nova só vê o que AINDA está na VM-2; o que rodadas anteriores já tiraram
        # de lá continua no HD e no índice (sem isto, cada rodada apagaria do índice as anteriores).
        novos = {x["origem_rel"] for x in linhas}
        if idx_f.is_file():
            linhas = [x for x in (json.loads(t) for t in idx_f.read_text().splitlines() if t.strip())
                      if x["origem_rel"] not in novos] + linhas
        (MIG / f"indice_{src}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in linhas))
        sai = [x["origem_rel"] for x in linhas if x["sai_da_vm2"] and x["origem_rel"] in novos]
        (MIG / f"sai_da_vm2_{src}.txt").write_text("".join(f"{r}\n" for r in sai))
        print(f"{src}: {len(linhas)} arquivos, {sum(x['conferido'] for x in linhas)} conferidos, "
              f"{sum(x['pendente_ocr'] for x in linhas)} pendentes de OCR, {len(sai)} podem sair da VM-2")
        todas += linhas
    if not todas:
        return 1
    (MIG / "00-LEIAME.md").write_text(leiame(todas, em), encoding="utf-8")
    (MIG / "indice.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in todas))
    if a.publicar:
        for local, remoto in ((MIG / "indice.jsonl", f"{HD}/_indice/indice.jsonl"),
                              (MIG / "00-LEIAME.md", f"{HD}/00-LEIAME.md")):
            r = subprocess.run([RCLONE, "copyto", "--checksum", str(local), DESTINO + remoto], capture_output=True,
                               text=True, timeout=600)
            print(f"publicado {remoto}: rc={r.returncode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
