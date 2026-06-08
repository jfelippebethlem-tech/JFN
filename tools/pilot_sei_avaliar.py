# -*- coding: utf-8 -*-
"""Piloto SEI (Onda B): varre N processos de contratação do SEI, salva a ÁRVORE real (calibração —
responde P0.2/P0.3 do HANDOFF), classifica documentos, tenta extrair preço unitário e AVALIA
(taxa de sucesso, tipos de doc vistos, dispersão de preço).

HONESTO / ADAPTADO ao que existe na VM (Fase 0):
- fonte dos processos: --processos "a,b,c"  OU  --auto (pega numero_sei BEM-FORMADOS de ordens_bancarias,
  pois processos_sei está vazia);
- NÃO classifica família (o spec AVALIARGASTOS-RJ não foi enviado → módulos gastos/* não existem);
- LLM via LLMRouter se disponível; senão roda só tabela/texto e marca a extração como 'pendente';
- nunca fabrica número; salva discovery log em data/pilot/.

Uso:
  cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.pilot_sei_avaliar --processos "SEI-140001/017080/2022"
  cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.pilot_sei_avaliar --auto --n 5
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.sei import classificador_doc, extrator_precos, navegador

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
OUT = _REPO / "data" / "pilot"
CAL = OUT / "calibracao"
OUT.mkdir(parents=True, exist_ok=True)
CAL.mkdir(parents=True, exist_ok=True)

_SEI_BEMFORMADO = re.compile(r"^(SEI[- ]|E-)?\d{2,}", re.I)


def _gerar_opcional():
    """Devolve uma função gerar(prompt)->str se houver LLM; senão None (degrada honesto)."""
    try:
        from compliance_agent.llm.router import LLMRouter
        r = LLMRouter()
        return lambda prompt: r.gerar(prompt) if hasattr(r, "gerar") else None
    except Exception:  # noqa: BLE001
        return None


def selecionar(processos: str | None, auto: bool, n: int) -> list[str]:
    if processos:
        return [p.strip() for p in processos.split(",") if p.strip()][:n]
    if auto and _DB.exists():
        con = sqlite3.connect(str(_DB))
        rows = con.execute(
            "SELECT DISTINCT numero_sei FROM ordens_bancarias "
            "WHERE numero_sei LIKE 'SEI%' OR numero_sei LIKE 'E-%' LIMIT 200").fetchall()
        con.close()
        cand = [r[0] for r in rows if r[0] and _SEI_BEMFORMADO.match(r[0].strip())]
        return cand[:n]
    return []


def processar(numero: str, gerar) -> dict:
    reg = {"processo": numero, "ok_abertura": False, "n_docs": 0, "tipos": {}, "itens": [], "erro": ""}
    res = navegador.abrir_processo(numero)
    if not res.get("ok"):
        reg["erro"] = res.get("erro", "falha ao abrir")
        return reg
    reg["ok_abertura"] = True
    docs = res["docs"]
    reg["n_docs"] = len(docs)
    # calibração: salva a árvore real (rótulos como o SEI-RJ os nomeia — P0.2/P0.3)
    try:
        (CAL / f"arvore_{re.sub(r'[^0-9A-Za-z]', '_', numero)}.json").write_text(
            json.dumps([{"titulo": d.titulo, "tipo": classificador_doc.classificar_doc(d.titulo, d.conteudo),
                         "url": d.url, "formato": d.formato} for d in docs], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    tipos = Counter()
    for d in docs:
        tipo = classificador_doc.classificar_doc(d.titulo, d.conteudo)
        tipos[tipo] += 1
        if classificador_doc.tem_preco(tipo) and d.conteudo:
            itens, metodo, conf = extrator_precos.extrair_itens(d.conteudo, gerar=gerar)
            for it in itens:
                it.update({"processo": numero, "doc": d.titulo, "tipo_doc": tipo,
                           "metodo": metodo, "confianca": conf})
            reg["itens"].extend(itens)
    reg["tipos"] = dict(tipos)
    return reg


def avaliar(regs: list[dict], gerar_ok: bool) -> dict:
    abertos = [r for r in regs if r["ok_abertura"]]
    todos_itens = [it for r in regs for it in r["itens"]]
    precos = [it["valor_unitario"] for it in todos_itens if isinstance(it.get("valor_unitario"), (int, float))]
    tipos_glob = Counter()
    for r in regs:
        tipos_glob.update(r.get("tipos", {}))
    disp = {}
    if len(precos) >= 2:
        disp = {"n": len(precos), "min": min(precos), "max": max(precos),
                "mediana": round(statistics.median(precos), 2),
                "cv": round(statistics.pstdev(precos) / (statistics.mean(precos) or 1), 3)}
    return {
        "n_processos": len(regs),
        "abertos_ok": len(abertos),
        "taxa_abertura": round(len(abertos) / len(regs), 2) if regs else 0,
        "com_itens": sum(1 for r in regs if r["itens"]),
        "n_itens_extraidos": len(todos_itens),
        "tipos_doc_vistos": dict(tipos_glob),
        "dispersao_preco": disp,
        "llm_disponivel": gerar_ok,
        "_nota": ("Extração de itens depende de LLM/PDF: o SEI entrega TEXTO; sem LLM (ou sem PDF p/ tabela) "
                  "a camada de preço fica pendente — honesto, não fabrica." if not gerar_ok else
                  "Itens extraídos por LLM sobre o texto do documento; conferir na fonte (proveniência)."),
        "P0_descobertas": {
            "P0.2_arvore_salva_em": str(CAL),
            "P0.3_tipos_reais": dict(tipos_glob),
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Piloto SEI — varre processos, calibra e avalia.")
    ap.add_argument("--processos", default="")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--n", type=int, default=5)
    a = ap.parse_args()
    alvos = selecionar(a.processos or None, a.auto, a.n)
    if not alvos:
        print(json.dumps({"ok": False, "erro": "sem processos (use --processos ou --auto)"}, ensure_ascii=False))
        return
    gerar = _gerar_opcional()
    regs = [processar(num, gerar) for num in alvos]
    rel = {"ok": True, "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "processos": alvos, "avaliacao": avaliar(regs, gerar is not None), "detalhe": regs}
    (OUT / "ultimo_pilot.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rel["avaliacao"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
