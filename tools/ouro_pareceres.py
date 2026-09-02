# -*- coding: utf-8 -*-
"""Conjunto-ouro com RÓTULO HUMANO REAL: o que o parecerista da PGE/CGE apontou nos autos.

Por que este módulo existe
--------------------------
Medido em 2026-08-02: o loop de autoaprimoramento rodou 36 vezes em um mês, testou 922
candidatos, manteve ZERO, com `f1_inicial == f1_final == 1.0` em todas as rodadas. O motivo é
estrutural — o conjunto-ouro são 8 casos SINTÉTICOS que o motor já acerta 100%. Sem margem, o
loop não pode aprender nada; e as 4.180 perícias gravadas têm `veredito_perito` nulo em 4.180,
ou seja, nunca houve rótulo humano.

Rótulo não se inventa. Mas existe um rótulo humano independente já dentro dos autos: as
**condicionantes do parecer jurídico**. O parecerista da PGE/PGM/CGE nomeia o que falta
("junte-se a pesquisa de preços", "comprove a dotação", "corrija a cláusula X"). É a opinião de
um jurista do próprio Estado, anterior e alheia ao JFN — verdade externa, não circular.

Como o rótulo é lido (e onde ele NÃO fala)
------------------------------------------
Para cada condicionante, `parecer_cumprimento` já resolve o status nos documentos POSTERIORES:

  NAO_CUMPRIDA    → POSITIVO: o jurista exigiu e os autos não comprovaram. A casa deveria acender.
  CUMPRIDA        → NEGATIVO: exigiu e os autos comprovaram. A casa NÃO deveria acender.
  NAO_VERIFICAVEL → INDISPONÍVEL: fica FORA da conta, nos dois lados.

E o silêncio do parecer sobre uma família **nunca** vira negativo: parecer que não fala de
garantia contratual não atesta que a garantia esteja regular. Sem essa regra o recall seria
falso — o número pareceria ótimo justamente onde não há informação.

Saída
-----
`data/ouro_pareceres.json` (bruto, resumível) + relatório md. Com `--promover`, os processos
rotulados viram casos-ouro reais em `data/nucleo_casos_ouro.json`, e o loop finalmente ganha
inclinação.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from compliance_agent import parecer_cumprimento as PC  # noqa: E402
from compliance_agent import processo_360 as P360  # noqa: E402
from compliance_agent.sei import manifesto_norm  # noqa: E402

ESTADO = RAIZ / "data" / "ouro_pareceres.json"

# Mapa achado-da-casa → família de condicionante. É EXPLÍCITO de propósito: um mapa oculto
# transformaria a medição em opinião. Cada padrão casa contra `diz`/`falta`/`codigo` do achado.
# O que não casar nenhum padrão é reportado em `--vocabulario` para o mapa crescer com prova.
_MAPA: tuple[tuple[str, str], ...] = (
    ("pesquisa_precos", r"pesquisa\s+de\s+pre[çc]|mapa\s+de\s+pre[çc]|cota[çc][õo]es|"
                        r"or[çc]amento\s+estimad|sobrepre[çc]o|pre[çc]o\s+(?:acima|incompat)"),
    ("dotacao_orcamentaria", r"dota[çc][ãa]o|or[çc]ament[áa]ri|reserva|empenho\s+(?:ausente|sem)"),
    ("regularidade_fiscal", r"certid[ãa]o|regularidade\s+fiscal|CND|SICAF|FGTS|INSS|"
                            r"sancionad|inid[ôo]ne|impedid"),
    ("garantia_contratual", r"garantia\s+contratual|seguro-?garantia|cau[çc][ãa]o"),
    ("designacao_fiscal", r"fiscal\s+do\s+contrato|gestor\s+do\s+contrato|designa[çc][ãa]o\s+de\s+fiscal|"
                          r"fiscaliza[çc][ãa]o\s+(?:ausente|sem)"),
    ("publicidade", r"publica[çc][ãa]o|di[áa]rio\s+oficial|PNCP|extrato|divulga[çc][ãa]o"),
    ("minuta_clausula", r"cl[áa]usula|minuta|contrato/ata\s+formalizad|"
                        r"contrato\s+ou\s+instrumento\s+equivalente|contrato\s+antes\s+do\s+parecer"),
    ("estudo_justificativa", r"justificativa|motiva[çc][ãa]o|estudo\s+t[ée]cnico|\bETP\b|"
                             r"termo\s+de\s+refer[êe]ncia|projeto\s+b[áa]sico|\bDFD\b|planejamento"),
    ("prazo_vigencia", r"vig[êe]ncia|prazo\s+contratual|cronograma|prorroga"),
)


def _familia_do_achado(a: dict) -> str | None:
    alvo = " ".join(str(a.get(k) or "") for k in ("diz", "falta", "codigo", "origem", "observacao"))
    for nome, pat in _MAPA:
        if re.search(pat, alvo, re.I):
            return nome
    return None


def _docs_com_texto(pasta: Path) -> list[dict]:
    """Documentos NA ORDEM, com o texto lido do disco (o manifesto guarda só o caminho)."""
    man = manifesto_norm.normalizar(
        {**json.loads((pasta / "manifest.json").read_text(encoding="utf-8")), "_pasta": str(pasta)})
    return [{"ref": d.get("titulo", ""), "tipo": d.get("tipo", ""),
             "texto": P360._texto_de(pasta, d)} for d in man["docs"]]


def rotular(pasta: Path) -> dict | None:
    """Rótulo humano do processo. None quando o parecer não fala (nada a medir)."""
    aud = PC.auditar_parecer_pge(_docs_com_texto(pasta))
    if aud["veredito"] in ("SEM_PARECER_LOCALIZADO", "SEM_CONDICIONANTES"):
        return None
    positivos: set[str] = set()
    negativos: set[str] = set()
    indisponiveis: set[str] = set()
    for c in aud["condicionantes"]:
        fam = c.get("tipo") or "outra"
        if fam == "outra":
            continue  # sem família nomeada não há o que confrontar — honesto deixar de fora
        {"NAO_CUMPRIDA": positivos, "CUMPRIDA": negativos,
         "NAO_VERIFICAVEL": indisponiveis}.get(c["status"], indisponiveis).add(fam)
    # um mesmo processo pode ter a família nos dois lados (itens diferentes): o positivo vence,
    # porque basta uma exigência descumprida para o vício existir.
    negativos -= positivos
    indisponiveis -= (positivos | negativos)
    if not (positivos or negativos):
        return None
    return {"veredito": aud["veredito"], "positivos": sorted(positivos),
            "negativos": sorted(negativos), "indisponiveis": sorted(indisponiveis),
            "pareceres": aud["pareceres"]}


# Achado da casa que aponta condicionante de parecer pendente SEM nomear a família. Ele responde
# a pergunta de PROCESSO ("sobrou exigência sem resposta?"), não a de família ("qual exigência?").
# Confundir as duas faria o relatório publicar "cobertura 0%" num caso em que a casa acertou o
# processo inteiro e só não etiquetou o tipo do vício — número enganoso é pior que número nenhum.
_RE_COND_GENERICA = re.compile(
    r"condiciona/?recomenda|condicionante.*(?:sem\s+resposta|n[ãa]o\s+atendid)|"
    r"parecer.*n[ãa]o\s+h[áa]\s+documento\s+posterior|ressalva\s+de\s+parecer", re.I)


def prever(pasta: Path) -> tuple[set[str], bool, list[dict]]:
    """O que os detectores da casa acendem: famílias nomeadas + sinal genérico de condicionante."""
    out = P360.avaliar_pasta(pasta)
    fams: set[str] = set()
    generico = False
    nao_mapeados: list[dict] = []
    for a in out.get("achados", []):
        alvo = " ".join(str(a.get(k) or "") for k in ("diz", "falta", "codigo", "observacao"))
        if _RE_COND_GENERICA.search(alvo):
            generico = True
        fam = _familia_do_achado(a)
        if fam:
            fams.add(fam)
        else:
            nao_mapeados.append({"origem": a.get("origem"), "diz": (a.get("diz") or "")[:90]})
    return fams, generico, nao_mapeados


def medir(linhas: list[dict]) -> dict:
    """Precisão/cobertura por família — só sobre o que o parecer efetivamente afirma."""
    fams = sorted({f for L in linhas for f in (L["positivos"] + L["negativos"])})
    por_familia = {}
    for f in fams:
        tp = sum(1 for L in linhas if f in L["positivos"] and f in L["previstos"])
        fn = sum(1 for L in linhas if f in L["positivos"] and f not in L["previstos"])
        fp = sum(1 for L in linhas if f in L["negativos"] and f in L["previstos"])
        tn = sum(1 for L in linhas if f in L["negativos"] and f not in L["previstos"])
        ind = sum(1 for L in linhas if f in L["indisponiveis"])
        prec = tp / (tp + fp) if (tp + fp) else None
        cob = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * prec * cob / (prec + cob)) if (prec and cob) else (0.0 if (tp + fn + fp) else None)
        por_familia[f] = {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "indisponivel": ind,
                          "precisao": prec, "cobertura": cob, "f1": f1}
    tp = sum(v["tp"] for v in por_familia.values())
    fn = sum(v["fn"] for v in por_familia.values())
    fp = sum(v["fp"] for v in por_familia.values())
    prec = tp / (tp + fp) if (tp + fp) else None
    cob = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * cob / (prec + cob)) if (prec and cob) else 0.0
    # Duas perguntas, dois placares. PROCESSO: "sobrou exigência do parecer sem resposta?" — a casa
    # tem achado próprio para isso. FAMÍLIA: "qual exigência?" — é o que ela ainda não nomeia.
    com_pos = [L for L in linhas if L["positivos"]]
    acertou_proc = sum(1 for L in com_pos if L.get("previstos") or L.get("generico"))
    return {"n_processos": len(linhas),
            "processo": {"com_vicio_apontado": len(com_pos), "detectados": acertou_proc,
                         "cobertura": (acertou_proc / len(com_pos)) if com_pos else None},
            "global": {"tp": tp, "fn": fn, "fp": fp,
                       "precisao": prec, "cobertura": cob, "f1": f1},
            "por_familia": por_familia}


def relatorio_md(m: dict, vocab: list[dict]) -> str:
    def pct(x):
        return "—" if x is None else f"{x:.0%}"
    L = ["# Conjunto-ouro por parecer jurídico — precisão real dos detectores", "",
         f"**{m['n_processos']} processos** com condicionante de parecer rotulada. O rótulo é do "
         "parecerista (PGE/PGM/CGE), não do JFN.", "",
         "| Família de vício (nomeada pelo jurista) | Acertos | Perdidos | Falsos alarmes | "
         "Precisão | Cobertura | F1 | INDISPONÍVEL |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for f, v in sorted(m["por_familia"].items(), key=lambda kv: -(kv[1]["tp"] + kv[1]["fn"])):
        L.append(f"| {f} | {v['tp']} | {v['fn']} | {v['fp']} | {pct(v['precisao'])} | "
                 f"{pct(v['cobertura'])} | {pct(v['f1'])} | {v['indisponivel']} |")
    g, pr = m["global"], m["processo"]
    L += ["", f"**Por família:** precisão {pct(g['precisao'])} · cobertura {pct(g['cobertura'])} · "
              f"F1 {pct(g['f1'])} (acertos {g['tp']} · perdidos {g['fn']} · falsos alarmes {g['fp']})",
          "", f"**Por processo** (a casa apontou que sobrou exigência sem resposta, mesmo sem nomear "
              f"a família): {pr['detectados']} de {pr['com_vicio_apontado']} — {pct(pr['cobertura'])}. "
              "Os dois placares medem perguntas diferentes: publicar só o de família faria a casa "
              "parecer cega num processo que ela de fato apontou.",
          "", "> Onde o parecer é silente, não há linha: silêncio do jurista não é atestado de "
              "regularidade. INDISPONÍVEL fica fora da conta, nos dois lados."]
    if vocab:
        L += ["", "## Achados da casa sem família mapeada (auditoria do mapa)", ""]
        vistos: dict[str, int] = {}
        for v in vocab:
            vistos[f"{v['origem']} — {v['diz']}"] = vistos.get(f"{v['origem']} — {v['diz']}", 0) + 1
        for k, n in sorted(vistos.items(), key=lambda kv: -kv[1])[:25]:
            L.append(f"- ({n}×) {k}")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=120, help="processos por sessão")
    ap.add_argument("--segundos", type=int, default=900, help="teto de tempo (VM 2 vCPU)")
    ap.add_argument("--vocabulario", action="store_true", help="lista achados sem família")
    ap.add_argument("--promover", action="store_true", help="grava os rotulados como casos-ouro")
    ap.add_argument("--saida", default="reports/ouro_pareceres.md")
    a = ap.parse_args()

    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    linhas: list[dict] = estado.get("linhas", [])
    feitos = {L["processo"] for L in linhas}
    vocab: list[dict] = []
    t0 = time.time()
    n = 0
    for man in sorted((RAIZ / "data" / "sei_arquivo").glob("*/manifest.json")):
        pasta = man.parent
        if pasta.name in feitos or n >= a.limite or (time.time() - t0) > a.segundos:
            if n >= a.limite or (time.time() - t0) > a.segundos:
                break
            continue
        try:
            rot = rotular(pasta)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"  ! rótulo falhou em {pasta.name}: {e}", file=sys.stderr)
            continue
        n += 1
        if not rot:
            feitos.add(pasta.name)
            continue
        try:
            previstos, generico, nm = prever(pasta)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"  ! detecção falhou em {pasta.name}: {e}", file=sys.stderr)
            continue
        vocab += nm
        linhas.append({"processo": pasta.name, **rot, "previstos": sorted(previstos),
                       "generico": generico})
        feitos.add(pasta.name)
        print(f"  · {pasta.name}: ouro+{len(rot['positivos'])}/-{len(rot['negativos'])} "
              f"prev={len(previstos)}", flush=True)

    ESTADO.write_text(json.dumps({"linhas": linhas}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    if not linhas:
        print("Nenhum processo com condicionante rotulável ainda.")
        return 0
    m = medir(linhas)
    saida = RAIZ / a.saida
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(relatorio_md(m, vocab if a.vocabulario else []), encoding="utf-8")
    print(json.dumps(m["global"], ensure_ascii=False))
    print(f"→ {saida}  ({m['n_processos']} processos rotulados)")
    if a.promover:
        print(f"promovidos: {promover(linhas)} casos-ouro")
    return 0


def promover(linhas: list[dict]) -> int:
    """Cada processo rotulado vira caso-ouro — a régua passa a medir o acervo real."""
    from compliance_agent.nucleo.avaliacao import CasoOuro, adicionar_caso_ouro
    n = 0
    for L in linhas:
        if not L["positivos"]:
            continue
        adicionar_caso_ouro(CasoOuro(
            id=f"ouro_parecer_{L['processo']}",
            descricao=(f"Condicionantes do parecer jurídico em {L['processo']} "
                       f"({L['veredito']}) — rótulo do parecerista, não do JFN"),
            dossie={"_fonte": "parecer_pge", "processo": L["processo"]},
            deve_disparar=L["positivos"], nao_pode_disparar=L["negativos"]))
        n += 1
    return n


if __name__ == "__main__":
    raise SystemExit(main())
