# -*- coding: utf-8 -*-
"""E10 · `e10.candidato_p4_siafe` — CANDIDATO ao P4 pela ótica do pagamento (SIAFE), nunca "fracionamento" (SOMBRA ⚖️).

Porta `tools/fracionamento_siafe_sweep.py` + a régua de `compliance_agent/fracionamento_siafe.triagem` (plano §4 item 5,
O5.3 fatia 2). O plano é explícito: fracionamento é o mesmo OBJETO em contratações distintas, na mesma UG e exercício
(art. 75, §1º) — e a série de OB por credor × UG NÃO lê objeto nem modalidade (o processo do SIAFE não casa com o
SEI). Por isso este detector **não emite fracionamento**: cada disparo é `candidato_p4(processos[])`, estado INCERTO,
com a lista dos processos que o P4 (`e10.p4_fracionamento_objeto`, por objeto) e a leitura dos autos podem resolver.

Régua (idêntica à da triagem, sem cópia das peneiras): OB "paga" pelo status (`_pago`), credor licitável (regex local
+ `eh_nao_fornecedor`), NL cujo empenho é sentença/DEA/indenização fora, 0 < valor < teto do exercício
(`limites_dispensa.limite_dispensa`), ≥ `MIN_OBS` OB **e** ≥ `MIN_OBS` processos distintos, soma > teto.
Elegibilidade (invariante 3): só OB com veredito 'E' na exigência `soma_art75` da E9 entram na série.

Contrato de persistência do sweep ("retirada escopada por exercício"): é o próprio contrato do E10 — a rodada
marca a geração, a origem `e10:<detector>:<escopo>:<chave>` é única e a geração anterior nunca é apagada.
"""
from __future__ import annotations

import sqlite3
import statistics
from collections import Counter
from decimal import Decimal
from functools import lru_cache

from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.entidades_gov import eh_nao_fornecedor
from compliance_agent.fracionamento_siafe import (_CREDOR_NAO_LICITAVEL, FAIXA_RENTE_AO_TETO, MIN_OBS, _data,
                                                  _nl_nao_contratacao, _pago, _prioridade)
from compliance_agent.limites_dispensa import ato_normativo, limite_dispensa
from compliance_agent.reporting.intel_base import reais

ID = "e10.candidato_p4_siafe"
UNIDADE = "ob_siafe"
VERSAO = "e10-cp4-1"
NATUREZA = "candidato_p4"
RESSALVA = ("Candidato ao P4, não achado: o SIAFE não traz o OBJETO nem a MODALIDADE da contratação e o processo do "
            "SIAFE não casa com o do SEI. Só o P4 (mesmo objeto em contratações distintas) decide; pagamento repetido "
            "ao mesmo credor é, na maioria, execução de contrato licitado ou ata de registro de preços.")

# ob-qualquer-status: a régua da triagem classifica a OB paga linha a linha (`_pago`, contado no resumo) e a E9
# (`soma_art75`) aplica o predicado canônico por item — a consulta lê o exercício inteiro de propósito
_SQL = ("SELECT ug_emitente, credor, nome_credor, data_emissao, valor, processo, numero_ob, status, {nl}, exercicio "
        "FROM ob_orcamentaria_siafe WHERE exercicio = ? {extra}")


@lru_cache(maxsize=None)
def _licitavel(nome: str) -> bool:
    return bool(nome) and not _CREDOR_NAO_LICITAVEL.search(nome) and not eh_nao_fornecedor(nome)


def _exercicios(con: sqlite3.Connection, exercicio: int | None) -> list[int]:
    if exercicio:
        return [int(exercicio)]
    # ob-qualquer-status: metadado (quais exercícios existem), não soma
    return [int(r[0]) for r in con.execute("SELECT DISTINCT exercicio FROM ob_orcamentaria_siafe "
                                           "WHERE exercicio IS NOT NULL ORDER BY 1")]


def _ler(con: sqlite3.Connection, ex: int, extra: str = "", par: tuple = ()) -> tuple[list[dict], Counter]:
    """Itens do exercício que passam nas peneiras da triagem (status, credor, natureza, faixa de valor) + contadores
    do que caiu em cada uma (o resumo declara o denominador)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    nl_col = "nl" if "nl" in cols else "NULL AS nl"
    teto = limite_dispensa(ex, "compras")
    nao_contr = _nl_nao_contratacao(con, ex)
    cont: Counter = Counter()
    itens = []
    for ug, credor, nome, dt, valor, proc, num, status, nl, exr in con.execute(
            _SQL.format(nl=nl_col, extra=extra), (ex, *par)):
        cont["obs_lidas"] += 1
        if not _pago(status):
            cont["obs_descartadas_status"] += 1
            continue
        nome = (nome or "").strip()
        if not _licitavel(nome):
            cont["obs_descartadas_credor"] += 1
            continue
        if (ug, nl) in nao_contr:
            cont["obs_descartadas_natureza"] += 1
            continue
        v = float(valor or 0)
        if v <= 0 or v >= teto:
            cont["obs_fora_da_faixa"] += 1
            continue
        cred = (credor or nome).strip()
        itens.append({"chave_e9": f"{ug}|{num}|{exr}", "grupo": f"{ex}|{ug}|{cred}", "exercicio": ex, "ug": ug,
                      "credor": cred, "nome_credor": nome, "data": _data(dt), "valor": v, "processo": proc,
                      "numero_ob": num, "teto": teto})
    return itens, cont


def carregar(con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
    itens, cont = [], Counter()
    for ex in _exercicios(con, exercicio):
        i, c = _ler(con, ex)
        itens += i
        cont.update(c)
    return Carga(itens=itens, contexto={**dict(cont), "exercicios": _exercicios(con, exercicio)})


def grupo_de(d: Disparo) -> str:
    return d.grupo


def carregar_grupo(con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
    ex, ug, cred = grupo.split("|", 2)
    itens, _ = _ler(con, int(ex), "AND ug_emitente = ?", (ug,))
    return Carga(itens=[c for c in itens if c["credor"] == cred])


def _fato(c: dict) -> Fato:
    return Fato(papel=Papel.SUPORTE, tipo="ob", fonte="ob_orcamentaria_siafe", referencia=str(c["numero_ob"]),
                valor=Decimal(str(round(c["valor"], 2))), descricao=f"OB da UG {c['ug']} no processo {c['processo']}",
                dados={"ug": c["ug"], "exercicio": c["exercicio"], "data": str(c["data"] or ""),
                       "processo": c["processo"], "veredito_e9": c.get("e9")})


def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
    grupos: dict[str, list[dict]] = {}
    for c in itens:
        if elegivel(c):
            grupos.setdefault(c["grupo"], []).append(c)
    out = []
    for grupo, obs in sorted(grupos.items()):
        if len(obs) < MIN_OBS:
            continue
        procs = sorted({str(o["processo"]) for o in obs if o["processo"]})
        if len(procs) < MIN_OBS:
            continue
        teto, ex, ug = obs[0]["teto"], obs[0]["exercicio"], obs[0]["ug"]
        soma = sum(o["valor"] for o in obs)
        if soma <= teto:
            continue
        rente = [o for o in obs if o["valor"] >= teto * FAIXA_RENTE_AO_TETO]
        datas = sorted(o["data"] for o in obs if o["data"])
        inter = [(b - a).days for a, b in zip(datas, datas[1:])]
        med = statistics.median(inter) if inter else None
        obs = sorted(obs, key=lambda o: (str(o["data"] or ""), str(o["numero_ob"])))
        prio = _prioridade(med, soma / teto, len(obs), len(rente) / len(obs))
        out.append(Disparo(
            chave=grupo, grupo=grupo, estado="INCERTO", motivo_estado=f"{NATUREZA}: sem objeto nem modalidade",
            observacao=(f"{NATUREZA}: {len(obs)} OB ({len(procs)} processos distintos) da UG {ug} ao credor "
                        f"{obs[0]['nome_credor']} em {ex}, cada uma abaixo do teto de dispensa ({reais(teto)}) e "
                        f"somando {reais(soma)} ({soma / teto:.1f}× o teto); {len(rente)} rente(s) ao teto. "
                        f"{RESSALVA}"),
            entradas={"grupo": grupo, "teto": teto, "obs": [{"ob": o["numero_ob"], "valor": round(o["valor"], 2),
                                                           "data": str(o["data"] or ""), "processo": o["processo"],
                                                           "e9": o.get("e9")} for o in obs]},
            valores={"natureza": NATUREZA, "processos": procs, "n_obs": len(obs), "n_processos": len(procs),
                     "soma": round(soma, 2), "limite_dispensa": teto, "razao_soma_limite": round(soma / teto, 2),
                     "intervalo_mediano_dias": med, "n_rente_ao_teto": len(rente), "prioridade": prio,
                     "primeira_ob": datas[0].isoformat() if datas else None,
                     "ultima_ob": datas[-1].isoformat() if datas else None,
                     "fundamento": f"art. 75, §1º · {ato_normativo(ex)}"},
            evidencias=[_fato(o) for o in obs[:50]]))
    return out


def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
    por = Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in itens)
    val = Counter()
    for c in itens:
        val[c.get("e9") or "?:SEM_LINHA_E9"] += c["valor"]
    indet = sum(n for k, n in por.items() if k.startswith("?"))
    return {"obs_na_faixa": len(itens), "por_veredito": dict(sorted(por.items())),
            "valor_por_veredito": {k: round(v, 2) for k, v in sorted(val.items())},
            "cobertura": round(1 - indet / len(itens), 4) if itens else None, "disparos": len(disparos),
            "natureza": NATUREZA, "soma_disparos": round(sum(d.valores["soma"] for d in disparos), 2)}
