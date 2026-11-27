"""Recaptura dos relatórios fotográficos que chegaram SÓ com o texto do cache (regra única #58 do mapa O1.2,
ex-`sei_integra_fila._relatorio_fotografico_sem_foto`; auditoria de 27/11/2026: 175 processos / 252 relatórios).

Lê os manifestos do arquivo SEI (origem «cache CDP», documento de relatório/registro/memorial fotográfico com zero
foto), grava o pedido em `recaptura_pedida` (captura_003: a versão LEGADA deixa de contar como captura) e reabre o
`arvore:<processo>` com o contrato do E2 — o E2 vê o documento faltando e o E3 o baixa pela íntegra (a que traz as
fotos). Idempotente (PK e chave do job). Sem `--executar`, só mede.
    python -m tools.recaptura_fotos [--executar] [--limite N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RX_REL_FOTO = re.compile(r"relat[óo]rio\s+fotogr|registro\s+fotogr|memorial\s+fotogr", re.I)
RX_ID = re.compile(r"\((\d{6,})\)\s*$")
MOTIVO = "relatório fotográfico só com o texto do cache (sem foto) — regra única #58"


def pedidos_do_manifesto(m: dict) -> list[tuple[str, str]]:
    """[(processo, doc_id)] do manifesto: só origem «cache CDP», só relatório fotográfico sem foto, só com o número
    SEI no título (é o doc_id do PG: `sei:<número>`). Puro."""
    if not isinstance(m, dict) or not str(m.get("origem") or "").startswith("cache CDP"):
        return []
    proc = str(m.get("processo") or "").strip()
    out = []
    for d in m.get("docs") or []:
        if not isinstance(d, dict):
            continue
        tit = str(d.get("titulo") or "")
        if RX_REL_FOTO.search(tit) and str(d.get("fotos") or "[]") in ("[]", "") and (n := RX_ID.search(tit)) and proc:
            out.append((proc, f"sei:{n[1]}"))
    return out


def coletar(raiz: Path) -> list[tuple[str, str]]:
    out = []
    for f in sorted(raiz.glob("*/manifest.json")):
        try:
            out += pedidos_do_manifesto(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--executar", action="store_true")
    ap.add_argument("--limite", type=int, default=0, help="no máximo N processos reabertos (0 = todos)")
    ap.add_argument("--raiz", default="data/sei_arquivo")
    a = ap.parse_args(argv)
    pedidos = coletar(Path(a.raiz))
    procs = sorted({p for p, _ in pedidos})
    print(f"recaptura_fotos: {len(pedidos)} relatório(s) fotográfico(s) sem foto em {len(procs)} processo(s)")
    if not a.executar:
        return 0
    from compliance_agent.aplicacao.estagios import arvore as A
    from compliance_agent.fluxo import fila
    from compliance_agent.fluxo import grafo as G
    con = A.conectar(None, None)
    try:
        legado = {(p, d) for p, d in con.execute(
            "SELECT processo, doc_id FROM versoes WHERE origem = 'sei_arquivo' AND (processo, doc_id) IN "
            "(SELECT unnest(%s::text[]), unnest(%s::text[]))", ([p for p, _ in pedidos], [d for _, d in pedidos]))}
        for p, d in sorted(legado):
            con.execute("INSERT INTO recaptura_pedida(processo, doc_id, motivo) VALUES (%s, %s, %s) "
                        "ON CONFLICT DO NOTHING", (p, d, MOTIVO))
    finally:
        con.close()
    g = G.carregar()
    c, base = g.contrato_do_estagio("E2"), g.payload_do_estagio("E2")
    alvo = sorted({p for p, _ in legado})[: a.limite or None]
    cf = fila.conectar()
    try:
        novos = sum(1 for p in alvo if fila.enfileirar(
            cf, "arvore", f"arvore:{p}", {**base, "processo": p, "origem": "recaptura_fotos"}, prioridade=c["prioridade"],
            recursos=c["recursos"], volta=c["volta"], no_preferido=c["no_preferido"],
            correlation_id="recaptura_fotos", reabrir=True) is not None)
    finally:
        cf.close()
    print(f"recaptura_fotos: {len(legado)} pedido(s) gravado(s) (versão legada presente no PG); "
          f"{len(alvo)} árvore(s) reaberta(s)/enfileirada(s) ({novos} mudaram de estado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
