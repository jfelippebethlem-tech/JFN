# -*- coding: utf-8 -*-
"""Reserva técnica (percentual de sobra de MATERIAL) aplicada a locais, pessoas, horas ou transporte — paga-se
quantidade maior do que a executada.

ORIGEM (perícia por agente, 18/11/2026): SEEDUC × Fundação Cesgranrio, SEI-030001/047970/2026. O relatório da própria
contratada (doc 37) diz "A estratégia logística utilizou 137 polos de distribuição" e "Cada um dos 137 polos recebeu
um quantitativo de 5% de material reserva"; o detalhamento para desembolso (doc 38) paga "Transporte - Distribuição dos
instrumentos de avaliação nos polos regionais | locais | 137 | 0.05 | 144 | 1 | 1 | 7407.18" — 144 locais (137 + 5%)
a R$ 7.407,18, e o mesmo no recolhimento. Reserva técnica faz sentido para caderno impresso (sobra para extravio);
não para a viagem a um polo que não existe nem para o coordenador do 144º polo.

SINAL (linha de tabela de desembolso/medição com coluna de reserva técnica): quantidade Q, percentual p > 0 e
total T com T = ⌈Q·(1+p)⌉ × fatores (ou T > Q·fatores), em linha cuja UNIDADE ou descrição é lugar, pessoa, hora,
dia, diária, viagem ou transporte. Grau:
  · forte = algum OUTRO documento do mesmo processo declara a quantidade executada = Q ("utilizou 137 polos") —
            a própria contratada diz que executou menos do que foi pago;
  · medio = só a tabela (a reserva pode ter sido prevista no contrato — quem abre lê a cláusula de preço).
`excesso_estimado` = (T − Q·fatores) × valor unitário, por linha; `valor_pago_ob` = OB paga do processo (piso).

EXPLICAÇÕES INOCENTES: contrato/TR que preveja expressamente a reserva sobre aquele item (aí o vício migra para o
planejamento, mas o pagamento é contratual); polo extra efetivamente montado e não citado no relatório. Linhas de
material impresso (caderno, prova, instrumento, malote, kit) ficam fora por código. Indício, não acusação.
Norma: Lei 4.320/1964 art. 63 §2º (liquidação pela prestação efetiva); Lei 14.133/2021 art. 140 e 141.
"""
from __future__ import annotations

import math
import re

from compliance_agent.padroes import _pagamento_comum as C

ID = "reserva_tecnica_multiplicada"

_UM_NAO_MATERIAL = re.compile(
    r"^(locais|local|polos?|hora|horas|h|dias?|di[aá]rias?|pessoas?|viagens?|ve[ií]culos?|km|servi[cç]os?|"
    r"aplicador(es)?|turnos?|m[eê]s|meses|equipes?|postos?)$", re.I)
_DESC_PESSOA = re.compile(r"coordenador|aplicador|fiscal|apoio|motorista|transporte|deslocamento|aluguel de espa[cç]o|"
                          r"supervisor|chefe|monitor|equipe", re.I)
_DESC_MATERIAL = re.compile(r"caderno|prova\b|impress|malote|kit|exemplar|instrumento[s]? f[ií]sic|cart[aã]o resposta|"
                            r"envelope|lacre|material", re.I)
_N = r"(\d+(?:[.,]\d+)?)"
# "| 5 | Transporte - Distribuição … | locais | 137 | 0.05 | 144 | 1 | 1 | 7407.18 | 1066633.92 |"
_LINHA = re.compile(r"\|?\s*\d{1,3}\s*\|\s*([^|\n]{4,160}?)\s*\|\s*([^|\n]{1,20}?)\s*\|\s*" + _N + r"\s*\|\s*"
                    + r"(0[.,]\d{1,3})\s*\|\s*" + _N + r"\s*\|\s*" + _N + r"\s*\|\s*" + _N + r"\s*\|\s*" + _N)
_DECLARA = r"(?:utiliz\w*|receb\w*|atend\w*|mobiliz\w*|montad\w*|foram|contou com|total de)\s+(?:\w+\s+){0,2}?{q}\s+"


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def linhas_reserva(texto: str) -> list[dict]:
    """Linhas em que a reserva técnica multiplicou quantidade de lugar/pessoa/hora/transporte."""
    out = []
    t = texto.replace("\n", " ")
    for m in _LINHA.finditer(t):
        desc, um = m[1].strip(), m[2].strip()
        q, p, tot, f1, f2, unit = _f(m[3]), _f(m[4]), _f(m[5]), _f(m[6]), _f(m[7]), _f(m[8])
        if q <= 0 or p <= 0 or unit <= 0 or _DESC_MATERIAL.search(desc) and not _DESC_PESSOA.search(desc):
            continue
        if not (_UM_NAO_MATERIAL.match(um) or _DESC_PESSOA.search(desc)):
            continue
        fatores = (f1 or 1) * (f2 or 1)
        base = q * fatores
        if tot <= base + 0.5:
            continue
        if abs(tot - math.ceil(q * (1 + p) - 1e-9) * fatores) > 0.5:
            continue                    # o excesso não é a reserva: outra regra de cálculo — não é este padrão
        out.append({"descricao": desc[:120], "unidade": um, "quantidade": q, "reserva": p, "total_pago": tot,
                    "fatores": fatores, "valor_unitario": unit,
                    "excesso_estimado": round((tot - base) * unit, 2), "trecho": C.mascarar_cpf(m[0].strip())[:300]})
    return out


def declara_quantidade(texto: str, q: float) -> str | None:
    """Trecho em que o texto declara ter executado exatamente Q (polos, locais…)."""
    qs = str(int(q)) if q == int(q) else str(q)
    m = re.search(_DECLARA.replace("{q}", re.escape(qs)) + r"(polos?|locais|locali|pontos|unidades|escolas|"
                  r"coordenador|aplicador|ve[ií]culos|rotas)", texto, re.I)
    return C.trecho(texto, m.start(), m.end(), 60) if m else None


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    cands = C.grep_candidatos("reserva t[eé]cnica", so, limite)
    cob = {"processos_com_reserva_tecnica": len(cands)}
    brutos = []
    for tag, arqs in cands.items():
        pasta = C.ACERVO / tag
        man = C.manifesto(pasta)
        if not man:
            continue
        por_arq = C.docs_por_arquivo(man)
        lin = []
        for a in arqs:
            d = por_arq.get(a)
            if d:                                      # só documento declarado no manifesto
                lin += [{**x, "doc": C.numero_doc(d)} for x in linhas_reserva(C.ler(pasta, man, d))]
        # a mesma linha volta em cada página/cópia do desembolso: conta uma vez
        lin = list({(x["descricao"], x["unidade"], x["quantidade"], x["total_pago"], x["valor_unitario"]): x
                    for x in lin}.values())
        if not lin:
            continue
        declaracoes = {}
        for d in C.docs(man):
            if not lin:
                break
            t = None
            for x in lin:
                if x["quantidade"] in declaracoes or C.numero_doc(d) == x["doc"]:
                    continue
                t = t if t is not None else C.ler(pasta, man, d, teto=200000)
                tr = declara_quantidade(t, x["quantidade"])
                if tr:
                    declaracoes[x["quantidade"]] = f"{C.numero_doc(d)} — \"{tr}\""
        brutos.append((tag, lin, declaracoes))
    con = C.con_ro()
    obs = C.obs_pagas(con, [C.processo(t) for t, _, _ in brutos])
    con.close()
    achados = []
    for tag, lin, decl in brutos:
        proc = C.processo(tag)
        com = [x for x in lin if x["quantidade"] in decl]
        g = "forte" if com else "medio"
        x0 = (com or lin)[0]
        achados.append({
            "processo": proc, "grau": g, "linhas": lin[:12],
            "excesso_estimado": round(sum(x["excesso_estimado"] for x in lin), 2),
            "prova": (f"{x0['doc']} — \"{x0['trecho']}\"" + (f"; {decl[x0['quantidade']]}" if com else "")),
            "valor_pago_ob": C.pago(obs.get(proc, [])),
            "credor": next((o["nome_credor"] for o in obs.get(proc, []) if o.get("nome_credor")), None),
            "porque": ("reserva técnica (sobra de material) multiplicou lugar/pessoa/hora/transporte"
                       + ("; a quantidade executada declarada nos autos é a base sem reserva" if com else "")
                       + "; inocente não excluída: reserva expressamente prevista no contrato para o item"),
            "fonte": "data/sei_arquivo (tabela de desembolso + relatório) × ob_orcamentaria_siafe/_ob_paga (piso)"})
    return C.resultado(ID, len(C.pastas(so)) if not limite else limite, cob, achados, "data/sei_arquivo × SIAFE")
