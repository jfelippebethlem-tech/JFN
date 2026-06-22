#!/usr/bin/env python3
"""pericia_aprendizado — LOOP DE INTELIGÊNCIA PROGRESSIVA da perícia do sweep SEI.

A cada run (fim do sweep, cron):
  (1) lê as PERÍCIAS recentes (`sei_ficha`) e agrega as DÚVIDAS que o modelo anotou (campo
      `duvidas`) + as LACUNAS recorrentes por tema (dado faltante);
  (2) SURFA os TÓPICOS para nós via `lex_feedback` → nota do vault que lemos no início de cada
      sessão ("a cada run avisa o que revisar"; duvidamos e tiramos nossa própria conclusão);
  (3) APRENDE: promove dúvidas/lacunas recorrentes a REGRAS DE MÉTODO (memoria categoria
      'metodo', chave 'pericia:*') — reforço por recorrência (sempre) + síntese de regra via
      Hermes (best-effort). O `tools/sei_ficha.py` REINJETA essas regras no prompt da próxima
      perícia, fechando o loop: dúvida recorrente → regra que a previne → aplicada na próxima.

Determinístico no núcleo (zero-LLM garantido); o passo de síntese de regra é best-effort.
NÃO é um loop que se re-aciona sozinho — o CRON repete (obediência > goal). VM-safe/bounded.

Uso: cd ~/JFN && PYTHONPATH=. .venv/bin/python -m tools.pericia_aprendizado [--max-proc N] [--limiar K] [--sem-llm]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "compliance.db"

# marcador de "dado faltante / lacuna" -> TEMA acionável (agrupa dúvidas dispersas em tópicos)
_TEMAS = [
    ("pagamento / execução financeira (OB)", r"pagament|ordem banc|\bob\b|empenho|liquida|execu[çc][aã]o financeira"),
    ("pesquisa de preços / planilha de custos", r"pesquisa de pre|planilha de custo|valor estimad|sobrepre|or[çc]ament"),
    ("parecer jurídico / habilitação / regularidade", r"parecer jur|habilita|regularidade fiscal|certid|cnd"),
    ("modalidade / fundamento legal", r"modalidade|fundamento|dispensa|inexigib|licita[çc]"),
    ("termo de referência / ETP / DFD", r"termo de refer|\betp\b|\bdfd\b|estudo t[ée]cnico|projeto b[áa]sico"),
    ("aditivo / reajuste / vigência", r"aditiv|reajust|repactua|vig[êe]ncia|prorrog"),
    ("entrega / execução do objeto / fiscalização", r"entrega|execu[çc][aã]o do objeto|fiscaliza|presta[çc][aã]o de contas|recebiment"),
]


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _coletar(max_proc: int) -> tuple[list[tuple[str, str]], list[tuple[str, str]], int]:
    """Lê perícias recentes; devolve (duvidas[(num,texto)], textos[(num,blob)], n_procs)."""
    con = _conn()
    try:
        rows = con.execute(
            """SELECT numero_sei, pericia_contabil, pericia_juridica, COALESCE(red_flags,'')
                 FROM sei_ficha
                WHERE (pericia_contabil IS NOT NULL AND pericia_contabil!='')
                   OR (pericia_juridica  IS NOT NULL AND pericia_juridica !='')
                ORDER BY atualizado_em DESC LIMIT ?""", (max_proc,)).fetchall()
    finally:
        con.close()
    duvidas: list[tuple[str, str]] = []
    textos: list[tuple[str, str]] = []
    for num, pc, pj, rf in rows:
        blob = [rf or ""]
        for raw in (pc, pj):
            try:
                o = json.loads(raw) if raw else {}
            except Exception:
                o = {}
            if isinstance(o, dict):
                for d in (o.get("duvidas") or []):
                    if isinstance(d, str) and d.strip():
                        duvidas.append((num, d.strip()))
                blob.append(json.dumps(o, ensure_ascii=False))
        textos.append((num, " ".join(blob)))
    return duvidas, textos, len(rows)


def _temas_recorrentes(textos: list[tuple[str, str]]) -> Counter:
    cnt: Counter = Counter()
    for _num, t in textos:
        tl = (t or "").lower()
        for nome, rx in _TEMAS:
            if re.search(rx, tl):
                cnt[nome] += 1
    return cnt


async def _sintetizar_regras(top_duvidas: list[tuple[str, int]], top_temas: list[tuple[str, int]]) -> int:
    """Best-effort: o Hermes vira perito-chefe e transforma as dúvidas/lacunas recorrentes em
    1-3 REGRAS DE MÉTODO acionáveis (memoria 'metodo','pericia:*'). Falha → 0 (núcleo já aprendeu)."""
    from compliance_agent.llm.hermes_agent import _hermes
    from compliance_agent.llm.memoria import aprender
    duv = "\n".join(f"- ({c}×) {d}" for d, c in top_duvidas) or "(nenhuma)"
    tem = "\n".join(f"- ({c}×) {t}" for t, c in top_temas) or "(nenhum)"
    system = (
        "Você é PERITO-CHEFE de controle externo (TCE-RJ) treinando um perito júnior que faz perícia "
        "contábil + jurídica de processos SEI-RJ em massa. Recebendo as DÚVIDAS e LACUNAS recorrentes "
        "dele, proponha de 1 a 3 REGRAS DE MÉTODO curtas, acionáveis e GERAIS que reduzam essas falhas "
        "nas próximas perícias (não sobre um processo específico). Honestidade obrigatória: indício ≠ "
        "acusação; INDISPONÍVEL ≠ 0; empenho ≠ liquidação ≠ OB (só a Ordem Bancária é pagamento); "
        "presunção de regularidade. Responda SOMENTE um JSON: "
        '{"regras":[{"chave":"slug-curto","regra":"regra acionável (1 frase)"}]}')
    prompt = f"DÚVIDAS RECORRENTES DO PERITO:\n{duv}\n\nLACUNAS POR TEMA:\n{tem}\n\nProduza as regras."
    raw = await _hermes(system, prompt, max_tokens=800)
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return 0
    n = 0
    for r in (json.loads(m.group(0)).get("regras") or [])[:3]:
        ch = re.sub(r"[^a-z0-9]+", "-", (r.get("chave") or "").lower()).strip("-")[:40] or "geral"
        rg = (r.get("regra") or "").strip()
        if rg:
            aprender("metodo", f"pericia:{ch}", rg, fonte="pericia_aprendizado_llm", delta_confianca=0.15)
            n += 1
    return n


def rodar(max_proc: int = 400, limiar: int = 3, top: int = 6, com_llm: bool = True) -> dict:
    duvidas, textos, n = _coletar(max_proc)
    if n == 0:
        print("[pericia_aprendizado] nenhuma perícia ainda — nada a aprender.")
        return {"pericias": 0}
    temas = _temas_recorrentes(textos)
    dnorm = Counter(re.sub(r"\s+", " ", d.lower())[:90] for _num, d in duvidas)
    top_temas = [(t, c) for t, c in temas.most_common(top) if c >= limiar]
    top_duvidas = [(d, c) for d, c in dnorm.most_common(top) if c >= max(2, limiar - 1)]

    # (2) SURFAR os tópicos p/ nós (lex_feedback → nota do vault)
    novos = 0
    try:
        from tools.lex_feedback import registrar, _regenerar_vault
        for tema, c in top_temas:
            msg = f"Perícia: tema '{tema}' aparece como lacuna/dúvida em {c} de {n} processos recentes."
            sug = "Avaliar wirar a fonte de dado desse tema na perícia (cruzar OB/contrato/NF/base) e calibrar o prompt."
            if registrar("jfn", "dificuldade", "perícia SEI (loop de aprendizado)", msg, sug):
                novos += 1
        for d, c in top_duvidas:
            if registrar("jfn", "dificuldade", "perícia SEI — dúvida recorrente do modelo", f"({c}×) {d}", ""):
                novos += 1
        try:
            _regenerar_vault()
        except Exception:
            pass
    except Exception as e:
        print("[pericia_aprendizado] lex_feedback indisponível:", str(e)[:80])

    # (3) APRENDER — reforço por recorrência (sempre, determinístico)
    regras = 0
    try:
        from compliance_agent.llm.memoria import aprender
        for tema, c in top_temas:
            slug = re.sub(r"[^a-z0-9]+", "-", tema.lower()).strip("-")[:40]
            regra = (f"PERÍCIA — lacuna recorrente em '{tema}' ({c} casos recentes): quando o trecho do SEI não "
                     "trouxer esse dado, declare INDISPONÍVEL (≠ 0), aponte a FONTE a cruzar e o que VERIFICAR; "
                     "nunca conclua por ausência (presunção de regularidade).")
            aprender("metodo", f"pericia:{slug}", regra, fonte="pericia_aprendizado", delta_confianca=0.1)
            regras += 1
    except Exception as e:
        print("[pericia_aprendizado] memoria (reforço) indisponível:", str(e)[:80])

    # síntese de regra via Hermes (best-effort)
    if com_llm and (top_duvidas or top_temas):
        try:
            regras += asyncio.run(_sintetizar_regras(top_duvidas, top_temas))
        except Exception as e:
            print("[pericia_aprendizado] síntese LLM pulada (best-effort):", str(e)[:80])

    # DIGEST do run (o "aviso a cada run")
    print(f"== PERÍCIA · aprendizado :: {n} perícias · {len(duvidas)} dúvidas · {novos} tópicos novos · {regras} regras ==")
    for t, c in top_temas:
        print(f"  tema   [{c:>3}×] {t}")
    for d, c in top_duvidas:
        print(f"  dúvida [{c:>3}×] {d[:100]}")
    return {"pericias": n, "duvidas": len(duvidas), "topicos_novos": novos, "regras": regras}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-proc", type=int, default=400)
    ap.add_argument("--limiar", type=int, default=3, help="mín. de ocorrências p/ virar tópico/regra")
    ap.add_argument("--sem-llm", action="store_true", help="só o núcleo determinístico (sem síntese Hermes)")
    a = ap.parse_args()
    rodar(a.max_proc, a.limiar, com_llm=not a.sem_llm)


if __name__ == "__main__":
    main()
