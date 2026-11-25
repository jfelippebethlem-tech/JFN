# -*- coding: utf-8 -*-
"""Régua de confiabilidade por PAR tarefa × modelo × prompt_version × release_ia (plano mestre v2 §3.10, O6.6).

Um par só produz saída EXIBIDA COMO JULGADA se cumprir TUDO (§3.10, item 1):
  (a) 0 erro grave num ouro CONGELADO (`qualidade/ouro.congelar`: sha256 + manifesto) com n ≥ 125, estratificado por
      processo, órgão e período (amostra por sorteio, não pela fila de prioridade);
  (b) limite superior do IC95 de Wilson do erro grave ≤ 3% — com 0 grave, n = 125 é exatamente o primeiro n que passa
      (3,8415/(125+3,8415) = 2,98%; com 124 dá 3,005%): (a) e (b) são a mesma conta vista de dois lados;
  (c) sombra prospectiva de 14 dias OU n ≥ 30 casos novos, com 0 grave;
  (d) portões determinísticos aprovados: citação, número contra a fonte, schema estrito e abstenção.
Sem régua cumprida o rótulo é "NÃO JULGADO — proposta de <modelo>" (§3.10, item 3).

ESTADOS do par em `config/regras_novas.yaml` (dono, data, motivo, evidência — aprovado pelo dono EM LOTE):
  NAO_JULGADO   — padrão de todo par (registrado ou não);
  EM_SOMBRA     — (a), (b) e (d) cumpridos; a sombra prospectiva (c) corre;
  APROVADO_DONO — (a)–(d) cumpridos E o dono aprovou (campo `dono`); prompt_version e release_ia exatos (sem "*");
  REBAIXADO     — perdeu a régua (1º erro grave na amostra contínua do Opus, 1/8); volta a NAO_JULGADO por versão nova.
O validador RECALCULA os critérios a partir da evidência (o Wilson é refeito aqui, nunca lido do arquivo): um
APROVADO_DONO cuja evidência não fecha é erro de carga (`ErroRegua`), não um par aprovado.

CHECAGEM, NÃO ROTEAMENTO (O6.6): `checar()` só diz o RÓTULO exibido; ninguém muda de camada ou de modelo por causa
dela agora. Quem lê: gateway (`Resposta.extras["regua"]`), E11 (`periciar.release_ia`) e E12 (conferente Sonnet).

AVALIAÇÃO com os dados que JÁ existem (sem chamar LLM): `avaliar_pares()` (pura) e a CLI `avaliar`, que lê só leitura
o cruzamento (`data/cruzamento_motores.db`, gabarito = Opus) e a bancada do Sonnet (`--bancada`).

    python -m compliance_agent.qualidade.regua validar
    python -m compliance_agent.qualidade.regua checar pericia_integral claude-opus-5-5 pv2-1 '<release>'
    python -m compliance_agent.qualidade.regua avaliar [--cruzamento DB] [--bancada DIR] [--saida JSON]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
NAO_JULGADO, EM_SOMBRA, APROVADO_DONO, REBAIXADO = "NAO_JULGADO", "EM_SOMBRA", "APROVADO_DONO", "REBAIXADO"
ESTADOS = (NAO_JULGADO, EM_SOMBRA, APROVADO_DONO, REBAIXADO)
CORINGA = "*"
PORTOES = ("citacao", "numero_fonte", "schema_estrito", "abstencao")
ESTRATOS = ("processo", "orgao", "periodo")
# os números do §3.10 — o YAML os repete em `criterios` e o validador recusa divergência (mudar = mudar o plano)
OURO_N_MIN = 125
IC95_GRAVE_MAX = 0.03
SOMBRA_DIAS_MIN = 14
SOMBRA_N_MIN = 30
CRITERIOS = {"ouro_n_min": OURO_N_MIN, "ic95_grave_max": IC95_GRAVE_MAX, "sombra_dias_min": SOMBRA_DIAS_MIN,
             "sombra_n_min": SOMBRA_N_MIN}
DECISOES = ("pendente", "aprovada", "recusada")
_Z = 1.959964
_RE_PROC = re.compile(r"(\d{6})/(\d{3,6})/(\d{4})")


class ErroRegua(ValueError):
    """`config/regras_novas.yaml` inválido: campo faltando, estado desconhecido, aprovação sem evidência que feche."""


def caminho() -> Path:
    return Path(os.environ.get("JFN_REGRAS_NOVAS") or (_REPO / "config" / "regras_novas.yaml"))


def wilson_sup(graves: int, n: int, z: float = _Z) -> float | None:
    """Limite SUPERIOR do IC95 de Wilson da taxa de erro grave; None sem n."""
    if not n:
        return None
    p = graves / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return min(1.0, c + h)


def modelo_base(m: str | None) -> str:
    """'claude-haiku-5-5@api-lote#25cd…' → 'claude-haiku-5-5@api-lote' (o sufixo é o lote, não o modelo)."""
    return (m or "").split("#", 1)[0].strip()


def tarefa_base(t: str | None) -> str:
    return (t or "").split(":", 1)[0].strip()


# ── critérios (a)–(d), recalculados da evidência ───────────────────────────────────────────────────────────────
def criterios(evidencia: dict | None) -> dict:
    """{a, b, c, d: bool, falta: [..]} a partir da evidência do par. Nada vem pronto do arquivo: o Wilson é refeito."""
    ev = evidencia if isinstance(evidencia, dict) else {}
    ouro, sombra, portoes = ev.get("ouro") or {}, ev.get("sombra") or {}, ev.get("portoes") or {}
    falta = []
    n, g = ouro.get("n"), ouro.get("graves")
    ok_n = isinstance(n, int) and isinstance(g, int) and n >= OURO_N_MIN
    if not ok_n:
        falta.append(f"ouro n={n}<{OURO_N_MIN}" if isinstance(n, int) else "ouro sem n/graves")
    if not ouro.get("sha256"):
        falta.append("ouro não congelado (sem sha256 do manifesto)")
    if ok_n and g != 0:
        falta.append(f"ouro com {g} grave(s)")
    sem_estrato = [e for e in ESTRATOS if not (ouro.get("estratos") or {}).get(e)]
    if not ouro.get("estratificado") or sem_estrato:
        falta.append("ouro não estratificado" + (f" ({', '.join(sem_estrato)})" if sem_estrato else ""))
    a = ok_n and g == 0 and bool(ouro.get("sha256")) and bool(ouro.get("estratificado")) and not sem_estrato
    sup = wilson_sup(g, n) if isinstance(n, int) and isinstance(g, int) and n > 0 else None
    b = sup is not None and sup <= IC95_GRAVE_MAX
    if not b:
        falta.append("IC95 sup. indisponível" if sup is None else f"IC95 sup. {sup:.2%} > {IC95_GRAVE_MAX:.0%}")
    sd, sn, sg = sombra.get("dias"), sombra.get("n"), sombra.get("graves")
    c = isinstance(sg, int) and sg == 0 and ((isinstance(sd, int) and sd >= SOMBRA_DIAS_MIN)
                                              or (isinstance(sn, int) and sn >= SOMBRA_N_MIN))
    if not c:
        falta.append("sombra prospectiva incompleta" if not isinstance(sg, int) or sg == 0
                     else f"sombra com {sg} grave(s)")
    pend = [p for p in PORTOES if portoes.get(p) is not True]
    d = not pend
    if pend:
        falta.append("portões não aprovados: " + ", ".join(pend))
    return {"a": a, "b": b, "c": c, "d": d, "ic95_sup": None if sup is None else round(sup, 4), "falta": falta}


# ── carga e validação ──────────────────────────────────────────────────────────────────────────────────────────
def _data(v, onde: str) -> None:
    try:
        date.fromisoformat(str(v))
    except ValueError as e:
        raise ErroRegua(f"{onde}: data inválida {v!r}") from e


def validar(doc: dict) -> dict:
    """Valida o documento inteiro e devolve-o normalizado. Qualquer inconsistência ⇒ `ErroRegua` (nada pela metade)."""
    if not isinstance(doc, dict):
        raise ErroRegua("regras_novas: raiz não é um mapa")
    crit = doc.get("criterios") or {}
    dif = {k: (crit.get(k), v) for k, v in CRITERIOS.items() if crit.get(k) != v}
    if dif:
        raise ErroRegua(f"criterios divergem do §3.10 (arquivo, plano): {dif}")
    vistos: set[tuple] = set()
    pares = []
    for i, p in enumerate(doc.get("pares") or []):
        onde = f"pares[{i}]"
        if not isinstance(p, dict):
            raise ErroRegua(f"{onde}: não é um mapa")
        for k in ("id", "tarefa", "modelo", "prompt_version", "release_ia", "estado", "data", "motivo", "evidencia"):
            if p.get(k) in (None, "") and k != "evidencia":
                raise ErroRegua(f"{onde}: falta `{k}`")
        if "dono" not in p:
            raise ErroRegua(f"{onde}: falta `dono` (null enquanto o dono não decide)")
        if not isinstance(p.get("evidencia"), dict) or not p["evidencia"]:
            raise ErroRegua(f"{onde}: `evidencia` vazia")
        if p["estado"] not in ESTADOS:
            raise ErroRegua(f"{onde}: estado {p['estado']!r} fora de {ESTADOS}")
        _data(p["data"], onde)
        chave = (p["tarefa"], modelo_base(p["modelo"]), str(p["prompt_version"]), str(p["release_ia"]))
        if chave in vistos:
            raise ErroRegua(f"{onde}: par repetido {chave}")
        vistos.add(chave)
        cr = criterios(p["evidencia"])
        if p["estado"] in (APROVADO_DONO, REBAIXADO) and not p.get("dono"):
            raise ErroRegua(f"{onde} ({p['id']}): {p['estado']} exige `dono` (quem aprovou/rebaixou)")
        if p["estado"] == APROVADO_DONO:
            if CORINGA in (str(p["prompt_version"]), str(p["release_ia"])):
                raise ErroRegua(f"{onde} ({p['id']}): APROVADO_DONO exige prompt_version e release_ia exatos")
            if not all(cr[k] for k in "abcd"):
                raise ErroRegua(f"{onde} ({p['id']}): APROVADO_DONO sem a régua cumprida — {'; '.join(cr['falta'])}")
        if p["estado"] == EM_SOMBRA and not (cr["a"] and cr["b"] and cr["d"]):
            raise ErroRegua(f"{onde} ({p['id']}): EM_SOMBRA exige (a), (b) e (d) — {'; '.join(cr['falta'])}")
        pares.append(dict(p, modelo=modelo_base(p["modelo"]), _criterios=cr))
    ids = [p["id"] for p in pares]
    propostas = []
    for i, r in enumerate(doc.get("propostas") or []):
        onde = f"propostas[{i}]"
        for k in ("id", "titulo", "data", "motivo", "evidencia", "decisao"):
            if not r.get(k):
                raise ErroRegua(f"{onde}: falta `{k}`")
        if "dono" not in r:
            raise ErroRegua(f"{onde}: falta `dono`")
        if r["decisao"] not in DECISOES:
            raise ErroRegua(f"{onde}: decisao {r['decisao']!r} fora de {DECISOES}")
        if r["decisao"] != "pendente" and not r.get("dono"):
            raise ErroRegua(f"{onde} ({r['id']}): decisão {r['decisao']} sem `dono`")
        _data(r["data"], onde)
        ids.append(r["id"])
        propostas.append(r)
    rep = {x for x in ids if ids.count(x) > 1}
    if rep:
        raise ErroRegua(f"ids repetidos: {sorted(rep)}")
    return {**doc, "pares": pares, "propostas": propostas}


_CACHE: dict = {}


def carregar(arq: Path | None = None) -> dict:
    """Lê e valida (cache por mtime: mudou o YAML, vale na próxima leitura)."""
    arq = Path(arq or caminho())
    mt = arq.stat().st_mtime_ns
    if _CACHE.get("chave") != (str(arq), mt):
        doc = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        _CACHE.update(chave=(str(arq), mt), doc=validar(doc))
    return _CACHE["doc"]


# ── checagem (o rótulo exibido) ───────────────────────────────────────────────────────────────────────────────
def rotulo_nao_julgado(modelo: str | None) -> str:
    return f"NÃO JULGADO — proposta de {modelo_base(modelo) or 'modelo desconhecido'}"


def checar(tarefa: str, modelo: str | None, prompt_version: str | None, release_ia: str | None,
           arq: Path | None = None) -> dict:
    """Rótulo do par. Nunca levanta: régua ilegível ⇒ NÃO JULGADO com o motivo (falha-fechado)."""
    m = modelo_base(modelo)
    base = {"estado": NAO_JULGADO, "julgado": False, "rotulo": rotulo_nao_julgado(m), "par": None,
            "motivo": "par sem régua registrada em config/regras_novas.yaml (§3.10)"}
    try:
        doc = carregar(arq)
    except (OSError, yaml.YAMLError, ErroRegua) as e:
        return dict(base, motivo=f"régua ilegível ({type(e).__name__}: {str(e)[:160]}) — nada é julgado")
    t = tarefa_base(tarefa)
    cands = [p for p in doc["pares"] if p["tarefa"] in (tarefa, t) and p["modelo"] == m
             and str(p["prompt_version"]) in (str(prompt_version), CORINGA)
             and str(p["release_ia"]) in (str(release_ia), CORINGA)]
    if not cands:
        return base
    # o mais específico vence: exato em prompt e release > coringa
    p = max(cands, key=lambda x: (str(x["prompt_version"]) != CORINGA, str(x["release_ia"]) != CORINGA,
                                  x["tarefa"] == tarefa))
    exato = str(p["prompt_version"]) == str(prompt_version) and str(p["release_ia"]) == str(release_ia)
    julgado = p["estado"] == APROVADO_DONO and exato
    return {"estado": p["estado"] if (exato or p["estado"] != APROVADO_DONO) else NAO_JULGADO, "julgado": julgado,
            "rotulo": f"JULGADO — {m} (régua {p['id']})" if julgado else rotulo_nao_julgado(m), "par": p["id"],
            "motivo": p["motivo"] if julgado or p["estado"] != APROVADO_DONO else
                      "aprovação do dono é de outra prompt_version/release_ia",
            "falta": [] if julgado else p["_criterios"]["falta"]}


# ── avaliação com os dados existentes ─────────────────────────────────────────────────────────────────────────
def estratos_do_item(item: str | None) -> dict:
    """processo / órgão (prefixo de 6 dígitos do nº SEI) / período (ano) de um item `sei:<processo>`; None se não há."""
    mt = _RE_PROC.search(str(item or "")) if str(item or "").startswith("sei:") else None
    if not mt:
        return {"processo": None, "orgao": None, "periodo": None}
    return {"processo": f"{mt.group(1)}/{mt.group(2)}/{mt.group(3)}", "orgao": mt.group(1), "periodo": mt.group(3)}


def avaliar_pares(pares, estratificado_por_origem: dict | None = None) -> list[dict]:
    """`pares`: dicts {tarefa, modelo, item, nivel, nivel_ref}. Grave = |nível − nível de referência| ≥ 2 (🔴×⚪, a
    régua do cruzamento). A UNIDADE é o item (eixos do mesmo processo não são independentes): item grave = algum par
    grave. Devolve, por (tarefa, modelo), n, graves, Wilson, estratos e o que falta para (a)/(b)."""
    origem = estratificado_por_origem or {}
    g: dict = defaultdict(lambda: {"pares": 0, "graves_pares": 0, "itens": {}, "proc": set(), "org": set(),
                                   "per": set(), "sem_estrato": 0})
    for p in pares:
        if p.get("nivel") is None or p.get("nivel_ref") is None:
            continue
        k = (tarefa_base(p["tarefa"]), modelo_base(p["modelo"]))
        x = g[k]
        grave = abs(int(p["nivel"]) - int(p["nivel_ref"])) >= 2
        x["pares"] += 1
        x["graves_pares"] += grave
        it = str(p.get("item"))
        x["itens"][it] = x["itens"].get(it, False) or grave
        e = estratos_do_item(p.get("item"))
        if e["processo"]:
            x["proc"].add(e["processo"])
            x["org"].add(e["orgao"])
            x["per"].add(e["periodo"])
        else:
            x["sem_estrato"] += 1
    out = []
    for (t, m), x in sorted(g.items()):
        n, gv = len(x["itens"]), sum(x["itens"].values())
        sup = wilson_sup(gv, n)
        estr = bool(origem.get((t, m)))
        a_falta = []
        if n < OURO_N_MIN:
            a_falta.append(f"faltam {OURO_N_MIN - n} itens")
        if gv:
            a_falta.append(f"{gv} item(ns) grave(s) — este release não passa; só versão nova")
        if not estr:
            a_falta.append("origem por prioridade, não sorteio (não estratificada)")
        a_falta.append("ouro não congelado")
        out.append({"tarefa": t, "modelo": m, "pares": x["pares"], "graves_pares": x["graves_pares"], "n_itens": n,
                    "graves_itens": gv, "ic95_sup": None if sup is None else round(sup, 4),
                    "processos": len(x["proc"]), "orgaos": len(x["org"]), "periodos": sorted(x["per"]),
                    "pares_sem_estrato": x["sem_estrato"], "estratificado_por_origem": estr,
                    "cumpre_a": False, "cumpre_b": sup is not None and sup <= IC95_GRAVE_MAX,
                    "n_para_b_com_0_grave": OURO_N_MIN if gv == 0 else None, "falta_a": a_falta})
    return out


_SQL_OPUS = """
SELECT o.tarefa, o.modelo, o.item, o.nivel, c.nivel
FROM veredito c JOIN veredito o ON o.par = c.par AND o.motor = 'cascata'
WHERE c.motor = 'claude' AND c.modelo LIKE 'claude-opus%' AND o.tarefa NOT LIKE '%:%:%'
  AND o.modelo NOT LIKE '%opus%' AND o.modelo <> 'cascata'
"""
_SQL_SONNET = """
SELECT s.tarefa, s.modelo, s.item, s.nivel, o.nivel FROM veredito s JOIN veredito o ON o.tarefa = s.tarefa
  AND o.item = s.item WHERE s.modelo LIKE 'claude-sonnet%' AND o.modelo LIKE 'claude-opus%' AND s.item IS NOT NULL
  AND s.tarefa NOT LIKE '%:%:%'
"""


def pares_do_cruzamento(con: sqlite3.Connection) -> list[dict]:
    rows = list(con.execute(_SQL_OPUS)) + list(con.execute(_SQL_SONNET))
    return [{"tarefa": t, "modelo": m, "item": i, "nivel": n, "nivel_ref": r} for t, m, i, n, r in rows]


def pares_da_bancada(pasta: Path) -> list[dict]:
    """Bancada do Sonnet (23/11): um JSONL por tarefa com {item, sonnet: {tarefa: nível}, opus: {tarefa: nível}}."""
    out = []
    for arq in sorted(Path(pasta).glob("*.jsonl")):
        with arq.open(encoding="utf-8") as f:
            for ln in f:
                r = json.loads(ln)
                s, o = r.get("sonnet") or {}, r.get("opus") or {}
                out += [{"tarefa": k, "modelo": "claude-sonnet-5-5 (bancada 2026-11-23)", "item": r.get("item"),
                         "nivel": s.get(k), "nivel_ref": v} for k, v in o.items()]
    return out


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Régua de confiabilidade (§3.10)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validar")
    c = sub.add_parser("checar")
    for k in ("tarefa", "modelo", "prompt_version", "release_ia"):
        c.add_argument(k)
    a = sub.add_parser("avaliar", help="pares em uso com os dados existentes (só leitura, sem LLM)")
    a.add_argument("--cruzamento", default=str(_REPO / "data" / "cruzamento_motores.db"))
    a.add_argument("--bancada", help="pasta res/ da bancada do Sonnet")
    a.add_argument("--saida")
    x = ap.parse_args(argv)
    if x.cmd == "validar":
        d = carregar()
        print(f"ok: {len(d['pares'])} par(es), {len(d['propostas'])} proposta(s)")
        return 0
    if x.cmd == "checar":
        print(json.dumps(checar(x.tarefa, x.modelo, x.prompt_version, x.release_ia), ensure_ascii=False))
        return 0
    con = sqlite3.connect(f"file:{x.cruzamento}?mode=ro", uri=True, timeout=30)
    try:
        pares = pares_do_cruzamento(con)
    finally:
        con.close()
    origem = {}
    if x.bancada:
        pares += pares_da_bancada(Path(x.bancada))
        # só a perícia de execução da bancada foi SORTEADA (semente 20261123); as outras vêm de leituras já gravadas
        origem[("pericia_execucao", "claude-sonnet-5-5 (bancada 2026-11-23)")] = True
    res = avaliar_pares(pares, origem)
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    if x.saida:
        Path(x.saida).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
