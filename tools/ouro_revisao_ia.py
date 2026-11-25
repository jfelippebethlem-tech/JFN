# -*- coding: utf-8 -*-
"""ouro_revisao_ia — 2º revisor do OURO por IA independente (Opus da assinatura), NÃO humano (decisão delegada D6).

CONTEXTO (O5.4, ~/vault/refatoracao/o54-calibracao.md §4): os 71 itens reservados ao ouro têm UM rótulo (o 1º revisor:
o Opus da triagem — `alertas_triagem.leitura_opus` — ou o dono, na fachada). O Tier 1 pelo ouro exige 2 revisores
com kappa ≥ 0,60 E ao menos um HUMANO (`qualidade.ouro.estado_revisao_tier1`). Sem humano disponível, isto prepara
uma REVISÃO POR IA INDEPENDENTE, NÃO HUMANA:
  · CEGA ao 1º rótulo: o prompt leva só o texto do alerta (`triagem_alertas.texto_do_alerta`, CPF mascarado) — nunca a
    prioridade, a leitura do Opus, a justificativa, o estado nem a existência de outro revisor;
  · RUBRICA PRÓPRIA (não a da triagem): o detector acertou? `falso` | `verdadeiro` | `indeterminado`, com citação
    literal conferida por código (citação que não está no texto ⇒ `indeterminado`);
  · rótulo gravado com revisor `claude-opus-5-5 (revisão por IA independente, não humana)` — `ouro._humano` o lê como
    NÃO humano, então nada vira Tier 1 só com ele;
  · LIMITE HONESTO: quando o 1º rótulo também é do Opus, o kappa mede REPRODUTIBILIDADE do mesmo modelo com outro
    prompt, não concordância entre revisores independentes. O relatório separa os dois casos.

QUANDO: `rodar` só depois de sábado 28/11/2026 19:00 (-03:00), pela assinatura (`backend="cli"`, nunca a API).

    python -m tools.ouro_revisao_ia preparar --fonte <compliance.db ou extrato> --saida data/ouro_revisao_ia/lote.json
    python -m tools.ouro_revisao_ia rodar --lote data/ouro_revisao_ia/lote.json --executar     # depois de 28/11 19h
    python -m tools.ouro_revisao_ia kappa --lote data/ouro_revisao_ia/lote.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ABRE = datetime(2026, 11, 28, 19, 0, tzinfo=timezone(timedelta(hours=-3)))
TAREFA = "verificacao_opus"           # o orçamento diário do Opus de juízo já existente (`llm/orcamento`)
PROMPT_VERSION = "ouro-ia-1"
REVISOR = "claude-opus-5-5 (revisão por IA independente, não humana)"
ROTULO_RELATORIO = "REVISÃO POR IA INDEPENDENTE — NÃO HUMANA"
ROTULOS_IA = ("falso", "verdadeiro", "indeterminado")
SISTEMA = (
    "Você é revisor independente de controle externo (TCE-RJ). Recebe UM alerta automático de um detector do sistema "
    "JFN e decide se o detector ACERTOU. Regras: indício não é acusação; dado ausente é INDISPONÍVEL, não "
    "irregularidade; presunção de legitimidade; nunca invente fato fora do texto. Responda SÓ o JSON pedido.")
INSTRUCAO = (
    "\n\nDecida:\n  · \"falso\" — FALSO POSITIVO: o próprio texto mostra que o fato não é o que o detector diz (regra "
    "mal aplicada, dado que explica o caso, situação normal);\n  · \"verdadeiro\" — o indício procede como descrito "
    "(merece o acompanhamento que o detector propõe);\n  · \"indeterminado\" — o texto não basta para decidir.\n"
    "Responda em JSON: {\"rotulo\": \"falso|verdadeiro|indeterminado\", \"citacao\": \"trecho LITERAL do alerta em "
    "que se apoia\", \"justificativa\": \"até 3 frases\"}")
_REPO = Path(__file__).resolve().parents[1]


def _rotulo_1(falso) -> str | None:
    return None if falso is None else ("falso" if falso else "verdadeiro")


def preparar(fonte: str) -> dict:
    """Os itens reservados ao ouro com o 1º rótulo (fora do prompt) e o prompt CEGO de cada um."""
    from compliance_agent.aplicacao.estagios import calibrar as CAL
    from compliance_agent.triagem_alertas import texto_do_alerta
    conferidos, fora = CAL.ler_conferidos(fonte)
    reservados = [c for c in CAL.marcar_ouro(conferidos) if c["_ouro"]]
    con = sqlite3.connect(f"file:{fonte}?mode=ro", uri=True, timeout=30)
    itens, sem_texto = [], []
    try:
        for c in sorted(reservados, key=lambda x: (str(x["detector"]), str(x["item"]))):
            base = {"detector": c["detector"], "item": c["item"], "rotulo_1": _rotulo_1(c.get("falso")),
                    "revisor_1": c.get("revisor"), "bloco": c.get("bloco"), "processo": c.get("processo"),
                    "orgao": c.get("orgao"), "periodo": c.get("periodo"),
                    "entidade_hash": hashlib.sha1(str(c["entidade"]).encode()).hexdigest()[:12]
                    if c.get("entidade") else None}
            if not str(c["item"]).startswith("alerta:"):
                sem_texto.append({**base, "motivo": "sem texto cego do item (só alerta tem texto) — INDISPONÍVEL"})
                continue
            r = con.execute("SELECT id, tipo, severidade, titulo, descricao, evidencias FROM alertas WHERE id=?",
                            (int(c["item"].split(":", 1)[1]),)).fetchone()
            if r is None:
                sem_texto.append({**base, "motivo": "alerta ausente da fonte — INDISPONÍVEL"})
                continue
            texto = texto_do_alerta(dict(zip(("id", "tipo", "severidade", "titulo", "descricao", "evidencias"), r)))
            itens.append({**base, "texto": texto, "prompt_sha": hashlib.sha256(texto.encode()).hexdigest()})
    finally:
        con.close()
    return {"preparado_em": datetime.now().isoformat(timespec="seconds"), "fonte": str(fonte), "rotulo": ROTULO_RELATORIO,
            "prompt_version": PROMPT_VERSION, "reservados": len(reservados), "itens": itens, "sem_texto": sem_texto,
            "fora": fora}


def interpretar(texto: str, fonte: str) -> dict:
    """Rótulo validado: fora do formato ou citação que não confere no texto ⇒ `indeterminado` (com o porquê)."""
    from compliance_agent.llm.json_resposta import parse_json_llm
    from compliance_agent.llm.verificacao import citacao_existe
    d = parse_json_llm(texto or "")
    if not isinstance(d, dict) or d.get("rotulo") not in ROTULOS_IA:
        return {"rotulo": "indeterminado", "motivo": "resposta fora do formato"}
    if d["rotulo"] != "indeterminado" and not citacao_existe(str(d.get("citacao") or ""), fonte):
        return {"rotulo": "indeterminado", "motivo": "citação não confere no texto do alerta",
                "rotulo_dito": d["rotulo"]}
    return {"rotulo": d["rotulo"], "citacao": str(d.get("citacao") or "")[:400],
            "justificativa": str(d.get("justificativa") or "")[:600]}


def precondicoes(agora: datetime | None = None, nivel=None) -> list[str]:
    from compliance_agent.llm import ritmo_assinatura as R
    agora = agora or datetime.now(timezone.utc)
    out = []
    if agora < ABRE:
        out.append(f"antes de {ABRE.isoformat()} (assinatura contida até a virada da semana)")
    n = (nivel or R.nivel)()
    if n.get("medido") and n.get("nivel") == "contido":
        out.append(f"ritmo da assinatura contido: {n.get('motivo')}")
    return out


def rodar(lote: dict, *, pensar=None, ja: dict | None = None) -> dict:
    """Uma leitura cega por item pela ASSINATURA. `ja` = respostas de uma rodada anterior (retoma sem repetir)."""
    from compliance_agent.llm import claude_motor as CM
    pensar = pensar or CM.pensar
    resp = dict(ja or {})
    for it in lote["itens"]:
        if it["item"] in resp:
            continue
        p = pensar(TAREFA, it["texto"] + INSTRUCAO, modelo=CM.MODELO_JUIZO, sistema=SISTEMA, backend="cli",
                   timeout=300.0, espera=420.0)
        if p is None:
            resp["_parou"] = f"assinatura sem resposta: {CM.ultimo_motivo}"
            break
        resp[it["item"]] = {**interpretar(p.texto, it["texto"]), "modelo": p.modelo, "em": datetime.now().isoformat(
            timespec="seconds"), "prompt_version": PROMPT_VERSION}
    return resp


def kappa(lote: dict, respostas: dict) -> dict:
    """Kappa de Cohen entre o 1º rótulo e o da IA, nos itens que os DOIS decidiram (indeterminado fica fora, contado).
    Separado por quem foi o 1º revisor: Opus (reprodutibilidade do mesmo modelo) × humano (concordância IA × humano)."""
    from compliance_agent.qualidade.ouro import _humano, kappa_cohen

    def bloco(sub):
        pares = [(i["rotulo_1"], respostas[i["item"]]["rotulo"]) for i in sub
                 if i["item"] in respostas and i["rotulo_1"] in ("falso", "verdadeiro")
                 and respostas[i["item"]]["rotulo"] in ("falso", "verdadeiro")]
        a, b = [x for x, _ in pares], [y for _, y in pares]
        matriz = {f"{x}|{y}": sum(1 for p in pares if p == (x, y)) for x in ("falso", "verdadeiro")
                  for y in ("falso", "verdadeiro")}
        return {"itens": len(sub), "respondidos": sum(1 for i in sub if i["item"] in respostas),
                "indeterminados_ia": sum(1 for i in sub if respostas.get(i["item"], {}).get("rotulo") == "indeterminado"),
                "pareados": len(pares), "concordancia": round(sum(x == y for x, y in pares) / len(pares), 4)
                if pares else None, "kappa": kappa_cohen(a, b), "matriz_1o_x_ia": matriz}
    itens = lote["itens"]
    por_rev = {"1o_revisor_ia (reprodutibilidade, não independência)": [i for i in itens if not _humano(i["revisor_1"])],
               "1o_revisor_humano (IA × humano)": [i for i in itens if _humano(i["revisor_1"])]}
    return {"rotulo": ROTULO_RELATORIO, "revisor_2": REVISOR, "prompt_version": PROMPT_VERSION,
            "geral": bloco(itens), "por_1o_revisor": {k: bloco(v) for k, v in por_rev.items()},
            "sem_texto": len(lote.get("sem_texto") or []),
            "aviso": "Não satisfaz o 2º revisor HUMANO do Tier 1 (qualidade.ouro.estado_revisao_tier1 exige humano)."}


def rotulos_ia(lote: dict, respostas: dict, rotulado_em: str) -> list:
    """`ouro.Rotulo` do revisor IA (só os decididos) — para congelar À PARTE, com o rótulo de não humano."""
    from compliance_agent.qualidade.ouro import Rotulo
    date.fromisoformat(rotulado_em)
    return [Rotulo(detector=str(i["detector"]), item=i["item"], rotulo=respostas[i["item"]]["rotulo"], revisor=REVISOR,
                   rotulado_em=rotulado_em, processo=i.get("processo"), entidade_hash=i.get("entidade_hash"),
                   orgao=i.get("orgao"), periodo=i.get("periodo"))
            for i in lote["itens"] if respostas.get(i["item"], {}).get("rotulo") in ("falso", "verdadeiro")]


def _gravar(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(p, 0o600)                 # texto de alerta (CPF mascarado, mas nomes e valores seguem)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=f"2º revisor do ouro — {ROTULO_RELATORIO}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("--fonte", required=True)
    p.add_argument("--saida", default=str(_REPO / "data" / "ouro_revisao_ia" / "lote.json"))
    r = sub.add_parser("rodar")
    r.add_argument("--lote", required=True)
    r.add_argument("--executar", action="store_true", help="sem isto, só diz o que faria")
    k = sub.add_parser("kappa")
    k.add_argument("--lote", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "preparar":
        lote = preparar(a.fonte)
        _gravar(Path(a.saida), lote)
        print(f"{len(lote['itens'])} item(ns) com prompt cego de {lote['reservados']} reservados ao ouro; "
              f"{len(lote['sem_texto'])} sem texto (INDISPONÍVEL). Lote: {a.saida}")
        return 0
    lote = json.loads(Path(a.lote).read_text(encoding="utf-8"))
    arq_resp = Path(a.lote).with_name("respostas.json")
    resp = json.loads(arq_resp.read_text(encoding="utf-8")) if arq_resp.exists() else {}
    if a.cmd == "rodar":
        if not a.executar:
            print(f"rodaria {sum(1 for i in lote['itens'] if i['item'] not in resp)} leitura(s) cega(s) pelo Opus da "
                  f"assinatura; pré-condições: {precondicoes() or 'OK'}")
            return 0
        barrado = precondicoes()
        if barrado:
            print("NÃO roda: " + " | ".join(barrado), file=sys.stderr)
            return 2
        resp = rodar(lote, ja=resp)
        _gravar(arq_resp, resp)
        print(f"{sum(1 for k_ in resp if not k_.startswith('_'))} resposta(s); {resp.get('_parou') or 'completo'}")
        return 0
    rel = kappa(lote, resp)
    _gravar(Path(a.lote).with_name("kappa.json"), rel)
    print(json.dumps(rel, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
