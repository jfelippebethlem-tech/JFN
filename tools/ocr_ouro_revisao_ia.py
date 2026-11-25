# -*- coding: utf-8 -*-
"""Revisão por IA independente da lista de revisão do ouro do OCR (O3.6) — PRONTA, NÃO RODADA.

Quando: SÓ DEPOIS de sáb 28/11/2026 19h (BRT) — antes disso a assinatura fica para o resto da semana (ritmo semanal,
virada de sábado 19h). O guarda é por código: antes da hora o comando recusa (sem `--forcar` nenhum).
Quem: Claude pela ASSINATURA (`claude_motor.pensar(..., backend="cli")`), com a ferramenta Read para VER o recorte
PNG — nunca a API paga, nunca a cascata barata. Rótulo NÃO HUMANO: `revisor = "claude-<modelo>-assinatura"`,
`humano = False` — o `ouro.estado_revisao_tier1` nunca o conta como humano.
O quê: para cada número em revisão, a IA lê o recorte e diz o número que está escrito (ou `ilegivel`). Vira rótulo
só se o que a IA leu, normalizado, for IGUAL a um dos números que algum motor leu (a IA desempata, não inventa).
Saída: uma VERSÃO NOVA do ouro (`ouro-ocr-r1-<data>.jsonl`, congelada com sha256) — a de origem fica intacta.

    python -m tools.ocr_ouro_revisao_ia --ouro data/ouro_ocr/ouro-ocr-2026-11-25.jsonl \\
        --revisao data/ouro_ocr/revisao-2026-11-25.jsonl --recortes data/ouro_ocr/revisao [--limite N]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

BRT = timezone(timedelta(hours=-3))
LIBERADO_EM = datetime(2026, 11, 28, 19, 0, tzinfo=BRT)
TAREFA = "ocr_ouro_revisao"
_SYS = ("Você confere a leitura de UM número num recorte de documento escaneado. Abra a imagem com a ferramenta Read. "
        "Responda SÓ com JSON {\"lido\": \"<o número exatamente como está escrito>\" | null, \"legivel\": true|false}. "
        "Nunca complete dígito que não dá para ver: ilegível ⇒ legivel=false e lido=null.")


def liberado(agora: datetime | None = None) -> bool:
    return (agora or datetime.now(BRT)) >= LIBERADO_EM


def prompt(item: dict, recortes: Path) -> str:
    tipo = item["numero"].split(":", 1)[0]
    return (f"Imagem: {recortes / item['recorte_png']}\nTipo do número procurado: {tipo} "
            f"(valor em reais, CNPJ, data dd/mm/aaaa ou nº de processo SEI). Qual {tipo} está escrito no recorte?")


def decidir(item: dict, resposta: dict | None) -> str | None:
    """O número (`tipo:norma`) que vira rótulo, ou None. Só aceita leitura da IA que coincide com a de algum motor."""
    from compliance_agent.sei import ocr_ia_prova as P
    if not resposta or not resposta.get("legivel") or not resposta.get("lido"):
        return None
    tipo = item["numero"].split(":", 1)[0]
    lidos = {f"{x['tipo']}:{x['norma']}" for x in P.extrair(str(resposta["lido"]), tolerante=True) if x["tipo"] == tipo}
    motores = {n for ns in (item.get("leituras") or {}).values() for n in ns} | {item["numero"]}
    return next(iter(sorted(lidos & motores)), None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="revisão por IA (assinatura) do ouro do OCR — depois de 28/11 19h")
    ap.add_argument("--ouro", required=True)
    ap.add_argument("--revisao", required=True)
    ap.add_argument("--recortes", required=True)
    ap.add_argument("--limite", type=int)
    a = ap.parse_args(argv)
    if not liberado():
        print(f"recusado: a revisão por IA só roda depois de {LIBERADO_EM:%d/%m/%Y %Hh} (BRT) — ritmo da assinatura")
        return 2
    from compliance_agent.llm import claude_motor
    from compliance_agent.qualidade import ouro_ocr as OO
    pags = {p.img_sha: p for p in OO.ler_congelado(Path(a.ouro))}
    itens = [json.loads(ln) for ln in Path(a.revisao).read_text(encoding="utf-8").splitlines() if ln.strip()]
    itens = [i for i in itens if i.get("recorte_png")][:a.limite] if a.limite else [i for i in itens
                                                                                   if i.get("recorte_png")]
    novos: dict[str, list[str]] = {}
    feitos = 0
    for it in itens:
        p = claude_motor.pensar(TAREFA, prompt(it, Path(a.recortes)), modelo=claude_motor.MODELO_JUIZO,
                                sistema=_SYS, ferramentas=("Read",), backend="cli")
        if p is None:
            break                                     # sem cota da assinatura: para; o que ficou volta na próxima
        feitos += 1
        try:
            resp = json.loads(p.texto.strip().strip("`").removeprefix("json").strip())
        except ValueError:
            resp = None
        n = decidir(it, resp)
        if n:
            novos.setdefault(it["img_sha"], []).append(n)
    hoje = datetime.now(BRT).strftime("%Y-%m-%d")
    rev = f"claude-{claude_motor.MODELO_JUIZO}-assinatura"
    saida = []
    for s, pg in pags.items():
        add = sorted(set(novos.get(s, [])) - set(pg.rotulos))
        if add:
            resto = tuple(r for r in pg.revisar if (r["numero"] if isinstance(r, dict) else r) not in add)
            pg = replace(pg, rotulos=tuple(sorted(pg.rotulos + tuple(add))), revisar=resto, revisor=rev,
                         rotulado_em=hoje, extra={**pg.extra, "revisao_ia": add, "humano": False})
        saida.append(pg)
    arq = OO.congelar(saida, Path(a.ouro).parent, hoje, nome="ouro-ocr-r1")
    print(json.dumps({"revisados": feitos, "de": len(itens), "viraram_rotulo": sum(map(len, novos.values())),
                      "versao_nova": str(arq), "revisor": rev, "humano": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
