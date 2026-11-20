# -*- coding: utf-8 -*-
"""Execução da parceria declarada EXATAMENTE no limiar de liberação — escreveu-se o limiar, não o executado.

ORIGEM (perícia por agente, 18/11/2026): Núcleo Social Bem Viver × SEIJES, SEI-280001/000624/2025, Termo de Colaboração
001/2025. Doc 60 — "resultando em um total de R$ 7.005.347,65 o que equivale a 65% do montante total das parcelas que
já foram pagas" — e o montante no mesmo relatório é R$ 10.777.457,93: 0,65 × 10.777.457,93 = 7.005.347,65 AO CENTAVO.
Repete-se nos docs 85 (10.110.695,30 = 0,65 × 15.554.915,85) e 135 (16.321.390,60 = 0,65 × 25.109.831,69). Execução
real não cai três vezes no centavo do percentual que libera a parcela seguinte.

SINAL: num relatório de execução/prestação de contas/parecer de parceria, a frase "R$ X … equivale/corresponde a P%" com
X == round(P% × Y, 2) (±R$ 0,01) para algum Y > X impresso no MESMO documento, em contexto de execução (executado,
aplicado, comprovado, prestação de contas), SEM qualificador ("mais de", "ao menos", "cerca de", "superior a").
  · forte: o mesmo processo repete o cálculo exato em ≥ 2 relatórios com valores diferentes;
  · medio: um relatório.

EXPLICAÇÕES INOCENTES AVALIADAS (regra no código):
  · relatório que diz "mais de 65%" com o valor executado real (Bem Viver doc 109) — qualificador → fora;
  · parcela PLANEJADA descrita como fração do total ("a parcela de R$ X corresponde a 10% do valor global") — exige
    contexto de execução na janela anterior e ausência de "parcela/desembolso/cronograma" colado ao valor;
  · P = 100% (valor igual ao total) não é limiar → fora; P < 5% (taxa, tarifa, contrapartida) → fora;
  · redação abreviada de "ao menos P%": não descartada pelo código — por isso grau ≤ forte só por repetição, e a
    peça pede a planilha de execução financeira (art. 63 a 68 da Lei 13.019/2014).

NORMA: Lei 13.019/2014 arts. 48 (liberação condicionada), 63 e 66 (prestação de contas: execução real), 67.
Indício, não acusação.
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _pagamento_comum as C
from compliance_agent.padroes._mrosc_comum import eh_parceria, plano, universo

ID = "mrosc_execucao_igual_limiar"

_TITULO = re.compile(r"relat[oó]rio|presta[cç][aã]o de contas|parecer|an[aá]lise|monitoramento|fiscaliza|execu[cç]",
                     re.I)
_FRASE = re.compile(
    r"R\$\s*(" + C.MOEDA + r")[^.;%]{0,90}?\b(?:equivale|corresponde|representa|perfaz)\w*\s+(?:a|ao|à)?\s*"
    r"(mais\s+de\s+|cerca\s+de\s+|aproximadamente\s+|ao\s+menos\s+|pelo\s+menos\s+|superior\s+a\s+|acima\s+de\s+|"
    r"quase\s+|menos\s+de\s+)?(\d{1,2}(?:,\d{1,2})?)\s*%", re.I)
_EXECUCAO = re.compile(r"execu|aplica|comprov|gast|utiliza|despesa|presta[cç][aã]o de contas|avaliad", re.I)
_PLANEJADO = re.compile(r"parcela\s+de\s+R\$|desembolso\s+de\s+R\$|cronograma", re.I)


def avaliar_texto(texto: str) -> list[dict]:
    """Frases de execução cujo valor é exatamente P% de outro valor do mesmo documento."""
    t = plano(texto)
    valores = {C.num(v) for v in re.findall(C.MOEDA, t)}
    out = []
    for m in _FRASE.finditer(t):
        if m.group(2):                         # "mais de 65%" etc.: não afirma o valor exato
            continue
        x, p = C.num(m.group(1)), float(m.group(3).replace(",", "."))
        if not (5 <= p < 100) or x <= 0:
            continue
        antes = t[max(0, m.start() - 250):m.start()]
        if not _EXECUCAO.search(antes + m.group(0)) or _PLANEJADO.search(t[max(0, m.start() - 40):m.start() + 5]):
            continue
        bases = sorted(y for y in valores if y > x and abs(round(y * p / 100, 2) - x) <= 0.01)
        if bases:
            out.append({"executado": x, "percentual": p, "base": bases[0],
                        "trecho": C.trecho(t, m.start(), m.end(), 120)})
    return out


def _processo(pasta, man, sel):
    if not eh_parceria(man):
        return [], {}
    cob = {"parcerias_avaliadas": 1}
    hits = []
    for d in sel:
        for h in avaliar_texto(C.ler(pasta, man, d)):
            hits.append({**h, "doc": C.numero_doc(d), "titulo": str(d.get("titulo") or "")[:120]})
    if not hits:
        return [], cob
    distintos = {h["executado"] for h in hits}
    proc = C.processo(pasta.name)
    prova = " · ".join(
        f"{h['doc']} — \"{h['trecho']}\" (= {C.fmt(h['percentual'])}% × R$ {C.fmt(h['base'])})"
        for h in sorted({h['executado']: h for h in hits}.values(), key=lambda h: h["executado"])[:4])
    return [{
        "processo": proc, "grau": "forte" if len(distintos) >= 2 else "medio", "prova": prova,
        "valor_pago_ob": None, "relatorios_exatos": len(distintos),
        "porque": ("Inocente avaliada: redação abreviada de 'ao menos P%' — não descartável pelo texto; exige a "
                   "planilha de execução financeira da OSC. Repetição exata em relatórios distintos torna improvável."),
        "fonte": "SEI (manifesto + texto) · OB SIAFE _ob_paga (piso)"}], cob


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    so = universo(so, limite)
    achados, cob, n = C.varrer_acervo(_TITULO, _processo, so=so)
    C.completar_com_ob(achados)
    cob["universo_definicao"] = "processos de parceria (títulos do manifesto, _mrosc_comum.eh_parceria)"
    return C.resultado(ID, cob.get("parcerias_avaliadas", 0), cob, achados,
                       "data/sei_arquivo/*/manifest.json + texto; ob_orcamentaria_siafe (_ob_paga, soma por processo = PISO)")
