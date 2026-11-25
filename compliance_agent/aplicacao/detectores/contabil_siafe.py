# -*- coding: utf-8 -*-
"""E10 · testes contábeis contra o próprio SIAFE (SOMBRA ⚖️) — portados de `compliance_agent/lex_fatos.py`.

Até aqui os dois testes só existiam dentro do parecer do Lex (`execucao` + `achados_contabeis`), rodando por ALVO
(um fornecedor por vez). Viram detectores genéricos do E10 sobre o universo das OB do SIAFE (plano §16.3; registro
`a_portar.lex_fatos.c_pago_maior_que_nl` e `…c_ob_antes_da_nl`):

  e10.ob_paga_acima_liquidado  a soma das OB PAGAS que citam a mesma NL supera o valor liquidado nela (NL
                               contabilizada; folga de R$ 0,02 de arredondamento)
  e10.ob_antes_da_liquidacao   OB PAGA emitida em data anterior à da NL que ela cita

Régua do pago (invariante 1): `dominio.pagamento.ob_paga_sql` (= `cruzamentos_intel._ob_paga`): OB contabilizada,
não devolvida, não complementar, não reemitida, com número; e valor > 0 (a regularização de valor zero não é
pagamento). OB anulada/cancelada nunca entra.

Honestidade (INDISPONÍVEL ≠ AUSENTE ≠ 0): a coleta de NL do SIAFE é PARCIAL (por fatia de tela; ~4% das OB chegam
à NL). OB sem NL citada ou com NL fora da base NÃO é avaliada — é contada, com R$, no resumo como INDISPONÍVEL; nunca
"sem achado". A NL e a OB têm de ser do MESMO credor (raiz do CNPJ ou documento inteiro): par de credores
diferentes é identidade não resolvida (INCERTO, contado), não indício — no Lex o par nem se formava, porque ele lia
OB e NL filtradas pelo mesmo credor.

Elegibilidade (invariante 3): exigência `valor_liquido` (C-PAGO>NL — a OB com GD sem valor apurado é
`?:DEVOLUCAO_NAO_APURADA`; a apurada entra pelo líquido) e `execucao` (C-OB<NL) da E9 sobre `ob_siafe`. A NL só é avaliada se TODAS as OB pagas
que a citam são 'E' (uma 'I' torna a NL inelegível; uma '?' a deixa indeterminada); o C-OB<NL olha a OB elegível.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.dominio.pagamento import ob_paga_sql
from compliance_agent.reporting.intel_base import reais
from compliance_agent.siafe_gd import devolvido_por_ob

UNIDADE = "ob_siafe"
FOLGA = 0.02                       # arredondamento de centavos entre OB e NL (a mesma do lex_fatos)


def _data(s) -> date | None:
    s = str(s or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _doc(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _ident(bruto) -> str | None:
    """Identidade do credor para casar OB × NL: raiz do CNPJ (matriz e filiais) ou o documento inteiro. Inscrição
    genérica do SIAFE (CG/PP/RP…: "diversos beneficiários", lista de credores) não identifica ninguém → None (medido
    na paridade de 24/11: CG0007060 "DIV.BENEFIC.FES/RJ" casava 135–321 OB de pessoas distintas com uma NL)."""
    b = str(bruto or "").strip()
    doc = _doc(b)
    if not doc or re.search(r"[A-Za-z]", b):
        return None
    return doc[:8] if len(doc) == 14 else doc


def _nl_idx(con, where: str = "", par: tuple = ()) -> tuple[dict, int]:
    idx, dup = {}, 0
    for num, ug, st, valor, dt, credor in con.execute(
            f"SELECT numero, ug_emitente, status, valor, data_emissao, credor FROM nl_siafe {where}", par):
        k = (num, str(ug))
        dup += k in idx
        idx[k] = {"status": st or "", "valor": float(valor or 0), "data": _data(dt), "credor": _ident(credor),
                  "doc": _doc(credor) if _ident(credor) else ""}
    return idx, dup


def _item(numero, ug, ex, dt, nl, credor, valor, n, dev: dict | None = None) -> dict:
    doc = _doc(credor)
    return {"chave_e9": f"{ug}|{numero}|{ex}", "grupo": f"{nl}|{ug}", "numero_ob": numero, "ug": str(ug),
            "exercicio": ex, "data": _data(dt), "nl": nl, "valor": round(float(valor or 0), 2),
            # devolução APURADA (guia na gd_siafe): o líquido abate; a não apurada a E9 já deixou '?' (decisão 1)
            "devolvido": (dev or {}).get((str(numero or "").strip(), str(ug).strip())),
            "mesmo_credor": _ident(credor) is not None and _ident(credor) == n["credor"],
            "credor_raiz": doc[:8] if len(doc) == 14 else None,
            "credor_doc": doc if _ident(credor) else "", "nl_credor_doc": n.get("doc", ""),
            "nl_status": n["status"], "nl_valor": n["valor"], "nl_data": n["data"]}


_COLS_OB = "numero_ob, ug_emitente, exercicio, data_emissao, nl, credor, valor"


def carregar(con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
    nls, dup = _nl_idx(con)
    dev = devolvido_por_ob(con)
    filtro, par = ("AND exercicio = ?", (exercicio,)) if exercicio else ("", ())
    itens, sem_nl, fora = [], [0, 0.0], [0, 0.0]
    n_pagas, v_pagas = 0, 0.0
    for numero, ug, ex, dt, nl, credor, valor in con.execute(
            f"SELECT {_COLS_OB} FROM ob_orcamentaria_siafe WHERE {ob_paga_sql(con)} AND valor > 0 {filtro}", par):
        n_pagas, v_pagas = n_pagas + 1, v_pagas + float(valor or 0)
        n = nls.get((nl, str(ug))) if nl else None
        if n is None:
            alvo = fora if nl else sem_nl
            alvo[0], alvo[1] = alvo[0] + 1, alvo[1] + float(valor or 0)
            continue
        itens.append(_item(numero, ug, ex, dt, nl, credor, valor, n, dev))
    return Carga(itens=itens, contexto={
        "ob_pagas": n_pagas, "ob_pagas_valor": round(v_pagas, 2), "nl_na_base": len(nls), "nl_chave_repetida": dup,
        "ob_sem_nl_citada": sem_nl[0], "ob_sem_nl_citada_valor": round(sem_nl[1], 2),
        "ob_nl_fora_da_base": fora[0], "ob_nl_fora_da_base_valor": round(fora[1], 2)})


def grupo_de(d: Disparo) -> str:
    return d.grupo


def carregar_grupo(con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
    nl, _, ug = grupo.rpartition("|")
    nls, _ = _nl_idx(con, "WHERE numero = ? AND ug_emitente = ?", (nl, ug))
    n = nls.get((nl, ug))
    if n is None:
        return Carga(itens=[])
    filtro, par = ("AND exercicio = ?", (exercicio,)) if exercicio else ("", ())
    rows = con.execute(f"SELECT {_COLS_OB} FROM ob_orcamentaria_siafe WHERE {ob_paga_sql(con)} AND valor > 0 "
                       f"AND nl = ? AND ug_emitente = ? {filtro}", (nl, ug, *par)).fetchall()
    dev = devolvido_por_ob(con)
    return Carga(itens=[_item(*r, n, dev) for r in rows])


_ORDEM_IDENTIDADE = ("forte", "parcial", "probabilistico", "homonimo", "indeterminado", "divergente")


def _reg(doc: str) -> dict:
    return {"cnpj": doc} if len(doc) == 14 else {"cpf": doc} if len(doc) == 11 else {}


def identidade(obs: list[dict]) -> str:
    """Nível de identidade (`dominio.identidade.resolver`) entre o credor da OB e o da NL, o MAIS FRACO entre as OB
    do disparo. Mesmo documento completo com DV válido = forte; matriz × filial (mesma raiz, sem nome para conferir)
    = indeterminado — casa para o detector (mesma pessoa jurídica), mas não sustenta grave (O4.8)."""
    from compliance_agent.dominio.identidade import resolver
    niveis = [resolver(_reg(c.get("credor_doc") or ""), _reg(c.get("nl_credor_doc") or "")).match_level for c in obs]
    return max(niveis, key=_ORDEM_IDENTIDADE.index) if niveis else "indeterminado"


def _fato_ob(c: dict, papel: Papel = Papel.SUPORTE) -> Fato:
    return Fato(papel=papel, tipo="ob", fonte="ob_orcamentaria_siafe", referencia=c["numero_ob"],
                valor=Decimal(str(c["valor"])), descricao=f"OB paga da UG {c['ug']} que cita a NL {c['nl']}",
                dados={"ug": c["ug"], "exercicio": c["exercicio"], "data": str(c["data"] or ""), "nl": c["nl"],
                       "veredito_e9": c.get("e9")})


def _fato_nl(c: dict) -> Fato:
    return Fato(papel=Papel.SUPORTE, tipo="nl", fonte="nl_siafe", referencia=c["nl"],
                valor=Decimal(str(round(c["nl_valor"], 2))), descricao=f"nota de liquidação da UG {c['ug']}",
                dados={"ug": c["ug"], "status": c["nl_status"], "data": str(c["nl_data"] or "")})


def _entrada_ob(c: dict) -> dict:
    return {"ob": c["numero_ob"], "ug": c["ug"], "exercicio": c["exercicio"], "data": str(c["data"] or ""),
            "valor": c["valor"], "credor_raiz": c["credor_raiz"], "mesmo_credor": c["mesmo_credor"], "e9": c.get("e9")} \
        | ({"devolvido": c["devolvido"]} if c.get("devolvido") is not None else {})


def liquido(c: dict) -> float:
    """Valor líquido da OB: o valor menos a devolução APURADA (`gd_siafe`); sem guia, o valor cheio."""
    return round(c["valor"] - float(c.get("devolvido") or 0), 2)


def _por_nl(itens: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    for c in itens:
        g.setdefault(c["grupo"], []).append(c)
    return g


def situacao_nl(obs: list[dict]) -> str:
    """'E' (todas as OB pagas da NL elegíveis), 'I' (alguma inelegível) ou '?' (alguma indeterminada)."""
    vs = [c.get("e9") or "?" for c in obs]
    if any(v.startswith("I") for v in vs):
        return "I"
    return "E" if all(v == "E" for v in vs) else "?"


@dataclass(frozen=True)
class _PagoAcima:
    ID: str = "e10.ob_paga_acima_liquidado"
    UNIDADE: str = UNIDADE
    VERSAO: str = "e10-cpago-3"     # 3: identidade do credor OB × NL (O4.8); 2: exigência `valor_liquido` + devolução apurada abatida (decisão do dono 1)

    carregar = staticmethod(carregar)
    carregar_grupo = staticmethod(carregar_grupo)
    grupo_de = staticmethod(grupo_de)

    @staticmethod
    def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
        out = []
        for grupo, obs in sorted(_por_nl(itens).items()):
            n0 = obs[0]
            if n0["nl_status"] != "Contabilizado" or situacao_nl(obs) != "E":
                continue
            if not all(c["mesmo_credor"] for c in obs):
                continue                                   # identidade não resolvida: INCERTO no resumo
            pago = round(sum(liquido(c) for c in obs), 2)
            if pago <= n0["nl_valor"] + FOLGA:
                continue
            obs = sorted(obs, key=lambda c: (str(c["data"] or ""), c["numero_ob"]))
            exc = round(pago - n0["nl_valor"], 2)
            out.append(Disparo(
                chave=grupo, grupo=grupo, estado="INDICIO",
                observacao=(f"A soma das {len(obs)} OB pagas que citam a NL {n0['nl']} da UG {n0['ug']} é "
                            f"{reais(pago)}, acima do valor liquidado de {reais(n0['nl_valor'])} (excedente de "
                            f"{reais(exc)}). Fonte: ob_orcamentaria_siafe × nl_siafe."),
                entradas={"nl": n0["nl"], "ug": n0["ug"], "nl_status": n0["nl_status"], "nl_valor": n0["nl_valor"],
                          "obs": [_entrada_ob(c) for c in obs]},
                valores={"pago": pago, "liquidado": n0["nl_valor"], "excedente": exc, "n_ob": len(obs)},
                processo=None, evidencias=[_fato_nl(n0)] + [_fato_ob(c) for c in obs], identidade=identidade(obs)))
        return out

    @staticmethod
    def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
        return _resumo(itens, disparos, "excedente")


@dataclass(frozen=True)
class _ObAntes:
    ID: str = "e10.ob_antes_da_liquidacao"
    UNIDADE: str = UNIDADE
    VERSAO: str = "e10-cob-2"       # 2: identidade do credor OB × NL (O4.8)

    carregar = staticmethod(carregar)
    carregar_grupo = staticmethod(carregar_grupo)
    grupo_de = staticmethod(grupo_de)

    @staticmethod
    def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
        out = []
        for c in sorted(itens, key=lambda c: c["chave_e9"]):
            if not elegivel(c) or not c["mesmo_credor"]:
                continue
            if not (c["data"] and c["nl_data"] and c["data"] < c["nl_data"]):
                continue
            dias = (c["nl_data"] - c["data"]).days
            out.append(Disparo(
                chave=c["chave_e9"], grupo=c["grupo"], estado="INDICIO",
                observacao=(f"A OB {c['numero_ob']} da UG {c['ug']}, de {c['data']:%d/%m/%Y} ({reais(c['valor'])}), "
                            f"foi emitida {dias} dia(s) ANTES da NL {c['nl']} que ela cita, de "
                            f"{c['nl_data']:%d/%m/%Y}. Fonte: ob_orcamentaria_siafe × nl_siafe."),
                entradas={**_entrada_ob(c), "nl": c["nl"], "nl_data": str(c["nl_data"]), "nl_status": c["nl_status"]},
                valores={"dias_antes": dias, "valor": c["valor"]},
                evidencias=[_fato_ob(c), _fato_nl(c)], identidade=identidade([c])))
        return out

    @staticmethod
    def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
        return _resumo(itens, disparos, "valor")


def _resumo(itens: list[dict], disparos: list[Disparo], campo: str) -> dict:
    por = Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in itens)
    sit = Counter(situacao_nl(obs) for obs in _por_nl(itens).values())
    return {"ob_com_nl_na_base": len(itens), "ob_com_nl_na_base_valor": round(sum(c["valor"] for c in itens), 2),
            "ob_credor_diferente_da_nl": sum(1 for c in itens if not c["mesmo_credor"]),
            "por_veredito": dict(sorted(por.items())), "nl_elegiveis": sit["E"], "nl_inelegiveis": sit["I"],
            "nl_indeterminadas": sit["?"], "disparos": len(disparos),
            "soma_disparos": round(sum(float(d.valores[campo]) for d in disparos), 2)}


PAGO_ACIMA = _PagoAcima()
OB_ANTES = _ObAntes()
