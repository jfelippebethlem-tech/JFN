#!/usr/bin/env python3
"""Minerador da base processo_avaliacao — ranqueia pela QUALIDADE do achado, não pelo score cru.

O score de convergência satura no topo em processo grande (lição 2026-08-01); o que separa o
grave do burocrático é O QUE foi achado. Régua de prioridade (pontos por processo):
  A1/inversão contrato→parecer .... 5   (art. 53 — vício de legalidade na formação)
  pagamento sem execução (crítica) . 5   (dano potencial direto)
  emissor insuficiente ............. 4   (lição IDESI)
  acatamento IGNORADO .............. 4   (ressalva atropelada)
  A2 ressalva sem resposta ......... 3
  demais achados alto/alta ......... 2   · médio/média ......... 1

Uso: tools/processo_360_ranking.py [--top N] [--md]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def pontuar(achados: list[dict], acatamento: dict) -> tuple[int, list[str]]:
    pts, motivos = 0, []
    for a in achados or []:
        cod = str(a.get("codigo") or "")
        diz = str(a.get("diz") or "")
        grav = str(a.get("gravidade") or a.get("grau") or "")
        if cod == "A1_CONTRATO_ANTES_DO_PARECER" or a.get("origem") == "cadeia" and "parecer" in diz:
            pts += 5; motivos.append("contrato ANTES do parecer (art. 53)")
        elif grav == "critica":
            # O RÓTULO TEM DE SER O ACHADO. Este ramo escrevia "pagamento sem evidência de
            # execução" para QUALQUER achado crítico. Medido em 2026-08-04, depois de as famílias
            # X, C e P/E/J passarem a produzir achados visíveis: **24 no acervo seriam rotulados
            # errado** — um C9 de perfil de fornecedor, um X7 de dupla correção e um I3 de ato sem
            # assinatura, todos impressos como pagamento sem execução. O fiscal lê esta coluna e
            # abriria diligência pelo motivo errado.
            pts += 5
            motivos.append("pagamento sem evidência de execução"
                           if "Evidência de execução" in diz else (diz[:70] or cod or "achado crítico"))
        elif a.get("origem") == "suficiencia_emissor":
            pts += 4; motivos.append("parecer de emissor insuficiente")
        elif cod.startswith("A2"):
            pts += 3; motivos.append("ressalva de parecer sem resposta")
        elif grav in ("alto", "alta"):
            pts += 2; motivos.append(diz[:60] or cod or "achado alto")
        else:
            pts += 1
    if (acatamento or {}).get("veredito") == "IGNORADO_INDICIO":
        pts += 4; motivos.append("parecer IGNORADO pela autoridade")
    return pts, motivos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from processo_avaliacao").fetchall()
    con.close()

    ranking = []
    for r in rows:
        achados = json.loads(r["achados_json"] or "[]")
        ac = json.loads(r["acatamento_json"] or "{}")
        pts, motivos = pontuar(achados, ac)
        ranking.append({"processo": r["numero_sei"], "pontos": pts, "score100": r["score100"],
                        "grau": r["grau"], "faixa": r["faixa"], "cnpj": r["cnpj_vencedor"],
                        "motivos": sorted(set(motivos)), "avaliado_em": r["avaliado_em"]})
    ranking.sort(key=lambda x: (-x["pontos"], -(x["score100"] or 0)))

    top = ranking[: args.top]
    if args.md:
        print("| # | Processo | Pontos | Grau | Motivos |")
        print("|---|---|---|---|---|")
        for i, r in enumerate(top, 1):
            print(f"| {i} | {r['processo']} | {r['pontos']} | {r['grau']}/{r['faixa']} "
                  f"| {'; '.join(r['motivos'])[:160]} |")
    else:
        for i, r in enumerate(top, 1):
            print(f"{i:3d}. [{r['pontos']:2d} pts] {r['processo']} ({r['grau']}/{r['faixa']}) — "
                  f"{'; '.join(r['motivos'])[:140]}")
    print(f"\n{len(rows)} processos avaliados · {sum(1 for x in ranking if x['pontos'] >= 5)} "
          f"com achado forte (≥5 pts)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
