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



def sinal_osint() -> dict[str, dict]:
    """Processos cuja EMPRESA já tem sinal OSINT — a inteligência entra na régua do fiscal.

    A fila ordenava só por achado de DETECTOR, e a casa passou a sessão inteira construindo
    inteligência sobre as empresas — agente público no quadro societário, autos correndo no
    próprio órgão do agente, participante de certame dividindo contato com o concorrente — sem que
    nada disso mudasse a ordem em que os autos são abertos. Correlacionar é isto: o que se sabe da
    empresa muda o que se lê primeiro.

    A PONTUAÇÃO É MODESTA DE PROPÓSITO, e o motivo é a régua da casa. Achado de detector é vício
    LIDO NOS AUTOS; sinal OSINT é indício SOBRE A EMPRESA, casado por nome ou por contato. Deixar
    o indício empurrar o vício para baixo inverteria a hierarquia da prova:
      · autos no PRÓPRIO órgão do agente ..... 3  (art. 9º, III da Lei 8.429 — quase-objetivo)
      · agente público comissionado no QSA ... 2
      · agente público no QSA ................ 1

    Ausência do arquivo não derruba nada: sem os JSONs, devolve vazio e a ordem volta a ser a
    anterior. Prioridade que quebra a fila seria pior que prioridade nenhuma.
    """
    fora: dict[str, dict] = {}
    alvo = REPO / "data" / "osint_x_processos.json"
    if not alvo.exists():
        return fora
    try:
        corpo = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fora
    for x in corpo.get("achados", []):
        agentes = x.get("agentes") or []
        if not agentes:
            continue
        conflito = any(a.get("conflito_pelo_processo") or a.get("conflito_de_orgao")
                       for a in agentes)
        comissionado = any(a.get("comissionado") for a in agentes)
        pts = 3 if conflito else (2 if comissionado else 1)
        g = agentes[0]
        fora[str(x.get("processo") or "")] = {
            "pontos": pts,
            "motivo": ("OSINT: autos no PRÓPRIO órgão do agente — " if conflito else
                       ("OSINT: agente público COMISSIONADO no quadro societário — "
                        if comissionado else "OSINT: agente público no quadro societário — "))
                      + f"{g.get('nome', '')} ({g.get('cargo', '')}) · {g.get('entidade', '')}",
        }
    return fora


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--md", action="store_true")
    # `--osint`: lista TODOS os processos com sinal OSINT, em QUALQUER posição do ranking, no
    # formato plano. Existe porque o sinal OSINT pontua pouco (≤3) e cai para o fundo da fila — o
    # filtro "só OSINT" do painel, limitado ao top-N, dizia "0" quando os itens estavam logo abaixo
    # da janela. Zero por corte de janela lê-se como "não há", e a casa não deixa o corte mentir.
    ap.add_argument("--osint", action="store_true",
                    help="lista todos os processos com sinal OSINT, fora ou dentro do top")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from processo_avaliacao").fetchall()
    con.close()

    osint = sinal_osint()
    ranking = []
    for r in rows:
        achados = json.loads(r["achados_json"] or "[]")
        ac = json.loads(r["acatamento_json"] or "{}")
        pts, motivos = pontuar(achados, ac)
        # O NÚMERO SEI vem com prefixo em algumas fontes e sem em outras — casa pelos dígitos.
        chave = "".join(c for c in str(r["numero_sei"]) if c.isdigit())
        for k, v in osint.items():
            if "".join(c for c in k if c.isdigit()) == chave:
                pts += v["pontos"]
                motivos.append(v["motivo"])
                break
        ranking.append({"processo": r["numero_sei"], "pontos": pts, "score100": r["score100"],
                        "grau": r["grau"], "faixa": r["faixa"], "cnpj": r["cnpj_vencedor"],
                        "motivos": sorted(set(motivos)), "avaliado_em": r["avaliado_em"]})
    ranking.sort(key=lambda x: (-x["pontos"], -(x["score100"] or 0)))

    if args.osint:
        # ordem: os que JÁ estão no topo por vício próprio primeiro (têm as duas coisas), depois
        # os que só o OSINT trouxe — a posição real no ranking é preservada no número impresso.
        osint_todos = [(i, r) for i, r in enumerate(ranking, 1)
                       if any("OSINT:" in m for m in r["motivos"])]
        for pos, r in osint_todos:
            print(f"{pos:3d}. [{r['pontos']:2d} pts] {r['processo']} ({r['grau']}/{r['faixa']}) — "
                  f"{'; '.join(r['motivos'])[:140]}")
        print(f"\n{len(rows)} processos avaliados · {len(osint_todos)} com sinal OSINT",
              file=sys.stderr)
        return 0

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
    # SEÇÃO PRÓPRIA PARA O SINAL OSINT, e a razão é a hierarquia da prova. O indício sobre a
    # empresa pontua pouco de propósito (no máximo 3, contra 5 do vício lido nos autos), então um
    # processo SÓ com sinal OSINT nunca alcança o topo — e ficaria invisível. Invisível não serve:
    # o que se sabe da empresa precisa chegar a quem abre os autos, sem atropelar o que está neles.
    fora_do_topo = [r for r in ranking[args.top:] if any("OSINT:" in m for m in r["motivos"])]
    if fora_do_topo and args.md:
        print(f"\n### Com sinal OSINT, fora do top {args.top} "
              f"({len(fora_do_topo)} processo(s))\n")
        print("| Processo | Pontos | Grau | Sinal |")
        print("|---|---|---|---|")
        for r in fora_do_topo[:25]:
            sinal = next((m for m in r["motivos"] if "OSINT:" in m), "")
            print(f"| {r['processo']} | {r['pontos']} | {r['grau']}/{r['faixa']} | {sinal} |")

    print(f"\n{len(rows)} processos avaliados · {sum(1 for x in ranking if x['pontos'] >= 5)} "
          f"com achado forte (≥5 pts)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
